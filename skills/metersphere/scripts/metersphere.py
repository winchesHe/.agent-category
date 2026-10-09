#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
from __future__ import annotations

import argparse
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from mscli.client import Client
from mscli.commands import run
from mscli.config import load_config
from mscli.errors import MeterSphereError
from mscli.formatter import output


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description="MeterSphere 测试资产 API CLI")
    value.add_argument("--format", choices=("json", "human", "summary"), default="json")
    value.add_argument("command", nargs="?", help="doctor/raw 或资源名")
    value.add_argument("args", nargs=argparse.REMAINDER, help="动作及参数")
    return value


def main() -> int:
    args = parser().parse_args()
    if not args.command:
        parser().print_help()
        return 0
    try:
        config = load_config(require_auth=True)
        result = run(config, Client(config, timeout=config.timeout_seconds), args.command, args.args)
        if isinstance(result, str) and args.command.endswith("-md"):
            print(result, end="" if result.endswith("\n") else "\n")
        else:
            output(result, args.format)
        return 0
    except MeterSphereError as exc:
        print(f"错误: {exc}", file=sys.stderr)
        return exc.code


if __name__ == "__main__":
    raise SystemExit(main())
