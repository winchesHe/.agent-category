"""list-datastore-items: read projected Actions Datastore rows."""
from __future__ import annotations

import argparse
import json
import re
from typing import Any

from dd_v3.argtypes import bounded_int_type
from dd_v3.client import path_quote
from dd_v3.errors import ApiError, UsageError
from dd_v3.runtime import READ, CommandResult, RuntimeContext

NAME = "list-datastore-items"
_DATASTORE_ID = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
_SORT_FIELD = re.compile(r"^-?[A-Za-z_][A-Za-z0-9_]{0,62}$")


def _datastore_id(value: str) -> str:
    if not _DATASTORE_ID.fullmatch(value):
        raise argparse.ArgumentTypeError("datastore_id 格式无效")
    return value


def _sort_field(value: str) -> str:
    if not _SORT_FIELD.fullmatch(value):
        raise argparse.ArgumentTypeError("sort 字段格式无效")
    return value


def register(subparsers) -> None:
    parser = subparsers.add_parser(NAME, help="分页读取 Actions Datastore 条目")
    parser.add_argument("datastore_id", type=_datastore_id, help="Datastore ID")
    filters = parser.add_mutually_exclusive_group()
    filters.add_argument("--filter", dest="query_filter", help="Datastore 查询过滤条件")
    filters.add_argument("--item-key", help="按主键读取单个条目")
    parser.add_argument(
        "--page-size",
        type=bounded_int_type("--page-size", 1, 100),
        default=100,
        help="每页条数，默认 100，最大 100",
    )
    parser.add_argument(
        "--offset",
        type=bounded_int_type("--offset", 0, 10_000_000),
        default=0,
        help="起始偏移，默认 0",
    )
    parser.add_argument(
        "--sort",
        type=_sort_field,
        help="稳定排序字段；完整分页可用它替代多轮一致性扫描，降序加 - 前缀",
    )
    parser.add_argument(
        "--all-pages",
        action="store_true",
        help="从 offset 开始继续读取后续页",
    )
    parser.add_argument(
        "--consistency-passes",
        type=bounded_int_type("--consistency-passes", 1, 3),
        default=1,
        help="无稳定排序时完整扫描次数；至少 2 次且结果完全一致才算完整",
    )
    parser.add_argument(
        "--max-items",
        type=bounded_int_type("--max-items", 1, 10_000),
        default=10_000,
        help="--all-pages 最大返回条数，默认 10000",
    )
    parser.add_argument(
        "--field",
        dest="fields",
        action="append",
        default=[],
        help="只输出指定 value 字段，可重复",
    )
    parser.add_argument("--format", dest="fmt", choices=["json", "summary"], default="json")
    parser.set_defaults(_handler=run, _policy=READ)


def _page_metadata(body: Any) -> tuple[bool, int | None, dict[str, Any]]:
    if not isinstance(body, dict):
        raise ApiError("Datadog returned an invalid datastore response", error_code="invalid_response")
    meta = body.get("meta")
    if not isinstance(meta, dict):
        raise ApiError("Datadog returned invalid datastore metadata", error_code="invalid_response")
    page = meta.get("page")
    schema = meta.get("schema")
    if not isinstance(page, dict) or not isinstance(schema, dict):
        raise ApiError("Datadog returned invalid datastore metadata", error_code="invalid_response")
    has_more = page.get("hasMore")
    total = page.get("totalFilteredCount")
    if (
        not isinstance(has_more, bool)
        or not isinstance(total, int)
        or isinstance(total, bool)
        or total < 0
    ):
        raise ApiError("Datadog returned invalid datastore pagination", error_code="invalid_response")
    return has_more, total, schema


def _schema_fields(schema: dict[str, Any]) -> dict[str, str]:
    fields = schema.get("fields")
    if not isinstance(fields, list):
        raise ApiError("Datadog returned invalid datastore schema", error_code="invalid_response")
    normalized: dict[str, str] = {}
    for field in fields:
        if not isinstance(field, dict):
            raise ApiError("Datadog returned invalid datastore schema", error_code="invalid_response")
        name = field.get("name")
        field_type = field.get("type")
        if not isinstance(name, str) or not name or not isinstance(field_type, str):
            raise ApiError("Datadog returned invalid datastore schema", error_code="invalid_response")
        normalized[name] = field_type
    return normalized


def _normalize_item(item: Any, fields: list[str]) -> dict[str, Any]:
    if (
        not isinstance(item, dict)
        or not isinstance(item.get("id"), str)
        or item.get("type") != "items"
    ):
        raise ApiError("Datadog returned an invalid datastore item", error_code="invalid_response")
    attributes = item.get("attributes")
    if not isinstance(attributes, dict) or not isinstance(attributes.get("value"), dict):
        raise ApiError("Datadog returned an invalid datastore item", error_code="invalid_response")
    value = attributes["value"]
    projected = {field: value.get(field) for field in fields} if fields else dict(value)
    return {
        "id": item["id"],
        "created_at": attributes.get("created_at"),
        "modified_at": attributes.get("modified_at"),
        "value": projected,
    }


