"""get-dashboard: fetch Datadog dashboard widget definitions by ID."""
from __future__ import annotations

import sys
from typing import Any

from dd.client import DatadogClient
from dd.formatter import output

NAME = "get-dashboard"


def register(subparsers) -> None:
    p = subparsers.add_parser(NAME, help="获取 Dashboard 定义（含 widget 查询）")
    p.add_argument("dashboard_id", help="Dashboard 短 ID，如 ian-th8-5fh")
    p.add_argument("--format", dest="fmt", choices=["json", "human", "summary"], default="json")
    p.set_defaults(_handler=run)


def _extract_widget_query(definition: dict[str, Any]) -> list[dict[str, Any]]:
    """Recursively extract query definitions from widget requests."""
    queries: list[dict[str, Any]] = []
    requests = definition.get("requests")
    if isinstance(requests, list):
        for req in requests:
            if not isinstance(req, dict):
                continue
            # v2 widget format: requests[].queries[]
            req_queries = req.get("queries")
            if isinstance(req_queries, list):
                for q in req_queries:
                    if isinstance(q, dict):
                        queries.append(q)
            # v1 widget format: requests[].q
            q_str = req.get("q")
            if isinstance(q_str, str):
                queries.append({"query": q_str, "data_source": "metrics"})
            # log/span analytics: requests[].search / requests[].data_source
            search = req.get("search")
            if isinstance(search, dict):
                queries.append({
                    "query": search.get("query", ""),
                    "data_source": req.get("data_source", "logs"),
                })
    return queries


def _extract_widget(widget: dict[str, Any]) -> dict[str, Any]:
    """Extract a normalized widget summary from raw dashboard widget."""
    definition = widget.get("definition", {}) if isinstance(widget.get("definition"), dict) else {}
    title = definition.get("title") or widget.get("title") or ""
    widget_type = definition.get("type") or ""
    queries = _extract_widget_query(definition)

    # Handle nested group widgets
    nested_widgets: list[dict[str, Any]] = []
    if widget_type == "group":
        inner = definition.get("widgets")
        if isinstance(inner, list):
            for w in inner:
                if isinstance(w, dict):
                    nested_widgets.append(_extract_widget(w))

    result: dict[str, Any] = {
        "title": title,
        "type": widget_type,
        "queries": queries,
    }
    if nested_widgets:
        result["widgets"] = nested_widgets
    return result


def extract_dashboard(body: dict[str, Any]) -> dict[str, Any]:
    """Extract structured dashboard info from API response."""
    widgets_raw = body.get("widgets", [])
    widgets: list[dict[str, Any]] = []
    if isinstance(widgets_raw, list):
        for widget in widgets_raw:
            if isinstance(widget, dict):
                widgets.append(_extract_widget(widget))

    template_variables = body.get("template_variables", [])
    return {
        "id": body.get("id"),
        "title": body.get("title"),
        "description": body.get("description"),
        "layout_type": body.get("layout_type"),
        "template_variables": template_variables if isinstance(template_variables, list) else [],
        "widgets": widgets,
        "widget_count": len(widgets),
    }


def _render_human(result: dict[str, Any]) -> None:
    sys.stderr.write(f"Dashboard: {result.get('title')} ({result.get('id')})\n")
    sys.stderr.write(f"Layout: {result.get('layout_type')}\n")
    tpl_vars = result.get("template_variables", [])
    if tpl_vars:
        sys.stderr.write(f"Template variables: {[v.get('name') for v in tpl_vars if isinstance(v, dict)]}\n")
    sys.stderr.write(f"Widgets ({result.get('widget_count')}):\n")
    for widget in result.get("widgets", []):
        sys.stderr.write(f"  [{widget.get('type')}] {widget.get('title')}\n")
        for q in widget.get("queries", []):
            sys.stderr.write(f"    query: {q.get('query', q.get('name', ''))}\n")


def run(args, config) -> int:
    sys.stderr.write(f"[get-dashboard] id={args.dashboard_id}\n")
    body = DatadogClient(config).get(f"/api/v1/dashboard/{args.dashboard_id}")
    result = extract_dashboard(body)
    if args.fmt == "human":
        _render_human(result)
    output(result, fmt=args.fmt)
    return 0
