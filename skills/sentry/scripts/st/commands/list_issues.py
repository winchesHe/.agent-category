"""list-issues: list grouped Sentry issues with query syntax."""
from __future__ import annotations

from st.client import SentryClient, path_quote
from st.commands._common import add_common_flags, render_human
from st.extract import compact_issue
from st.formatter import output

NAME = "list-issues"


def register(subparsers) -> None:
    p = subparsers.add_parser(NAME, help="用 Sentry issue query syntax 列出 grouped issues")
    p.add_argument("--org", help="Sentry organization slug，默认 SENTRY_ORG_SLUG/moego-ey")
    p.add_argument("--project", help="Project slug；默认 SENTRY_DEFAULT_PROJECT")
    p.add_argument("--query", required=True, help='Issue query，如 "is:unresolved lastSeen:-24h"')
    p.add_argument("--sort", choices=["date", "freq", "new", "user"], default="date", help="排序：date/freq/new/user")
    p.add_argument("--limit", type=int, default=20, help="返回数量，默认 20，最大 100")
    p.add_argument("--include-raw", action="store_true", help="附带原始 API 响应")
    add_common_flags(p)
    p.set_defaults(_handler=run)


def run(args, config) -> int:
    org = args.org or config.default_org_slug
    project = args.project or config.default_project
    params = {
        "query": args.query,
        "sort": args.sort,
        "per_page": str(min(max(args.limit, 1), 100)),
        "statsPeriod": "24h",
        "collapse": "unhandled",
    }
    path = (
        f"/api/0/projects/{path_quote(org)}/{path_quote(project)}/issues/"
        if project
        else f"/api/0/organizations/{path_quote(org)}/issues/"
    )
    body = SentryClient(config).get(path, params=params)
    items = body if isinstance(body, list) else body.get("data", []) if isinstance(body, dict) else []
    result = {
        "query": {
            "organization_slug": org,
            "project": project,
            "query": args.query,
            "sort": args.sort,
            "limit": min(max(args.limit, 1), 100),
        },
        "items": [compact_issue(item) for item in items if isinstance(item, dict)],
        "count": len(items) if isinstance(items, list) else 0,
        "warnings": ["Sentry event count 受采样和循环崩溃影响；评估影响面优先看 userCount"],
    }
    if args.include_raw:
        result["raw"] = body
    if args.fmt == "human":
        render_human("Sentry Issues", result)
    output(result, fmt=args.fmt)
    return 0
