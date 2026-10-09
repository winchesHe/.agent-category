#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = [
#   "huggingface-hub>=0.27,<2",
#   "imageio-ffmpeg==0.6.0",
#   "mlx-whisper==0.4.3",
# ]
# ///
"""MLX Whisper 本地语音转写 CLI。"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from mwt.commands import ALL
from mwt.config import load_config
from mwt.errors import (
    EXIT_CONFIG_ERROR,
    EXIT_OPERATION_ERROR,
    EXIT_PERMISSION_ERROR,
    MwtCliError,
)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="mlx-whisper-transcription",
        description="Apple Silicon Mac 本地离线语音转写 CLI",
    )
    subparsers = parser.add_subparsers(dest="command", metavar="<subcommand>")
    subparsers.required = True
    for command in ALL:
        command.register(subparsers)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    handler = getattr(args, "_handler", None)
    if handler is None:
        parser.print_help(sys.stderr)
        return EXIT_CONFIG_ERROR

    try:
        config = load_config(args)
        return int(handler(args, config) or 0)
    except KeyboardInterrupt:
        sys.stderr.write("[mlx-whisper-transcription] 已中断\n")
        return 130
    except PermissionError as error:
        sys.stderr.write(f"[mlx-whisper-transcription] 权限不足：{error}\n")
        return EXIT_PERMISSION_ERROR
    except MwtCliError as error:
        sys.stderr.write(f"[mlx-whisper-transcription] {error.message}\n")
        return error.code
    except Exception as error:  # noqa: BLE001 - CLI boundary maps unknown failures.
        sys.stderr.write(f"[mlx-whisper-transcription] 未预期错误：{error}\n")
        return EXIT_OPERATION_ERROR


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
