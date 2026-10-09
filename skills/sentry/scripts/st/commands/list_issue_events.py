"""list-issue-events: list/filter events within a single issue."""
from __future__ import annotations

from st.client import SentryClient
from st.commands._common import add_common_flags, add_issue_identity_flags, render_human
from st.extract import compact_issue_event
from st.formatter import output
from st.urls import resolve_issue_args

NAME = "list-issue-events"


def register(subparsers) -> None:
    p = subparsers.add_parser(NAME, help="在单个 Sentry issue 内筛选/对比 events")
    add_issue_identity_flags(p)
    p.add_argument("--query", default="", help='Issue 内 event query；不要加 issue: 前缀，如 "environment:production"')
    p.add_argument("--sort", default="-timestamp", help="排序字段，默认 -timestamp")
    p.add_argument("--stats-period", default="14d", help="时间窗口，如 1h/24h/14d/30d")
    p.add_argument("--limit", type=int, default=50, help="返回数量，默认 50，最大 100")
    p.add_argument("--include-raw", action="store_true", help="附带原始 API 响应")
    add_common_flags(p)
    p.set_defaults(_handler=run)


def run(args, config) -> int:
    org, issue_id, _event_id, parsed = resolve_issue_args(args, config)
    params = {
        "query": args.query,
        "sort": args.sort,
        "statsPeriod": args.stats_period,
        "per_page": str(min(max(args.limit, 1), 100)),
    }
    body = SentryClient(config).get_issue_resource(
        org, issue_id, "events/", params=params
    )
    items = body if isinstance(body, list) else body.get("data", []) if isinstance(body, dict) else []
    result = {
        "query": {
            "url": args.url,
            "organization_slug": org,
            "issue_id": issue_id,
            "project_id": parsed.project_id if parsed else None,
            "query": args.query,
            "sort": args.sort,
            "stats_period": args.stats_period,
            "limit": min(max(args.limit, 1), 100),
        },
        "items": [compact_issue_event(item) for item in items if isinstance(item, dict)],
        "count": len(items) if isinstance(items, list) else 0,
        "warnings": ["该 endpoint 已限定 issue；query 中不要再添加 issue: 前缀"],
    }
    if args.include_raw:
        result["raw"] = body
    if args.fmt == "human":
        render_human("Sentry Issue Events", result)
    output(result, fmt=args.fmt)
    return 0
