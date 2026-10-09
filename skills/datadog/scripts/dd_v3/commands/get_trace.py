"""get-trace: fetch and normalize a Datadog trace.

Datadog 另有按 ID 获取 pruned trace 的公开端点；当前 CLI 为了返回可归一化的
span 集合，使用 `POST /api/v2/spans/events/search`，按 `trace_id:<value>` 和
明确时间窗口过滤，再把返回的 span 拼成树。
"""
from __future__ import annotations

import argparse
import re
from typing import Any

from dd_v3.argtypes import bounded_int_type
from dd_v3.errors import ApiError
from dd_v3.log_analysis import merge_warnings, response_coverage
from dd_v3.runtime import READ, CommandResult, RuntimeContext
from dd_v3.span_utils import (
    _is_error_status,
    _span_duration_ns,
    span_error_fields,
    span_http_fields,
    validate_span_attributes,
)
from dd_v3.timeutil import normalize_datadog_time

NAME = "get-trace"
_TRACE_ID_RE = re.compile(r"^(?:[0-9a-fA-F]{32}|[0-9]{1,39})$")


def _trace_id(value: str) -> str:
    if not _TRACE_ID_RE.fullmatch(value):
        raise argparse.ArgumentTypeError(
            "TRACE_ID 必须是 32 位十六进制或最多 39 位十进制值"
        )
    return value


def register(subparsers) -> None:
    p = subparsers.add_parser(NAME, help="获取 Trace 详情（含 span 树形结构）")
    p.add_argument(
        "trace_id",
        type=_trace_id,
        help="Trace ID（Datadog 返回的 32 位 hex 或最多 39 位 decimal；按原值传入）",
    )
    p.add_argument("--from", default="now-1h", dest="from_time", help="搜索起始时间，默认 now-1h")
    p.add_argument("--to", default="now", dest="to_time", help="搜索结束时间，默认 now")
    p.add_argument(
        "--limit",
        type=bounded_int_type("--limit", 1, 1000),
        default=200,
        help="单次拉取的最大 span 数，默认 200，最大 1000",
    )
    p.add_argument("--cursor", help="继续同一 Trace 查询的分页游标")
    p.add_argument("--verbose", action="store_true", help="输出每个 span 的完整 meta")
    p.add_argument("--format", dest="fmt", choices=["json", "summary"], default="json")
    p.set_defaults(_handler=run, _policy=READ)



def _nested_dict(source: dict[str, Any], key: str) -> dict[str, Any]:
    value = source.get(key)
    return value if isinstance(value, dict) else {}


def _normalize_span(item: Any) -> dict[str, Any]:
    """把 v2 spans-search resource 拍平到内部 span 字典。"""
    if not isinstance(item, dict) or not isinstance(item.get("attributes"), dict):
        raise ApiError("Datadog returned an invalid trace span", error_code="invalid_response")
    attr = item["attributes"]
    validate_span_attributes(attr)
    span_id = attr.get("span_id")
    if not isinstance(span_id, str) or not span_id:
        raise ApiError("Datadog returned a trace span without span_id", error_code="invalid_response")
    trace_id = attr.get("trace_id")
    if not isinstance(trace_id, str) or not trace_id:
        raise ApiError("Datadog returned a trace span without trace_id", error_code="invalid_response")
    parent_id = attr.get("parent_id")
    if (
        parent_id not in (None, "", 0, "0")
        and (
            isinstance(parent_id, bool)
            or not isinstance(parent_id, (str, int))
        )
    ):
        raise ApiError("Datadog returned an invalid trace parent_id", error_code="invalid_response")
    custom = attr.get("custom") if isinstance(attr.get("custom"), dict) else {}
    meta = attr.get("meta") if isinstance(attr.get("meta"), dict) else custom
    metrics = attr.get("metrics") if isinstance(attr.get("metrics"), dict) else {}
    http = span_http_fields(attr)
    response = _nested_dict(custom, "response")
    normalized_error = span_error_fields(attr)
    status_code = http["status_code"]
    error_flag = bool(
        attr.get("error")
        or normalized_error
        or attr.get("status") == "error"
        or _is_error_status(status_code)
    )
    error = None
    if error_flag:
        error = {
            "message": (normalized_error or {}).get("message") or "",
            "type": (normalized_error or {}).get("kind") or "",
            "stack": (normalized_error or {}).get("stack") or "",
        }
    return {
        "trace_id": trace_id,
        "span_id": span_id,
        "parent_id": str(parent_id) if parent_id not in (None, "", 0, "0") else None,
        "service": attr.get("service") or "unknown",
        "operation": attr.get("operation_name") or attr.get("name") or "unknown",
        "resource": attr.get("resource_name") or attr.get("resource") or "unknown",
        "start": attr.get("start_timestamp") or attr.get("start") or attr.get("timestamp"),
        "duration_ns": _span_duration_ns(attr),
        "status": attr.get("status"),
        "error_flag": error_flag,
        "http": http if any(value is not None for value in http.values()) else None,
        "error": error,
        "response": response if response else None,
        "meta": meta if isinstance(meta, dict) else {},
        "metrics": metrics,
    }


def parse_spans(body: Any) -> list[dict[str, Any]]:
    """从 v2 spans-search 响应中抽出 span 列表。"""
    if not isinstance(body, dict):
        raise ApiError("Datadog returned an invalid trace response", error_code="invalid_response")
    data = body.get("data")
    if not isinstance(data, list):
        raise ApiError("Datadog returned an invalid trace response", error_code="invalid_response")
    return [_normalize_span(raw) for raw in data]


