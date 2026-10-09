"""Shared argparse and rendering helpers for Sentry commands."""
from __future__ import annotations

import sys
from typing import Any


def add_common_flags(parser) -> None:
    parser.add_argument("--format", dest="fmt", choices=["json", "human", "summary"], default="json")


def add_issue_identity_flags(parser) -> None:
    parser.add_argument("--url", help="Sentry issue/event URL")
    parser.add_argument("--org", help="Sentry organization slug，默认 SENTRY_ORG_SLUG/moego-ey")
    parser.add_argument("--issue-id", help="Sentry issue id 或 short id，如 PROJECT-123")


def render_human(title: str, data: dict[str, Any]) -> None:
    sys.stderr.write(f"# {title}\n")
    issue = data.get("issue")
    if isinstance(issue, dict):
        sys.stderr.write(f"Issue: {issue.get('shortId') or issue.get('id')} {issue.get('title')}\n")
        sys.stderr.write(f"Status: {issue.get('status')} Level: {issue.get('level')} Users: {issue.get('userCount')}\n")
        if issue.get("permalink"):
            sys.stderr.write(f"URL: {issue['permalink']}\n")
    event = data.get("event")
    if isinstance(event, dict):
        sys.stderr.write(f"Event: {event.get('id')} {event.get('title')}\n")
        for exc in event.get("exception") or []:
            sys.stderr.write(f"Exception: {exc.get('type')}: {exc.get('value')}\n")
            for frame in exc.get("frames") or []:
                marker = " in_app" if frame.get("in_app") else ""
                sys.stderr.write(
                    f"  {frame.get('filename')}:{frame.get('lineno')} {frame.get('function')}{marker}\n"
                )
        crumbs = event.get("breadcrumbs") or []
        if crumbs:
            sys.stderr.write("Recent breadcrumbs:\n")
            for crumb in crumbs[-10:]:
                sys.stderr.write(
                    f"  [{crumb.get('timestamp')}] {crumb.get('category')}: {crumb.get('message')}\n"
                )
    items = data.get("items")
    if isinstance(items, list):
        sys.stderr.write(f"Items: {len(items)}\n")
        for item in items[:20]:
            if isinstance(item, dict):
                label = item.get("shortId") or item.get("id") or item.get("slug") or item.get("value")
                detail = item.get("title") or item.get("name") or item.get("count") or ""
                sys.stderr.write(f"- {label} {detail}\n")
    for warning in data.get("warnings") or []:
        sys.stderr.write(f"warning: {warning}\n")