def _extract_page(
    body: Any,
    fields: list[str],
) -> tuple[list[dict[str, Any]], bool, int, dict[str, Any]]:
    if not isinstance(body, dict) or not isinstance(body.get("data"), list):
        raise ApiError("Datadog returned an invalid datastore response", error_code="invalid_response")
    has_more, total, schema = _page_metadata(body)
    available = _schema_fields(schema)
    unknown = sorted(set(fields) - set(available))
    if unknown:
        raise ApiError(
            f"Datastore schema does not contain requested fields: {', '.join(unknown)}",
            error_code="unknown_field",
        )
    items = [_normalize_item(item, fields) for item in body["data"]]
    if has_more and not items:
        raise ApiError("Datadog returned an empty datastore page with hasMore=true", error_code="invalid_response")
    projected_schema = {
        "primary_key": schema.get("primary_key"),
        "fields": [
            {"name": name, "type": field_type}
            for name, field_type in available.items()
            if not fields or name in fields
        ],
    }
    return items, has_more, total, projected_schema


def _params(args, *, offset: int, limit: int) -> dict[str, Any]:
    params: dict[str, Any] = {"page[limit]": limit, "page[offset]": offset}
    if args.query_filter:
        params["filter"] = args.query_filter
    if args.item_key:
        params["item_key"] = args.item_key
    if args.sort:
        params["sort"] = args.sort
    return params


def _scan(args, context: RuntimeContext, path: str, fields: list[str]) -> dict[str, Any]:
    offset = args.offset
    items: list[dict[str, Any]] = []
    has_more = False
    total: int | None = None
    schema: dict[str, Any] = {}
    while True:
        remaining = args.max_items - len(items) if args.all_pages else args.page_size
        limit = min(args.page_size, remaining)
        body = context.client.request_read(
            "GET",
            path,
            params=_params(args, offset=offset, limit=limit),
        )
        page_items, has_more, page_total, page_schema = _extract_page(body, fields)
        if total is None:
            total = page_total
            schema = page_schema
        elif page_total != total:
            raise ApiError(
                "Datastore result count changed during pagination",
                error_code="pagination_changed",
                category="conflict",
                retry_class="safe",
            )
        items.extend(page_items)
        offset += len(page_items)
        if not args.all_pages or not has_more or len(items) >= args.max_items:
            break

    truncated = has_more and len(items) >= args.max_items
    if args.all_pages and not truncated:
        expected = max((total or 0) - args.offset, 0)
        if len(items) != expected:
            raise ApiError(
                "Datastore pagination returned fewer items than totalFilteredCount",
                error_code="pagination_changed",
                category="conflict",
                retry_class="safe",
            )
    if truncated:
        completion = "truncated"
    elif has_more:
        completion = "partial"
    else:
        completion = "complete"
    item_ids = [item["id"] for item in items]
    if len(item_ids) != len(set(item_ids)):
        raise ApiError(
            "Datastore pagination returned duplicate item ids",
            error_code="pagination_changed",
            category="conflict",
            retry_class="safe",
        )
    return {
        "items": items,
        "has_more": has_more,
        "total": total,
        "schema": schema,
        "offset": offset,
        "completion": completion,
        "truncated": truncated,
    }


def _scan_signature(scan: dict[str, Any]) -> tuple[Any, ...]:
    items = scan["items"]
    by_id = {
        item["id"]: json.dumps(item, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        for item in items
    }
    return (
        scan["total"],
        json.dumps(scan["schema"], ensure_ascii=False, sort_keys=True, separators=(",", ":")),
        tuple(sorted(by_id.items())),
    )


def run(args, context: RuntimeContext) -> CommandResult:
    if args.consistency_passes != 1 and not args.all_pages:
        raise UsageError("--consistency-passes 只能与 --all-pages 一起使用")
    if args.all_pages and not args.sort and args.consistency_passes < 2:
        raise UsageError("无稳定 --sort 时，--all-pages 必须提供至少 2 次一致性扫描")
    if args.sort and args.consistency_passes != 1:
        raise UsageError("稳定 --sort 与 --consistency-passes 不能同时使用")

    fields = list(dict.fromkeys(args.fields))
    target = context.bind_target(
        {
            "kind": "actions_datastore_items",
            "datastore_id": args.datastore_id,
            "filter": args.query_filter,
            "item_key": args.item_key,
            "sort": args.sort,
            "fields": fields,
        }
    )
    path = f"/api/v2/actions-datastores/{path_quote(args.datastore_id)}/items"
    scan = _scan(args, context, path, fields)
    verification = None
    if args.all_pages and not scan["truncated"]:
        if args.sort:
            verification = {
                "mode": "stable-sort",
                "field": args.sort,
                "passes": 1,
                "matched": True,
            }
        else:
            expected_signature = _scan_signature(scan)
            for _pass_number in range(2, args.consistency_passes + 1):
                candidate = _scan(args, context, path, fields)
                if candidate["truncated"] or _scan_signature(candidate) != expected_signature:
                    raise ApiError(
                        "Datastore pagination did not converge across consistency passes",
                        error_code="pagination_changed",
                        category="conflict",
                        retry_class="safe",
                    )
                scan = candidate
            verification = {
                "mode": "converged-read",
                "passes": args.consistency_passes,
                "matched": True,
            }

    warnings = ["datastore_items_truncated"] if scan["truncated"] else []
    return CommandResult(
        target=target,
        result={"items": scan["items"], "returned": len(scan["items"])},
        meta={
            "schema": scan["schema"],
            "pagination": {
                "mode": "offset",
                "start": args.offset,
                "limit": args.page_size,
                "returned": len(scan["items"]),
                "total": scan["total"],
                "has_more": scan["has_more"],
                "next": {"offset": scan["offset"]} if scan["has_more"] else None,
                "completion": scan["completion"],
            },
        },
        verification=verification,
        warnings=warnings,
    )
