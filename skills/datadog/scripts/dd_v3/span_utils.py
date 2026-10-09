"""Shared span utility functions used by get_trace and search_spans."""
from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any

from dd_v3.errors import ApiError


def _first_present(*values: Any) -> Any:
    for value in values:
        if value not in (None, ""):
            return value
    return None


def span_http_fields(attr: dict[str, Any]) -> dict[str, Any]:
    """Merge allowlisted HTTP fields across supported Datadog span layouts."""
    attr_http = attr.get("http") if isinstance(attr.get("http"), dict) else {}
    custom = attr.get("custom") if isinstance(attr.get("custom"), dict) else {}
    custom_http = custom.get("http") if isinstance(custom.get("http"), dict) else {}
    response = custom.get("response") if isinstance(custom.get("response"), dict) else {}
    attr_url = (
        attr_http.get("url_details")
        if isinstance(attr_http.get("url_details"), dict)
        else {}
    )
    custom_url = (
        custom_http.get("url_details")
        if isinstance(custom_http.get("url_details"), dict)
        else {}
    )
    return {
        "method": _first_present(
            attr_http.get("method"),
            custom_http.get("method"),
            attr.get("http.method"),
            custom.get("http.method"),
        ),
        "status_code": _first_present(
            attr_http.get("status_code"),
            custom_http.get("status_code"),
            attr.get("http.status_code"),
            custom.get("http.status_code"),
            response.get("status_code"),
        ),
        "url": _first_present(
            attr_http.get("url"),
            custom_http.get("url"),
            attr.get("http.url"),
            custom.get("http.url"),
        ),
        "path": _first_present(
            attr_url.get("path"),
            attr_http.get("path_group"),
            custom_url.get("path"),
            custom_http.get("path_group"),
            attr.get("http.url_details.path"),
            custom.get("http.url_details.path"),
        ),
    }


def span_error_fields(attr: dict[str, Any]) -> dict[str, Any] | None:
    """Merge allowlisted error fields across supported Datadog span layouts."""
    attr_error = attr.get("error") if isinstance(attr.get("error"), dict) else {}
    custom = attr.get("custom") if isinstance(attr.get("custom"), dict) else {}
    custom_error = custom.get("error") if isinstance(custom.get("error"), dict) else {}
    if not attr_error and not custom_error:
        return None
    return {
        "message": _first_present(custom_error.get("message"), attr_error.get("message")),
        "kind": _first_present(
            custom_error.get("type"),
            custom_error.get("kind"),
            attr_error.get("type"),
            attr_error.get("kind"),
        ),
        "stack": _first_present(custom_error.get("stack"), attr_error.get("stack")),
    }


