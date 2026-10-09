"""导出前的确定性诊断；不决定业务结论或替代画面审阅。"""
from __future__ import annotations

from pathlib import Path
import json
import warnings
from typing import Any

if __package__:
    from . import delivery_artifacts as reports
    from .report_media import IMAGE_EXTENSIONS, complete_image_metadata
else:
    import delivery_artifacts as reports
    from report_media import IMAGE_EXTENSIONS, complete_image_metadata


class ExportValidationError(ValueError):
    def __init__(self, diagnostics: list[dict[str, Any]]):
        self.diagnostics = diagnostics
        super().__init__(json.dumps(diagnostics, ensure_ascii=False))


class ExportFileNotFoundError(ExportValidationError, FileNotFoundError):
    """保留已有调用方对缺失文件的异常处理。"""


class ExportDiagnosticsWarning(UserWarning):
    def __init__(self, diagnostics: list[dict[str, Any]]):
        self.diagnostics = diagnostics
        super().__init__(json.dumps(diagnostics, ensure_ascii=False))


def assessment(task_id: str, issues: list[dict[str, Any]]) -> dict[str, Any]:
    counts = {level: sum(item["severity"] == level for item in issues) for level in ("error", "warning", "info")}
    return {"schema_version": 1, "task_id": task_id, "can_export": counts["error"] == 0,
            "requires_review": counts["warning"] > 0, "counts": counts, "diagnostics": issues}


def enforce(result: dict[str, Any]) -> None:
    if not result["can_export"]:
        exception = ExportValidationError
        if any(item["code"] == "asset_missing" and item["severity"] == "error" for item in result["diagnostics"]):
            exception = ExportFileNotFoundError
        raise exception(result["diagnostics"])
    review = [item for item in result["diagnostics"] if item["severity"] == "warning"]
    if review:
        warnings.warn(ExportDiagnosticsWarning(review), stacklevel=2)


def diagnostic(code: str, severity: str, category: str, message: str, suggested_action: str,
               *, round_id: str | None = None, case_id: str | None = None,
               asset_ids: list[str] | None = None, field: str = "") -> dict[str, Any]:
    return reports._clean({"code": code, "severity": severity, "category": category,
                           "round_id": round_id, "case_id": case_id, "asset_ids": asset_ids or [],
                           "field": field, "message": message, "suggested_action": suggested_action})


