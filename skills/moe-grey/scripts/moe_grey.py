#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.9"
# dependencies = [
#   "requests>=2.31.0,<3",
# ]
# ///
import argparse
import sys

from mgrey.commands import register
from mgrey.config import load_config
from mgrey.errors import CliError
from mgrey.formatter import output


def build_parser():
    parser = argparse.ArgumentParser(prog="moe-grey", description="MoeGo Grey 查询与受控 CRUD CLI")
    parser.add_argument("--format", choices=["json", "human", "summary"], default="json")
    register(parser.add_subparsers(dest="grey_action", required=True))
    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args._handler(args, load_config()) or 0)
    except CliError as exc:
        print(str(exc), file=sys.stderr)
        return exc.exit_code
    except KeyboardInterrupt:
        print("操作已取消", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
