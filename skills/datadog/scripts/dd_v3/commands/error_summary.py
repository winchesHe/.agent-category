"""summarize-errors: aggregate errors and rank a bounded message sample."""
from __future__ import annotations

from typing import Any

from dd_v3.argtypes import bounded_int_type
from dd_v3.log_analysis import (
    LOG_AGGREGATE_PATH,
    LOG_SEARCH_PATH,
    aggregate_buckets,
    aggregate_facet_counts,
    aggregate_total,
    build_count_payload,
    build_log_search_payload,
    combine_query,
    cursor_pagination,
    data_items,
    limited_pagination,
    merge_warnings,
    normalize_time_range,
    ranked_messages,
    response_coverage,
)
from dd_v3.runtime import READ, CommandResult, RuntimeContext
from dd_v3.timeutil import now_millis

NAME = "summarize-errors"
_FACET_LIMIT = 20


def register(subparsers) -> None:
    parser = subparsers.add_parser(NAME, help="汇总错误数量、服务和消息样本")
    parser.add_argument("--from", required=True, dest="from_time", help="起始时间")
    parser.add_argument("--to", default="now", dest="to_time", help="结束时间，默认 now")
    parser.add_argument("--query", default="status:error", help="日志查询，默认 status:error")
    parser.add_argument("--service", help="可选服务过滤")
    parser.add_argument(
        "--sample-limit",
        type=bounded_int_type("--sample-limit", 1, 500),
        default=200,
        help="消息样本上限，默认 200，最大 500",
    )
    parser.add_argument("--format", dest="fmt", choices=["json", "summary"], default="json")
    parser.set_defaults(_handler=run, _policy=READ)


def build_payloads(args, *, now_ms: int) -> dict[str, Any]:
    query = combine_query(args.query, args.service)
    from_time, to_time = normalize_time_range(args.from_time, args.to_time, now_ms=now_ms)
    return {
        "query": query,
        "from": from_time,
        "to": to_time,
        "by_service": build_count_payload(
            query=query,
            from_time=from_time,
            to_time=to_time,
            facet="service",
            limit=_FACET_LIMIT,
        ),
        "by_error_kind": build_count_payload(
            query=query,
            from_time=from_time,
            to_time=to_time,
            facet="@error.kind",
            limit=_FACET_LIMIT,
        ),
        "total": build_count_payload(query=query, from_time=from_time, to_time=to_time),
        "messages": build_log_search_payload(
            query=query,
            from_time=from_time,
            to_time=to_time,
            limit=args.sample_limit,
            sort="-timestamp",
        ),
    }


def run(args, context: RuntimeContext) -> CommandResult:
    payloads = build_payloads(args, now_ms=now_millis())
    target = context.bind_target({"kind": "error_summary", "query": payloads["query"]})
    by_service_body = context.client.request_read(
        "POST",
        LOG_AGGREGATE_PATH,
        json_body=payloads["by_service"],
    )
    by_error_kind_body = context.client.request_read(
        "POST",
        LOG_AGGREGATE_PATH,
        json_body=payloads["by_error_kind"],
    )
    total_body = context.client.request_read(
        "POST",
        LOG_AGGREGATE_PATH,
        json_body=payloads["total"],
    )
    messages_body = context.client.request_read(
        "POST",
        LOG_SEARCH_PATH,
        json_body=payloads["messages"],
    )
    sample_size = len(data_items(messages_body))
    by_service = aggregate_facet_counts(
        by_service_body,
        facet="service",
        output_key="service",
    )
    by_error_kind = aggregate_facet_counts(
        by_error_kind_body,
        facet="@error.kind",
        output_key="error_kind",
    )
    by_service_response, by_service_warnings = response_coverage(by_service_body)
    by_error_kind_response, by_error_kind_warnings = response_coverage(
        by_error_kind_body
    )
    total_response, total_warnings = response_coverage(total_body)
    messages_response, messages_warnings = response_coverage(messages_body)
    facet_coverage = {
        "by_service": limited_pagination(
            returned=len(aggregate_buckets(by_service_body)),
            limit=_FACET_LIMIT,
            partial=by_service_response["partial"],
        ),
        "by_error_kind": limited_pagination(
            returned=len(aggregate_buckets(by_error_kind_body)),
            limit=_FACET_LIMIT,
            partial=by_error_kind_response["partial"],
        ),
    }
    coverage_warnings = []
    if facet_coverage["by_service"]["completion"] == "unknown":
        coverage_warnings.append("by_service_facet_may_be_truncated")
    if facet_coverage["by_error_kind"]["completion"] == "unknown":
        coverage_warnings.append("by_error_kind_facet_may_be_truncated")
    return CommandResult(
        target=target,
        result={
            "total": aggregate_total(total_body),
            "by_service": by_service,
            "by_error_kind": by_error_kind,
            "top_messages": ranked_messages(messages_body),
            "message_sample": {
                "coverage": "sampled",
                "sample_size": sample_size,
                "requested_sample_size": args.sample_limit,
            },
        },
        meta={
            "time_range": {"from": payloads["from"], "to": payloads["to"]},
            "pagination": cursor_pagination(
                messages_body,
                returned=sample_size,
                limit=args.sample_limit,
                partial=messages_response["partial"],
            ),
            "facet_coverage": facet_coverage,
            "response": {
                "by_service": by_service_response,
                "by_error_kind": by_error_kind_response,
                "total": total_response,
                "messages": messages_response,
            },
        },
        verification=None,
        warnings=merge_warnings(
            by_service_warnings,
            by_error_kind_warnings,
            total_warnings,
            messages_warnings,
            coverage_warnings,
        ),
    )
