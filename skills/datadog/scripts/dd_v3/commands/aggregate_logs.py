"""aggregate-logs: server-side log analytics aggregations."""
from __future__ import annotations

import re
from typing import Any

from dd_v3.argtypes import bounded_int_type
from dd_v3.errors import ApiError, UsageError
from dd_v3.log_analysis import response_coverage
from dd_v3.runtime import READ, CommandResult, RuntimeContext
from dd_v3.timeutil import normalize_datadog_time

from .search_logs import normalize_storage

NAME = "aggregate-logs"

_VALID_SORTS = {"count", "cardinality", "pc75", "pc90", "pc95", "pc98", "pc99", "sum", "min", "max"}
_VALID_FIELD_AGGS = {"avg", "sum", "min", "max", "median", "cardinality"}
_VALID_INTERVALS = {"1s", "5s", "10s", "30s", "1m", "5m", "10m", "30m", "1h", "4h", "12h", "1d", "7d", "1M"}


def register(subparsers) -> None:
    p = subparsers.add_parser(NAME, help="聚合 Datadog 日志")
    p.add_argument("--query", required=True, help="Datadog 日志搜索语法")
    p.add_argument("--from", required=True, dest="from_time", help="起始时间，如 15m / now-1h / RFC3339")
    p.add_argument("--to", default="now", dest="to_time", help="结束时间，默认 now")
    p.add_argument(
        "--compute",
        action="append",
        help="聚合表达式：count、avg(@duration)、percentile(@duration, 95)，可重复",
    )
    p.add_argument("--group-by", action="append", default=[], help="分组 facet，可重复")
    p.add_argument(
        "--limit",
        type=bounded_int_type("--limit", 1, 1000),
        default=50,
        help="每个 group-by 的 bucket 上限，默认 50，最大 1000",
    )
    p.add_argument("--storage", choices=["indexes", "online", "online-archives", "online_archives", "flex"], help="日志存储层")
    p.add_argument("--sort", default="count", help="group-by 排序聚合，默认 count")
    p.add_argument("--sort-metric", help="非 count 排序使用的 measure facet，如 @duration")
    p.add_argument("--interval", "-i", help="时序间隔，如 1d / 1h / 5m；指定后返回 timeseries 桶而非总聚合")
    p.add_argument("--timezone", default="UTC", help="时序聚合时区，默认 UTC")
    p.add_argument("--format", dest="fmt", choices=["json", "summary"], default="json")
    p.set_defaults(_handler=run, _policy=READ)


def split_compute_args(values: list[str] | None) -> list[str]:
    if not values:
        return ["count"]
    result: list[str] = []
    for value in values:
        current = []
        depth = 0
        for char in value:
            if char == "(":
                depth += 1
            elif char == ")":
                depth = max(0, depth - 1)
            if char == "," and depth == 0:
                part = "".join(current).strip()
                if part:
                    result.append(part)
                current = []
                continue
            current.append(char)
        part = "".join(current).strip()
        if part:
            result.append(part)
    return result or ["count"]


def parse_compute(value: str) -> dict[str, str]:
    text = value.strip()
    if text == "count":
        return {"aggregation": "count"}
    match = re.match(r"^([a-zA-Z_][a-zA-Z0-9_]*)\((.+)\)$", text)
    if not match:
        raise ApiError(
            f"无效 --compute: {value!r}; 期望 count、avg(@field)、percentile(@field, 95)"
        )
    func, raw_args = match.group(1), match.group(2)
    if func == "count":
        raise ApiError("count 不接受字段参数，请使用 --compute count")
    if func == "percentile":
        parts = [part.strip() for part in raw_args.split(",", 1)]
        if len(parts) != 2 or not parts[0] or not parts[1]:
            raise ApiError("percentile 需要字段和分位值，如 percentile(@duration, 95)")
        pct_map = {"75": "pc75", "90": "pc90", "95": "pc95", "98": "pc98", "99": "pc99"}
        if parts[1] not in pct_map:
            raise ApiError("percentile 仅支持 75/90/95/98/99")
        return {"aggregation": pct_map[parts[1]], "metric": parts[0]}
    if func not in _VALID_FIELD_AGGS:
        raise ApiError(f"未知聚合函数: {func}")
    metric = raw_args.strip()
    if not metric:
        raise ApiError(f"{func} 需要字段参数")
    return {"aggregation": func, "metric": metric}


