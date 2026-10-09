"""从已有验收记录生成 Sites 项目；不修改原始证据或 HTML。"""
from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
from typing import Any

if __package__:
    from .delivery_artifacts import ALLOWED_EXTENSIONS, MAX_ASSET_BYTES, read_report
    from .report_media import META_FIELDS, complete_image_metadata
    from .report_diagnostics import ExportValidationError, ExportFileNotFoundError, ExportDiagnosticsWarning, assessment, enforce, diagnostic, inspect_report
else:
    from delivery_artifacts import ALLOWED_EXTENSIONS, MAX_ASSET_BYTES, read_report
    from report_media import META_FIELDS, complete_image_metadata
    from report_diagnostics import ExportValidationError, ExportFileNotFoundError, ExportDiagnosticsWarning, assessment, enforce, diagnostic, inspect_report

TEMPLATE = Path(__file__).resolve().parents[1] / "templates" / "sites"
MARKER = ".moe-acceptance-sites.json"
CASE_FIELDS = ("id", "title", "problem", "claim", "input", "observed", "verdict", "evidence_ids", "kind", "ui_comparisons")
ASSET_FIELDS = ("asset_id", "kind", "label", "note", "round_id", "captured_at", "registered_at", "supersedes", "replacement_reason")


def _json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _media_file(task: Path, asset: dict[str, Any]) -> Path:
    # read_report 已校验新模型引用；这里也保护旧快照及生成目录的文件复制边界。
    value = asset.get("path", "")
    if not isinstance(value, str) or not re.fullmatch(r"\.\./assets/[A-Za-z0-9._-]+", value):
        raise ValueError("证据路径必须位于任务 assets 目录")
    file = task / "assets" / value.removeprefix("../assets/")
    if file.is_symlink() or file.suffix.lower() not in ALLOWED_EXTENSIONS:
        raise ValueError("证据必须是允许类型的非 symlink 文件")
    if not file.is_file():
        raise FileNotFoundError(f"证据文件缺失：{file.name}")
    if file.stat().st_size > MAX_ASSET_BYTES:
        raise ValueError("证据文件超过 100 MB")
    return file


def _metadata(asset: dict[str, Any], file: Path) -> dict[str, Any]:
    raw = complete_image_metadata(file, asset.get("metadata", {}))
    return {key: raw[key] for key in META_FIELDS if key in raw}


def _content(source: dict[str, Any]) -> dict[str, Any]:
    result = {key: copy.deepcopy(source[key]) for key in ("title", "summary", "ui_acceptance", "excluded_cases") if key in source}
    result["cases"] = [{key: copy.deepcopy(case[key]) for key in CASE_FIELDS if key in case}
                       for case in source.get("cases", [])]
    return result


def _presentation(value: Any, views: list[dict[str, Any]]) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict) or set(value) - {"rounds"}:
        raise ValueError("Sites 展示配置仅支持 rounds")
    rounds = value.get("rounds", {})
    if not isinstance(rounds, dict):
        raise ValueError("展示配置 rounds 必须是对象")
    index = {view["round"]["id"]: view for view in views}
    for round_id, cases in rounds.items():
        if round_id not in index or not isinstance(cases, dict):
            raise ValueError(f"展示配置引用未知轮次：{round_id}")
        case_index = {case["id"]: case for case in index[round_id]["manifest"]["cases"]}
        for case_id, hints in cases.items():
            if case_id not in case_index or not isinstance(hints, dict) or set(hints) - {"short_title", "primary_evidence_id"}:
                raise ValueError(f"Case 展示配置不合法：{case_id}")
            if "short_title" in hints and (not isinstance(hints["short_title"], str) or not hints["short_title"].strip()):
                raise ValueError("目录短标题不能为空")
            if "primary_evidence_id" in hints and hints["primary_evidence_id"] not in case_index[case_id].get("evidence_ids", []):
                raise ValueError("主证据必须属于该轮 Case 已选择的 evidence_ids")
    return copy.deepcopy(rounds)


