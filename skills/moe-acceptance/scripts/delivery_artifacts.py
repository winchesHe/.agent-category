"""为一个验收任务维护同一份脱敏 manifest 和 report/index.html。"""
from __future__ import annotations
import copy
import datetime as dt
import html
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
from typing import Any

if __package__:
    from .report_media import META_FIELDS, complete_image_metadata
    from .ui_review import validate_ui_case
else:
    from report_media import META_FIELDS, complete_image_metadata
    from ui_review import validate_ui_case

ALLOWED_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".mp4", ".webm", ".mov", ".mp3", ".wav", ".m4a"}
ASSET_KINDS = {"screenshot", "image", "video", "gif", "audio", "before", "after", "comparison"}
MAX_ASSET_BYTES = 100 * 1024 * 1024
SENSITIVE_KEY = re.compile(r"(?:token|access_token|refresh_token|cookie|password|authorization|secret|query|body)", re.IGNORECASE)
SENSITIVE_ASSIGNMENT = re.compile(r"(?i)(token|access_token|refresh_token|cookie|password|authorization|secret)\s*[:=]\s*[^\s,;&]+")
SENSITIVE_QUERY = re.compile(r"(?i)([?&](?:token|access_token|refresh_token|cookie|password|authorization|secret)=)[^&#\s]+")


def _task_dir(task_dir: str | Path, task_id: str) -> Path:
    path = Path(task_dir)
    if path.is_symlink() or not path.is_dir() or path.name != task_id:
        raise ValueError("非法 task_dir：必须是名称与 task_id 相同的真实目录")
    for child in ("manifest.json", "report", "assets"):
        if (path / child).is_symlink():
            raise ValueError(f"禁止使用 symlink：{child}")
    return path


def _manifest_path(path: Path) -> Path:
    manifest = path / "manifest.json"
    if manifest.is_symlink() or not manifest.is_file():
        raise FileNotFoundError("任务尚未 initialize，缺少 manifest.json")
    return manifest


def _clean(value: Any) -> Any:
    """递归移除敏感字段，并遮盖文本中的凭据和 URL 查询参数。"""
    if isinstance(value, dict):
        return {key: _clean(item) for key, item in value.items() if not SENSITIVE_KEY.search(str(key))}
    if isinstance(value, list):
        return [_clean(item) for item in value]
    if isinstance(value, str):
        value = SENSITIVE_ASSIGNMENT.sub("[已隐藏]", value)
        return SENSITIVE_QUERY.sub(r"\1[已隐藏]", value)
    return value


def _read_manifest(path: Path, task_id: str) -> dict[str, Any]:
    try:
        data = json.loads(_manifest_path(path).read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError("manifest.json 不是有效 JSON") from exc
    if not isinstance(data, dict) or data.get("task_id") != task_id:
        raise ValueError("manifest/task_id 不匹配")
    data.setdefault("manifest", {})
    data.setdefault("history", [])
    data.setdefault("assets", [])
    data.setdefault("report_enabled", False)
    if type(data.get("schema_version", 1)) is not int or data.get("schema_version", 1) not in {1, 2}:
        raise ValueError("不支持的报告 schema_version")
    if not isinstance(data["assets"], list) or any(not isinstance(asset, dict) for asset in data["assets"]):
        raise ValueError("assets 必须是资产对象列表")
    # 旧文件只在内存补稳定 ID；不猜测采集时间或来源轮次。
    if data.get("schema_version", 1) == 1:
        for index, asset in enumerate(data["assets"], 1):
            asset.setdefault("asset_id", f"asset-{index}")
            for key in ("round_id", "captured_at", "registered_at"):
                asset.setdefault(key, None)
            asset.setdefault("supersedes", [])
            asset.setdefault("replacement_reason", "")
    _asset_index(data)
    if data.get("schema_version") == 2:
        _round_entries(data)
    return data


def _identifier(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} 必须是非空字符串")
    return value


def _timestamp(value: Any, field: str) -> str | None:
    if value is None:
        return None
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, TypeError, ValueError) as exc:
        raise ValueError(f"{field} 必须是带时区的 ISO 时间或 null") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"{field} 必须包含时区")
    return value


def _asset_index(data: dict[str, Any]) -> dict[str, dict[str, Any]]:
    result = {}
    for asset in data["assets"]:
        asset_id = _identifier(asset.get("asset_id"), "asset_id")
        if asset_id in result:
            raise ValueError(f"重复 asset_id：{asset_id}")
        result[asset_id] = asset
    return result


def _ids(value: Any, field: str) -> list[str]:
    if not isinstance(value, list):
        raise ValueError(f"{field} 必须是显式 ID 列表")
    for item in value:
        _identifier(item, field)
    if len(set(value)) != len(value):
        raise ValueError(f"{field} 不允许重复 ID")
    return value