def inspect_report(task: Path, task_id: str, case_fields: tuple[str, ...], *, target: str = "sites") -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    try:
        data = reports._read_manifest(reports._task_dir(task, task_id), task_id)
        if target == "sites" and data.get("schema_version") != 2:
            raise ValueError("Sites 导出需要显式轮次和 evidence_ids；请先通过 update 升级旧报告")
        entries = reports._round_entries(data) if data.get("schema_version") == 2 else [
            {"id": None, "legacy": True, "manifest": data["manifest"],
             "asset_ids": [asset["asset_id"] for asset in data["assets"]]}]
    except (ValueError, OSError) as exc:
        return [diagnostic("report_invalid", "error", "structure", str(exc),
                           "检查任务目录和报告结构；旧报告用现有 update API 显式升级。", field="manifest")]
    index = reports._asset_index(data)
    media_cache: dict[str, dict[str, Any] | Exception] = {}
    for entry in entries:
        round_id = entry["id"]
        historical = round_id != data.get("current_round", {}).get("id")
        legacy_cases = entry["manifest"].get("cases", [])
        if entry.get("legacy") and isinstance(legacy_cases, list) and any(
            isinstance(case, dict) and (case.get("kind") == "ui" or "ui_comparisons" in case)
            for case in legacy_cases
        ):
            issues.append(diagnostic("ui_round_required", "error", "structure",
                                     "UI 走查需要显式轮次，不能使用旧图集的隐式采用关系。",
                                     "通过 update 和 report_round 升级旧报告，再显式采用配对证据。",
                                     round_id=round_id, field="cases/ui_comparisons"))
            continue
        if entry.get("legacy") and target == "sites":
            issues.append(diagnostic("legacy_text_only", "info", "content", "旧快照仅导出未经复核的历史文字。",
                                     "需要发布旧媒体时，先检查并显式采用有效证据。", round_id=round_id))
            continue
        content = entry["manifest"]
        cases = content.get("cases", [])
        legacy = entry.get("legacy", False)
        if legacy:
            # HTML 兼容旧图集的全量展示，不为旧记录补造 Case 或采用关系。
            cases = [{"id": (index[asset_id]["metadata"].get("case_id")
                             if isinstance(index[asset_id].get("metadata"), dict) else None), "evidence_ids": [asset_id]}
                     for asset_id in entry["asset_ids"] if asset_id in index]
        try:
            if not isinstance(cases, list) or any(not isinstance(case, dict) for case in cases):
                raise ValueError("cases 必须是 Case 对象列表")
            case_ids = [] if legacy else reports._ids([case.get("id") for case in cases], "case_id")
            if any(asset_id not in index for asset_id in entry["asset_ids"]):
                raise ValueError("轮次的 asset_ids 引用了未知资产")
        except ValueError as exc:
            issues.append(diagnostic("round_invalid", "error", "structure", str(exc),
                                     "修正该轮次的结构或引用，保留原始快照备份。", round_id=round_id, field="cases/asset_ids"))
            continue
        ui = content.get("ui_acceptance", [])
        if not legacy and (not isinstance(ui, list) or any(not isinstance(item, dict) or item.get("case_id") not in case_ids for item in ui)):
            issues.append(diagnostic("ui_reference_invalid", "error", "references", "UI 条目未引用该轮次有效的 Case。",
                                     "核对 ui_acceptance 的 Case 归属。", round_id=round_id, field="ui_acceptance"))
        for case in cases:
            context = {"round_id": round_id, "case_id": case["id"]}
            try:
                ids = reports._ids(case.get("evidence_ids"), "evidence_ids")
            except ValueError as exc:
                issues.append(diagnostic("selection_invalid", "error", "references", str(exc),
                                         "显式提供去重后的证据 ID 列表；非视觉 Case 可使用空列表。", **context, field="evidence_ids"))
                continue
            if not historical and not legacy:
                for field in ("title", "claim", "observed"):
                    if not case.get(field) or (isinstance(case[field], str) and not case[field].strip()):
                        issues.append(diagnostic("case_content_missing", "warning", "content", f"Case 缺少 {field}。",
                                                 "依据已有验收事实补充说明；缺观察时明确其限制，不补写通过。", **context, field=field))
                if case.get("verdict") not in ("通过", "不通过", "信息不足"):
                    issues.append(diagnostic("verdict_unrecognized", "warning", "content", "Case 结论不属于三态，页面将显示信息不足。",
                                             "由 Agent 根据已有观察明确业务结论。", **context, field="verdict"))
                for field in sorted(set(case) - set(case_fields)):
                    issues.append(diagnostic("content_not_rendered", "warning", "presentation", f"Case 字段 {field} 不在当前 {target} 展示合同内。",
                                             "核对该信息是否影响评审；必要说明放入受支持字段，或明确调整模板。", **context, field=field))
            try:
                reports.validate_ui_case(case, index)
            except ValueError as exc:
                issues.append(diagnostic("ui_comparison_invalid", "error", "relationships", str(exc),
                                         "修正 UI Case 的配对字段及显式图片引用。", **context, field="ui_comparisons"))
            if not historical and case.get("kind") == "ui":
                pairs = case.get("ui_comparisons", [])
                pair_ids = {pair.get("id") for pair in pairs if isinstance(pair, dict) and isinstance(pair.get("id"), str)} if isinstance(pairs, list) else set()
                checks = [item for item in ui if isinstance(item, dict) and item.get("case_id") == case["id"]] if isinstance(ui, list) else []
                linked = {item.get("ui_comparison_id") for item in checks if isinstance(item.get("ui_comparison_id"), str)}
                if linked - pair_ids or any(
                    "ui_comparison_id" in item and not isinstance(item["ui_comparison_id"], str) for item in checks
                ):
                    issues.append(diagnostic("ui_check_reference_invalid", "error", "references",
                                             "UI 检查点引用了该 Case 中不存在的配对。",
                                             "核对 ui_comparison_id；未关联的旧记录可保留，但不能当作逐图走查齐备。",
                                             **context, field="ui_acceptance.ui_comparison_id"))
                if not checks or pair_ids - linked or any(
                    not item.get("ui_comparison_id") or
                    any(not isinstance(item.get(field), str) or not item[field].strip() for field in ("criterion", "observed")) or
                    item.get("verdict") not in ("通过", "不通过", "信息不足")
                    for item in checks
                ):
                    issues.append(diagnostic("ui_checks_incomplete", "warning", "content",
                                             "UI 走查记录未齐备：每组图片需有对应检查点、设计预期、实际观察与结论。",
                                             "按实际对比补充关联及记录；可导出草稿，但交付未完成。",
                                             **context, field="ui_acceptance"))
                if case.get("verdict") == "通过" and any(item.get("verdict") != "通过" for item in checks):
                    issues.append(diagnostic("ui_verdict_conflict", "error", "content",
                                             "UI Case 为通过，但存在未通过或未明确结论的检查点。",
                                             "复核实际证据并修正矛盾，不自动改写 Case 或检查点结论。",
                                             **context, field="ui_acceptance.verdict"))
                if isinstance(pairs, list) and (not pairs or any(
                    isinstance(pair, dict) and (not pair.get("design_asset_id") or not pair.get("implementation_asset_id"))
                    for pair in pairs
                )):
                    issues.append(diagnostic("ui_comparison_incomplete", "warning", "relationships",
                                             "UI 走查缺少设计稿或实现截图，不能将报告视为证据齐备。",
                                             "补选有效原图；原始证据缺失时按授权补验，不自动改变业务结论。",
                                             **context, field="ui_comparisons"))
            images = []
            for asset_id in ids:
                location = {**context, "asset_ids": [asset_id]}
                if asset_id not in entry["asset_ids"]:
                    issues.append(diagnostic("asset_reference_invalid", "error", "references", "证据 ID 不属于该轮次可用资产。",
                                             "核对 evidence_ids 和资产来源轮次；不要把后续采集伪装成历史证据。", **location, field="evidence_ids"))
                    continue
                asset = index[asset_id]
                if asset_id not in media_cache:
                    try:
                        if asset.get("kind") not in tuple(reports.ASSET_KINDS):
                            raise ValueError("资产 kind 不属于支持的媒体类型")
                        file = reports._asset_file(task, asset)
                        media_cache[asset_id] = complete_image_metadata(file, asset.get("metadata", {}))
                    except (ValueError, OSError) as exc:
                        media_cache[asset_id] = exc
                metadata = media_cache[asset_id]
                if isinstance(metadata, Exception):
                    missing = isinstance(metadata, FileNotFoundError)
                    issues.append(diagnostic("asset_missing" if missing else "asset_invalid",
                                             "warning" if missing and historical else "error", "media", str(metadata),
                                             "核对原文件和 metadata；缺失历史媒体会保留文字并隐藏该轮图集，当前无效媒体需恢复或替换。",
                                             **location, field="path" if missing else "metadata/file"))
                    continue
                if metadata.get("case_id") not in {None, case["id"]}:
                    issues.append(diagnostic("asset_owner_conflict", "error", "references", "证据 metadata 与采用它的 Case 归属冲突。",
                                             "核对归属，通过 update_asset_metadata 或 update 修正。", **location, field="metadata.case_id"))
                original = asset.get("metadata", {})
                corrected = {key: {"before": original[key], "after": metadata[key]} for key in ("width", "height")
                             if key in original and key in metadata and
                             (type(original[key]) is not type(metadata[key]) or original[key] != metadata[key])}
                if corrected:
                    issues.append(diagnostic("image_dimensions_corrected", "info", "metadata",
                                             "导出副本已采用文件实际尺寸：" + json.dumps(corrected, ensure_ascii=False),
                                             "原记录保持不变；需要写回时调用 update_asset_metadata 留痕。",
                                             **location, field="metadata.width/height"))
                if any(key not in original for key in ("width", "height")) and Path(asset["path"]).suffix in IMAGE_EXTENSIONS:
                    issues.append(diagnostic("image_dimensions_completed", "info", "metadata", "已取得图片实际宽高，将补入导出副本。",
                                             "可用 update_asset_metadata 的空补丁将实际尺寸留痕写回；不改写原 viewport。", **location, field="metadata.width/height"))
                if not historical and (not asset.get("label") or not str(asset["label"]).strip()):
                    issues.append(diagnostic("asset_label_missing", "warning", "presentation", "媒体缺少可读标题，页面会使用资产 ID。",
                                             "核对现有说明能否定位对象和观察目的，必要时补充报告说明。", **location, field="label"))
                if Path(asset["path"]).suffix in IMAGE_EXTENSIONS:
                    images.append({**asset, "metadata": metadata})
            if historical or legacy:
                continue
            groups: dict[str, list[dict[str, Any]]] = {}
            for image in images:
                comparison = image["metadata"].get("comparison_id")
                if comparison:
                    groups.setdefault(comparison, []).append(image)
            for group in groups.values():
                if len(group) != 2 or {image["kind"] for image in group} != {"before", "after"}:
                    issues.append(diagnostic("comparison_ambiguous", "warning", "relationships", "对比组不是明确的一张 before 和一张 after。",
                                             "检查场景与观察阶段；补齐、拆分关系或说明当前展示的限制，不自动配对。",
                                             **context, asset_ids=[image["asset_id"] for image in group], field="metadata.comparison_id"))
            unpaired = [image for image in images if image["kind"] in {"before", "after"} and not image["metadata"].get("comparison_id")]
            if unpaired and {image["kind"] for image in images} >= {"before", "after"}:
                issues.append(diagnostic("comparison_unassigned", "warning", "relationships", "Case 包含前后证据，但部分图片没有明确展示关系。",
                                         "由 Agent 核对后补 comparison_id，或在报告更新说明中记录独立展示理由。",
                                         **context, asset_ids=[image["asset_id"] for image in unpaired], field="metadata.comparison_id"))
    return issues
