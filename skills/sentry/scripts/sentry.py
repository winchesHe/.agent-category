#!/usr/bin/env python3
"""Sentry CLI — single entry point."""
# /// script
# requires-python = ">=3.9"
# dependencies = [
#     "requests",
# ]
# ///
from __future__ import annotations

import argparse
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from st.config import load_config  # noqa: E402
from st.errors import EXIT_API_ERROR, MissingConfigError, SentryCliError  # noqa: E402

_SUBCOMMANDS = [
    "get-issue",
    "fetch-event",
    "list-issues",
    "list-issue-events",
    "tag-values",
    "list-projects",
    "analyze",
]


def _load_subcommands():
    try:
        from st.commands import ALL
    except ModuleNotFoundError as exc:
        if exc.name == "requests":
            raise MissingConfigError("缺少 Python 依赖 requests；请使用 `uv run` 执行当前脚本的绝对路径") from exc
        raise MissingConfigError(f"命令导入失败: {exc}") from exc
    except ImportError as exc:
        raise MissingConfigError(f"命令导入失败: {exc}") from exc
    return ALL


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sentry",
        description="MoeGo Sentry 只读查询 CLI",
    )
    sub = parser.add_subparsers(dest="command", metavar="<subcommand>")
    sub.required = True

    for mod in _load_subcommands():
        mod.register(sub)

    return parser


def main(argv: list[str] | None = None) -> int:
    try:
        parser = _build_parser()
        args = parser.parse_args(argv)

        handler = getattr(args, "_handler", None)
        if handler is None:
            parser.print_help(sys.stderr)
            return 1

        config = load_config()
        return int(handler(args, config) or 0)
    except KeyboardInterrupt:
        sys.stderr.write("[sentry] 已中断\n")
        return 130
    except SystemExit as e:
        return e.code if isinstance(e.code, int) else 1
    except SentryCliError as e:
        sys.stderr.write(f"[sentry] {e.message}\n")
        return e.code
    except Exception as e:
        sys.stderr.write(f"[sentry] {e}\n")
        return EXIT_API_ERROR


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
