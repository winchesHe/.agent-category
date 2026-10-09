"""search-trace-logs: find bounded log events correlated to one trace."""
from __future__ import annotations

from typing import Any

from dd_v3.argtypes import bounded_int_type
from dd_v3.log_analysis import (
    LOG_SEARCH_PATH,
    build_log_search_payload,
    cursor_pagination,
    data_items,
    normalize_log,
    normalize_time_range,
    response_coverage,
    trace_query,
)
from dd_v3.runtime import READ, CommandResult, RuntimeContext
from dd_v3.timeutil import now_millis

NAME = "search-trace-logs"


def register(subparsers) -> None:
    parser = subparsers.add_parser(NAME, help="按 Trace ID 搜索关联日志")
    parser.add_argument("trace_id", metavar="TRACE_ID", help="Trace ID")
    parser.add_argument("--from", required=True, dest="from_time", help="起始时间")
    parser.add_argument("--to", default="now", dest="to_time", help="结束时间，默认 now")
    parser.add_argument(
        "--limit",
        type=bounded_int_type("--limit", 1, 1000),
        default=100,
        help="返回上限，默认 100，最大 1000",
    )
    parser.add_argument("--cursor", help="继续上一页的游标")
    parser.add_argument("--format", dest="fmt", choices=["json", "summary"], default="json")
    parser.set_defaults(_handler=run, _policy=READ)


def build_payload(args, *, now_ms: int) -> tuple[dict[str, Any], str, str, str]:
    query = trace_query(args.trace_id)
    from_time, to_time = normalize_time_range(args.from_time, args.to_time, now_ms=now_ms)
    payload = build_log_search_payload(
        query=query,
        from_time=from_time,
        to_time=to_time,
        limit=args.limit,
        sort="timestamp",
        cursor=args.cursor,
    )
    return payload, query, from_time, to_time


def run(args, context: RuntimeContext) -> CommandResult:
    payload, query, from_time, to_time = build_payload(args, now_ms=now_millis())
    target = context.bind_target({
        "kind": "log_trace",
        "trace_id": args.trace_id,
        "query": query,
    })
    body = context.client.request_read("POST", LOG_SEARCH_PATH, json_body=payload)
    raw_logs = data_items(body)
    logs = [normalize_log(item) for item in raw_logs]
    response, warnings = response_coverage(body)
    return CommandResult(
        target=target,
        result={"trace_id": args.trace_id, "logs": logs, "returned": len(logs)},
        meta={
            "time_range": {"from": from_time, "to": to_time},
            "pagination": cursor_pagination(
                body,
                returned=len(logs),
                limit=args.limit,
                partial=response["partial"],
            ),
            "response": response,
        },
        verification=None,
        warnings=warnings,
    )
