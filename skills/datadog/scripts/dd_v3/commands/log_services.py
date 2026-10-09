"""list-log-services: discover services with log activity."""
from __future__ import annotations

from typing import Any

from dd_v3.argtypes import bounded_int_type
from dd_v3.log_analysis import (
    LOG_AGGREGATE_PATH,
    aggregate_buckets,
    aggregate_facet_counts,
    build_count_payload,
    limited_pagination,
    normalize_time_range,
    require_text,
    response_coverage,
)
from dd_v3.runtime import READ, CommandResult, RuntimeContext
from dd_v3.timeutil import now_millis

NAME = "list-log-services"


def register(subparsers) -> None:
    parser = subparsers.add_parser(NAME, help="列出有日志活动的服务")
    parser.add_argument("--from", required=True, dest="from_time", help="起始时间")
    parser.add_argument("--to", default="now", dest="to_time", help="结束时间，默认 now")
    parser.add_argument("--query", default="*", help="日志查询，默认 *")
    parser.add_argument(
        "--limit",
        type=bounded_int_type("--limit", 1, 500),
        default=100,
        help="服务上限，默认 100，最大 500",
    )
    parser.add_argument("--format", dest="fmt", choices=["json", "summary"], default="json")
    parser.set_defaults(_handler=run, _policy=READ)


def build_payload(args, *, now_ms: int) -> tuple[dict[str, Any], str, str, str]:
    query = require_text(args.query, "--query")
    from_time, to_time = normalize_time_range(args.from_time, args.to_time, now_ms=now_ms)
    payload = build_count_payload(
        query=query,
        from_time=from_time,
        to_time=to_time,
        facet="service",
        limit=args.limit,
    )
    return payload, query, from_time, to_time


def run(args, context: RuntimeContext) -> CommandResult:
    payload, query, from_time, to_time = build_payload(args, now_ms=now_millis())
    target = context.bind_target({"kind": "log_services", "query": query})
    body = context.client.request_read("POST", LOG_AGGREGATE_PATH, json_body=payload)
    services = aggregate_facet_counts(body, facet="service", output_key="name")
    response, warnings = response_coverage(body)
    for service in services:
        service["log_count"] = service.pop("count")
    return CommandResult(
        target=target,
        result={"services": services, "returned": len(services)},
        meta={
            "time_range": {"from": from_time, "to": to_time},
            "pagination": limited_pagination(
                returned=len(aggregate_buckets(body)),
                limit=args.limit,
                partial=response["partial"],
            ),
            "response": response,
        },
        verification=None,
        warnings=warnings,
    )
