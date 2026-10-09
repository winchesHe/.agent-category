from __future__ import annotations

import json
import sys
from typing import Any

FORMAT_CHOICES = ("json", "human", "summary")


def add_format_argument(parser: Any) -> None:
    parser.add_argument(
        "--format",
        choices=FORMAT_CHOICES,
        default="json",
        help="命令结果格式；json 写 stdout，human/summary 写 stderr（默认：json）",
    )


def output(payload: dict[str, Any], output_format: str) -> None:
    if output_format == "json":
        json.dump(payload, sys.stdout, ensure_ascii=False)
        sys.stdout.write("\n")
        return

    if output_format == "summary":
        status = payload.get("status", "unknown")
        command = payload.get("command", "command")
        details = payload.get("summary") or payload.get("message") or ""
        sys.stderr.write(f"[{command}] {status}: {details}\n")
        return

    sys.stderr.write(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
