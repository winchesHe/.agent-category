from __future__ import annotations

from typing import Any

from ..audio import ffmpeg_status
from ..config import Config
from ..formatter import add_format_argument, output
from ..model import model_status
from ..platform import platform_status


def register(subparsers: Any) -> None:
    parser = subparsers.add_parser("doctor", help="检查平台、解码器和正式模型状态")
    parser.add_argument("--model-dir", help="覆盖正式模型目录")
    add_format_argument(parser)
    parser.set_defaults(_handler=run)


def run(args: Any, config: Config) -> int:
    platform_result = platform_status()
    ffmpeg_result = ffmpeg_status()
    model_result = model_status(config.model_dir, config)
    ready = bool(
        platform_result["supported"]
        and ffmpeg_result["executable"]
        and model_result["valid"]
    )
    payload = {
        "command": "doctor",
        "status": "ready" if ready else "not_ready",
        "ready": ready,
        "platform": platform_result,
        "ffmpeg": ffmpeg_result,
        "model": model_result,
        "summary": "可直接转写" if ready else "存在未满足的前置条件",
    }
    output(payload, args.format)
    return 0
