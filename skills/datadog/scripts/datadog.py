#!/usr/bin/env python3
"""Datadog CLI — single entry point.

环境变量：
    DD_API_KEY / DD_APP_KEY   认证密钥（必填）
    DD_SITE                   API 地址，默认 https://api.us5.datadoghq.com
    DD_DEFAULT_ENV            默认环境，默认 ns-production

用法：
    python3 datadog.py <subcommand> [flags]
"""
# /// script
# requires-python = ">=3.9"
# dependencies = [
#     "requests",
#     "python-dateutil",
# ]
# ///
from __future__ import annotations

import argparse
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from dd.config import load_config  # noqa: E402
from dd.errors import DatadogCliError, EXIT_API_ERROR  # noqa: E402

_SUBCOMMANDS = [
    "search-logs",
    "aggregate-logs",
    "get-trace",
    "search-spans",
    "get-dependencies",
    "list-services",
    "get-dashboard",
    "query-metrics",
]

_SUPPLEMENTAL_COMMANDS = {
    "search-trace-logs": "按 trace_id 搜索关联日志",
    "get-log-context": "读取目标日志前后的上下文",
    "summarize-errors": "聚合错误日志并输出代表样本",
    "compare-log-counts": "比较两个时间窗口的日志数量",
    "group-log-patterns": "按消息模式聚类日志",
    "list-log-services": "列出日志中的服务",
    "list-dashboards": "分页列出 Dashboard",
    "list-dashboard-lists": "分页列出 Dashboard List",
    "get-dashboard-list": "读取单个 Dashboard List",
    "list-dashboard-list-items": "列出 Dashboard List 中的条目",
    "scan-slow-sql": "扫描慢 SQL Trace",
    "list-monitors": "分页列出 Monitors",
    "search-monitors": "搜索 Monitors",
    "get-monitor": "读取单个 Monitor",
    "list-datastores": "列出 Actions Datastore 摘要",
    "list-datastore-items": "分页读取 Actions Datastore 条目",
}


def _command_hint(argv: list[str]) -> str | None:
    for value in argv:
        if not value.startswith("-"):
            return value
    return None


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="datadog",
        description="Datadog 查询 CLI（winches-skills/datadog）",
    )
    sub = parser.add_subparsers(dest="command", metavar="<subcommand>")
    sub.required = True

    try:
        from dd.commands import ALL

        for mod in ALL:
            mod.register(sub)
    except (ImportError, AttributeError):
        for name in _SUBCOMMANDS:
            sub.add_parser(name, help=f"(未实现) {name}")

    for name, help_text in _SUPPLEMENTAL_COMMANDS.items():
        sub.add_parser(name, help=help_text)

    return parser


def main(argv: list[str] | None = None) -> int:
    values = list(sys.argv[1:] if argv is None else argv)
    if _command_hint(values) in _SUPPLEMENTAL_COMMANDS:
        from dd_v3.runtime import main as supplemental_main

        return supplemental_main(values)

    parser = _build_parser()
    args = parser.parse_args(values)

    handler = getattr(args, "_handler", None)
    if handler is None:
        parser.print_help(sys.stderr)
        return 1

    try:
        config = load_config()
        return int(handler(args, config) or 0)
    except KeyboardInterrupt:
        sys.stderr.write("[datadog] 已中断\n")
        return 130
    except SystemExit as e:
        return e.code if isinstance(e.code, int) else 1
    except DatadogCliError as e:
        sys.stderr.write(f"[datadog] {e.message}\n")
        return e.code
    except Exception as e:
        sys.stderr.write(f"[datadog] {e}\n")
        return EXIT_API_ERROR


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
