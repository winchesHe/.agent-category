"""get-trace: fetch and normalize a Datadog trace.

Datadog 公共 API 没有「按 trace_id 一次性返回 trace」的端点，
`/api/v1/trace/<id>` 不是公开接口（会返回 404）。
该命令使用 `POST /api/v2/spans/events/search`，按 `trace_id:<hex>`
过滤，把所有 span 拼成树。
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from typing import Any

from dd.client import DatadogClient
from dd.formatter import output
from dd.timeutil import normalize_datadog_time

NAME = "get-trace"


def register(subparsers) -> None:
    p = subparsers.add_parser(NAME, help="获取 Trace 详情（含 span 树形结构）")
    p.add_argument("trace_id", help="Trace ID（Datadog v2 spans 中的 trace_id，通常 32 位 hex）")
    p.add_argument("--from", default="now-1h", dest="from_time", help="搜索起始时间，默认 now-1h")
    p.add_argument("--to", default="now", dest="to_time", help="搜索结束时间，默认 now")
    p.add_argument("--limit", type=int, default=200, help="单次拉取的最大 span 数（默认 200）")
    p.add_argument("--verbose", action="store_true", help="输出每个 span 的完整 meta")
    p.add_argument("--format", dest="fmt", choices=["json", "human", "summary"], default="json")
    p.set_defaults(_handler=run)


def _parse_iso_to_ns(value: Any) -> int | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        text = value.replace("Z", "+00:00")
        dt = datetime.fromisoformat(text)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return int(dt.timestamp() * 1_000_000_000)
    except Exception:
        return None


def _span_duration_ns(attr: dict[str, Any]) -> int:
    direct = attr.get("duration")
    if isinstance(direct, (int, float)) and direct:
        return int(direct)
    custom = attr.get("custom") if isinstance(attr.get("custom"), dict) else {}
    custom_dur = custom.get("duration") if isinstance(custom, dict) else None
    if isinstance(custom_dur, (int, float)) and custom_dur:
        return int(custom_dur)
    start = _parse_iso_to_ns(attr.get("start_timestamp"))
    end = _parse_iso_to_ns(attr.get("end_timestamp"))
    if start is not None and end is not None and end >= start:
        return end - start
    return 0


def _is_error_status(value: Any) -> bool:
    if value in (None, ""):
        return False
    try:
        return int(value) >= 500
    except (TypeError, ValueError):
        return False


def _nested_dict(source: dict[str, Any], key: str) -> dict[str, Any]:
    value = source.get(key)
    return value if isinstance(value, dict) else {}


def _normalize_span(item: dict[str, Any]) -> dict[str, Any] | None:
    """把 v2 spans-search 返回的 item 拍平到内部 span 字典。

    同时兼容旧版 `/api/v1/trace/<id>` 直接返回的 span dict（无 attributes 包裹）。
    """
    if not isinstance(item, dict):
        return None
    if isinstance(item.get("attributes"), dict):
        attr = item["attributes"]
    else:
        attr = item
    span_id = attr.get("span_id") or attr.get("spanID") or attr.get("spanId")
    if span_id is None:
        return None
    parent_id = attr.get("parent_id") or attr.get("parentID") or attr.get("parentId")
    custom = attr.get("custom") if isinstance(attr.get("custom"), dict) else {}
    meta = attr.get("meta") if isinstance(attr.get("meta"), dict) else custom
    metrics = attr.get("metrics") if isinstance(attr.get("metrics"), dict) else {}
    http = _nested_dict(custom, "http")
    response = _nested_dict(custom, "response")
    custom_error = _nested_dict(custom, "error")
    attr_error = _nested_dict(attr, "error")
    status_code = (
        http.get("status_code")
        or custom.get("http.status_code")
        or response.get("status_code")
    )
    error_flag = bool(
        attr.get("error")
        or custom_error
        or attr.get("status") == "error"
        or _is_error_status(status_code)
    )
    error = None
    if error_flag:
        error = {
            "message": custom_error.get("message") or attr_error.get("message") or "",
            "type": custom_error.get("type") or attr_error.get("type") or "",
            "stack": custom_error.get("stack") or attr_error.get("stack") or "",
        }
    return {
        "span_id": str(span_id),
        "parent_id": str(parent_id) if parent_id not in (None, "", 0, "0") else None,
        "service": attr.get("service") or "unknown",
        "operation": attr.get("operation_name") or attr.get("name") or "unknown",
        "resource": attr.get("resource_name") or attr.get("resource") or "unknown",
        "start": attr.get("start_timestamp") or attr.get("start") or attr.get("timestamp"),
        "duration_ns": _span_duration_ns(attr),
        "status": attr.get("status"),
        "error_flag": error_flag,
        "http": {
            "method": http.get("method") or custom.get("http.method"),
            "status_code": status_code,
            "url": http.get("url") or custom.get("http.url"),
        } if http or status_code else None,
        "error": error,
        "response": response if response else None,
        "meta": meta if isinstance(meta, dict) else {},
        "metrics": metrics,
    }


def parse_spans(body: Any) -> list[dict[str, Any]]:
    """从 API 响应里抽出 span 列表（兼容多种 shape）。"""
    if not isinstance(body, dict):
        return []
    candidates: list[Any] = []
    # v2 spans-search: {"data": [<resource>, ...]}
    data = body.get("data")
    if isinstance(data, list):
        candidates.extend(data)
    # 旧 v1 trace API（如果未来恢复）：{"trace": {"spans": [...]} }
    trace = body.get("trace")
    if isinstance(trace, dict):
        spans = trace.get("spans")
        if isinstance(spans, list):
            candidates.extend(spans)
        elif isinstance(spans, dict):
            candidates.extend(spans.values())
        else:
            candidates.extend(v for v in trace.values() if isinstance(v, dict))
    if not candidates and "spans" in body:
        spans = body["spans"]
        if isinstance(spans, list):
            candidates.extend(spans)
        elif isinstance(spans, dict):
            candidates.extend(spans.values())
    out_list: list[dict[str, Any]] = []
    for raw in candidates:
        norm = _normalize_span(raw)
        if norm is not None:
            out_list.append(norm)
    return out_list


def build_span_tree(spans: list[dict[str, Any]]) -> list[dict[str, Any]]:
    id_map = {span["span_id"]: span for span in spans}
    for span in spans:
        depth = 0
        seen: set[str] = set()
        current = span.get("parent_id")
        while current and current in id_map and current not in seen:
            seen.add(current)
            depth += 1
            current = id_map[current].get("parent_id")
        span["_depth"] = depth
    return sorted(spans, key=lambda s: (s.get("start") or "", s.get("_depth", 0)))


def _first_meta(meta: dict[str, Any], keys: tuple[str, ...]) -> str | None:
    for key in keys:
        value = meta.get(key)
        if value not in (None, ""):
            text = str(value)
            return text[:500] + "...(truncated)" if len(text) > 500 else text
    return None


def format_span(span: dict[str, Any], *, verbose: bool = False) -> dict[str, Any]:
    meta = span.get("meta") or {}
    error_flag = span.get("error_flag", False)
    error = None
    if error_flag:
        error = span.get("error") or {
            "message": meta.get("error.message") or meta.get("error.msg") or "",
            "type": meta.get("error.type") or "",
            "stack": meta.get("error.stack") or "",
        }
    response = span.get("response") if isinstance(span.get("response"), dict) else {}
    payload = _first_meta(meta, ("request.body", "response.body", "payload", "input", "json"))
    if payload is None and response.get("body") not in (None, ""):
        payload = str(response["body"])[:500]
    return {
        "span_id": span.get("span_id"),
        "parent_id": span.get("parent_id"),
        "depth": span.get("_depth", 0),
        "service": span.get("service", "unknown"),
        "operation": span.get("operation", "unknown"),
        "resource": span.get("resource", "unknown"),
        "start": span.get("start"),
        "duration_ms": round((span.get("duration_ns") or 0) / 1_000_000.0, 2),
        "status": span.get("status"),
        "is_error": error_flag,
        "http": span.get("http"),
        "sql": _first_meta(meta, ("sql.query", "db.statement", "sql")),
        "payload": payload,
        "error": error,
        "response": response if response else None,
        "metrics": span.get("metrics") if verbose else {},
        "meta": meta if verbose else {},
    }


def _render_human(spans: list[dict[str, Any]]) -> None:
    for span in spans:
        indent = "  " * int(span.get("depth") or 0)
        err = "ERR " if span.get("is_error") else ""
        sys.stderr.write(
            f"{indent}{err}[{span.get('service')}] {span.get('operation')} "
            f"resource={span.get('resource')} {span.get('duration_ms')}ms\n"
        )
        if span.get("sql"):
            sys.stderr.write(f"{indent}  SQL: {span['sql']}\n")
        if span.get("payload"):
            sys.stderr.write(f"{indent}  payload: {span['payload']}\n")
        if span.get("error"):
            sys.stderr.write(f"{indent}  error: {span['error'].get('message')}\n")


def run(args, config) -> int:
    sys.stderr.write(
        f"[get-trace] trace_id={args.trace_id} from={args.from_time} to={args.to_time}\n"
    )
    payload = {
        "data": {
            "type": "search_request",
            "attributes": {
                "filter": {
                    "query": f"trace_id:{args.trace_id}",
                    "from": normalize_datadog_time(args.from_time),
                    "to": normalize_datadog_time(args.to_time),
                },
                "options": {"timezone": "UTC"},
                "page": {"limit": args.limit},
                "sort": "timestamp",
            },
        }
    }
    body = DatadogClient(config).post("/api/v2/spans/events/search", json_body=payload)
    raw_spans = build_span_tree(parse_spans(body))
    spans = [format_span(span, verbose=args.verbose) for span in raw_spans]
    result = {
        "trace_id": args.trace_id,
        "from": payload["data"]["attributes"]["filter"]["from"],
        "to": payload["data"]["attributes"]["filter"]["to"],
        "span_count": len(spans),
        "spans": spans,
    }
    if args.fmt == "human":
        _render_human(spans)
    output(result, fmt=args.fmt)
    return 0

