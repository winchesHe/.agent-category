"""search-spans: search Datadog APM span events."""
from __future__ import annotations

import math
import re
from typing import Any

from dd_v3.argtypes import bounded_int_type, positive_finite_float_type
from dd_v3.errors import ApiError, UsageError
from dd_v3.log_analysis import response_coverage
from dd_v3.runtime import READ, CommandResult, RuntimeContext
from dd_v3.span_utils import (
    _is_error_status,
    _span_duration_ns,
    span_error_fields,
    span_http_fields,
    validate_span_attributes,
)
from dd_v3.timeutil import normalize_datadog_time

NAME = "search-spans"
_MAX_DURATION_NS = 9_223_372_036_854_775_807
_ENV_VALUE_RE = re.compile(r"^[A-Za-z0-9_.:/-]+$")
_MAX_TAG_LENGTH = 200


def register(subparsers) -> None:
    p = subparsers.add_parser(NAME, help="搜索 Datadog Spans")
    p.add_argument("--query", required=True, help="Span 搜索语法")
    p.add_argument("--from", required=True, dest="from_time", help="起始时间，如 15m / now-1h / RFC3339")
    p.add_argument("--to", default="now", dest="to_time", help="结束时间，默认 now")
    p.add_argument(
        "--limit",
        type=bounded_int_type("--limit", 1, 1000),
        default=20,
        help="最大返回条数，默认 20，最大 1000",
    )
    p.add_argument("--env", help="环境标签；query 不含 env: 时自动追加")
    p.add_argument(
        "--slow-ms",
        type=positive_finite_float_type("--slow-ms"),
        help="服务端慢 span 阈值，单位毫秒",
    )
    p.add_argument("--sort", default="-timestamp", choices=["timestamp", "-timestamp"], help="排序，默认 -timestamp")
    p.add_argument("--cursor", help="分页游标")
    p.add_argument("--format", dest="fmt", choices=["json", "summary"], default="json")
    p.set_defaults(_handler=run, _policy=READ)


def build_query(
    query: str,
    env: str | None,
    slow_ms: float | None = None,
) -> str:
    query = query.strip()
    if not query:
        raise ApiError("--query 不能为空", error_code="invalid_usage", category="usage")
    clauses: list[str] = []
    if env is not None and not _has_unquoted_env_filter(query):
        clauses.append(_env_clause(env))
    if slow_ms is not None:
        if not math.isfinite(slow_ms) or slow_ms <= 0:
            raise ApiError(
                "--slow-ms 必须是大于 0 的有限数字",
                error_code="invalid_usage",
                category="usage",
            )
        duration_ns_value = slow_ms * 1_000_000
        if not math.isfinite(duration_ns_value) or duration_ns_value > _MAX_DURATION_NS:
            raise ApiError(
                "--slow-ms 超过 Datadog duration 可表示范围",
                error_code="invalid_usage",
                category="usage",
            )
        duration_ns = int(duration_ns_value)
        if duration_ns < 1:
            raise ApiError(
                "--slow-ms 小于 Datadog duration 最小精度",
                error_code="invalid_usage",
                category="usage",
            )
        clauses.append(f"@duration:>={duration_ns}")
    return query if not clauses else f"({query}) AND " + " AND ".join(clauses)


def _env_clause(value: Any) -> str:
    if (
        not isinstance(value, str)
        or not value
        or not _ENV_VALUE_RE.fullmatch(value)
        or len(f"env:{value}") > _MAX_TAG_LENGTH
    ):
        raise UsageError("--env 必须是单个有效 Datadog tag value")
    encoded = value.replace(":", r"\:").replace("/", r"\/")
    return f"env:{encoded}"


def _has_unquoted_env_filter(query: str) -> bool:
    """Return whether query contains an env facet outside a quoted value."""
    quote: str | None = None
    escaped = False
    index = 0
    while index < len(query):
        char = query[index]
        if quote is not None:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = None
            index += 1
            continue
        if char in {'"', "'"}:
            quote = char
            index += 1
            continue
        if query.startswith("env:", index):
            prefix = query[:index]
            direct_boundary = not prefix or prefix[-1].isspace() or prefix[-1] == "("
            unary_boundary = (
                bool(prefix)
                and prefix[-1] in "+-"
                and (
                    len(prefix) == 1
                    or prefix[-2].isspace()
                    or prefix[-2] == "("
                )
            )
            if direct_boundary or unary_boundary:
                return True
        index += 1
    return False