def _asset_file(path: Path, asset: dict[str, Any]) -> Path:
    relative = asset.get("path")
    prefix = "../assets/"
    if not isinstance(relative, str) or not relative.startswith(prefix):
        raise ValueError("证据路径必须位于任务 assets 目录")
    name = relative[len(prefix):]
    if not re.fullmatch(r"[A-Za-z0-9._-]+", name) or Path(name).name != name or name in {".", ".."}:
        raise ValueError("证据路径不得包含目录跳转")
    file = path / "assets" / name
    if file.is_symlink() or file.suffix.lower() not in ALLOWED_EXTENSIONS:
        raise ValueError("证据必须是允许类型的非 symlink 文件")
    if not file.is_file():
        raise FileNotFoundError(f"证据文件缺失：{name}")
    if file.stat().st_size > MAX_ASSET_BYTES:
        raise ValueError("证据文件超过 100 MB")
    return file


def _selected_assets(path: Path, data: dict[str, Any], content: dict[str, Any]) -> list[dict[str, Any]]:
    if not isinstance(content, dict) or not isinstance(content.get("cases", []), list):
        raise ValueError("摘要必须是对象，cases 必须是列表")
    assets = _asset_index(data)
    selected = []
    case_ids = set()
    for case in content.get("cases", []):
        if not isinstance(case, dict):
            raise ValueError("Case 必须是对象")
        case_id = _identifier(case.get("id"), "case_id")
        if case_id in case_ids:
            raise ValueError(f"重复 case_id：{case_id}")
        case_ids.add(case_id)
        evidence_ids = _ids(case.get("evidence_ids"), "evidence_ids")
        validate_ui_case(case, assets)
        for asset_id in evidence_ids:
            if asset_id not in assets:
                raise ValueError(f"未知证据引用：{asset_id}")
            asset = copy.deepcopy(assets[asset_id])
            metadata = asset.setdefault("metadata", {})
            if not isinstance(metadata, dict):
                raise ValueError("证据 metadata 必须是对象")
            if metadata.get("case_id") is not None and metadata["case_id"] != case_id:
                raise ValueError(f"证据 {asset_id} 不属于 Case {case_id}")
            _asset_file(path, asset)
            # 显式引用可以归类旧的无归属图，不回写或伪造原始资产 metadata。
            metadata["case_id"] = case_id
            selected.append(asset)
    ui_items = content.get("ui_acceptance", [])
    if not isinstance(ui_items, list) or any(
        not isinstance(item, dict) or not isinstance(item.get("case_id"), str)
        or item["case_id"] not in case_ids for item in ui_items
    ):
        raise ValueError("UI 验收条目必须引用本摘要中的 Case")
    return selected


