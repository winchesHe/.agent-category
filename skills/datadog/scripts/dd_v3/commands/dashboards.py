"""list-dashboards: list bounded dashboard summaries."""
from __future__ import annotations

from typing import Any

from dd_v3.argtypes import bounded_int_type
from dd_v3.errors import ApiError
from dd_v3.runtime import READ, CommandResult, RuntimeContext

NAME = "list-dashboards"
PATH = "/api/v1/dashboard"


def register(subparsers) -> None:
    parser = subparsers.add_parser(NAME, help="列出自定义 Dashboard 摘要")
    parser.add_argument(
        "--count",
        type=bounded_int_type("--count", 1, 100),
        default=25,
        help="页大小，默认 25，最大 100",
    )
    parser.add_argument(
        "--start",
        type=bounded_int_type("--start", 0, 1_000_000),
        default=0,
        help="起始偏移，默认 0",
    )
    parser.add_argument("--shared", action="store_true", help="只返回共享 Dashboard")
    parser.add_argument("--deleted", action="store_true", help="只返回已删除 Dashboard")
    parser.add_argument("--format", dest="fmt", choices=["json", "summary"], default="json")
    parser.set_defaults(_handler=run, _policy=READ)


def build_params(args) -> dict[str, Any]:
    if args.shared and args.deleted:
        raise ApiError("--shared 与 --deleted 不能同时使用")
    params: dict[str, Any] = {"count": args.count, "start": args.start}
    if args.shared:
        params["filter[shared]"] = True
    if args.deleted:
        params["filter[deleted]"] = True
    return params


def normalize_dashboard_summary(item: dict[str, Any]) -> dict[str, Any]:
    dashboard_id = item.get("id")
    title = item.get("title")
    if (
        not isinstance(dashboard_id, str)
        or not dashboard_id.strip()
        or not isinstance(title, str)
        or not title.strip()
    ):
        raise ApiError("Datadog returned an invalid dashboard item", error_code="invalid_response")
    return {
        "id": dashboard_id,
        "title": title,
        "description": item.get("description"),
        "layout_type": item.get("layout_type"),
        "is_read_only": item.get("is_read_only"),
        "author_handle": item.get("author_handle"),
        "created_at": item.get("created_at"),
        "modified_at": item.get("modified_at"),
        "url": item.get("url"),
    }


def extract_dashboards(body: Any) -> list[dict[str, Any]]:
    if not isinstance(body, dict):
        raise ApiError("Datadog returned an invalid dashboard response", error_code="invalid_response")
    dashboards = body.get("dashboards")
    if not isinstance(dashboards, list):
        raise ApiError("Datadog returned an invalid dashboard response", error_code="invalid_response")
    if any(not isinstance(item, dict) for item in dashboards):
        raise ApiError("Datadog returned an invalid dashboard item", error_code="invalid_response")
    return [normalize_dashboard_summary(item) for item in dashboards]


def pagination(*, returned: int, count: int, start: int) -> dict[str, Any]:
    full_page = returned >= count
    return {
        "mode": "offset",
        "limit": count,
        "returned": returned,
        "next": {"start": start + returned} if full_page else None,
        "total": None,
        "completion": "unknown" if full_page else "complete",
    }


def run(args, context: RuntimeContext) -> CommandResult:
    params = build_params(args)
    target = context.bind_target({
        "kind": "dashboards",
        "filters": {"shared": args.shared, "deleted": args.deleted},
    })
    body = context.client.request_read("GET", PATH, params=params)
    dashboards = extract_dashboards(body)
    return CommandResult(
        target=target,
        result={"dashboards": dashboards, "returned": len(dashboards)},
        meta={
            "pagination": pagination(
                returned=len(dashboards),
                count=args.count,
                start=args.start,
            )
        },
        verification=None,
        warnings=[],
    )
