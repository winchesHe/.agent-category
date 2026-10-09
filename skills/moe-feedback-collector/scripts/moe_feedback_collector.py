#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.9"
# dependencies = [
#   "python-dotenv>=1.0.0,<2",
# ]
# ///
from __future__ import annotations

import argparse
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from mfc.commands import ALL
from mfc.config import load_config
from mfc.errors import CliError
from mfc.formatter import output


def build_parser():
    parser = argparse.ArgumentParser(
        description="MoeGo 全渠道需求反馈采集器（Canny + Intercom + Jira + Facebook）"
    )
    parser.add_argument(
        "--format",
        choices=["json", "human", "summary"],
        default="json",
        help="输出格式（默认 json）",
    )
    parser.add_argument("--wiki-url", default="", help="覆盖飞书 Wiki 控制页")
    parser.add_argument("--output-root", default="", help="覆盖本地证据根目录")
    subparsers = parser.add_subparsers(dest="command", required=True)
    for command in ALL:
        command.register(subparsers)
    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        config = load_config(
            wiki_url=args.wiki_url or None,
            output_root=args.output_root or None,
        )
        result = args._handler(args, config)
        output(result, args.format)
        return 0
    except CliError as exc:
        print(f"{exc.code}: {exc}", file=sys.stderr)
        return exc.exit_code
    except KeyboardInterrupt:
        print("操作已取消", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
