"""fetch-event: fetch one Sentry event by issue URL/event URL/event id."""
from __future__ import annotations

from st.client import SentryClient, path_quote
from st.commands._common import add_common_flags, add_issue_identity_flags, render_human
from st.extract import compact_event
from st.formatter import output
from st.urls import resolve_issue_args
from st.errors import UsageError

NAME = "fetch-event"


def register(subparsers) -> None:
    p = subparsers.add_parser(NAME, help="读取单个 Sentry event")
    add_issue_identity_flags(p)
    p.add_argument("--event-id", help="指定 event id；使用 --issue-id 时必填")
    p.add_argument("--include-raw", action="store_true", help="附带原始 API 响应")
    add_common_flags(p)
    p.set_defaults(_handler=run)


def run(args, config) -> int:
    org, issue_id, event_id, parsed = resolve_issue_args(args, config)
    warnings = []
    if not event_id and parsed is None:
        raise UsageError("使用 --issue-id 时必须同时提供 --event-id；只有 --url 模式可在 URL 无 event id 时回退 latest")
    selected_event_id = event_id or "latest"
    if selected_event_id == "latest":
        warnings.append("未提供 event id，已回退读取 latest event；多个 event 时需对比共同点")
    event = SentryClient(config).get_issue_resource(
        org, issue_id, f"events/{path_quote(selected_event_id)}/"
    )
    result = {
        "input": {
            "url": args.url,
            "organization_slug": org,
            "issue_id": issue_id,
            "event_id": selected_event_id,
            "project_id": parsed.project_id if parsed else None,
        },
        "event": compact_event(event),
        "warnings": warnings,
    }
    if args.include_raw:
        result["raw"] = event
    if args.fmt == "human":
        render_human("Sentry Event", result)
    output(result, fmt=args.fmt)
    return 0
