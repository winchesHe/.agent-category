#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""tech-doc-architect 的确定性校验入口。"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from tda.commands import ALL  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="校验技术架构内容模型、文档集和跨载体语义一致性。"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    for command in ALL:
        command.register(subparsers)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    return args._handler(args)


if __name__ == "__main__":
    raise SystemExit(main())
