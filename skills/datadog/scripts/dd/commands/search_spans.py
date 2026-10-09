"""search-spans: search Datadog APM span events."""
from __future__ import annotations

import sys
from typing import Any

from dd.client import DatadogClient
from dd.formatter import output
from dd.timeutil import normalize_datadog_time

NAME = "search-spans"


def register(subparsers) -> None:
    p = subparsers.add_parser(NAME, help="搜索 Datadog Spans")
    p.add_argument("--query", required=True, help="Span 搜索语法")
    p.add_argument("--from", required=True, dest="from_time", help="起始时间，如 15m / now-1h / RFC3339")
    p.add_argument("--to", default="now", dest="to_time", help="结束时间，默认 now")
    p.add_argument("--limit", type=int, default=20, help="最大返回条数，默认 20")
    p.add_argument("--env", help="环境标签；query 不含 env: 时自动追加")
    p.add_argument("--slow-ms", type=float, help="慢 span 阈值，单位毫秒")
    p.add_argument("--sort", default="-timestamp", choices=["timestamp", "-timestamp"], help="排序，默认 -timestamp")
    p.add_argument("--cursor", help="分页游标")
    p.add_argument("--format", dest="fmt", choices=["json", "human", "summary"], default="json")
    p.set_defaults(_handler=run)


def build_query(query: str, env: str | None) -> str:
    if env and "env:" not in query:
        return f"{query} env:{env}"
    return query


def build_payload(args, default_env: str) -> dict[str, Any]:
    query = build_query(args.query, getattr(args, "env", None) or default_env)
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


def _parse_iso_to_ns(value: Any) -> int | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        from datetime import datetime, timezone
        text = value.replace("Z", "+00:00")
        dt = datetime.fromisoformat(text)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return int(dt.timestamp() * 1_000_000_000)
    except Exception:
        return None


def _span_duration_ns(attr: dict[str, Any]) -> int:
    """Datadog v2 spans：attr.duration 通常缺失，
    实际 duration 在 attr.custom.duration（纳秒）；否则用 end-start 推算。
    """
    direct = attr.get("duration")
    if isinstance(direct, (int, float)) and direct:
        return int(direct)
    custom = attr.get("custom") if isinstance(attr.get("custom"), dict) else {}
    custom_dur = custom.get("duration") if isinstance(custom, dict) else None
    if isinstance(custom_dur, (int, float)) and custom_dur:
        return int(custom_dur)
    start = _parse_iso_to_ns(attr.get("start_timestamp"))
    end = _parse_iso_to_ns(attr.get("end_timestamp"))
    if start is not None and end is not None and end >= start:
        return end - start
    return 0


def _extract_next_cursor(body: dict[str, Any]) -> str | None:
    meta = body.get("meta") if isinstance(body.get("meta"), dict) else {}
    page = meta.get("page") if isinstance(meta.get("page"), dict) else {}
    cursor = page.get("after")
    return str(cursor) if cursor else None


def _extract_data_list(body: Any) -> list[Any]:
    if not isinstance(body, dict):
        return []
    data = body.get("data")
    return data if isinstance(data, list) else []


def _is_error_status(value: Any) -> bool:
    if value in (None, ""):
        return False
    try:
        return int(value) >= 500
    except (TypeError, ValueError):
        return False


def extract_span(item: dict[str, Any], slow_ms: float | None = None) -> dict[str, Any]:
    attr = item.get("attributes", {}) if isinstance(item.get("attributes"), dict) else {}
    custom = attr.get("custom", {}) if isinstance(attr.get("custom"), dict) else {}
    http_info = attr.get("http", {}) if isinstance(attr.get("http"), dict) else {}
    if not http_info and isinstance(custom.get("http"), dict):
        http_info = custom["http"]
    error_info = attr.get("error", {}) if isinstance(attr.get("error"), dict) else {}
    custom_error = custom.get("error", {}) if isinstance(custom.get("error"), dict) else {}
    response = custom.get("response", {}) if isinstance(custom.get("response"), dict) else {}
    url_details = http_info.get("url_details", {}) if isinstance(http_info.get("url_details"), dict) else {}
    status_code = (
        http_info.get("status_code")
        or custom.get("http.status_code")
        or response.get("status_code")
    )
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
        "is_error": bool(attr.get("error") or custom_error or attr.get("status") == "error" or _is_error_status(status_code)),
        "http": {
            "method": http_info.get("method") or custom.get("http.method"),
            "status_code": status_code,
            "url": http_info.get("url") or custom.get("http.url"),
            "path": url_details.get("path") or http_info.get("path_group") or custom.get("http.url_details.path"),
        },
        "error": {
            "message": custom_error.get("message") or error_info.get("message"),
            "kind": custom_error.get("type") or error_info.get("type"),
            "stack": custom_error.get("stack") or error_info.get("stack"),
        } if (custom_error or error_info) else None,
        "response": response if response else None,
        "grpc": {"method": custom.get("grpc.method")} if custom.get("grpc.method") else None,
        "tags": attr.get("tags", []),
    }
    if slow_ms is not None:
        span["is_slow"] = duration_ms >= slow_ms
    return span


def _render_human(spans: list[dict[str, Any]]) -> None:
    for span in spans:
        err = "ERR " if span.get("is_error") else ""
        slow = "SLOW " if span.get("is_slow") else ""
        sys.stderr.write(
            f"[{span.get('timestamp') or ''}] {err}{slow}"
            f"[{span.get('service') or ''}] {span.get('resource') or ''} "
            f"{span.get('duration_ms')}ms\n"
        )
        if span.get("trace_id"):
            sys.stderr.write(f"  trace: python3 scripts/datadog.py get-trace {span['trace_id']}\n")


def run(args, config) -> int:
    payload = build_payload(args, config.default_env)
    query = payload["data"]["attributes"]["filter"]["query"]
    sys.stderr.write(f"[search-spans] query={query!r} from={args.from_time} to={args.to_time}\n")
    body = DatadogClient(config).post("/api/v2/spans/events/search", json_body=payload)
    raw_spans = _extract_data_list(body)
    spans = [extract_span(item, args.slow_ms) for item in raw_spans if isinstance(item, dict)]
    next_cursor = _extract_next_cursor(body) if isinstance(body, dict) else None
    result = {
        "query": query,
        "from": payload["data"]["attributes"]["filter"]["from"],
        "to": payload["data"]["attributes"]["filter"]["to"],
        "spans": spans,
        "count": len(spans),
        "has_more": bool(next_cursor),
        "next_cursor": next_cursor,
    }
    if args.fmt == "human":
        _render_human(spans)
    output(result, fmt=args.fmt)
    return 0
