"""group-log-patterns: group a bounded log sample by normalized message."""
from __future__ import annotations

from typing import Any

from dd_v3.argtypes import bounded_int_type
from dd_v3.log_analysis import (
    LOG_SEARCH_PATH,
    build_log_search_payload,
    cursor_pagination,
    data_items,
    group_patterns,
    normalize_time_range,
    require_text,
    response_coverage,
)
from dd_v3.runtime import READ, CommandResult, RuntimeContext
from dd_v3.timeutil import now_millis

NAME = "group-log-patterns"


def register(subparsers) -> None:
    parser = subparsers.add_parser(NAME, help="按归一化消息分组日志样本")
    parser.add_argument("--query", required=True, help="Datadog 日志查询")
    parser.add_argument("--from", required=True, dest="from_time", help="起始时间")
    parser.add_argument("--to", default="now", dest="to_time", help="结束时间，默认 now")
    parser.add_argument(
        "--limit",
        type=bounded_int_type("--limit", 1, 1000),
        default=500,
        help="分析样本上限，默认 500，最大 1000",
    )
    parser.add_argument(
        "--top",
        type=bounded_int_type("--top", 1, 100),
        default=50,
        help="模式上限，默认 50，最大 100",
    )
    parser.add_argument("--format", dest="fmt", choices=["json", "summary"], default="json")
    parser.set_defaults(_handler=run, _policy=READ)


def build_payload(args, *, now_ms: int) -> tuple[dict[str, Any], str, str, str]:
    query = require_text(args.query, "--query")
    from_time, to_time = normalize_time_range(args.from_time, args.to_time, now_ms=now_ms)
    payload = build_log_search_payload(
        query=query,
        from_time=from_time,
        to_time=to_time,
        limit=args.limit,
        sort="-timestamp",
    )
    return payload, query, from_time, to_time


def run(args, context: RuntimeContext) -> CommandResult:
    payload, query, from_time, to_time = build_payload(args, now_ms=now_millis())
    target = context.bind_target({"kind": "log_patterns", "query": query})
    body = context.client.request_read("POST", LOG_SEARCH_PATH, json_body=payload)
    sample_size = len(data_items(body))
    response, warnings = response_coverage(body)
    return CommandResult(
        target=target,
        result={
            "patterns": group_patterns(body, top=args.top),
            "coverage": "sampled",
            "sample_size": sample_size,
            "requested_sample_size": args.limit,
        },
        meta={
            "time_range": {"from": from_time, "to": to_time},
            "pagination": cursor_pagination(
                body,
                returned=sample_size,
                limit=args.limit,
                partial=response["partial"],
            ),
            "response": response,
        },
        verification=None,
        warnings=warnings,
    )
