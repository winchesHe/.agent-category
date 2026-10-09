"""compare-log-counts: compare two adjacent bounded log periods."""
from __future__ import annotations

from typing import Any

from dd_v3.log_analysis import (
    LOG_AGGREGATE_PATH,
    aggregate_total,
    build_count_payload,
    format_rfc3339,
    merge_warnings,
    normalize_instant,
    parse_duration_millis,
    require_text,
    response_coverage,
)
from dd_v3.runtime import READ, CommandResult, RuntimeContext
from dd_v3.timeutil import now_millis

NAME = "compare-log-counts"
_MAX_PERIOD_MS = 30 * 24 * 60 * 60 * 1000


def register(subparsers) -> None:
    parser = subparsers.add_parser(NAME, help="比较相邻两个时间段的日志数量")
    parser.add_argument("--query", required=True, help="Datadog 日志查询")
    parser.add_argument("--period", default="1h", help="每段时长，默认 1h，最大 30d")
    parser.add_argument("--to", default="now", dest="to_time", help="当前时间段终点，默认 now")
    parser.add_argument("--format", dest="fmt", choices=["json", "summary"], default="json")
    parser.set_defaults(_handler=run, _policy=READ)


def build_payloads(args, *, now_ms: int) -> dict[str, Any]:
    query = require_text(args.query, "--query")
    period_ms = parse_duration_millis(
        args.period,
        label="--period",
        maximum_ms=_MAX_PERIOD_MS,
    )
    current_to_ms, current_to = normalize_instant(args.to_time, now_ms=now_ms)
    current_from_ms = current_to_ms - period_ms
    previous_from_ms = current_from_ms - period_ms
    current_from = format_rfc3339(current_from_ms)
    previous_from = format_rfc3339(previous_from_ms)
    return {
        "query": query,
        "period": args.period,
        "current_range": {"from": current_from, "to": current_to},
        "previous_range": {"from": previous_from, "to": current_from},
        "current": build_count_payload(
            query=query,
            from_time=current_from,
            to_time=current_to,
        ),
        "previous": build_count_payload(
            query=query,
            from_time=previous_from,
            to_time=current_from,
        ),
    }


def compare_counts(current: int, previous: int) -> dict[str, Any]:
    absolute = current - previous
    baseline_zero = previous == 0
    percentage_change = None
    if not baseline_zero:
        percentage_change = round((absolute / previous) * 100, 1)
    return {
        "absolute": absolute,
        "percentage_change": percentage_change,
        "baseline_zero": baseline_zero,
    }


def run(args, context: RuntimeContext) -> CommandResult:
    payloads = build_payloads(args, now_ms=now_millis())
    target = context.bind_target({
        "kind": "log_count_comparison",
        "query": payloads["query"],
    })
    current_body = context.client.request_read(
        "POST",
        LOG_AGGREGATE_PATH,
        json_body=payloads["current"],
    )
    previous_body = context.client.request_read(
        "POST",
        LOG_AGGREGATE_PATH,
        json_body=payloads["previous"],
    )
    current_count = aggregate_total(current_body)
    previous_count = aggregate_total(previous_body)
    current_response, current_warnings = response_coverage(current_body)
    previous_response, previous_warnings = response_coverage(previous_body)
    return CommandResult(
        target=target,
        result={
            "current": {"count": current_count, **payloads["current_range"]},
            "previous": {"count": previous_count, **payloads["previous_range"]},
            "change": compare_counts(current_count, previous_count),
        },
        meta={
            "period": payloads["period"],
            "response": {
                "current": current_response,
                "previous": previous_response,
            },
        },
        verification=None,
        warnings=merge_warnings(current_warnings, previous_warnings),
    )
