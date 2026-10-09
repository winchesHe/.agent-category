"""get-dashboard: fetch Datadog dashboard widget definitions by ID."""
from __future__ import annotations

from typing import Any

from dd_v3.client import path_quote
from dd_v3.errors import ApiError
from dd_v3.runtime import READ, CommandResult, RuntimeContext

NAME = "get-dashboard"

_SCATTERPLOT_TABLE_KEYS = {"formulas", "queries", "response_format"}
_SCATTERPLOT_RESPONSE_FORMATS = {"event_list", "scalar", "timeseries"}
_SCATTERPLOT_AXIS_KEYS = {"x", "y"}
_SCATTERPLOT_REQUEST_KEYS = {"table", *_SCATTERPLOT_AXIS_KEYS}
_NESTED_WIDGET_QUERY_FIELDS = (
    "apm_query",
    "event_query",
    "log_query",
    "network_query",
    "process_query",
    "rum_query",
    "security_query",
)
_SCATTERPLOT_NESTED_AXIS_QUERY_FIELDS = _NESTED_WIDGET_QUERY_FIELDS
_SCATTERPLOT_AXIS_QUERY_FIELDS = ("q", *_SCATTERPLOT_NESTED_AXIS_QUERY_FIELDS)
_SCATTERPLOT_AXIS_REQUEST_KEYS = {"aggregator", *_SCATTERPLOT_AXIS_QUERY_FIELDS}
_SCATTERPLOT_AGGREGATORS = {"avg", "last", "max", "min", "sum"}
_LEGACY_WIDGET_QUERY_FIELDS = (
    *_NESTED_WIDGET_QUERY_FIELDS,
    "audit_query",
    "profile_metrics_query",
)


def register(subparsers) -> None:
    p = subparsers.add_parser(NAME, help="获取 Dashboard 定义（含 widget 查询）")
    p.add_argument("dashboard_id", help="Dashboard 短 ID，如 ian-th8-5fh")
    p.add_argument("--format", dest="fmt", choices=["json", "summary"], default="json")
    p.set_defaults(_handler=run, _policy=READ)


def _normalize_nested_widget_query(
    query_type: str, raw_query: Any
) -> dict[str, Any]:
    if not isinstance(raw_query, dict) or not raw_query:
        raise ApiError(
            "Datadog returned an invalid nested dashboard query",
            error_code="invalid_response",
        )
    query = dict(raw_query)
    query["query_type"] = query_type
    return query


def _extract_scatterplot_axis_query(
    axis_name: str, axis: dict[str, Any]
) -> dict[str, Any]:
    if set(axis) - _SCATTERPLOT_AXIS_REQUEST_KEYS:
        raise ApiError("Datadog returned an invalid scatterplot axis", error_code="invalid_response")
    aggregator = axis.get("aggregator")
    if "aggregator" in axis and (
        not isinstance(aggregator, str) or aggregator not in _SCATTERPLOT_AGGREGATORS
    ):
        raise ApiError(
            "Datadog returned an invalid scatterplot axis aggregator",
            error_code="invalid_response",
        )
    query_fields = [field for field in _SCATTERPLOT_AXIS_QUERY_FIELDS if field in axis]
    if len(query_fields) != 1:
        raise ApiError("Datadog returned an invalid scatterplot axis query", error_code="invalid_response")
    query_field = query_fields[0]
    query = axis[query_field]
    if query_field == "q":
        if not isinstance(query, str) or not query.strip():
            raise ApiError(
                "Datadog returned an invalid scatterplot axis query",
                error_code="invalid_response",
            )
        result: dict[str, Any] = {
            "axis": axis_name,
            "data_source": "metrics",
            "query": query,
        }
    else:
        result = _normalize_nested_widget_query(query_field, query)
        result["axis"] = axis_name
    if aggregator is not None:
        result["aggregator"] = aggregator
    return result


def _extract_scatterplot_queries(requests: dict[str, Any]) -> list[dict[str, Any]]:
    request_keys = set(requests)
    if not request_keys or request_keys - _SCATTERPLOT_REQUEST_KEYS:
        raise ApiError("Datadog returned an invalid scatterplot request", error_code="invalid_response")
    if any(
        axis_name in requests and not isinstance(requests[axis_name], dict)
        for axis_name in _SCATTERPLOT_AXIS_KEYS
    ):
        raise ApiError("Datadog returned an invalid scatterplot axis", error_code="invalid_response")
    queries: list[dict[str, Any]] = []
    if "table" in requests:
        table = requests["table"]
        if not isinstance(table, dict) or set(table) - _SCATTERPLOT_TABLE_KEYS:
            raise ApiError("Datadog returned an invalid scatterplot table", error_code="invalid_response")
        formulas = table.get("formulas", [])
        if not isinstance(formulas, list) or any(
            not isinstance(item, dict) for item in formulas
        ):
            raise ApiError("Datadog returned invalid scatterplot formulas", error_code="invalid_response")
        if (
            "response_format" in table
            and table["response_format"] not in _SCATTERPLOT_RESPONSE_FORMATS
        ):
            raise ApiError(
                "Datadog returned an invalid scatterplot response format",
                error_code="invalid_response",
            )
        raw_queries = table.get("queries", [])
        if not isinstance(raw_queries, list) or any(
            not isinstance(item, dict) for item in raw_queries
        ):
            raise ApiError("Datadog returned invalid scatterplot queries", error_code="invalid_response")
        queries.extend(dict(raw_query) for raw_query in raw_queries)
    for axis_name in ("x", "y"):
        if axis_name in requests:
            queries.append(_extract_scatterplot_axis_query(axis_name, requests[axis_name]))
    return queries


