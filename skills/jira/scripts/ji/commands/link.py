"""Create a typed link between two Jira issues."""
from __future__ import annotations

import argparse
from typing import Any

from ji.client import JiraClient
from ji.config import Config
from ji.errors import UsageError
from ji.formatter import output
from ji.parsing import parse_issue_key


def register(subparsers) -> None:
    parser = subparsers.add_parser("link", help="Link two Jira issues; dry-run unless --execute is set")
    parser.add_argument("inward_issue", help="Inward Jira key or URL")
    parser.add_argument("outward_issue", help="Outward Jira key or URL")
    parser.add_argument("--type", required=True, dest="link_type", help="Live Jira link type name")
    parser.add_argument("--execute", action="store_true", help="Actually create the issue link")
    parser.add_argument("--format", choices=("json", "human", "summary"), default="json")
    parser.set_defaults(_handler=run)


def _resolve_link_type(link_types: list[dict[str, Any]], requested: str) -> dict[str, Any]:
    normalized = requested.strip().casefold()
    matches = [
        item for item in link_types
        if isinstance(item.get("name"), str) and item["name"].casefold() == normalized
    ]
    if len(matches) == 1:
        return matches[0]
    available = ", ".join(sorted(str(item.get("name")) for item in link_types if item.get("name")))
    if not matches:
        raise UsageError(f"unknown Jira issue link type: {requested}. Available: {available}")
    raise UsageError(f"ambiguous Jira issue link type: {requested}")


def run(args: argparse.Namespace, config: Config) -> int:
    inward_key = parse_issue_key(args.inward_issue)
    outward_key = parse_issue_key(args.outward_issue)
    if inward_key == outward_key:
        raise UsageError("cannot link an issue to itself")

    client = JiraClient(config)
    link_type = _resolve_link_type(client.get_issue_link_types(), args.link_type)
    payload = {
        "type": {"name": link_type["name"]},
        "inwardIssue": {"key": inward_key},
        "outwardIssue": {"key": outward_key},
    }
    result: dict[str, Any] = {
        "schema_version": 1,
        "command": "link",
        "ok": True,
        "dry_run": not args.execute,
        "link_type": {
            "id": link_type.get("id"),
            "name": link_type.get("name"),
            "inward": link_type.get("inward"),
            "outward": link_type.get("outward"),
        },
        "payload": payload,
    }
    if args.execute:
        result["response"] = client.create_issue_link(payload)
    output(result, fmt=args.format)
    return 0
