"""统一 CLI 输出。"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any


OUTPUT_FORMATS = ("json", "human", "summary")


def add_format_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--format",
        choices=OUTPUT_FORMATS,
        default="json",
        help="输出格式，默认 json",
    )


def output(payload: dict[str, Any], output_format: str) -> None:
    if output_format == "json":
        sys.stdout.write(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
        return

    message = str(payload.get("message", ""))
    if output_format == "summary":
        state = "通过" if payload.get("ok") else "失败"
        sys.stderr.write(f"{payload.get('command')}: {state} — {message}\n")
        return

    sys.stderr.write(message + "\n")
    if not payload.get("ok"):
        for error in payload.get("errors", []):
            sys.stderr.write(f"- {error}\n")
