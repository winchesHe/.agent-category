"""Sentry URL parsing helpers."""
from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import parse_qs, urlparse

from st.errors import UsageError


@dataclass(frozen=True)
class ParsedSentryUrl:
    organization_slug: str | None
    issue_id: str | None
    event_id: str | None
    project_id: str | None


def parse_sentry_url(url: str) -> ParsedSentryUrl:
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.netloc:
        raise UsageError("无效 Sentry URL：必须是完整 https://... URL；拒绝 http://")

    path = parsed.path
    org = None
    org_match = re.search(r"/organizations/([^/]+)", path)
    if org_match:
        org = org_match.group(1)

    issue_id = None
    issue_match = re.search(r"/issues/([^/?#]+)", path)
    if issue_match:
        issue_id = issue_match.group(1)

    event_id = None
    event_match = re.search(r"/events/([^/?#]+)", path)
    if event_match:
        event_id = event_match.group(1)

    query = parse_qs(parsed.query)
    for key in ("eventId", "event_id"):
        if not event_id and query.get(key) and query[key][0]:
            event_id = query[key][0]
    project_id = query.get("project", [None])[0]

    if parsed.fragment:
        fragment = parse_qs(parsed.fragment)
        for key in ("eventId", "event_id"):
            if not event_id and fragment.get(key) and fragment[key][0]:
                event_id = fragment[key][0]

    return ParsedSentryUrl(
        organization_slug=org,
        issue_id=issue_id,
        event_id=event_id,
        project_id=project_id,
    )


def resolve_issue_args(args, config) -> tuple[str, str, str | None, ParsedSentryUrl | None]:
    parsed = parse_sentry_url(args.url) if getattr(args, "url", None) else None
    org = (parsed.organization_slug if parsed else None) or getattr(args, "org", None) or config.default_org_slug
    issue_id = getattr(args, "issue_id", None) or (parsed.issue_id if parsed else None)
    event_id = getattr(args, "event_id", None) or (parsed.event_id if parsed else None)
    if not issue_id:
        raise UsageError("必须提供 --url 或 --issue-id")
    return org, issue_id, event_id, parsed
