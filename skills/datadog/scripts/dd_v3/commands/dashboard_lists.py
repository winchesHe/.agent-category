"""Read-only Dashboard List commands."""
from __future__ import annotations

from typing import Any

from dd_v3.argtypes import bounded_int_type
from dd_v3.errors import ApiError
from dd_v3.runtime import READ, CommandResult, RuntimeContext

LIST_NAME = "list-dashboard-lists"
GET_NAME = "get-dashboard-list"
ITEMS_NAME = "list-dashboard-list-items"
LIST_PATH = "/api/v1/dashboard/lists/manual"
_MAX_UNPAGED_ITEMS = 1000


def register(subparsers) -> None:
    list_parser = subparsers.add_parser(LIST_NAME, help="列出 Dashboard List")
    list_parser.add_argument("--format", dest="fmt", choices=["json", "summary"], default="json")
    list_parser.set_defaults(_handler=run_list, _policy=READ)

    get_parser = subparsers.add_parser(GET_NAME, help="获取一个 Dashboard List")
    get_parser.add_argument(
        "list_id",
        metavar="ID",
        type=bounded_int_type("ID", 1, 9_223_372_036_854_775_807),
        help="Dashboard List ID",
    )
    get_parser.add_argument("--format", dest="fmt", choices=["json", "summary"], default="json")
    get_parser.set_defaults(_handler=run_get, _policy=READ)

    items_parser = subparsers.add_parser(ITEMS_NAME, help="列出 Dashboard List 内的 Dashboard")
    items_parser.add_argument(
        "list_id",
        metavar="ID",
        type=bounded_int_type("ID", 1, 9_223_372_036_854_775_807),
        help="Dashboard List ID",
    )
    items_parser.add_argument("--format", dest="fmt", choices=["json", "summary"], default="json")
    items_parser.set_defaults(_handler=run_items, _policy=READ)


def _normalize_creator(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    return {"handle": value.get("handle"), "name": value.get("name")}


def normalize_dashboard_list(item: dict[str, Any]) -> dict[str, Any]:
    list_id = item.get("id")
    name = item.get("name")
    if (
        isinstance(list_id, bool)
        or not isinstance(list_id, int)
        or list_id <= 0
        or not isinstance(name, str)
        or not name.strip()
    ):
        raise ApiError("Datadog returned an invalid Dashboard List item", error_code="invalid_response")
    return {
        "id": list_id,
        "name": name,
        "type": item.get("type"),
        "dashboard_count": item.get("dashboard_count"),
        "is_favorite": item.get("is_favorite"),
        "created": item.get("created"),
        "modified": item.get("modified"),
        "author": _normalize_creator(item.get("author")),
    }


def normalize_dashboard_list_item(item: dict[str, Any]) -> dict[str, Any]:
    dashboard_id = item.get("id")
    dashboard_type = item.get("type")
    if (
        not isinstance(dashboard_id, str)
        or not dashboard_id.strip()
        or not isinstance(dashboard_type, str)
        or not dashboard_type.strip()
    ):
        raise ApiError("Datadog returned an invalid Dashboard List item", error_code="invalid_response")
    return {
        "id": dashboard_id,
        "type": dashboard_type,
        "title": item.get("title"),
        "url": item.get("url"),
        "created": item.get("created"),
        "modified": item.get("modified"),
        "is_favorite": item.get("is_favorite"),
        "is_read_only": item.get("is_read_only"),
        "is_shared": item.get("is_shared"),
        "tags": item.get("tags") if isinstance(item.get("tags"), list) else [],
        "popularity": item.get("popularity"),
        "integration_id": item.get("integration_id"),
        "icon": item.get("icon"),
        "author": _normalize_creator(item.get("author")),
    }


def _bounded_unpaged(
    items: list[dict[str, Any]],
    *,
    total: int | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any], list[str]]:
    bounded = items[:_MAX_UNPAGED_ITEMS]
    truncated = len(items) > _MAX_UNPAGED_ITEMS
    known_total = total if total is not None else len(items)
    pagination = {
        "mode": "unpaged",
        "limit": _MAX_UNPAGED_ITEMS,
        "returned": len(bounded),
        "next": None,
        "total": known_total,
        "completion": "unknown" if truncated or known_total > len(bounded) else "complete",
    }
    warnings = []
    if pagination["completion"] == "unknown":
        warnings.append("Datadog Dashboard List API 不支持分页；输出已限制为 1000 项")
    return bounded, pagination, warnings


