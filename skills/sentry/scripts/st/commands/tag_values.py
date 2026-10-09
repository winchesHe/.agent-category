"""tag-values: get tag distribution for a specific Sentry issue."""
from __future__ import annotations

from st.client import SentryClient, path_quote
from st.commands._common import add_common_flags, add_issue_identity_flags, render_human
from st.extract import compact_tag_value
from st.formatter import output
from st.urls import resolve_issue_args

NAME = "tag-values"


def register(subparsers) -> None:
    p = subparsers.add_parser(NAME, help="查看单个 issue 的 tag value 分布")
    add_issue_identity_flags(p)
    p.add_argument("--tag", required=True, help="Tag key，如 release/environment/os.name/browser.name/user/url")
    p.add_argument("--include-raw", action="store_true", help="附带原始 API 响应")
    add_common_flags(p)
    p.set_defaults(_handler=run)


def run(args, config) -> int:
    org, issue_id, _event_id, parsed = resolve_issue_args(args, config)
    body = SentryClient(config).get_issue_resource(
        org, issue_id, f"tags/{path_quote(args.tag)}/"
    )
    values = []
    if isinstance(body, dict):
        raw_values = body.get("topValues") or body.get("values") or []
        values = raw_values if isinstance(raw_values, list) else []
    elif isinstance(body, list):
        values = body
    result = {
        "query": {
            "url": args.url,
            "organization_slug": org,
            "issue_id": issue_id,
            "project_id": parsed.project_id if parsed else None,
            "tag": args.tag,
        },
        "tag": {
            "key": body.get("key") if isinstance(body, dict) else args.tag,
            "name": body.get("name") if isinstance(body, dict) else args.tag,
            "totalValues": body.get("totalValues") if isinstance(body, dict) else None,
        },
        "items": [compact_tag_value(item) for item in values if isinstance(item, dict)],
        "count": len(values),
        "warnings": ["tag key 区分大小写；不确定字段时先看样本 event tags"],
    }
    if args.include_raw:
        result["raw"] = body
    if args.fmt == "human":
        render_human("Sentry Tag Values", result)
    output(result, fmt=args.fmt)
    return 0
