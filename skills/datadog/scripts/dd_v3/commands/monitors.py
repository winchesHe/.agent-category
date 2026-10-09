"""CLI adapters for read-only monitor queries."""
from __future__ import annotations

import argparse
from typing import Any

from dd_v3.monitor_operations import MonitorOperations
from dd_v3.runtime import CommandResult, READ, RuntimeContext

NAMES = (
    "list-monitors",
    "search-monitors",
    "get-monitor",
)


def _non_negative_int(value: str) -> int:
    parsed = int(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError("must be zero or greater")
    return parsed


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be greater than zero")
    return parsed


def _page_size(value: str) -> int:
    parsed = _positive_int(value)
    if parsed > 1000:
        raise argparse.ArgumentTypeError("must be 1000 or less")
    return parsed


def _format(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--format", dest="fmt", choices=("json", "summary"), default="json")


def register(subparsers) -> None:
    list_parser = subparsers.add_parser("list-monitors", help="分页列出 Monitors")
    list_parser.add_argument("--group-states")
    list_parser.add_argument("--name")
    list_parser.add_argument("--tags")
    list_parser.add_argument("--monitor-tags")
    list_parser.add_argument("--with-downtimes", action="store_true")
    list_parser.add_argument("--page", type=_non_negative_int, default=0)
    list_parser.add_argument("--page-size", type=_page_size, default=100)
    _format(list_parser)
    list_parser.set_defaults(_handler=run_list, _policy=READ)

    search_parser = subparsers.add_parser("search-monitors", help="搜索 Monitors")
    search_parser.add_argument("--query", required=True)
    search_parser.add_argument("--page", type=_non_negative_int, default=0)
    search_parser.add_argument("--per-page", type=_page_size, default=30)
    search_parser.add_argument("--sort", choices=("name,asc", "name,desc", "status,asc", "status,desc"))
    _format(search_parser)
    search_parser.set_defaults(_handler=run_search, _policy=READ)

    get_parser = subparsers.add_parser("get-monitor", help="读取单个 Monitor")
    get_parser.add_argument("monitor_id", type=_positive_int)
    get_parser.add_argument("--group-states")
    get_parser.add_argument("--with-downtimes", action="store_true")
    get_parser.add_argument("--with-assets", action="store_true")
    _format(get_parser)
    get_parser.set_defaults(_handler=run_get, _policy=READ)


def _compact_params(values: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in values.items() if value is not None}


def run_list(args: argparse.Namespace, context: RuntimeContext) -> CommandResult:
    params = _compact_params(
        {
            "group_states": args.group_states,
            "name": args.name,
            "tags": args.tags,
            "monitor_tags": args.monitor_tags,
            "with_downtimes": True if args.with_downtimes else None,
            "page": args.page,
            "page_size": args.page_size,
        }
    )
    target = context.bind_target(params)
    result = MonitorOperations(context.client).list(params)
    return CommandResult(target=target, result=result)


def run_search(args: argparse.Namespace, context: RuntimeContext) -> CommandResult:
    params = _compact_params(
        {
            "query": args.query,
            "page": args.page,
            "per_page": args.per_page,
            "sort": args.sort,
        }
    )
    target = context.bind_target(params)
    result = MonitorOperations(context.client).search(params)
    return CommandResult(target=target, result=result)


def run_get(args: argparse.Namespace, context: RuntimeContext) -> CommandResult:
    params = _compact_params(
        {
            "group_states": args.group_states,
            "with_downtimes": True if args.with_downtimes else None,
            "with_assets": True if args.with_assets else None,
        }
    )
    target = context.bind_target({"monitor_id": args.monitor_id})
    result = MonitorOperations(context.client).get(args.monitor_id, params)
    return CommandResult(target=target, result=result, meta={"params": params})