def _payload(task: Path, task_id: str, presentation: Any) -> tuple[dict[str, Any], dict[str, Path]]:
    current = read_report(task, task_id)
    if current["round"] is None:
        raise ValueError("Sites 导出需要显式轮次和 evidence_ids；请先通过现有 update API 升级旧报告")
    raw = _json(task / "manifest.json")
    views, files = [], {}
    for meta in current["rounds"]:
        warning = ""
        if meta.get("legacy"):
            # 旧快照没有显式采用记录，仅保留历史事实，未经复核的媒体不自动发布。
            saved = next(item for item in raw["rounds"] if item["id"] == meta["id"])
            view = {"round": meta, "manifest": saved["manifest"], "assets": []}
            warning = "旧报告快照，证据未复核；本页仅保留历史文字。"
        else:
            try:
                view = current if meta["id"] == current["round"]["id"] else read_report(task, task_id, round_id=meta["id"])
            except FileNotFoundError:
                if meta["id"] == current["round"]["id"]:
                    raise
                saved = next(item for item in raw["rounds"] if item["id"] == meta["id"])
                view = {"round": meta, "manifest": saved["manifest"], "assets": []}
                warning = "历史证据文件缺失，本快照暂不展示媒体；原业务结论保留。"
        assets = []
        for asset in view["assets"]:
            file = _media_file(task, asset)
            digest = _sha256(file)
            name = digest + file.suffix.lower()
            files[name] = file
            assets.append({**{key: copy.deepcopy(asset[key]) for key in ASSET_FIELDS if key in asset},
                           "url": f"/report/assets/{name}", "sha256": digest, "metadata": _metadata(asset, file)})
        views.append({"round": view["round"], "manifest": _content(view["manifest"]), "assets": assets, "warning": warning})
    return {"schema_version": 1, "task_id": task_id, "current_round_id": current["round"]["id"],
            "rounds": views, "presentation": _presentation(presentation, views)}, files


def _target(task: Path, task_id: str) -> tuple[Path, dict[str, Any]]:
    template = _json(TEMPLATE / "template.json")
    marker = {"task_id": task_id, "template": template}
    site = task / "sites"
    if site.is_symlink():
        raise ValueError("Sites 目录不得是 symlink")
    existing = site.exists()
    if existing:
        if not site.is_dir() or not (site / MARKER).is_file() or (site / MARKER).is_symlink():
            raise ValueError("Sites 目录非本导出器创建，拒绝覆盖")
        if _json(site / MARKER) != marker:
            raise ValueError("Sites 任务或模板版本不一致，需明确处理后再导出")
        if any((site / part).is_symlink() for part in ("public", "public/report")):
            raise ValueError("Sites 生成目录不得是 symlink")
    return site, marker


def _prepare(task: Path, task_id: str, presentation: Any) -> tuple[dict[str, Any], dict[str, Any], dict[str, Path]]:
    issues = inspect_report(task, task_id, CASE_FIELDS)
    payload, files = {}, {}
    if not any(item["severity"] == "error" for item in issues):
        try:
            payload, files = _payload(task, task_id, presentation)
        except (ValueError, OSError) as exc:
            issues.append(diagnostic("export_input_invalid", "error", "presentation", str(exc),
                                     "核对报告和展示配置，使配置引用已有轮次、Case 及采用的证据。", field="presentation/report"))
        try:
            _target(task, task_id)
        except (ValueError, OSError) as exc:
            issues.append(diagnostic("export_target_invalid", "error", "destination", str(exc),
                                     "核对任务标记、模板版本及输出目录归属；保留已有项目后明确处理。", field="sites"))
    return assessment(task_id, issues), payload, files


def check_sites_export(task_dir: str | Path, task_id: str, *, presentation: dict[str, Any] | None = None) -> dict[str, Any]:
    """只读返回导出诊断；无错误仅代表可生成，不代表业务或证据已验收。"""
    return _prepare(Path(task_dir), task_id, presentation)[0]


def export_sites(task_dir: str | Path, task_id: str, *, presentation: dict[str, Any] | None = None) -> Path:
    """生成或刷新 task_dir/sites；不安装依赖、不创建 Site、不发布。"""
    task = Path(task_dir)
    result, payload, files = _prepare(task, task_id, presentation)
    enforce(result)
    site, marker = _target(task, task_id)
    existing = site.exists()
    with tempfile.TemporaryDirectory(prefix=".sites-export-", dir=task) as temporary:
        stage = Path(temporary)
        report = stage / "report"
        (report / "assets").mkdir(parents=True)
        for name, source in files.items():
            destination = report / "assets" / name
            shutil.copy2(source, destination)
            if _sha256(destination) != name.split(".")[0]:
                raise ValueError("导出过程中证据发生变化，请重新导出")
        _write_json(report / "report.json", payload)
        if not existing:
            project = stage / "project"
            shutil.copytree(TEMPLATE, project)
            target = project / "public" / "report"
            if target.exists():
                shutil.rmtree(target)
            os.replace(report, target)
            _write_json(project / MARKER, marker)
            os.replace(project, site)
        else:
            target = site / "public" / "report"
            target.parent.mkdir(exist_ok=True)
            backup = stage / "previous-report"
            if target.exists():
                os.replace(target, backup)
            try:
                os.replace(report, target)
            except OSError:
                if backup.exists():
                    os.replace(backup, target)
                raise
    return site
