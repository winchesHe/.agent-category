"""get-issue: fetch Sentry issue details and optional event context."""
from __future__ import annotations

from st.client import SentryClient, path_quote
from st.commands._common import add_common_flags, add_issue_identity_flags, render_human
from st.extract import compact_event, compact_issue
from st.formatter import output
from st.urls import resolve_issue_args

NAME = "get-issue"


def register(subparsers) -> None:
    p = subparsers.add_parser(NAME, help="读取 Sentry issue，并可附带 latest/指定 event")
    add_issue_identity_flags(p)
    p.add_argument("--event-id", help="指定 event id；省略时可按 --include-event 策略读取 latest")
    p.add_argument(
        "--include-event",
        choices=["auto", "always", "never"],
        default="auto",
        help="auto: URL 有 event 读 event；URL 只有 issue 时读 latest；issue-id 模式默认不读",
    )
    p.add_argument("--include-raw", action="store_true", help="附带原始 API 响应")
    add_common_flags(p)
    p.set_defaults(_handler=run)


def run(args, config) -> int:
    org, issue_id, event_id, parsed = resolve_issue_args(args, config)
    client = SentryClient(config)
    issue = client.get_issue_resource(org, issue_id)

    warnings: list[str] = []
    should_fetch_event = False
    selected_event_id = event_id
    if args.include_event == "always":
        should_fetch_event = True
        selected_event_id = selected_event_id or "latest"
    elif args.include_event == "auto":
        if selected_event_id:
            should_fetch_event = True
        elif parsed is not None and parsed.issue_id:
            should_fetch_event = True
            selected_event_id = "latest"
            warnings.append("URL 未包含 event id，已回退读取 latest event；不要只基于 latest event 下最终结论")

    event = None
    if should_fetch_event:
        event = client.get_issue_resource(
            org, issue_id, f"events/{path_quote(selected_event_id or 'latest')}/"
        )

    result = {
        "input": {
            "url": args.url,
            "organization_slug": org,
            "issue_id": issue_id,
            "event_id": selected_event_id,
            "project_id": parsed.project_id if parsed else None,
        },
        "issue": compact_issue(issue),
        "event": compact_event(event) if isinstance(event, dict) else None,
        "warnings": warnings,
    }
    if args.include_raw:
        result["raw"] = {"issue": issue, "event": event}
    if args.fmt == "human":
        render_human("Sentry Issue", result)
    output(result, fmt=args.fmt)
    return 0
