"""query-metrics: retrieve time-series metric data from Datadog."""
from __future__ import annotations

import sys
from typing import Any

from dd.client import DatadogClient
from dd.formatter import output
from dd.timeutil import parse_time_to_unix_seconds

NAME = "query-metrics"


def register(subparsers) -> None:
    p = subparsers.add_parser(NAME, help="查询 Datadog Metrics 时序数据")
    p.add_argument("--query", required=True, help="Metrics 查询表达式，如 avg:system.cpu.user{service:moego-api-v3}")
    p.add_argument("--from", required=True, dest="from_time", help="起始时间，如 15m / now-1h / RFC3339")
    p.add_argument("--to", default="now", dest="to_time", help="结束时间，默认 now")
    p.add_argument("--format", dest="fmt", choices=["json", "human", "summary"], default="json")
    p.set_defaults(_handler=run)


def build_params(args) -> dict[str, Any]:
    return {
        "query": args.query,
        "from": parse_time_to_unix_seconds(args.from_time),
        "to": parse_time_to_unix_seconds(args.to_time),
    }


def _extract_series(body: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract normalized series from Datadog metrics query response."""
    series_raw = body.get("series", [])
    if not isinstance(series_raw, list):
        return []
    series: list[dict[str, Any]] = []
    for s in series_raw:
        if not isinstance(s, dict):
            continue
        pointlist = s.get("pointlist", [])
        points: list[dict[str, Any]] = []
        if isinstance(pointlist, list):
            for point in pointlist:
                if isinstance(point, (list, tuple)) and len(point) >= 2:
                    points.append({
                        "timestamp": point[0],
                        "value": point[1],
                    })
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
            "tag_set": s.get("tag_set", []),
        })
    return series


def extract_metrics(body: dict[str, Any]) -> dict[str, Any]:
    """Extract structured metrics result from API response."""
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


def _render_human(result: dict[str, Any]) -> None:
    sys.stderr.write(f"[query-metrics] series_count={result.get('series_count')}\n")
    for s in result.get("series", []):
        sys.stderr.write(
            f"  {s.get('display_name') or s.get('metric')} "
            f"scope={s.get('scope')} points={s.get('point_count')}\n"
        )
        points = s.get("points", [])
        if points:
            last = points[-1]
            sys.stderr.write(f"    latest: {last.get('value')} @ {last.get('timestamp')}\n")


def run(args, config) -> int:
    params = build_params(args)
    sys.stderr.write(
        f"[query-metrics] query={args.query!r} from={args.from_time} to={args.to_time}\n"
    )
    body = DatadogClient(config).get("/api/v1/query", params=params)
    result = extract_metrics(body)
    if args.fmt == "human":
        _render_human(result)
    output(result, fmt=args.fmt)
    return 0
