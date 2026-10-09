from __future__ import annotations

from typing import Any

from ..config import Config
from ..formatter import add_format_argument, output
from ..model import install_model
from ..platform import require_supported_platform


def register(subparsers: Any) -> None:
    parser = subparsers.add_parser("setup", help="安装模型到正式数据目录")
    parser.add_argument("--model-dir", help="覆盖正式模型目录")
    parser.add_argument("--force", action="store_true", help="重新下载并替换有效模型")
    add_format_argument(parser)
    parser.set_defaults(_handler=run)


def run(args: Any, config: Config) -> int:
    require_supported_platform()
    payload = install_model(config, force=args.force)
    payload.update(
        {
            "command": "setup",
            "summary": "模型已安装到正式目录"
            if payload["downloaded"]
            else "正式模型已存在，无需重复下载",
        }
    )
    output(payload, args.format)
    return 0
