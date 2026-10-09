"""报告媒体的可验证元数据；不推断采集环境或业务关系。"""
from __future__ import annotations

import copy
import math
from pathlib import Path
from typing import Any
import warnings

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
META_FIELDS = ("case_id", "page_ref", "comparison_id", "viewport", "capture_mode", "width", "height", "platform", "device", "duration_seconds", "chapters")


def image_dimensions(path: Path) -> dict[str, int]:
    if path.suffix.lower() not in IMAGE_EXTENSIONS:
        return {}
    try:
        from PIL import Image
    except ImportError as exc:
        raise ValueError("图片检查需要 Pillow；请安装 moe-acceptance/requirements-report.txt") from exc
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(path) as image:
                width, height = image.size
                orientation = image.getexif().get(274)
                image.load()
            # 浏览器默认应用 EXIF 方向；记录呈现后的像素轴，不把它当作 viewport。
            if orientation in {5, 6, 7, 8}:
                width, height = height, width
    except (OSError, ValueError, SyntaxError, Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
        raise ValueError("图片无法解码或尺寸超过安全限制，请检查原文件") from exc
    return {"width": width, "height": height}


def complete_image_metadata(path: Path, raw: Any, *, corrections: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ValueError("证据 metadata 必须是对象")
    result = copy.deepcopy(raw)
    for key, value in image_dimensions(path).items():
        if key in result and (type(result[key]) is not int or result[key] != value):
            change = {"field": key, "before": result[key], "after": value}
            if corrections is not None:
                corrections.append(change)
            warnings.warn(f"图片 {key} 已采用文件实际尺寸：{result[key]!r} → {value}", UserWarning, stacklevel=2)
        result[key] = value
    for key in ("case_id", "page_ref", "comparison_id", "viewport", "capture_mode", "platform", "device"):
        if key in result and (not isinstance(result[key], str) or not result[key].strip()):
            raise ValueError(f"证据 {key} 必须是非空文本")
    if result.get("capture_mode") not in {None, "viewport", "full_page"}:
        raise ValueError("capture_mode 必须是 viewport 或 full_page")
    for key in ("width", "height", "duration_seconds"):
        value = result.get(key)
        if key not in result:
            continue
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
            raise ValueError(f"证据 {key} 必须是正有限数值")
        if key in {"width", "height"} and not isinstance(value, int):
            raise ValueError(f"证据 {key} 必须是正整数")
    chapters = result.get("chapters", [])
    if not isinstance(chapters, list):
        raise ValueError("chapters 必须是时间点列表")
    for chapter in chapters:
        if not isinstance(chapter, dict) or set(chapter) != {"time", "label"}:
            raise ValueError("每个时间点必须提供 time（秒）和 label")
        time = chapter["time"]
        if isinstance(time, bool) or not isinstance(time, (int, float)) or not math.isfinite(time) or time < 0:
            raise ValueError("视频时间点必须是非负有限秒数")
        if not isinstance(chapter["label"], str) or not chapter["label"].strip():
            raise ValueError("视频时间点说明不能为空")
        if "duration_seconds" in result and time > result["duration_seconds"]:
            raise ValueError("视频时间点不能超过已记录时长")
    return result