def _extract_legacy_widget_queries(request: dict[str, Any]) -> list[dict[str, Any]]:
    queries: list[dict[str, Any]] = []
    for query_type in _LEGACY_WIDGET_QUERY_FIELDS:
        if query_type not in request:
            continue
        queries.append(_normalize_nested_widget_query(query_type, request[query_type]))
    return queries


def _extract_widget_query(definition: dict[str, Any]) -> list[dict[str, Any]]:
    """Recursively extract query definitions from widget requests."""
    queries: list[dict[str, Any]] = []
    requests = definition.get("requests")
    if isinstance(requests, dict):
        if definition.get("type") != "scatterplot":
            raise ApiError("Datadog returned an invalid dashboard request", error_code="invalid_response")
        return _extract_scatterplot_queries(requests)
    if requests is not None and not isinstance(requests, list):
        raise ApiError("Datadog returned an invalid dashboard request", error_code="invalid_response")
    if isinstance(requests, list):
        for req in requests:
            if not isinstance(req, dict):
                raise ApiError("Datadog returned an invalid dashboard request", error_code="invalid_response")
            req_queries = req.get("queries")  # v2: requests[].queries[]
            if req_queries is not None and not isinstance(req_queries, list):
                raise ApiError("Datadog returned an invalid dashboard query", error_code="invalid_response")
            if isinstance(req_queries, list):
                for q in req_queries:
                    if not isinstance(q, dict):
                        raise ApiError("Datadog returned an invalid dashboard query", error_code="invalid_response")
                    queries.append(q)
            q_str = req.get("q")  # v1: requests[].q
            if q_str is not None and not isinstance(q_str, str):
                raise ApiError("Datadog returned an invalid dashboard query", error_code="invalid_response")
            if isinstance(q_str, str):
                queries.append({"query": q_str, "data_source": "metrics"})
            search = req.get("search")  # log/span analytics: requests[].search
            if search is not None and not isinstance(search, dict):
                raise ApiError("Datadog returned an invalid dashboard search", error_code="invalid_response")
            if isinstance(search, dict):
                queries.append({
                    "query": search.get("query", ""),
                    "data_source": req.get("data_source", "logs"),
                })
            queries.extend(_extract_legacy_widget_queries(req))
    return queries


def _extract_widget(widget: dict[str, Any]) -> dict[str, Any]:
    """Extract a normalized widget summary from raw dashboard widget."""
    definition = widget.get("definition")
    if not isinstance(definition, dict):
        raise ApiError("Datadog returned an invalid dashboard widget", error_code="invalid_response")
    title = definition.get("title") or widget.get("title") or ""
    widget_type = definition.get("type") or ""
    if not isinstance(widget_type, str) or not widget_type:
        raise ApiError("Datadog returned an invalid dashboard widget", error_code="invalid_response")
    queries = _extract_widget_query(definition)

    nested_widgets: list[dict[str, Any]] = []
    if widget_type == "group":
        inner = definition.get("widgets")
        if not isinstance(inner, list):
            raise ApiError("Datadog returned an invalid dashboard group", error_code="invalid_response")
        for w in inner:
            if not isinstance(w, dict):
                raise ApiError("Datadog returned an invalid dashboard widget", error_code="invalid_response")
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
    if (
        not isinstance(body, dict)
        or not isinstance(body.get("id"), str)
        or not body["id"].strip()
        or not isinstance(body.get("title"), str)
        or not body["title"].strip()
        or not isinstance(body.get("layout_type"), str)
        or not body["layout_type"].strip()
        or "widgets" not in body
    ):
        raise ApiError("Datadog returned an invalid dashboard response", error_code="invalid_response")
    widgets_raw = body.get("widgets", [])
    if not isinstance(widgets_raw, list):
        raise ApiError("Datadog returned an invalid dashboard response", error_code="invalid_response")
    widgets: list[dict[str, Any]] = []
    for widget in widgets_raw:
        if not isinstance(widget, dict):
            raise ApiError("Datadog returned an invalid dashboard widget", error_code="invalid_response")
        widgets.append(_extract_widget(widget))

    template_variables = body.get("template_variables", [])
    if not isinstance(template_variables, list) or any(
        not isinstance(item, dict) for item in template_variables
    ):
        raise ApiError("Datadog returned invalid dashboard variables", error_code="invalid_response")
    return {
        "id": body.get("id"),
        "title": body.get("title"),
        "description": body.get("description"),
        "layout_type": body.get("layout_type"),
        "template_variables": template_variables,
        "widgets": widgets,
        "widget_count": len(widgets),
    }


def run(args, context: RuntimeContext) -> CommandResult:
    target = context.bind_target({"dashboard_id": args.dashboard_id})
    body = context.client.request_read(
        "GET", f"/api/v1/dashboard/{path_quote(args.dashboard_id)}"
    )
    dashboard = extract_dashboard(body)
    if dashboard["id"] != args.dashboard_id:
        raise ApiError("Datadog dashboard ID does not match request", error_code="invalid_response")
    return CommandResult(
        target=target,
        result=dashboard,
    )