def build_payload(args, default_env: str) -> dict[str, Any]:
    env = getattr(args, "env", None)
    if env is None:
        env = default_env
    query = build_query(
        args.query,
        env,
        getattr(args, "slow_ms", None),
    )
    page: dict[str, Any] = {"limit": args.limit}
    if args.cursor:
        page["cursor"] = args.cursor
    return {
        "data": {
            "attributes": {
                "filter": {
                    "from": normalize_datadog_time(args.from_time),
                    "to": normalize_datadog_time(args.to_time),
                    "query": query,
                },
                "options": {"timezone": "UTC"},
                "page": page,
                "sort": args.sort,
            },
            "type": "search_request",
        }
    }



def _extract_next_cursor(body: dict[str, Any]) -> str | None:
    meta = body.get("meta")
    if meta is None:
        return None
    if not isinstance(meta, dict):
        raise ApiError("Datadog returned invalid pagination", error_code="invalid_response")
    page = meta.get("page")
    if page is None:
        return None
    if not isinstance(page, dict):
        raise ApiError("Datadog returned invalid pagination", error_code="invalid_response")
    cursor = page.get("after")
    if cursor in (None, ""):
        return None
    if not isinstance(cursor, str):
        raise ApiError("Datadog returned invalid pagination", error_code="invalid_response")
    return cursor


def _extract_data_list(body: Any) -> list[dict[str, Any]]:
    if not isinstance(body, dict):
        raise ApiError("Datadog returned an invalid span response", error_code="invalid_response")
    data = body.get("data")
    if not isinstance(data, list):
        raise ApiError("Datadog returned an invalid span response", error_code="invalid_response")
    for item in data:
        if not isinstance(item, dict) or not isinstance(item.get("attributes"), dict):
            raise ApiError("Datadog returned an invalid span item", error_code="invalid_response")
        attributes = item["attributes"]
        validate_span_attributes(attributes)
        span_id = attributes.get("span_id")
        trace_id = attributes.get("trace_id")
        if (
            not isinstance(span_id, str)
            or not span_id
            or not isinstance(trace_id, str)
            or not trace_id
        ):
            raise ApiError("Datadog returned an invalid span item", error_code="invalid_response")
    return data



def extract_span(item: dict[str, Any], slow_ms: float | None = None) -> dict[str, Any]:
    attr = item.get("attributes", {}) if isinstance(item.get("attributes"), dict) else {}
    validate_span_attributes(attr)
    custom = attr.get("custom", {}) if isinstance(attr.get("custom"), dict) else {}
    http_info = span_http_fields(attr)
    error_info = span_error_fields(attr)
    response = custom.get("response", {}) if isinstance(custom.get("response"), dict) else {}
    response_summary = (
        {"status_code": response.get("status_code")}
        if response.get("status_code") is not None
        else None
    )
    status_code = http_info["status_code"]
    duration_ms = _span_duration_ns(attr) / 1_000_000.0
    span = {
        "timestamp": attr.get("start_timestamp") or attr.get("timestamp"),
        "service": attr.get("service"),
        "resource": attr.get("resource_name") or attr.get("resource"),
        "operation": attr.get("operation_name") or attr.get("name"),
        "trace_id": attr.get("trace_id"),
        "span_id": attr.get("span_id"),
        "parent_id": attr.get("parent_id"),
        "duration_ms": round(duration_ms, 2),
        "status": attr.get("status"),
        "is_error": bool(attr.get("error") or error_info or attr.get("status") == "error" or _is_error_status(status_code)),
        "http": http_info,
        "error": error_info,
        "response": response_summary,
        "grpc": {"method": custom.get("grpc.method")} if custom.get("grpc.method") else None,
        "tags": attr.get("tags", []),
    }
    if slow_ms is not None:
        span["is_slow"] = duration_ms >= slow_ms
    return span


def run(args, context: RuntimeContext) -> CommandResult:
    payload = build_payload(args, context.config.default_env)
    query = payload["data"]["attributes"]["filter"]["query"]
    target = context.bind_target({
        "query": query,
        "from": payload["data"]["attributes"]["filter"]["from"],
        "to": payload["data"]["attributes"]["filter"]["to"],
        "slow_ms": args.slow_ms,
    })
    body = context.client.request_read(
        "POST",
        "/api/v2/spans/events/search",
        json_body=payload,
    )
    raw_spans = _extract_data_list(body)
    spans = [extract_span(item, args.slow_ms) for item in raw_spans]
    next_cursor = _extract_next_cursor(body) if isinstance(body, dict) else None
    response, warnings = response_coverage(body)
    return CommandResult(
        target=target,
        result={"spans": spans, "count": len(spans)},
        meta={
            "page": {
                "limit": args.limit,
                "sort": args.sort,
                "has_more": bool(next_cursor),
                "next_cursor": next_cursor,
                "completion": (
                    "unknown"
                    if response["partial"]
                    else ("more_available" if next_cursor else "complete")
                ),
            },
            "response": response,
        },
        warnings=warnings,
    )
