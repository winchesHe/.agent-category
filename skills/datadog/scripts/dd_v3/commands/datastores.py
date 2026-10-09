"""list-datastores: discover organization Actions Datastores."""
from __future__ import annotations

from typing import Any

from dd_v3.errors import ApiError
from dd_v3.runtime import READ, CommandResult, RuntimeContext

NAME = "list-datastores"
PATH = "/api/v2/actions-datastores"
_MAX_DATASTORES = 1000
_PRIMARY_KEY_STRATEGIES = {"none", "uuid"}


def register(subparsers) -> None:
    parser = subparsers.add_parser(NAME, help="列出 Actions Datastore 摘要")
    parser.add_argument("--format", dest="fmt", choices=["json", "summary"], default="json")
    parser.set_defaults(_handler=run, _policy=READ)


def _optional_string(attributes: dict[str, Any], name: str) -> str | None:
    value = attributes.get(name)
    if value is not None and not isinstance(value, str):
        raise ApiError("Datadog returned an invalid datastore item", error_code="invalid_response")
    return value


def _normalize_datastore(item: Any) -> dict[str, Any]:
    if (
        not isinstance(item, dict)
        or not isinstance(item.get("id"), str)
        or not item["id"].strip()
        or item.get("type") != "datastores"
        or not isinstance(item.get("attributes"), dict)
    ):
        raise ApiError("Datadog returned an invalid datastore item", error_code="invalid_response")
    attributes = item["attributes"]
    name = attributes.get("name")
    primary_column_name = attributes.get("primary_column_name")
    strategy = attributes.get("primary_key_generation_strategy")
    if (
        not isinstance(name, str)
        or not name.strip()
        or not isinstance(primary_column_name, str)
        or not isinstance(strategy, str)
        or strategy not in _PRIMARY_KEY_STRATEGIES
    ):
        raise ApiError("Datadog returned an invalid datastore item", error_code="invalid_response")
    return {
        "id": item["id"],
        "name": name,
        "description": _optional_string(attributes, "description"),
        "primary_column_name": primary_column_name,
        "primary_key_generation_strategy": strategy,
        "created_at": _optional_string(attributes, "created_at"),
        "modified_at": _optional_string(attributes, "modified_at"),
    }


def _extract_datastores(body: Any) -> list[dict[str, Any]]:
    if not isinstance(body, dict) or not isinstance(body.get("data"), list):
        raise ApiError("Datadog returned an invalid datastore response", error_code="invalid_response")
    return [_normalize_datastore(item) for item in body["data"]]


def run(args, context: RuntimeContext) -> CommandResult:
    target = context.bind_target({"kind": "actions_datastores"})
    datastores = _extract_datastores(context.client.request_read("GET", PATH))
    bounded = datastores[:_MAX_DATASTORES]
    truncated = len(datastores) > _MAX_DATASTORES
    return CommandResult(
        target=target,
        result={"datastores": bounded, "returned": len(bounded)},
        meta={
            "pagination": {
                "mode": "unpaged",
                "limit": _MAX_DATASTORES,
                "returned": len(bounded),
                "total": len(datastores),
                "next": None,
                "completion": "unknown" if truncated else "complete",
            }
        },
        verification=None,
        warnings=["datastores_truncated"] if truncated else [],
    )
