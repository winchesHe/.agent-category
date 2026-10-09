"""query-metrics: retrieve time-series metric data from Datadog."""
from __future__ import annotations

import math
from typing import Any

from dd_v3.errors import ApiError
from dd_v3.runtime import READ, CommandResult, RuntimeContext
from dd_v3.timeutil import parse_time_to_unix_seconds

NAME = "query-metrics"


def register(subparsers) -> None:
    p = subparsers.add_parser(NAME, help="查询 Datadog Metrics 时序数据")
    p.add_argument("--query", required=True, help="Metrics 查询表达式，如 avg:system.cpu.user{service:moego-api-v3}")
    p.add_argument("--from", required=True, dest="from_time", help="起始时间，如 15m / now-1h / RFC3339")
    p.add_argument("--to", default="now", dest="to_time", help="结束时间，默认 now")
    p.add_argument("--format", dest="fmt", choices=["json", "summary"], default="json")
    p.set_defaults(_handler=run, _policy=READ)


def build_params(args) -> dict[str, Any]:
    return {
        "query": args.query,
        "from": parse_time_to_unix_seconds(args.from_time),
        "to": parse_time_to_unix_seconds(args.to_time),
    }


def _extract_series(body: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract normalized series from Datadog metrics query response."""
    series_raw = body.get("series")
    if not isinstance(series_raw, list):
        raise ApiError("Datadog returned an invalid metrics response", error_code="invalid_response")
    series: list[dict[str, Any]] = []
    for s in series_raw:
        if not isinstance(s, dict):
            raise ApiError("Datadog returned an invalid metric series", error_code="invalid_response")
        pointlist = s.get("pointlist")
        points: list[dict[str, Any]] = []
        if pointlist is None:
            pointlist = []
        if not isinstance(pointlist, list):
            raise ApiError("Datadog returned an invalid metric point list", error_code="invalid_response")
        for point in pointlist:
            if not isinstance(point, (list, tuple)) or len(point) < 2:
                raise ApiError("Datadog returned an invalid metric point", error_code="invalid_response")
            timestamp, value = point[0], point[1]
            if (
                isinstance(timestamp, bool)
                or not isinstance(timestamp, (int, float))
                or not math.isfinite(float(timestamp))
                or (
                    value is not None
                    and (
                        isinstance(value, bool)
                        or not isinstance(value, (int, float))
                        or not math.isfinite(float(value))
                    )
                )
            ):
                raise ApiError("Datadog returned an invalid metric point", error_code="invalid_response")
            points.append({
                "timestamp": timestamp,
                "value": value,
            })
        tag_set = s.get("tag_set", [])
        if not isinstance(tag_set, list):
            raise ApiError("Datadog returned an invalid metric tag set", error_code="invalid_response")
        series.append({
            "metric": s.get("metric") or s.get("query_index") or "",
            "display_name": s.get("display_name") or s.get("expression") or "",
            "scope": s.get("scope") or "",
            "unit": s.get("unit"),
            "points": points,
            "point_count": len(points),
            "start": s.get("start"),
            "end": s.get("end"),
            "interval": s.get("interval"),
            "aggr": s.get("aggr"),
            "tag_set": tag_set,
        })
    return series


def extract_metrics(body: dict[str, Any]) -> dict[str, Any]:
    """Extract structured metrics result from API response."""
    if (
        not isinstance(body, dict)
        or body.get("status") != "ok"
        or body.get("error") not in (None, "")
        or not isinstance(body.get("series"), list)
    ):
        raise ApiError("Datadog returned an invalid metrics response", error_code="invalid_response")
    series = _extract_series(body)
    return {
        "status": body.get("status"),
        "query": body.get("query") or body.get("res_type"),
        "from_date": body.get("from_date"),
        "to_date": body.get("to_date"),
        "group_by": body.get("group_by", []),
        "series": series,
        "series_count": len(series),
    }


def run(args, context: RuntimeContext) -> CommandResult:
    params = build_params(args)
    target = context.bind_target({
        "query": args.query,
        "from": args.from_time,
        "to": args.to_time,
        "from_ts": params["from"],
        "to_ts": params["to"],
    })
    body = context.client.request_read(
        "GET",
        "/api/v1/query",
        params=params,
    )
    return CommandResult(
        target=target,
        result=extract_metrics(body),
    )
