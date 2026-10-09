"""UI 走查的显式配对合同；不推断设计关系或判定视觉通过。"""
from pathlib import Path
from urllib.parse import urlsplit

if __package__:
    from .report_media import IMAGE_EXTENSIONS
else:
    from report_media import IMAGE_EXTENSIONS


def validate_ui_case(case, assets):
    if case.get("kind", "functional") not in ("functional", "ui"):
        raise ValueError("Case kind 必须是 functional 或 ui")
    pairs = case.get("ui_comparisons", [])
    if not isinstance(pairs, list) or (pairs and case.get("kind") != "ui"):
        raise ValueError("ui_comparisons 必须是 UI Case 的配对列表")
    seen = set()
    for pair in pairs:
        if not isinstance(pair, dict) or set(pair) - {
            "id", "platform", "design_url", "design_asset_id", "implementation_asset_id"
        }:
            raise ValueError("UI 对比字段不合法")
        for field in ("id", "platform", "design_url"):
            if not isinstance(pair.get(field), str) or not pair[field].strip():
                raise ValueError(f"UI 对比 {field} 必须是非空文本")
        if pair["id"] in seen:
            raise ValueError("UI 对比 id 不允许重复")
        seen.add(pair["id"])
        url = urlsplit(pair["design_url"])
        if (url.scheme != "https" or url.netloc not in ("figma.com", "www.figma.com")
                or not url.path.startswith(("/design/", "/file/", "/proto/"))):
            raise ValueError("design_url 必须是 Figma HTTPS 设计节点链接")
        pair_ids = []
        for field in ("design_asset_id", "implementation_asset_id"):
            asset_id = pair.get(field)
            if asset_id is None:
                continue  # 缺图可保存为草稿；导出诊断和页面须显式显示缺口。
            if not isinstance(asset_id, str) or asset_id not in case.get("evidence_ids", []):
                raise ValueError("UI 对比图片必须来自本 Case 的 evidence_ids")
            asset = assets.get(asset_id)
            if (not asset or asset.get("kind") in ("audio", "video")
                    or Path(asset.get("path", "")).suffix.lower() not in IMAGE_EXTENSIONS):
                raise ValueError("UI 对比只能引用已登记图片")
            pair_ids.append(asset_id)
        if len(pair_ids) == 2 and pair_ids[0] == pair_ids[1]:
            raise ValueError("设计稿与实现不能引用同一资产")