def _round_metadata(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("report_round 必须是对象")
    value = _clean(value)
    return {
        "id": _identifier(value.get("id"), "round_id"),
        "label": _identifier(value.get("label", value.get("id")), "round label"),
        "reason": _identifier(value.get("reason"), "round reason"),
        "observed_at": _timestamp(value.get("observed_at"), "observed_at"),
    }


def _set_round(data: dict[str, Any], report_round: dict[str, Any] | None) -> None:
    if report_round is None:
        return
    if isinstance(report_round, dict) and report_round.get("id") == data.get("current_round", {}).get("id"):
        report_round = {**data["current_round"], **report_round}
    metadata = _round_metadata(report_round)
    if metadata["id"] == "legacy":
        raise ValueError("legacy 是旧报告快照的保留 ID")
    if data.get("schema_version", 1) == 1:
        data["rounds"] = [{
            "id": "legacy", "label": "旧报告快照（未复核）", "reason": "显式升级前的已存内容",
            "observed_at": None, "legacy": True,
            "manifest": copy.deepcopy(data["manifest"]),
            "asset_ids": [asset["asset_id"] for asset in data["assets"]],
        }]
        data["schema_version"] = 2
    elif metadata["id"] != data["current_round"]["id"]:
        if any(item["id"] == metadata["id"] for item in data["rounds"]):
            raise ValueError("历史轮次不可被 update 覆写；请使用新的 round_id")
        data["rounds"].append({
            **copy.deepcopy(data["current_round"]), "manifest": copy.deepcopy(data["manifest"]),
            "asset_ids": [asset["asset_id"] for asset in data["assets"]],
        })
    data["current_round"] = metadata


def _round_entries(data: dict[str, Any]) -> list[dict[str, Any]]:
    current = data.get("current_round")
    rounds = data.get("rounds")
    if not isinstance(current, dict) or not isinstance(rounds, list):
        raise ValueError("轮次报告缺少 current_round 或 rounds")
    entries = [*rounds, {**current, "manifest": data["manifest"],
                        "asset_ids": [asset["asset_id"] for asset in data["assets"]]}]
    _ids([entry.get("id") if isinstance(entry, dict) else None for entry in entries], "rounds")
    for entry in entries:
        _round_metadata(entry)
        if not isinstance(entry.get("manifest"), dict):
            raise ValueError("轮次缺少完整 manifest 快照")
        _ids(entry.get("asset_ids"), "round asset_ids")
    if current.get("legacy") or current["id"] == "legacy":
        raise ValueError("旧快照不能自动作为当前轮次")
    return entries


def _report_view(path: Path, data: dict[str, Any], round_id: str | None = None) -> dict[str, Any]:
    if data.get("schema_version", 1) == 1:
        if round_id is not None:
            raise ValueError("旧报告没有可确认的轮次")
        return {"task_id": data["task_id"], "round": None, "rounds": [],
                "manifest": copy.deepcopy(data["manifest"]), "assets": copy.deepcopy(data["assets"]),
                "unassigned_assets": []}
    entries = _round_entries(data)
    ids = [entry["id"] for entry in entries]
    selected_id = round_id if round_id is not None else data["current_round"]["id"]
    if selected_id not in ids:
        raise ValueError(f"未知轮次：{selected_id}")
    entry = entries[ids.index(selected_id)]
    content = entry["manifest"]
    index = _asset_index(data)
    asset_ids = entry["asset_ids"]
    if any(asset_id not in index for asset_id in asset_ids):
        raise ValueError("报告快照引用了未知资产")
    available = [index[asset_id] for asset_id in asset_ids]
    if entry.get("legacy"):
        selected = copy.deepcopy(available)
    else:
        selected = _selected_assets(path, {"assets": available}, content)
    selected_ids = {asset["asset_id"] for asset in selected}
    def metadata(item: dict[str, Any]) -> dict[str, Any]:
        return {key: copy.deepcopy(value) for key, value in item.items() if key not in {"manifest", "asset_ids"}}

    return {
        "task_id": data["task_id"], "round": metadata(entry), "rounds": [metadata(item) for item in entries],
        "manifest": copy.deepcopy(content), "assets": selected,
        "unassigned_assets": [copy.deepcopy(asset) for asset in available if asset["asset_id"] not in selected_ids],
    }


def read_report(task_dir: str | Path, task_id: str, *, round_id: str | None = None) -> dict[str, Any]:
    """只读选择报告内容；不迁移文件、不创建轮次、不改变当前结果。"""
    path = _task_dir(task_dir, task_id)
    return _report_view(path, _read_manifest(path, task_id), round_id)


def _atomic_write(path: Path, content: str) -> None:
    """在同一目录中以受限权限原子替换文件，避免半写入报告。"""
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except Exception:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def _write_manifest(path: Path, data: dict[str, Any]) -> None:
    _atomic_write(path / "manifest.json", json.dumps(data, ensure_ascii=False, indent=2) + "\n")


def initialize(
    task_dir: str | Path,
    task_id: str,
    manifest: dict[str, Any] | None = None,
    *,
    render_report: bool = False,
    report_round: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """初始化任务；只有正式交付需要时才开启 HTML 报告。"""
    path = _task_dir(task_dir, task_id)
    if (path / "manifest.json").exists():
        raise FileExistsError("任务已 initialize；请使用 update 继续写入同一报告页")
    (path / "assets").mkdir(exist_ok=True, mode=0o700)
    data = {
        "task_id": task_id,
        "manifest": _clean(manifest or {}),
        "history": [],
        "assets": [],
        "report_enabled": bool(render_report),
    }
    if report_round is not None:
        data.update(schema_version=2, current_round=_round_metadata(report_round), rounds=[])
        if data["current_round"]["id"] == "legacy":
            raise ValueError("legacy 是旧报告快照的保留 ID")
        _report_view(path, data)
    _write_manifest(path, data)
    if render_report:
        render(path, task_id)
    return data


def register_asset(
    task_dir: str | Path,
    task_id: str,
    source: str | Path,
    kind: str,
    label: str = "",
    note: str = "",
    metadata: dict[str, Any] | None = None,
    *,
    captured_at: str | None = None,
    supersedes: list[str] | None = None,
    replacement_reason: str = "",
) -> dict[str, Any]:
    path = _task_dir(task_dir, task_id)
    data = _read_manifest(path, task_id)
    if kind not in ASSET_KINDS:
        raise ValueError(f"不支持的资产类型：{kind}")
    source_path = Path(source)
    if (source_path.is_symlink() or not source_path.is_file() or source_path.suffix.lower() not in ALLOWED_EXTENSIONS or source_path.stat().st_size > MAX_ASSET_BYTES):
        raise ValueError("资产必须是非 symlink、允许扩展名且不超过 100 MB 的文件")
    assets = path / "assets"
    assets.mkdir(exist_ok=True, mode=0o700)
    index = len(data["assets"])
    safe_stem = re.sub(r"[^A-Za-z0-9._-]+", "_", source_path.stem).strip("._") or "asset"
    destination = assets / f"{safe_stem}_{index}{source_path.suffix.lower()}"
    if metadata is not None and not isinstance(metadata, dict):
        raise ValueError("metadata 必须是对象")
    corrections = []
    metadata_clean = complete_image_metadata(source_path, _clean(metadata or {}), corrections=corrections)
    owner = metadata_clean.get("case_id")
    index_by_id = _asset_index(data)
    asset_number = len(data["assets"]) + 1
    while f"asset-{asset_number}" in index_by_id:
        asset_number += 1
    supersedes = _ids(supersedes if supersedes is not None else [], "supersedes")
    if any(asset_id not in index_by_id for asset_id in supersedes):
        raise ValueError("supersedes 必须引用已登记的证据")
    if supersedes:
        _identifier(replacement_reason, "replacement_reason")
        for asset_id in supersedes:
            previous_metadata = index_by_id[asset_id].get("metadata", {})
            if not isinstance(previous_metadata, dict):
                raise ValueError("被替代证据的 metadata 必须是对象")
            previous_owner = previous_metadata.get("case_id")
            if owner is not None and previous_owner is not None and previous_owner != owner:
                raise ValueError("supersedes 不可替代其它 Case 的证据")
    if not isinstance(replacement_reason, str):
        raise ValueError("replacement_reason 必须是字符串")
    item = {
        "asset_id": f"asset-{asset_number}",
        "round_id": data.get("current_round", {}).get("id"),
        "captured_at": _timestamp(captured_at, "captured_at"),
        "registered_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "supersedes": supersedes,
        "replacement_reason": str(_clean(replacement_reason)),
        "kind": kind,
        "label": str(_clean(label)),
        "note": str(_clean(note)),
        "path": f"../assets/{destination.name}",
        "metadata": metadata_clean,
    }
    # 所有校验通过后才复制；写 manifest 失败时只回收本次新文件。
    if destination.exists() or destination.is_symlink():
        raise FileExistsError("资产目标文件已存在，不覆盖未登记文件")
    try:
        shutil.copy2(source_path, destination)
        item["metadata"] = complete_image_metadata(destination, metadata_clean, corrections=corrections)
        data["assets"].append(item)
        if corrections:
            data["history"].append({"time": dt.datetime.now(dt.timezone.utc).isoformat(),
                                    "change": "登记图片时采用文件实际尺寸", "action": "correct_image_dimensions",
                                    "asset_id": item["asset_id"], "corrections": corrections})
        _write_manifest(path, data)
    except Exception:
        destination.unlink(missing_ok=True)
        raise
    if data.get("report_enabled") and data.get("schema_version", 1) == 1:
        render(path, task_id)
    return item


def update_asset_metadata(
    task_dir: str | Path, task_id: str, asset_id: str, metadata: dict[str, Any], *, reason: str,
) -> dict[str, Any]:
    """合并更正已有资产的元数据；null 删除字段，空补丁可补齐图片尺寸。"""
    _identifier(asset_id, "asset_id")
    path = _task_dir(task_dir, task_id)
    data = _read_manifest(path, task_id)
    index = _asset_index(data)
    if asset_id not in index:
        raise ValueError("未知 asset_id")
    _identifier(reason, "reason")
    if not isinstance(metadata, dict) or set(metadata) - set(META_FIELDS):
        raise ValueError("仅支持修订已定义的媒体 metadata 字段")
    item = index[asset_id]
    before = copy.deepcopy(item.get("metadata", {}))
    if not isinstance(before, dict):
        raise ValueError("原 metadata 必须是对象")
    patched = copy.deepcopy(before)
    for key, value in _clean(metadata).items():
        if value is None:
            patched.pop(key, None)
        else:
            patched[key] = value
    corrections = []
    item["metadata"] = complete_image_metadata(_asset_file(path, item), patched, corrections=corrections)
    # 资产跨轮复用；归属修订不能使任何已有选择指向另一个 Case。
    if data.get("schema_version") == 2:
        for entry in _round_entries(data):
            for case in entry["manifest"].get("cases", []):
                if asset_id in case.get("evidence_ids", []) and item["metadata"].get("case_id") not in {None, case["id"]}:
                    raise ValueError("metadata 修订与已有轮次的 Case 归属冲突")
    if item["metadata"] == before and not corrections:
        return copy.deepcopy(item)
    data["history"].append({"time": dt.datetime.now(dt.timezone.utc).isoformat(),
                            "change": str(_clean(reason)), "action": "update_asset_metadata",
                            "asset_id": asset_id, "before": _clean(before), "after": copy.deepcopy(item["metadata"]),
                            **({"corrections": corrections} if corrections else {})})
    _write_manifest(path, data)
    if data.get("report_enabled"):
        render(path, task_id)
    return copy.deepcopy(item)


def update(
    task_dir: str | Path, task_id: str, content: dict[str, Any], change: str = "", *,
    report_round: dict[str, Any] | None = None,
) -> dict[str, Any]:
    path = _task_dir(task_dir, task_id)
    data = _read_manifest(path, task_id)
    cleaned = _clean(content)
    _set_round(data, report_round)
    data["manifest"] = cleaned
    if data.get("schema_version") == 2:
        _report_view(path, data)
    elif any(isinstance(case, dict) and (case.get("kind") == "ui" or "ui_comparisons" in case)
             for case in cleaned.get("cases", []) or []):
        raise ValueError("UI 走查需要显式轮次；请通过 report_round 升级旧报告")
    data["history"].append({"time": dt.datetime.now(dt.timezone.utc).isoformat(), "change": str(_clean(change)), "summary": str(cleaned)[:240]})
    _write_manifest(path, data)
    if data.get("report_enabled"):
        render(path, task_id)
    return data


def _text(value: Any) -> str:
    return html.escape(str(value or ""))


def _paragraphs(value: Any) -> str:
    # 只按作者显式留出的空行分段，不根据标点猜测业务语义。
    text = str(value or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    return "".join(f"<p>{_text(part.strip())}</p>" for part in re.split(r"\n[ \t]*\n(?:[ \t]*\n)*", text) if part.strip())


def check_html_export(task_dir: str | Path, task_id: str) -> dict[str, Any]:
    """只读检查 HTML 的内容、引用和媒体；旧报告沿用原图集语义。"""
    if __package__:
        from .report_diagnostics import assessment, diagnostic, inspect_report
    else:
        from report_diagnostics import assessment, diagnostic, inspect_report
    fields = ("id", "title", "claim", "input", "observed", "verdict", "evidence_ids", "kind", "ui_comparisons")
    issues = inspect_report(Path(task_dir), task_id, fields, target="html")
    report = Path(task_dir) / "report"
    page = report / "index.html"
    if (report.exists() and not report.is_dir()) or page.is_symlink() or (page.exists() and not page.is_file()):
        issues.append(diagnostic("export_target_invalid", "error", "destination", "HTML 输出位置不是正常目录或文件。",
                                 "核对 report/index.html 的归属和类型，保留已有内容后处理冲突。", field="report/index.html"))
    return assessment(task_id, issues)


def _complete_view_media(path: Path, view: dict[str, Any]) -> None:
    for asset in view["assets"]:
        asset["metadata"] = complete_image_metadata(_asset_file(path, asset), asset.get("metadata", {}))


def render(task_dir: str | Path, task_id: str) -> Path:
    """检查任务 manifest 并生成 HTML；返回路径，确定错误时保留已有页面。"""
    if __package__:
        from .report_diagnostics import enforce
    else:
        from report_diagnostics import enforce
    enforce(check_html_export(task_dir, task_id))
    path = _task_dir(task_dir, task_id)
    data = _read_manifest(path, task_id)
    view = _report_view(path, data)
    _complete_view_media(path, view)
    if not data.get("report_enabled"):
        data["report_enabled"] = True
        _write_manifest(path, data)
    current_id = data.get("current_round", {}).get("id")
    page, current = _render_view(task_id, view, current_id)
    round_views = {}
    if current_id is not None:
        round_views[current_id] = current
        for entry in data["rounds"]:
            try:
                historical = _report_view(path, data, entry["id"])
                _complete_view_media(path, historical)
            except FileNotFoundError:
                # 历史文件丢失不阻断当前交付，也不改变已保存的业务结论。
                historical = {"manifest": entry["manifest"], "round": entry,
                              "rounds": view["rounds"], "assets": [],
                              "evidence_warning": "历史证据文件缺失，本快照暂不展示媒体；原业务结论保留。"}
            _, round_views[entry["id"]] = _render_view(task_id, historical, current_id)
    if round_views:
        page, _ = _render_view(task_id, view, current_id, round_views)
    history = [item for item in data.get("history", []) if isinstance(item, dict)]
    if history:
        audit = " | ".join(_text(item.get("change")) for item in history)
        page = page.replace("</body>", "<!-- history: " + audit + " --></body>")
    report = path / "report" / "index.html"
    _atomic_write(report, page)
    return report


def _render_view(
    task_id: str, view: dict[str, Any], current_id: str | None,
    round_views: dict[str, Any] | None = None,
) -> tuple[str, dict[str, Any]]:
    manifest = view["manifest"] if isinstance(view["manifest"], dict) else {}
    esc = _text
    cases = [case for case in manifest.get("cases", []) or [] if isinstance(case, dict)]
    cases.sort(key=lambda case: case.get("kind") == "ui")
    case_ids = {case.get("id") for case in cases}
    assets = [asset for asset in view["assets"] if isinstance(asset, dict)]
    ui_items = [item for item in manifest.get("ui_acceptance", []) or [] if isinstance(item, dict)]
    selected_round = view.get("round") or {}
    historical = bool(selected_round) and selected_round["id"] != current_id
    title = str(manifest.get("title") or task_id)
    lightbox_assets: list[dict[str, str]] = []

    def state(verdict: Any) -> str:
        return {"通过": "pass", "不通过": "fail"}.get(str(verdict or "").strip(), "unknown")

    def badge(verdict: Any) -> str:
        symbol = '<path d="m2 6 2.6 2.6L10 3.5"/>' if state(verdict) == "pass" else '<path d="M6 2v5m0 2v1"/>'
        return (f'<span class="status {state(verdict)}"><svg viewBox="0 0 12 12" fill="none" '
                f'stroke="currentColor" stroke-width="1.5" aria-hidden="true">{symbol}</svg>{esc(verdict or "信息不足")}</span>')

    def metadata(asset: dict[str, Any]) -> dict[str, Any]:
        value = asset.get("metadata")
        return value if isinstance(value, dict) else {}

    def media(asset: dict[str, Any]) -> str:
        href = asset.get("path")
        if not isinstance(href, str) or not re.fullmatch(r"\.\./assets/[A-Za-z0-9._-]+", href):
            return ""
        if Path(href).name in {".", ".."}:
            return ""
        info = metadata(asset)
        label = str(asset.get("label") or "证据")
        note = str(asset.get("note") or label)
        details = []
        if selected_round:
            details.extend([("采集时间", asset.get("captured_at") or "未知"),
                            ("来源轮次", asset.get("round_id") or "未知")])
            if asset.get("supersedes"):
                details.append(("替代 " + "、".join(asset["supersedes"]), asset.get("replacement_reason") or "未记录"))
        if info.get("width") and info.get("height"):
            details.append(("图像尺寸", f'{info["width"]} × {info["height"]} px'))
        if info.get("viewport"):
            details.append(("视口", info["viewport"]))
        mode = {"full_page": "全页截图", "viewport": "视口截图"}.get(info.get("capture_mode"), "未记录")
        if asset.get("kind") not in {"audio", "video"}:
            details.append(("采集方式", mode))
        if info.get("page_ref"):
            details.append(("页面", info["page_ref"]))
        detail_text = " · ".join(f"{key}：{value}" for key, value in details)
        kind = asset.get("kind")
        if kind == "video":
            element = f'<video controls preload="metadata" src="{esc(href)}" aria-label="{esc(label)}"></video>'
        elif kind == "audio":
            element = f'<audio controls preload="metadata" src="{esc(href)}" aria-label="{esc(label)}"></audio>'
        else:
            index = len(lightbox_assets)
            lightbox_assets.append({"src": href, "label": label, "note": note, "meta": detail_text,
                                    "caseId": str(info.get("case_id") or "未归类")})
            element = (f'<button type="button" class="image-button" data-image="{index}" aria-label="放大：{esc(label)}">'
                       f'<img src="{esc(href)}" alt="{esc(label)}">'
                       '<span class="expand-icon" aria-hidden="true">↗</span></button>')
        proof_prefix = "原始证据说明（未复核）：" if selected_round.get("legacy") else ""
        detail_html = "".join(f'<div>{esc(key)}：{esc(value)}</div>' for key, value in details)
        return (f'<figure>{element}<figcaption>{esc(label)}</figcaption><p class="proof">{esc(proof_prefix + note)}</p>'
                f'<details class="asset-details"><summary>证据详情</summary>{detail_html}</details></figure>')

    def evidence(items: list[dict[str, Any]]) -> str:
        groups: dict[Any, list[dict[str, Any]]] = {}
        singles = []
        for asset in items:
            comparison_id = metadata(asset).get("comparison_id")
            if comparison_id is None:
                singles.append(asset)
            else:
                groups.setdefault(comparison_id, []).append(asset)
        comparisons = []
        for comparison_id, group in groups.items():
            if len(group) < 2:
                singles.extend(group)
                continue
            ordered = sorted(group, key=lambda asset: {"before": 0, "after": 2}.get(asset.get("kind"), 1))
            comparisons.append(f'<section class="comparison" aria-label="前后对比：{esc(comparison_id)}">'
                               '<p class="group-label">前后对比</p><div class="pair">'
                               + "".join(media(asset) for asset in ordered) + '</div></section>')
        blocks = comparisons + [f'<div class="media-group single">{media(asset)}</div>' for asset in singles]
        return f'<div class="evidence gallery wide {"has-comparison" if comparisons else ""}">' + "".join(blocks) + '</div>'

    def ui_checks(checks):
        rows = []
        for check in checks:
            verdict = check.get("verdict") or "信息不足"
            symbol = "✓" if state(verdict) == "pass" else "!"
            rows.append(f'<li><span class="check-mark {state(verdict)}" aria-hidden="true">{symbol}</span><div>'
                        f'<strong>检查点与预期：{esc(check.get("criterion") or "未记录")}</strong>'
                        f'<p>实际观察：{esc(check.get("observed") or "未记录")} · 结论：{esc(verdict)}</p></div></li>')
        return '<ul class="checks">' + "".join(rows) + '</ul>' if rows else ""

    def ui_evidence(case, items, checks):
        asset_index = {asset["asset_id"]: asset for asset in items}
        paired = set()
        blocks = []
        for pair in case.get("ui_comparisons", []):
            blocks.append(f'<section class="ui-comparison" data-comparison-id="{esc(pair["id"])}">'
                          f'<header><strong>{esc(pair["platform"])}</strong> · '
                          f'<a href="{esc(pair["design_url"])}" target="_blank" rel="noreferrer">查看 Figma 节点 ↗</a></header>'
                          '<div class="ui-pair">')
            for field, label in (("design_asset_id", "Figma 设计稿"), ("implementation_asset_id", "实际实现")):
                asset_id = pair.get(field)
                asset = asset_index.get(asset_id)
                paired.add(asset_id)
                image = media(asset) if asset else '<p class="no-media">缺少图片，当前对比证据未齐备。</p>'
                blocks.append(f'<div class="ui-side"><h4>{label}</h4>{image}</div>')
            related = [item for item in checks if item.get("ui_comparison_id") == pair["id"]]
            blocks.append('</div>' + ui_checks(related))
            if not related or any(
                any(not isinstance(item.get(field), str) or not item[field].strip() for field in ("criterion", "observed"))
                or item.get("verdict") not in ("通过", "不通过", "信息不足") for item in related
            ):
                blocks.append('<p class="no-media">本组走查记录未齐备，交付未完成。</p>')
            blocks.append('</section>')
        if not blocks:
            blocks.append('<p class="no-media">尚未登记设计稿与实现的配对证据，交付未完成。</p>')
        if any(item.get("ui_comparison_id") not in [pair["id"] for pair in case.get("ui_comparisons", [])] for item in checks):
            blocks.append('<p class="no-media">存在未关联到图片的检查点，详见操作记录；走查记录未齐备，交付未完成。</p>')
        extra = [asset for asset in items if asset["asset_id"] not in paired]
        return "".join(blocks) + (evidence(extra) if extra else "")

    counts = {key: sum(state(case.get("verdict")) == key for case in cases) for key in ("pass", "fail", "unknown")}
    if counts["fail"]:
        overall = "不通过"
    elif counts["unknown"] or not cases:
        overall = "信息不足"
    else:
        overall = "通过"
    count_text = " · ".join(f'{counts[key]} {label}' for key, label in (("pass", "通过"), ("fail", "不通过"), ("unknown", "信息不足")) if counts[key]) or "尚无场景 · 信息不足"
    summary = _paragraphs(manifest.get("summary"))
    round_reason = _paragraphs(selected_round.get("reason"))
    round_details = f'<details class="report-summary"><summary>轮次说明</summary>{round_reason}</details>' if round_reason else ""
    round_control = ""
    if selected_round:
        options = []
        for item in reversed(view["rounds"]):
            selected = " selected" if item["id"] == selected_round["id"] else ""
            prefix = "当前" if item["id"] == current_id else "历史"
            options.append(f'<option value="{esc(item["id"])}"{selected}>{prefix} · {esc(item["label"])}</option>')
        round_control = '<div class="round-control"><label for="report-round">报告轮次</label><select id="report-round">' + "".join(options) + '</select></div>'
    observed_at = selected_round.get("observed_at") or "未知"
    pieces = [
        '<div class="wrap"><header class="masthead"><div class="brand"><span class="brand-mark">M</span><span>验收报告</span></div>',
        f'<span class="task-id">{esc(task_id)}</span></header><section class="hero" id="report-top"><div class="eyebrow">',
        f'<span>{"历史快照" if historical else "当前报告"}</span><span class="dot"></span><span>观察时间：{esc(observed_at)}</span></div>',
        f'<div class="hero-title"><h1>{esc(title)}</h1><span class="status overall {state(overall)}" aria-label="场景汇总：{overall}">{count_text}</span></div>',
        f'<div class="hero-sub">{summary}</div>{round_details}',
        f'<div class="hero-bottom"><div class="stats"><span><b>{len(cases)}</b> 个场景</span>',
        f'<span><b>{counts["pass"]}</b> 个通过</span><span><b>{len(assets)}</b> 项证据</span></div>{round_control}</div></section>',
    ]
    if historical:
        warning = "历史快照，不代表当前结果"
        if selected_round.get("legacy"):
            warning += "；旧报告证据未复核，不代表证据充分或交付通过"
        pieces.append(f'<aside class="notice" role="status"><strong>{warning}</strong><p>{esc(selected_round.get("reason"))}</p></aside>')
    if view.get("evidence_warning"):
        pieces.append(f'<aside class="notice" role="alert">{esc(view["evidence_warning"])}</aside>')
    for excluded in manifest.get("excluded_cases", []) or []:
        if isinstance(excluded, dict):
            pieces.append(f'<aside class="scope-note"><strong>本轮范围说明 · {esc(excluded.get("title"))}</strong><p>{esc(excluded.get("reason"))}</p></aside>')
    pieces.append('</div>')
    if cases:
        pieces.append('<nav class="case-nav" aria-label="验收场景"><div class="wrap nav-inner">')
        for index, case in enumerate(cases):
            cid = case.get("id")
            pieces.append(f'<a href="#case-{esc(cid)}" class="{"active" if index == 0 else ""}"><span class="nav-id">{esc(cid)}</span>'
                          f'<span class="nav-title">{esc(case.get("title"))}</span><span class="nav-dot {state(case.get("verdict"))}" aria-label="{esc(case.get("verdict") or "信息不足")}"></span></a>')
        pieces.append('</div></nav>')
    pieces.append('<div class="wrap" id="report-content">')
    if not cases:
        pieces.append('<p class="empty-state">尚无验收场景，信息不足；请依据实际观察补充。</p>')
    has_ui = any(case.get("kind") == "ui" for case in cases)
    previous_kind = None
    for index, case in enumerate(cases, 1):
        kind = "ui" if case.get("kind") == "ui" else "functional"
        if has_ui and kind != previous_kind:
            group_cases = [item for item in cases if (item.get("kind") == "ui") == (kind == "ui")]
            group_counts = " · ".join(f'{sum(state(item.get("verdict")) == status for item in group_cases)} {label}'
                                      for status, label in (("pass", "通过"), ("fail", "不通过"), ("unknown", "信息不足")))
            pieces.append(f'<header class="case-section" id="section-{kind}"><h2>{"UI 走查" if kind == "ui" else "功能验收"}</h2><p>{group_counts}</p></header>')
        previous_kind = kind
        cid = case.get("id")
        items = [asset for asset in assets if metadata(asset).get("case_id") == cid]
        checks = [item for item in ui_items if item.get("case_id") == cid]
        pieces.append(f'<article class="case" id="case-{esc(cid)}"><header class="case-heading"><span class="case-number">{index:02d}</span>'
                      f'<h2>{esc(case.get("title"))}</h2>{badge(case.get("verdict"))}</header>'
                      f'<p class="claim"><span class="case-ref">{esc(cid)}</span>{esc(case.get("claim"))}</p><div class="story">'
                      f'{ui_evidence(case, items, checks) if kind == "ui" else ""}'
                      f'<section class="observation"><h3 class="section-label">实际观察</h3>{_paragraphs(case.get("observed"))}</section>'
                      f'<details class="execution"{" open" if kind == "ui" else ""}><summary>操作记录{f"与 {len(checks)} 项 UI 验收" if checks else ""}</summary>'
                      f'<div class="execution-content"><h3 class="section-label">输入与操作</h3><p>{esc(case.get("input"))}</p>')
        pair_ids = [pair["id"] for pair in case.get("ui_comparisons", [])] if kind == "ui" else []
        pieces.append(ui_checks([item for item in checks if item.get("ui_comparison_id") not in pair_ids]))
        pieces.append('</div></details>')
        if items and kind != "ui":
            pieces.append(f'<header class="evidence-heading"><h3>证据 <span>· {len(items)}</span></h3><span>点击图片查看原图</span></header>{evidence(items)}')
        elif kind != "ui":
            pieces.append('<p class="no-media">本场景未展示媒体，请结合实际观察与证据要求判断。</p>')
        pieces.append('</div></article>')
    orphan_ui = [item for item in ui_items if item.get("case_id") not in case_ids]
    if orphan_ui:
        pieces.append('<section class="orphan"><h2>未归类 UI 验收</h2>')
        pieces.extend(f'<p>{esc(item.get("criterion"))} {esc(item.get("observed"))} {esc(item.get("verdict"))}</p>' for item in orphan_ui)
        pieces.append('</section>')
    unassigned = [asset for asset in assets if metadata(asset).get("case_id") not in case_ids]
    if unassigned:
        pieces.append('<section class="orphan"><h2>未归类证据</h2>' + evidence(unassigned) + '</section>')
    pieces.append('<footer class="footer"><span>依据已记录的观察与证据整理</span><a href="#report-top">返回顶部 ↑</a></footer></div>')
    content = "".join(pieces)
    resources = Path(__file__).with_name("report_ui")
    css = (resources / "report.css").read_text(encoding="utf-8")
    js = (resources / "report.js").read_text(encoding="utf-8")
    # 历史正文只在选中后进入 DOM；转义 HTML 起始符以保护内联脚本边界。
    gallery_data = json.dumps(lightbox_assets, ensure_ascii=False).replace("<", "\\u003c")
    round_data = json.dumps(round_views or {}, ensure_ascii=False).replace("<", "\\u003c")
    viewer = ('<div class="lightbox" role="dialog" aria-modal="true" aria-labelledby="viewer-title" aria-hidden="true">'
              '<header class="viewer-toolbar"><div><p id="viewer-title"></p><small id="viewer-position"></small></div>'
              '<div class="viewer-actions"><button id="viewer-zoom" aria-pressed="false">原始尺寸</button>'
              '<button id="viewer-close" aria-label="关闭图片">关闭 ×</button></div></header>'
              '<div class="viewer-stage" tabindex="0" aria-label="图像区域，可滚动查看原始尺寸"><img id="viewer-image" alt=""></div>'
              '<button class="viewer-arrow prev" id="viewer-prev" aria-label="上一张">‹</button>'
              '<button class="viewer-arrow next" id="viewer-next" aria-label="下一张">›</button>'
              '<footer class="viewer-bottom"><span id="viewer-meta"></span><p id="viewer-caption"></p></footer></div>')
    page = ('<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<title>{esc(title)}</title><style>{css}</style></head><body><a class="skip" href="#report-content">跳到验收内容</a>'
            f'<main>{content}</main>{viewer}<script>let lightboxAssets={gallery_data};const roundViews={round_data};\n{js}</script></body></html>')
    return page, {"html": content, "assets": lightbox_assets, "title": title}
