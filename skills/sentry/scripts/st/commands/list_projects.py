"""list-projects: discover Sentry project slugs."""
from __future__ import annotations

from st.client import SentryClient, path_quote
from st.commands._common import add_common_flags, render_human
from st.extract import compact_project
from st.formatter import output

NAME = "list-projects"


def register(subparsers) -> None:
    p = subparsers.add_parser(NAME, help="列出/搜索 Sentry projects")
    p.add_argument("--org", help="Sentry organization slug，默认 SENTRY_ORG_SLUG/moego-ey")
    p.add_argument("--query", help="Project 搜索关键字")
    p.add_argument("--limit", type=int, default=25, help="返回数量，默认 25，最大 100")
    p.add_argument("--include-raw", action="store_true", help="附带原始 API 响应")
    add_common_flags(p)
    p.set_defaults(_handler=run)


def run(args, config) -> int:
    org = args.org or config.default_org_slug
    params = {"per_page": str(min(max(args.limit, 1), 100))}
    if args.query:
        params["query"] = args.query
    body = SentryClient(config).get(f"/api/0/organizations/{path_quote(org)}/projects/", params=params)
    items = body if isinstance(body, list) else body.get("data", []) if isinstance(body, dict) else []
    result = {
        "query": {
            "organization_slug": org,
            "query": args.query,
            "limit": min(max(args.limit, 1), 100),
        },
        "items": [compact_project(item) for item in items if isinstance(item, dict)],
        "count": len(items) if isinstance(items, list) else 0,
        "warnings": [],
    }
    if args.include_raw:
        result["raw"] = body
    if args.fmt == "human":
        render_human("Sentry Projects", result)
    output(result, fmt=args.fmt)
    return 0