def build_payload(args) -> dict[str, Any]:
    filter_obj: dict[str, Any] = {
        "from": normalize_datadog_time(args.from_time),
        "to": normalize_datadog_time(args.to_time),
        "query": args.query,
    }
    storage = normalize_storage(args.storage)
    if storage:
        filter_obj["storage_tier"] = storage

    computes = [parse_compute(value) for value in split_compute_args(args.compute)]

    interval = getattr(args, "interval", None)
    if interval:
        if interval not in _VALID_INTERVALS:
            raise ApiError(f"未知 --interval: {interval}; 支持 {', '.join(sorted(_VALID_INTERVALS))}")
        for compute in computes:
            compute["interval"] = interval
            compute["type"] = "timeseries"

    body: dict[str, Any] = {"filter": filter_obj, "compute": computes}

    timezone = getattr(args, "timezone", "UTC")
    if interval and timezone:
        body["options"] = {"timezone": timezone}

    sort = args.sort.strip().lower()
    if sort not in _VALID_SORTS:
        raise ApiError(f"未知 --sort: {args.sort}; 支持 {', '.join(sorted(_VALID_SORTS))}")
    sort_metric = getattr(args, "sort_metric", None)
    if sort == "count" and sort_metric is not None:
        raise UsageError("--sort-metric is not valid with --sort count")
    if sort != "count" and (
        not isinstance(sort_metric, str) or not sort_metric.strip()
    ):
        raise UsageError(
            f"--sort {sort} requires --sort-metric",
        )
    if not args.group_by and sort != "count":
        raise UsageError("non-count --sort requires --group-by")
    if args.group_by:
        sort_rule: dict[str, Any] = {
            "type": "measure",
            "order": "desc",
            "aggregation": sort,
        }
        if sort != "count" and isinstance(sort_metric, str):
            sort_rule["metric"] = sort_metric.strip()
        body["group_by"] = [
            {
                "facet": facet,
                "limit": args.limit,
                "sort": dict(sort_rule),
            }
            for facet in args.group_by
        ]
    return body


def _extract_buckets(body: Any) -> list[dict[str, Any]]:
    if not isinstance(body, dict):
        raise ApiError("Datadog returned an invalid aggregate response", error_code="invalid_response")
    data = body.get("data")
    if not isinstance(data, dict):
        raise ApiError("Datadog returned an invalid aggregate response", error_code="invalid_response")
    buckets = data.get("buckets")
    if not isinstance(buckets, list):
        raise ApiError("Datadog returned an invalid aggregate response", error_code="invalid_response")
    if any(
        not isinstance(bucket, dict)
        or not isinstance(bucket.get("computes"), dict)
        for bucket in buckets
    ):
        raise ApiError("Datadog returned an invalid aggregate bucket", error_code="invalid_response")
    return buckets


def run(args, context: RuntimeContext) -> CommandResult:
    payload = build_payload(args)
    target = context.bind_target({
        "query": args.query,
        "from": payload["filter"]["from"],
        "to": payload["filter"]["to"],
        "storage": payload["filter"].get("storage_tier"),
        "compute": payload["compute"],
        "group_by": args.group_by,
        "interval": args.interval,
        "timezone": args.timezone if args.interval else None,
    })
    body = context.client.request_read(
        "POST",
        "/api/v2/logs/analytics/aggregate",
        json_body=payload,
    )
    buckets = _extract_buckets(body)
    response, warnings = response_coverage(body)
    return CommandResult(
        target=target,
        result={"buckets": buckets, "count": len(buckets)},
        meta={"response": response},
        warnings=warnings,
    )
