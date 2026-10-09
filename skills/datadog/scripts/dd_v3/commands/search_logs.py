"""search-logs: search Datadog log events."""
from __future__ import annotations

from typing import Any

from dd_v3.argtypes import bounded_int_type
from dd_v3.errors import ApiError
from dd_v3.log_analysis import data_items, normalize_log, response_coverage
from dd_v3.runtime import READ, CommandResult, RuntimeContext
from dd_v3.timeutil import normalize_datadog_time

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
    p.add_argument(
        "--limit",
        type=bounded_int_type("--limit", 1, 1000),
        default=20,
        help="最大返回条数，默认 20，最大 1000",
    )
    p.add_argument("--sort", default="-timestamp", choices=["timestamp", "-timestamp"], help="排序，默认 -timestamp")
    p.add_argument(
        "--storage",
        choices=sorted(_STORAGE_ALIASES),
        help="日志存储层：indexes / online-archives / flex；online 是 indexes 别名",
    )
    p.add_argument("--cursor", help="分页游标")
    p.add_argument("--format", dest="fmt", choices=["json", "summary"], default="json")
    p.set_defaults(_handler=run, _policy=READ)


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


def extract_log(item: dict[str, Any]) -> dict[str, Any]:
    return normalize_log(item)


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
    return data_items(body)


def run(args, context: RuntimeContext) -> CommandResult:
    payload = build_payload(args)
    target = context.bind_target({
        "query": args.query,
        "from": payload["filter"]["from"],
        "to": payload["filter"]["to"],
        "storage": payload["filter"].get("storage_tier"),
    })
    body = context.client.request_read(
        "POST",
        "/api/v2/logs/events/search",
        json_body=payload,
    )
    raw_logs = _extract_data_list(body)
    logs = [extract_log(item) for item in raw_logs]
    next_cursor = _extract_next_cursor(body) if isinstance(body, dict) else None
    response, warnings = response_coverage(body)

    return CommandResult(
        target=target,
        result={"logs": logs, "count": len(logs)},
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
