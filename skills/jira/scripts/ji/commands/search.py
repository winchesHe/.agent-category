"""Search Jira issues with JQL."""
from __future__ import annotations

import argparse
from typing import Any

from ji.adf import extract_value
from ji.client import JiraClient
from ji.config import Config
from ji.formatter import output
from ji.parsing import csv_list

DEFAULT_SEARCH_FIELDS = [
    "summary",
    "status",
    "issuetype",
    "created",
    "updated",
    "assignee",
    "priority",
    "components",
    "issuelinks",
    "customfield_10049",
    "customfield_10089",
    "customfield_10088",
]


def register(subparsers) -> None:
    parser = subparsers.add_parser("search", help="Search Jira issues via POST /rest/api/3/search/jql")
    parser.add_argument("jql", help="JQL query string")
    parser.add_argument("--limit", type=int, default=10, help="Maximum results (default: 10)")
    parser.add_argument("--fields", default=",".join(DEFAULT_SEARCH_FIELDS), help="Comma-separated fields")
    parser.add_argument("--page-token", help="Jira Cloud nextPageToken")
    parser.add_argument("--format", choices=("json", "human", "summary"), default="json")
    parser.set_defaults(_handler=run)


def _project_key(issue_key: Any) -> str | None:
    if not isinstance(issue_key, str) or "-" not in issue_key:
        return None
    return issue_key.split("-", 1)[0] or None


def _simplify_links(value: Any, base_url: str) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    links = []
    for item in value:
        if not isinstance(item, dict):
            continue
        target = item.get("outwardIssue")
        direction = "outward"
        relationship_key = "outward"
        if not isinstance(target, dict):
            target = item.get("inwardIssue")
            direction = "inward"
            relationship_key = "inward"
        if not isinstance(target, dict):
            continue
        issue_key = target.get("key")
        if not isinstance(issue_key, str) or not issue_key:
            continue
        target_fields = target.get("fields") or {}
        if not isinstance(target_fields, dict):
            target_fields = {}
        link_type = item.get("type") or {}
        if not isinstance(link_type, dict):
            link_type = {}
        links.append(
            {
                "id": item.get("id"),
                "type": link_type.get("name"),
                "direction": direction,
                "relationship": link_type.get(relationship_key),
                "key": issue_key,
                "project_key": _project_key(issue_key),
                "issue_type": extract_value(target_fields.get("issuetype")),
                "status": extract_value(target_fields.get("status")),
                "url": f"{base_url.rstrip('/')}/browse/{issue_key}",
            }
        )
    return links


def _simplify_issue(item: dict[str, Any], base_url: str) -> dict[str, Any]:
    fields = item.get("fields") or {}
    components = extract_value(fields.get("components")) or []
    if not isinstance(components, list):
        components = [components]
    raw_links = fields.get("issuelinks")
    links = _simplify_links(raw_links, base_url)
    issue_key = item.get("key")
    return {
        "key": item.get("key"),
        "id": item.get("id"),
        "url": (
            f"{base_url.rstrip('/')}/browse/{issue_key}"
            if isinstance(issue_key, str) and issue_key
            else None
        ),
        "summary": fields.get("summary"),
        "issue_type": extract_value(fields.get("issuetype")),
        "status": extract_value(fields.get("status")),
        "priority": extract_value(fields.get("priority") or fields.get("customfield_10049")),
        "squad": extract_value(fields.get("customfield_10089")),
        "issue_cause": extract_value(fields.get("customfield_10088")),
        "assignee": extract_value(fields.get("assignee")),
        "components": components,
        "created": fields.get("created"),
        "updated": fields.get("updated"),
        "link_count": len(raw_links) if isinstance(raw_links, list) else 0,
        "links": links,
    }


def run(args: argparse.Namespace, config: Config) -> int:
    client = JiraClient(config)
    payload = client.search_jql(
        jql=args.jql,
        fields=csv_list(args.fields),
        limit=args.limit,
        page_token=args.page_token,
    )
    issues = [
        _simplify_issue(item, config.jira_base_url)
        for item in payload.get("issues", [])
        if isinstance(item, dict)
    ]
    result = {
        "schema_version": 1,
        "command": "search",
        "ok": True,
        "jql": args.jql,
        "fields": csv_list(args.fields),
        "count": len(issues),
        "total": payload.get("total"),
        "is_last": payload.get("isLast"),
        "next_page_token": payload.get("nextPageToken"),
        "issues": issues,
    }
    output(result, fmt=args.format)
    return 0
