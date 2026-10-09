"""Read live Jira create-screen metadata."""
from __future__ import annotations

import argparse
from typing import Any

from ji.client import JiraClient
from ji.config import Config
from ji.errors import ApiError
from ji.formatter import output


def register(subparsers) -> None:
    parser = subparsers.add_parser(
        "create-meta",
        help="Read live create-screen fields and allowed values for an issue type",
    )
    parser.add_argument("--project", required=True, help="Jira project key or id")
    parser.add_argument("--issue-type-id", required=True, help="Jira issue type id")
    parser.add_argument("--format", choices=("json", "human", "summary"), default="json")
    parser.set_defaults(_handler=run)


def _simplify(item: dict[str, Any]) -> dict[str, Any]:
    result = {
        "id": item.get("fieldId") or item.get("key") or item.get("id"),
        "name": item.get("name"),
        "required": bool(item.get("required")),
        "schema": item.get("schema") or {},
        "operations": item.get("operations") or [],
    }
    if isinstance(item.get("allowedValues"), list):
        result["allowed_values"] = item["allowedValues"]
    return result


def run(args: argparse.Namespace, config: Config) -> int:
    fields, _pages = JiraClient(config).get_create_fields(args.project, str(args.issue_type_id))
    if not fields:
        raise ApiError(
            f"Jira returned no create fields for {args.project}/{args.issue_type_id}; "
            "verify the project, issue type, permissions, and endpoint response"
        )
    result = {
        "schema_version": 1,
        "command": "create-meta",
        "ok": True,
        "project": args.project,
        "issue_type_id": str(args.issue_type_id),
        "fields": [_simplify(item) for item in fields],
    }
    output(result, fmt=args.format)
    return 0
