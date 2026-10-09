"""search-logs: search Datadog log events."""
from __future__ import annotations

import sys
from typing import Any

from dd.client import DatadogClient
from dd.errors import ApiError
from dd.formatter import output
from dd.timeutil import normalize_datadog_time

NAME = "search-logs"

_STORAGE_ALIASES = {
    "online": "indexes",
    "standard": "indexes",
    "index": "indexes",
    "indexes": "indexes",
    "online-archives": "online-archives",
    "online_archives": "online-archives",
    "flex": "flex",
    "flex_tier": "flex",
}


def register(subparsers) -> None:
    p = subparsers.add_parser(NAME, help="搜索 Datadog 日志")
    p.add_argument("--query", required=True, help="Datadog 日志搜索语法")
    p.add_argument("--from", required=True, dest="from_time", help="起始时间，如 15m / now-1h / RFC3339")
    p.add_argument("--to", default="now", dest="to_time", help="结束时间，默认 now")
    p.add_argument("--limit", type=int, default=20, help="最大返回条数，默认 20")
    p.add_argument("--sort", default="-timestamp", choices=["timestamp", "-timestamp"], help="排序，默认 -timestamp")
    p.add_argument(
        "--storage",
        choices=sorted(_STORAGE_ALIASES),
        help="日志存储层：indexes / online-archives / flex；online 是 indexes 别名",
    )
    p.add_argument("--cursor", help="分页游标")
    p.add_argument("--format", dest="fmt", choices=["json", "human", "summary"], default="json")
    p.set_defaults(_handler=run)


def normalize_storage(storage: str | None) -> str | None:
    if storage is None:
        return None
    try:
        return _STORAGE_ALIASES[storage]
    except KeyError as exc:
        raise ApiError(f"未知 storage: {storage}") from exc


def build_payload(args) -> dict[str, Any]:
    filter_obj: dict[str, Any] = {
        "from": normalize_datadog_time(args.from_time),
        "to": normalize_datadog_time(args.to_time),
        "query": args.query,
    }
    storage = normalize_storage(args.storage)
    if storage:
        filter_obj["storage_tier"] = storage

    page_obj: dict[str, Any] = {"limit": args.limit}
    if args.cursor:
        page_obj["cursor"] = args.cursor

    return {
        "filter": filter_obj,
        "page": page_obj,
        "sort": args.sort,
    }


def _nested_get(data: dict[str, Any], *paths: str) -> Any:
    for path in paths:
        current: Any = data
        found = True
        for part in path.split("."):
            if isinstance(current, dict) and part in current:
                current = current[part]
            else:
                found = False
                break
        if found and current not in (None, ""):
            return current
    return None


def _extract_message(attr: dict[str, Any]) -> str:
    inner = attr.get("attributes", {}) if isinstance(attr.get("attributes"), dict) else {}
    message = attr.get("message") or inner.get("message")
    if message:
        return str(message)
    method = _nested_get(inner, "http.method", "method")
    path = _nested_get(inner, "http.url_details.path", "path", "url")
    code = _nested_get(inner, "http.status_code", "status")
    if method and path:
        return f"{method} {path} ({code})"
    return ""


def extract_log(item: dict[str, Any]) -> dict[str, Any]:
    attr = item.get("attributes", {}) if isinstance(item.get("attributes"), dict) else {}
    # Datadog v2 logs 真实形态：所有字段直接挂在 attributes 下（flat）
    # 旧测试 fixture 用了 attributes.attributes 嵌套，这里做兼容：
    nested = attr.get("attributes", {}) if isinstance(attr.get("attributes"), dict) else {}
    inner = nested if nested else attr
    http = inner.get("http", {}) if isinstance(inner.get("http"), dict) else {}
    error = inner.get("error", {}) if isinstance(inner.get("error"), dict) else {}
    dd_block = inner.get("dd", {}) if isinstance(inner.get("dd"), dict) else {}
    return {
        "id": item.get("id"),
        "timestamp": attr.get("timestamp") or inner.get("timestamp"),
        "service": attr.get("service") or inner.get("service"),
        "status": attr.get("status") or inner.get("status"),
        "message": _extract_message(attr),
        "trace_id": (
            inner.get("trace_id")
            or attr.get("trace_id")
            or dd_block.get("trace_id")
        ),
        "span_id": (
            inner.get("span_id")
            or attr.get("span_id")
            or dd_block.get("span_id")
        ),
        "request_id": (
            inner.get("@id")
            or inner.get("request_id")
            or attr.get("@id")
            or attr.get("request_id")
        ),
        "http": {
            "method": http.get("method") or inner.get("method"),
            "url": http.get("url") or inner.get("url"),
            "path": _nested_get(inner, "http.url_details.path", "path"),
            "status_code": http.get("status_code") or inner.get("status_code"),
        },
        "error": {
            "message": error.get("message"),
            "kind": error.get("kind") or error.get("type"),
            "stack": error.get("stack"),
        } if error else None,
        "host": attr.get("host") or inner.get("host"),
        "tags": attr.get("tags") if isinstance(attr.get("tags"), list) else inner.get("tags"),
        "raw_attributes": inner,
    }


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


def _render_human(logs: list[dict[str, Any]]) -> None:
    for log in logs:
        sys.stderr.write(
            f"[{log.get('timestamp') or ''}] "
            f"[{log.get('service') or ''}] "
            f"[{log.get('status') or ''}] "
            f"{log.get('message') or ''}\n"
        )
        if log.get("trace_id"):
            sys.stderr.write(f"  trace_id: {log['trace_id']}\n")
        if log.get("error"):
            sys.stderr.write(f"  error: {log['error'].get('message') or ''}\n")


def run(args, config) -> int:
    payload = build_payload(args)
    sys.stderr.write(
        f"[search-logs] query={args.query!r} from={args.from_time} to={args.to_time} "
        f"limit={args.limit}\n"
    )
    body = DatadogClient(config).post("/api/v2/logs/events/search", json_body=payload)
    raw_logs = _extract_data_list(body)
    logs = [extract_log(item) for item in raw_logs if isinstance(item, dict)]
    next_cursor = _extract_next_cursor(body) if isinstance(body, dict) else None

    result = {
        "query": args.query,
        "from": payload["filter"]["from"],
        "to": payload["filter"]["to"],
        "storage": payload["filter"].get("storage_tier"),
        "logs": logs,
        "count": len(logs),
        "has_more": bool(next_cursor),
        "next_cursor": next_cursor,
    }
    if args.fmt == "human":
        _render_human(logs)
    output(result, fmt=args.fmt)
    return 0