def _dashboard_lists(body: Any) -> list[dict[str, Any]]:
    if not isinstance(body, dict):
        raise ApiError("Datadog returned an invalid Dashboard List response", error_code="invalid_response")
    values = body.get("dashboard_lists")
    if not isinstance(values, list):
        raise ApiError("Datadog returned an invalid Dashboard List response", error_code="invalid_response")
    if any(not isinstance(item, dict) for item in values):
        raise ApiError("Datadog returned an invalid Dashboard List item", error_code="invalid_response")
    return [normalize_dashboard_list(item) for item in values]


def _dashboard_list_items(body: Any) -> list[dict[str, Any]]:
    if not isinstance(body, dict):
        raise ApiError("Datadog returned an invalid Dashboard List response", error_code="invalid_response")
    values = body.get("dashboards")
    if not isinstance(values, list):
        raise ApiError("Datadog returned an invalid Dashboard List response", error_code="invalid_response")
    if any(not isinstance(item, dict) for item in values):
        raise ApiError("Datadog returned an invalid Dashboard List item", error_code="invalid_response")
    return [normalize_dashboard_list_item(item) for item in values]


def run_list(args, context: RuntimeContext) -> CommandResult:
    target = context.bind_target({"kind": "dashboard_lists"})
    body = context.client.request_read("GET", LIST_PATH)
    dashboard_lists, pagination, warnings = _bounded_unpaged(_dashboard_lists(body))
    return CommandResult(
        target=target,
        result={"dashboard_lists": dashboard_lists, "returned": len(dashboard_lists)},
        meta={"pagination": pagination},
        verification=None,
        warnings=warnings,
    )


def run_get(args, context: RuntimeContext) -> CommandResult:
    path = f"{LIST_PATH}/{args.list_id}"
    target = context.bind_target({"kind": "dashboard_list", "list_id": args.list_id})
    body = context.client.request_read("GET", path)
    if not isinstance(body, dict):
        raise ApiError("Datadog returned an invalid Dashboard List response", error_code="invalid_response")
    dashboard_list = normalize_dashboard_list(body)
    if dashboard_list["id"] != args.list_id:
        raise ApiError("Datadog Dashboard List ID does not match request", error_code="invalid_response")
    return CommandResult(
        target=target,
        result={"dashboard_list": dashboard_list},
        meta={},
        verification=None,
        warnings=[],
    )


def run_items(args, context: RuntimeContext) -> CommandResult:
    path = f"/api/v2/dashboard/lists/manual/{args.list_id}/dashboards"
    target = context.bind_target({
        "kind": "dashboard_list_items",
        "list_id": args.list_id,
    })
    body = context.client.request_read("GET", path)
    raw_items = _dashboard_list_items(body)
    raw_total = body.get("total")
    if raw_total is not None and (
        isinstance(raw_total, bool)
        or not isinstance(raw_total, int)
        or raw_total < len(raw_items)
    ):
        raise ApiError("Datadog returned an invalid Dashboard List total", error_code="invalid_response")
    total = raw_total if isinstance(raw_total, int) and not isinstance(raw_total, bool) else None
    dashboards, pagination, warnings = _bounded_unpaged(raw_items, total=total)
    return CommandResult(
        target=target,
        result={"dashboards": dashboards, "returned": len(dashboards)},
        meta={"pagination": pagination},
        verification=None,
        warnings=warnings,
    )