def validate_span_attributes(attr: Any) -> None:
    if not isinstance(attr, dict):
        raise ApiError("Datadog returned invalid span attributes", error_code="invalid_response")
    for field_name in (
        "service",
        "resource_name",
        "resource",
        "operation_name",
        "name",
        "start_timestamp",
        "end_timestamp",
        "timestamp",
        "status",
    ):
        value = attr.get(field_name)
        if value is not None and not isinstance(value, str):
            raise ApiError("Datadog returned invalid span attributes", error_code="invalid_response")
    for field_name in ("start_timestamp", "end_timestamp", "timestamp"):
        if field_name in attr and attr[field_name] is not None:
            _parse_iso_to_ns(attr[field_name])
    tags = attr.get("tags")
    if tags is not None and (
        not isinstance(tags, list)
        or any(not isinstance(tag, str) for tag in tags)
    ):
        raise ApiError("Datadog returned invalid span tags", error_code="invalid_response")
    parent_id = attr.get("parent_id")
    if parent_id is not None and (
        isinstance(parent_id, bool)
        or not isinstance(parent_id, (str, int))
    ):
        raise ApiError("Datadog returned invalid span parent_id", error_code="invalid_response")
    for field_name in ("custom", "http"):
        value = attr.get(field_name)
        if value is not None and not isinstance(value, dict):
            raise ApiError("Datadog returned invalid span attributes", error_code="invalid_response")

    custom = attr.get("custom") if isinstance(attr.get("custom"), dict) else {}
    for source in (attr, custom):
        for field_name in (
            "http.method",
            "http.url",
            "http.url_details.path",
            "grpc.method",
        ):
            value = source.get(field_name)
            if value is not None and not isinstance(value, str):
                raise ApiError("Datadog returned invalid span field", error_code="invalid_response")
        dotted_status = source.get("http.status_code")
        if dotted_status is not None and (
            isinstance(dotted_status, bool)
            or not isinstance(dotted_status, (str, int))
        ):
            raise ApiError("Datadog returned invalid span HTTP field", error_code="invalid_response")
    for source, field_name in (
        (custom, "http"),
        (custom, "error"),
        (custom, "response"),
    ):
        value = source.get(field_name)
        if value is not None and not isinstance(value, dict):
            raise ApiError("Datadog returned invalid span attributes", error_code="invalid_response")

    attr_error = attr.get("error")
    if attr_error is not None and not isinstance(attr_error, (bool, int, dict)):
        raise ApiError("Datadog returned invalid span error", error_code="invalid_response")
    for error in (
        attr_error if isinstance(attr_error, dict) else {},
        custom.get("error") if isinstance(custom.get("error"), dict) else {},
    ):
        for field_name in ("message", "kind", "type", "stack"):
            value = error.get(field_name)
            if value is not None and not isinstance(value, str):
                raise ApiError("Datadog returned invalid span error", error_code="invalid_response")

    for http in (
        attr.get("http") if isinstance(attr.get("http"), dict) else {},
        custom.get("http") if isinstance(custom.get("http"), dict) else {},
    ):
        for field_name in ("method", "url", "path_group"):
            value = http.get(field_name)
            if value is not None and not isinstance(value, str):
                raise ApiError("Datadog returned invalid span HTTP field", error_code="invalid_response")
        status_code = http.get("status_code")
        if status_code is not None and (
            isinstance(status_code, bool)
            or not isinstance(status_code, (str, int))
        ):
            raise ApiError("Datadog returned invalid span HTTP field", error_code="invalid_response")
        url_details = http.get("url_details")
        if url_details is not None and not isinstance(url_details, dict):
            raise ApiError("Datadog returned invalid span HTTP field", error_code="invalid_response")
        if isinstance(url_details, dict):
            path = url_details.get("path")
            if path is not None and not isinstance(path, str):
                raise ApiError("Datadog returned invalid span HTTP field", error_code="invalid_response")

    response = custom.get("response") if isinstance(custom.get("response"), dict) else {}
    response_status = response.get("status_code")
    if response_status is not None and (
        isinstance(response_status, bool)
        or not isinstance(response_status, (str, int))
    ):
        raise ApiError("Datadog returned invalid span response", error_code="invalid_response")


def _duration_value(value: Any) -> int:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(float(value))
        or value < 0
    ):
        raise ApiError("Datadog returned invalid span duration", error_code="invalid_response")
    return int(value)


def _parse_iso_to_ns(value: Any) -> int | None:
    """Parse an ISO timestamp string to nanoseconds since epoch."""
    if value is None:
        return None
    if not isinstance(value, str) or not value:
        raise ApiError("Datadog returned invalid span timestamp", error_code="invalid_response")
    try:
        text = value[:-1] + "+00:00" if value.endswith("Z") else value
        dt = datetime.fromisoformat(text)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return int(dt.timestamp() * 1_000_000_000)
    except (OSError, OverflowError, ValueError) as exc:
        raise ApiError(
            "Datadog returned invalid span timestamp",
            error_code="invalid_response",
        ) from exc


def _span_duration_ns(attr: dict[str, Any]) -> int:
    """Compute span duration in nanoseconds from various attribute layouts.

    Datadog v2 spans: attr.duration is often missing; actual duration lives
    in attr.custom.duration (nanoseconds); otherwise computed from end - start.
    """
    if "duration" in attr and attr.get("duration") is not None:
        return _duration_value(attr["duration"])
    custom = attr.get("custom") if isinstance(attr.get("custom"), dict) else {}
    if "duration" in custom and custom.get("duration") is not None:
        return _duration_value(custom["duration"])
    start = _parse_iso_to_ns(attr.get("start_timestamp"))
    end = _parse_iso_to_ns(attr.get("end_timestamp"))
    if start is not None and end is not None:
        if end < start:
            raise ApiError("Datadog returned invalid span timestamps", error_code="invalid_response")
        return end - start
    return 0


def _is_error_status(value: Any) -> bool:
    """Return True if value represents an HTTP error status (>= 500)."""
    if value in (None, ""):
        return False
    try:
        return int(value) >= 500
    except (TypeError, ValueError):
        return False