def _extract_next_cursor(body: Any) -> str | None:
    if not isinstance(body, dict):
        raise ApiError("Datadog returned invalid trace pagination", error_code="invalid_response")
    meta = body.get("meta")
    if meta is None:
        return None
    if not isinstance(meta, dict):
        raise ApiError("Datadog returned invalid trace pagination", error_code="invalid_response")
    page = meta.get("page")
    if page is None:
        return None
    if not isinstance(page, dict):
        raise ApiError("Datadog returned invalid trace pagination", error_code="invalid_response")
    cursor = page.get("after")
    if cursor in (None, ""):
        return None
    if not isinstance(cursor, str):
        raise ApiError("Datadog returned invalid trace pagination", error_code="invalid_response")
    return cursor


def build_span_tree(spans: list[dict[str, Any]]) -> list[dict[str, Any]]:
    id_map = {span["span_id"]: span for span in spans}
    for span in spans:
        depth = 0
        seen: set[str] = set()
        current = span.get("parent_id")
        while current and current in id_map and current not in seen:
            seen.add(current)
            depth += 1
            current = id_map[current].get("parent_id")
        span["_depth"] = depth
    return sorted(spans, key=lambda s: (s.get("start") or "", s.get("_depth", 0)))


def _validate_trace_membership(spans: list[dict[str, Any]], expected_trace_id: str) -> None:
    if any(span["trace_id"] != expected_trace_id for span in spans):
        raise ApiError("Datadog returned a span from a different trace", error_code="invalid_response")


def _first_meta(meta: dict[str, Any], keys: tuple[str, ...]) -> str | None:
    for key in keys:
        value = meta.get(key)
        if value not in (None, ""):
            text = str(value)
            return text[:500] + "...(truncated)" if len(text) > 500 else text
    return None


def format_span(span: dict[str, Any], *, verbose: bool = False) -> dict[str, Any]:
    meta = span.get("meta") or {}
    error_flag = span.get("error_flag", False)
    error = None
    if error_flag:
        error = span.get("error") or {
            "message": meta.get("error.message") or meta.get("error.msg") or "",
            "type": meta.get("error.type") or "",
            "stack": meta.get("error.stack") or "",
        }
    response = span.get("response") if isinstance(span.get("response"), dict) else {}

    # payload/response body may contain customer PII — only include with --verbose
    payload = None
    if verbose:
        payload = _first_meta(meta, ("request.body", "response.body", "payload", "input", "json"))
        if payload is None and response.get("body") not in (None, ""):
            payload = str(response["body"])[:500]

    return {
        "span_id": span.get("span_id"),
        "parent_id": span.get("parent_id"),
        "depth": span.get("_depth", 0),
        "service": span.get("service", "unknown"),
        "operation": span.get("operation", "unknown"),
        "resource": span.get("resource", "unknown"),
        "start": span.get("start"),
        "duration_ms": round((span.get("duration_ns") or 0) / 1_000_000.0, 2),
        "status": span.get("status"),
        "is_error": error_flag,
        "http": span.get("http"),
        "sql": _first_meta(meta, ("sql.query", "db.statement", "sql")),
        "payload": payload,
        "error": error,
        "response": response if (response and verbose) else None,
        "metrics": span.get("metrics") if verbose else {},
        "meta": meta if verbose else {},
    }


def run(args, context: RuntimeContext) -> CommandResult:
    page: dict[str, Any] = {"limit": args.limit}
    cursor = getattr(args, "cursor", None)
    if cursor:
        page["cursor"] = cursor
    payload = {
        "data": {
            "type": "search_request",
            "attributes": {
                "filter": {
                    "query": f"trace_id:{args.trace_id}",
                    "from": normalize_datadog_time(args.from_time),
                    "to": normalize_datadog_time(args.to_time),
                },
                "options": {"timezone": "UTC"},
                "page": page,
                "sort": "timestamp",
            },
        }
    }
    target = context.bind_target({
        "trace_id": args.trace_id,
        "from": payload["data"]["attributes"]["filter"]["from"],
        "to": payload["data"]["attributes"]["filter"]["to"],
    })
    body = context.client.request_read(
        "POST",
        "/api/v2/spans/events/search",
        json_body=payload,
    )
    parsed_spans = parse_spans(body)
    _validate_trace_membership(parsed_spans, args.trace_id)
    raw_spans = build_span_tree(parsed_spans)
    spans = [format_span(span, verbose=args.verbose) for span in raw_spans]
    next_cursor = _extract_next_cursor(body)
    response, response_warnings = response_coverage(body)
    tree_warnings = []
    if cursor or next_cursor:
        tree_warnings.append("trace_tree_is_page_local")
    return CommandResult(
        target=target,
        result={"span_count": len(spans), "spans": spans, "coverage": "page"},
        meta={
            "page": {
                "limit": args.limit,
                "sort": "timestamp",
                "has_more": bool(next_cursor),
                "next_cursor": next_cursor,
                "completion": (
                    "unknown"
                    if response["partial"]
                    else ("more_available" if next_cursor else "complete")
                ),
            },
            "response": response,
            "verbose": args.verbose,
        },
        warnings=merge_warnings(response_warnings, tree_warnings),
    )
