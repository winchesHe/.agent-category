#!/usr/bin/env python3
"""Jira CLI - single entry point."""
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
from __future__ import annotations

import argparse
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from ji.config import load_config  # noqa: E402
from ji.errors import EXIT_API_ERROR, JiraCliError  # noqa: E402


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="jira",
        description="Jira 查询与工单创建 CLI（winches-skills/jira）",
    )
    sub = parser.add_subparsers(dest="command", metavar="<subcommand>")
    sub.required = True

    from ji.commands import ALL  # noqa: PLC0415

    for mod in ALL:
        mod.register(sub)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    handler = getattr(args, "_handler", None)
    if handler is None:
        parser.print_help(sys.stderr)
        return 1

    try:
        config = load_config()
        return int(handler(args, config) or 0)
    except KeyboardInterrupt:
        sys.stderr.write("[jira] interrupted\n")
        return 130
    except SystemExit as exc:
        return exc.code if isinstance(exc.code, int) else 1
    except JiraCliError as exc:
        prefix = f"{exc.error_code}: " if exc.error_code else ""
        sys.stderr.write(f"[jira] {prefix}{exc.message}\n")
        return exc.code
    except Exception as exc:
        sys.stderr.write(f"[jira] {exc}\n")
        return EXIT_API_ERROR


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
