"""Bounded, reusable primitives for read-only log analysis commands."""
from __future__ import annotations

import hashlib
import math
import re
from collections import Counter
from datetime import datetime, timezone
from typing import Any

from dd_v3.errors import ApiError
from dd_v3.timeutil import parse_time_to_unix_millis

LOG_SEARCH_PATH = "/api/v2/logs/events/search"
LOG_AGGREGATE_PATH = "/api/v2/logs/analytics/aggregate"

_DURATION_RE = re.compile(r"^(\d+)(s|m|h|d|w)$", re.IGNORECASE)
_TRACE_ID_RE = re.compile(r"^[A-Za-z0-9._-]{1,128}$")
_SERVICE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,127}$")
_UUID_RE = re.compile(
    r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b",
    re.IGNORECASE,
)
_HEX_RE = re.compile(r"\b[0-9a-f]{32,}\b", re.IGNORECASE)
_IP_RE = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
_EMAIL_RE = re.compile(r"\b[\w.+-]+@[\w.-]+\.\w+\b")
_URL_RE = re.compile(r"https?://[^\s]+", re.IGNORECASE)
_OPAQUE_TOKEN_RE = re.compile(r"\b[A-Za-z0-9_=-]{24,}\b")
_NUMBER_RE = re.compile(r"\b\d+\b")
_DOUBLE_QUOTED_RE = re.compile(r'"[^"\n]*"')
_SINGLE_QUOTED_RE = re.compile(r"'[^'\n]*'")


def response_coverage(body: Any) -> tuple[dict[str, Any], list[str]]:
    """Normalize Datadog v2 partial-response signals without exposing details."""
    if not isinstance(body, dict):
        raise ApiError("Datadog returned invalid response metadata", error_code="invalid_response")
    meta = body.get("meta")
    if meta is None:
        return {
            "status": None,
            "warning_count": 0,
            "partial": False,
            "completion": "complete",
        }, []
    if not isinstance(meta, dict):
        raise ApiError("Datadog returned invalid response metadata", error_code="invalid_response")
    status = meta.get("status")
    if status is not None and status not in {"done", "timeout"}:
        raise ApiError("Datadog returned invalid response status", error_code="invalid_response")
    raw_warnings = meta.get("warnings")
    if raw_warnings is None:
        raw_warnings = []
    if not isinstance(raw_warnings, list) or any(
        not isinstance(warning, dict) for warning in raw_warnings
    ):
        raise ApiError("Datadog returned invalid response warnings", error_code="invalid_response")
    partial = status == "timeout" or bool(raw_warnings)
    warnings: list[str] = []
    if status == "timeout":
        warnings.append("datadog_response_timeout")
    if raw_warnings:
        warnings.append("datadog_response_warnings")
    return {
        "status": status,
        "warning_count": len(raw_warnings),
        "partial": partial,
        "completion": "unknown" if partial else "complete",
    }, warnings


def merge_warnings(*groups: list[str]) -> list[str]:
    return list(dict.fromkeys(warning for group in groups for warning in group))


def require_text(value: str | None, label: str, *, maximum: int = 4096) -> str:
    text = value.strip() if isinstance(value, str) else ""
    if not text:
        raise ApiError(f"{label} 不能为空")
    if len(text) > maximum:
        raise ApiError(f"{label} 长度不能超过 {maximum}")
    return text


def parse_duration_millis(
    value: str,
    *,
    label: str,
    maximum_ms: int,
) -> int:
    """Parse a positive short duration and fail closed for malformed values."""
    text = value.strip()
    match = _DURATION_RE.fullmatch(text)
    if not match:
        raise ApiError(f"{label} 必须是正整数加 s/m/h/d/w，例如 5m 或 1h")
    amount = int(match.group(1))
    if amount <= 0:
        raise ApiError(f"{label} 必须大于 0")
    unit = match.group(2).lower()
    multipliers = {
        "s": 1_000,
        "m": 60_000,
        "h": 3_600_000,
        "d": 86_400_000,
        "w": 604_800_000,
    }
    duration_ms = amount * multipliers[unit]
    if duration_ms > maximum_ms:
        raise ApiError(f"{label} 超过允许上限")
    return duration_ms


