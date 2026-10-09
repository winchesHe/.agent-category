"""get-log-context: read bounded log windows around one timestamp."""
from __future__ import annotations

from typing import Any

from dd_v3.argtypes import bounded_int_type
from dd_v3.log_analysis import (
    LOG_SEARCH_PATH,
    build_log_search_payload,
    combine_query,
    cursor_pagination,
    data_items,
    format_rfc3339,
    normalize_instant,
    normalize_log,
    parse_duration_millis,
    merge_warnings,
    response_coverage,
)
from dd_v3.runtime import READ, CommandResult, RuntimeContext
from dd_v3.timeutil import now_millis

NAME = "get-log-context"
_MAX_CONTEXT_MS = 24 * 60 * 60 * 1000


def register(subparsers) -> None:
    parser = subparsers.add_parser(NAME, help="读取指定时间点前后的日志")
    parser.add_argument("--timestamp", required=True, help="目标时间")
    parser.add_argument("--query", help="Datadog 日志查询；与 --service 至少提供一个")
    parser.add_argument("--service", help="服务名；与 --query 至少提供一个")
    parser.add_argument("--before", default="5m", help="目标前窗口，默认 5m，最大 24h")
    parser.add_argument("--after", default="5m", help="目标后窗口，默认 5m，最大 24h")
    parser.add_argument(
        "--limit",
        type=bounded_int_type("--limit", 1, 500),
        default=50,
        help="每侧返回上限，默认 50，最大 500",
    )
    parser.add_argument("--format", dest="fmt", choices=["json", "summary"], default="json")
    parser.set_defaults(_handler=run, _policy=READ)


def build_payloads(args, *, now_ms: int) -> dict[str, Any]:
    query = combine_query(args.query, args.service)
    target_ms, target_time = normalize_instant(args.timestamp, now_ms=now_ms)
    before_ms = parse_duration_millis(
        args.before,
        label="--before",
        maximum_ms=_MAX_CONTEXT_MS,
    )
    after_ms = parse_duration_millis(
        args.after,
        label="--after",
        maximum_ms=_MAX_CONTEXT_MS,
    )
    before_from = format_rfc3339(target_ms - before_ms)
    after_to = format_rfc3339(target_ms + after_ms)
    return {
        "query": query,
        "target_time": target_time,
        "before_range": {"from": before_from, "to": target_time},
        "after_range": {"from": target_time, "to": after_to},
        "before": build_log_search_payload(
            query=query,
            from_time=before_from,
            to_time=target_time,
            limit=args.limit,
            sort="-timestamp",
        ),
        "after": build_log_search_payload(
            query=query,
            from_time=target_time,
            to_time=after_to,
            limit=args.limit,
            sort="timestamp",
        ),
    }


def run(args, context: RuntimeContext) -> CommandResult:
    requests = build_payloads(args, now_ms=now_millis())
    target = context.bind_target({
        "kind": "log_context",
        "timestamp": requests["target_time"],
        "query": requests["query"],
    })
    before_body = context.client.request_read(
        "POST",
        LOG_SEARCH_PATH,
        json_body=requests["before"],
    )
    after_body = context.client.request_read(
        "POST",
        LOG_SEARCH_PATH,
        json_body=requests["after"],
    )
    before_logs = [normalize_log(item) for item in reversed(data_items(before_body))]
    after_logs = [normalize_log(item) for item in data_items(after_body)]
    before_response, before_warnings = response_coverage(before_body)
    after_response, after_warnings = response_coverage(after_body)
    return CommandResult(
        target=target,
        result={
            "target_timestamp": requests["target_time"],
            "before": before_logs,
            "after": after_logs,
        },
        meta={
            "before_range": requests["before_range"],
            "after_range": requests["after_range"],
            "pagination": {
                "before": cursor_pagination(
                    before_body,
                    returned=len(before_logs),
                    limit=args.limit,
                    partial=before_response["partial"],
                ),
                "after": cursor_pagination(
                    after_body,
                    returned=len(after_logs),
                    limit=args.limit,
                    partial=after_response["partial"],
                ),
            },
            "response": {
                "before": before_response,
                "after": after_response,
            },
        },
        verification=None,
        warnings=merge_warnings(before_warnings, after_warnings),
    )