def format_rfc3339(unix_ms: int) -> str:
    return (
        datetime.fromtimestamp(unix_ms / 1000, tz=timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


def normalize_time_range(
    from_value: str,
    to_value: str,
    *,
    now_ms: int,
) -> tuple[str, str]:
    from_ms = parse_time_to_unix_millis(from_value, now_ms=now_ms)
    to_ms = parse_time_to_unix_millis(to_value, now_ms=now_ms)
    if from_ms >= to_ms:
        raise ApiError("起始时间必须早于结束时间")
    return format_rfc3339(from_ms), format_rfc3339(to_ms)


def normalize_instant(value: str, *, now_ms: int) -> tuple[int, str]:
    instant_ms = parse_time_to_unix_millis(value, now_ms=now_ms)
    return instant_ms, format_rfc3339(instant_ms)


def trace_query(trace_id: str) -> str:
    trace_id = require_text(trace_id, "TRACE_ID", maximum=128)
    if not _TRACE_ID_RE.fullmatch(trace_id):
        raise ApiError("TRACE_ID 只能包含字母、数字、点、下划线和连字符")
    return f"trace_id:{trace_id} OR @trace_id:{trace_id} OR @dd.trace_id:{trace_id}"


def combine_query(query: str | None, service: str | None) -> str:
    query_text = require_text(query, "--query") if query is not None else ""
    service_text = require_text(service, "--service", maximum=128) if service is not None else ""
    if not query_text and not service_text:
        raise ApiError("必须提供 --query 或 --service")
    if service_text and not _SERVICE_RE.fullmatch(service_text):
        raise ApiError("--service 包含不支持的字符")
    if not service_text:
        return query_text
    service_clause = f"service:{service_text}"
    if not query_text or query_text == "*":
        return service_clause
    return f"({query_text}) {service_clause}"


def build_log_search_payload(
    *,
    query: str,
    from_time: str,
    to_time: str,
    limit: int,
    sort: str = "-timestamp",
    cursor: str | None = None,
) -> dict[str, Any]:
    if sort not in {"timestamp", "-timestamp"}:
        raise ApiError("日志排序仅支持 timestamp 或 -timestamp")
    payload: dict[str, Any] = {
        "filter": {
            "query": require_text(query, "--query"),
            "from": from_time,
            "to": to_time,
        },
        "sort": sort,
        "page": {"limit": limit},
    }
    if cursor:
        payload["page"]["cursor"] = require_text(cursor, "--cursor", maximum=2048)
    return payload


def build_count_payload(
    *,
    query: str,
    from_time: str,
    to_time: str,
    facet: str | None = None,
    limit: int | None = None,
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "filter": {
            "query": require_text(query, "--query"),
            "from": from_time,
            "to": to_time,
        },
        "compute": [{"aggregation": "count", "type": "total"}],
    }
    if facet is not None:
        if limit is None:
            raise ApiError("分组聚合必须设置 limit")
        body["group_by"] = [
            {
                "facet": facet,
                "limit": limit,
                "sort": {
                    "aggregation": "count",
                    "order": "desc",
                    "type": "measure",
                },
            }
        ]
    return body


def validate_log_item(item: Any) -> None:
    """Validate the allowlisted Datadog log fields used by every command."""
    if not isinstance(item, dict) or not isinstance(item.get("attributes"), dict):
        raise ApiError("Datadog returned an invalid data item", error_code="invalid_response")
    if item.get("id") is not None and not isinstance(item["id"], str):
        raise ApiError("Datadog returned an invalid data item", error_code="invalid_response")

    attributes = item["attributes"]
    nested_value = attributes.get("attributes")
    if "attributes" in attributes and not isinstance(nested_value, dict):
        raise ApiError("Datadog returned an invalid log attributes", error_code="invalid_response")
    nested = nested_value if isinstance(nested_value, dict) else {}

    for source in (attributes, nested):
        for field_name in ("message", "service", "status", "host", "timestamp"):
            value = source.get(field_name)
            if value is not None and not isinstance(value, str):
                raise ApiError("Datadog returned an invalid log field", error_code="invalid_response")
        tags = source.get("tags")
        if tags is not None and (
            not isinstance(tags, list)
            or any(not isinstance(tag, str) for tag in tags)
        ):
            raise ApiError("Datadog returned invalid log tags", error_code="invalid_response")
        for field_name in ("http", "error", "dd"):
            value = source.get(field_name)
            if value is not None and not isinstance(value, dict):
                raise ApiError("Datadog returned an invalid log field", error_code="invalid_response")
        for field_name in (
            "trace_id",
            "dd.trace_id",
            "span_id",
            "dd.span_id",
            "request_id",
            "@id",
            "method",
            "path",
        ):
            value = source.get(field_name)
            if value is not None and not isinstance(value, str):
                raise ApiError("Datadog returned an invalid log field", error_code="invalid_response")
        status_code = source.get("status_code")
        if status_code is not None and (
            isinstance(status_code, bool)
            or not isinstance(status_code, (str, int))
        ):
            raise ApiError("Datadog returned an invalid log field", error_code="invalid_response")

        http = source.get("http") if isinstance(source.get("http"), dict) else {}
        for field_name in ("method", "url", "path_group"):
            value = http.get(field_name)
            if value is not None and not isinstance(value, str):
                raise ApiError("Datadog returned an invalid log HTTP field", error_code="invalid_response")
        http_status = http.get("status_code")
        if http_status is not None and (
            isinstance(http_status, bool)
            or not isinstance(http_status, (str, int))
        ):
            raise ApiError("Datadog returned an invalid log HTTP field", error_code="invalid_response")
        url_details = http.get("url_details")
        if url_details is not None and not isinstance(url_details, dict):
            raise ApiError("Datadog returned an invalid log HTTP field", error_code="invalid_response")
        if isinstance(url_details, dict):
            path = url_details.get("path")
            if path is not None and not isinstance(path, str):
                raise ApiError("Datadog returned an invalid log HTTP field", error_code="invalid_response")

        error = source.get("error") if isinstance(source.get("error"), dict) else {}
        for field_name in ("kind", "type", "message"):
            value = error.get(field_name)
            if value is not None and not isinstance(value, str):
                raise ApiError("Datadog returned an invalid log error field", error_code="invalid_response")

        dd_values = source.get("dd") if isinstance(source.get("dd"), dict) else {}
        for field_name in ("trace_id", "span_id"):
            value = dd_values.get(field_name)
            if value is not None and not isinstance(value, str):
                raise ApiError("Datadog returned an invalid log field", error_code="invalid_response")


def data_items(body: Any) -> list[dict[str, Any]]:
    if not isinstance(body, dict):
        raise ApiError("Datadog returned an invalid data response", error_code="invalid_response")
    data = body.get("data")
    if not isinstance(data, list):
        raise ApiError("Datadog returned an invalid data response", error_code="invalid_response")
    for item in data:
        validate_log_item(item)
    return data


def next_cursor(body: Any) -> str | None:
    if not isinstance(body, dict):
        raise ApiError("Datadog returned invalid pagination", error_code="invalid_response")
    meta = body.get("meta")
    if meta is None:
        return None
    if not isinstance(meta, dict):
        raise ApiError("Datadog returned invalid pagination", error_code="invalid_response")
    page = meta.get("page")
    if page is None:
        return None
    if not isinstance(page, dict):
        raise ApiError("Datadog returned invalid pagination", error_code="invalid_response")
    after = page.get("after") if isinstance(page, dict) else None
    if after in (None, ""):
        return None
    if not isinstance(after, str):
        raise ApiError("Datadog returned invalid pagination", error_code="invalid_response")
    return after


def cursor_pagination(
    body: Any,
    *,
    returned: int,
    limit: int,
    partial: bool = False,
) -> dict[str, Any]:
    cursor = next_cursor(body)
    return {
        "mode": "cursor",
        "limit": limit,
        "returned": returned,
        "next": {"cursor": cursor} if cursor else None,
        "total": None,
        "completion": "unknown" if partial else ("more_available" if cursor else "complete"),
    }


def limited_pagination(
    *,
    returned: int,
    limit: int,
    partial: bool = False,
) -> dict[str, Any]:
    return {
        "mode": "limit",
        "limit": limit,
        "returned": returned,
        "next": None,
        "total": None,
        "completion": "unknown" if partial or returned >= limit else "complete",
    }


def aggregate_buckets(body: Any) -> list[dict[str, Any]]:
    if not isinstance(body, dict):
        raise ApiError("Datadog returned an invalid aggregate response", error_code="invalid_response")
    data = body.get("data")
    buckets = data.get("buckets") if isinstance(data, dict) else None
    if not isinstance(buckets, list):
        raise ApiError("Datadog returned an invalid aggregate response", error_code="invalid_response")
    if any(not isinstance(bucket, dict) for bucket in buckets):
        raise ApiError("Datadog returned an invalid aggregate bucket", error_code="invalid_response")
    return buckets


def _normalize_count(value: Any, *, message: str) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
        raise ApiError(message, error_code="invalid_response")
    if isinstance(value, float) and (
        not math.isfinite(value) or not value.is_integer()
    ):
        raise ApiError(message, error_code="invalid_response")
    return int(value)


def aggregate_total(body: Any) -> int:
    buckets = aggregate_buckets(body)
    if not buckets:
        return 0
    if len(buckets) != 1:
        raise ApiError("Datadog returned an invalid aggregate count", error_code="invalid_response")
    computes = buckets[0].get("computes")
    value = computes.get("c0") if isinstance(computes, dict) else None
    return _normalize_count(
        value,
        message="Datadog returned an invalid aggregate count",
    )


def aggregate_facet_counts(
    body: Any,
    *,
    facet: str,
    output_key: str,
) -> list[dict[str, Any]]:
    counts: list[dict[str, Any]] = []
    fallback_facet = facet[1:] if facet.startswith("@") else facet
    for bucket in aggregate_buckets(body):
        by = bucket.get("by")
        computes = bucket.get("computes")
        if not isinstance(by, dict) or not isinstance(computes, dict):
            raise ApiError("Datadog returned an invalid facet bucket", error_code="invalid_response")
        value = by.get(facet, by.get(fallback_facet))
        count = computes.get("c0")
        normalized_count = _normalize_count(
            count,
            message="Datadog returned an invalid facet count",
        )
        if value in (None, ""):
            continue
        if not isinstance(value, str):
            raise ApiError("Datadog returned an invalid facet value", error_code="invalid_response")
        counts.append({output_key: value, "count": normalized_count})
    counts.sort(key=lambda item: (-item["count"], item[output_key]))
    return counts


def _nested_get(data: dict[str, Any], *paths: str) -> Any:
    for path in paths:
        current: Any = data
        for part in path.split("."):
            if not isinstance(current, dict) or part not in current:
                break
            current = current[part]
        else:
            if current not in (None, ""):
                return current
    return None


def _first_nested_get(sources: tuple[dict[str, Any], ...], *paths: str) -> Any:
    for source in sources:
        value = _nested_get(source, *paths)
        if value not in (None, ""):
            return value
    return None


def _message_from_valid_log(item: dict[str, Any]) -> str:
    attributes = item.get("attributes") if isinstance(item.get("attributes"), dict) else {}
    nested = attributes.get("attributes") if isinstance(attributes.get("attributes"), dict) else {}
    message = attributes.get("message") or nested.get("message")
    if isinstance(message, str) and message:
        return message
    sources = (nested, attributes)
    method = _first_nested_get(sources, "http.method", "method")
    path = _first_nested_get(sources, "http.url_details.path", "path", "url")
    code = _first_nested_get(sources, "http.status_code", "status_code")
    if isinstance(method, str) and isinstance(path, str):
        suffix = f" ({code})" if code not in (None, "") else ""
        return f"{method} {path}{suffix}"
    return ""


def message_from_log(item: dict[str, Any]) -> str:
    validate_log_item(item)
    return _message_from_valid_log(item)


def normalize_log(item: dict[str, Any]) -> dict[str, Any]:
    validate_log_item(item)
    attributes = item.get("attributes") if isinstance(item.get("attributes"), dict) else {}
    nested = attributes.get("attributes") if isinstance(attributes.get("attributes"), dict) else {}
    custom_sources = (nested, attributes)
    tags = attributes.get("tags")
    if not isinstance(tags, list):
        tags = nested.get("tags") if isinstance(nested.get("tags"), list) else []
    error_kind = _first_nested_get(custom_sources, "error.kind", "error.type")
    error_message = _first_nested_get(custom_sources, "error.message")
    normalized_error = (
        {"kind": error_kind, "message": error_message}
        if error_kind is not None or error_message is not None
        else None
    )
    return {
        "id": item.get("id"),
        "timestamp": attributes.get("timestamp") or nested.get("timestamp"),
        "service": attributes.get("service") or nested.get("service"),
        "status": attributes.get("status") or nested.get("status"),
        "message": _message_from_valid_log(item),
        "trace_id": (
            nested.get("trace_id")
            or nested.get("dd.trace_id")
            or attributes.get("trace_id")
            or attributes.get("dd.trace_id")
            or _first_nested_get(custom_sources, "dd.trace_id")
        ),
        "span_id": (
            nested.get("span_id")
            or nested.get("dd.span_id")
            or attributes.get("span_id")
            or attributes.get("dd.span_id")
            or _first_nested_get(custom_sources, "dd.span_id")
        ),
        "request_id": (
            nested.get("@id")
            or nested.get("request_id")
            or attributes.get("@id")
            or attributes.get("request_id")
        ),
        "host": attributes.get("host") or nested.get("host"),
        "tags": [str(tag) for tag in tags if tag not in (None, "")],
        "http": {
            "method": _first_nested_get(custom_sources, "http.method", "method"),
            "path": _first_nested_get(
                custom_sources,
                "http.url_details.path",
                "http.path_group",
                "path",
            ),
            "status_code": _first_nested_get(
                custom_sources,
                "http.status_code",
                "status_code",
            ),
        },
        "error": normalized_error,
    }


def truncate_message(message: str, *, maximum: int = 100) -> str:
    cleaned = re.sub(r"\s+", " ", message).strip()
    if len(cleaned) <= maximum:
        return cleaned
    fingerprint = hashlib.sha256(cleaned.encode("utf-8")).hexdigest()[:8]
    return f"{cleaned[:maximum]}... [#{fingerprint}]"


def ranked_messages(body: Any, *, top: int = 10) -> list[dict[str, Any]]:
    counts = Counter(
        message
        for item in data_items(body)
        if (message := re.sub(r"\s+", " ", message_from_log(item)).strip())
    )
    return [
        {"message": truncate_message(message), "sample_count": count}
        for message, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))[:top]
    ]


def extract_pattern(message: str) -> str:
    pattern = _URL_RE.sub("<URL>", message)
    pattern = _EMAIL_RE.sub("<EMAIL>", pattern)
    pattern = _UUID_RE.sub("<UUID>", pattern)
    pattern = _IP_RE.sub("<IP>", pattern)
    pattern = _HEX_RE.sub("<HEX>", pattern)
    pattern = _DOUBLE_QUOTED_RE.sub('"<STR>"', pattern)
    pattern = _SINGLE_QUOTED_RE.sub("'<STR>'", pattern)
    pattern = _OPAQUE_TOKEN_RE.sub("<TOKEN>", pattern)
    pattern = _NUMBER_RE.sub("<N>", pattern)
    normalized = re.sub(r"\s+", " ", pattern).strip()
    return normalized or "<EMPTY>"


def group_patterns(body: Any, *, top: int) -> list[dict[str, Any]]:
    counts = Counter(extract_pattern(message_from_log(item)) for item in data_items(body))
    return [
        {"pattern": pattern, "count": count}
        for pattern, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))[:top]
    ]
