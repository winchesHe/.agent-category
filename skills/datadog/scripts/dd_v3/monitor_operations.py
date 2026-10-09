"""Monitor 只读查询与响应校验。"""
from __future__ import annotations

from typing import Any

from dd_v3.client import DatadogClient, path_quote
from dd_v3.errors import ApiError


def monitor_path(monitor_id: int) -> str:
    return f"/api/v1/monitor/{path_quote(str(monitor_id))}"


def _validate_monitor_summary(monitor: Any) -> None:
    if not isinstance(monitor, dict):
        raise ApiError("Datadog Monitor 返回格式无效", error_code="invalid_response")
    monitor_id = monitor.get("id")
    if isinstance(monitor_id, bool) or not isinstance(monitor_id, int) or monitor_id <= 0:
        raise ApiError("Datadog Monitor ID 返回格式无效", error_code="invalid_response")
    for field_name in ("name", "type"):
        value = monitor.get(field_name)
        if not isinstance(value, str) or not value.strip():
            raise ApiError("Datadog Monitor 返回格式无效", error_code="invalid_response")


def _validate_search_metadata(metadata: Any) -> None:
    if not isinstance(metadata, dict):
        raise ApiError("Datadog Monitor search metadata 返回格式无效", error_code="invalid_response")
    for field_name in ("page", "page_count", "per_page", "total_count"):
        value = metadata.get(field_name)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ApiError("Datadog Monitor search metadata 返回格式无效", error_code="invalid_response")
    if metadata["per_page"] == 0:
        raise ApiError("Datadog Monitor search metadata 返回格式无效", error_code="invalid_response")


class MonitorOperations:
    def __init__(self, client: DatadogClient) -> None:
        self.client = client

    def list(self, params: dict[str, Any]) -> dict[str, Any]:
        body = self.client.request_read("GET", "/api/v1/monitor", params=params)
        if not isinstance(body, list):
            raise ApiError("Datadog Monitor 列表返回格式无效", error_code="invalid_response")
        for monitor in body:
            _validate_monitor_summary(monitor)
        return {
            "monitors": body,
            "count": len(body),
            "page": params["page"],
            "page_size": params["page_size"],
            "has_more": len(body) == params["page_size"],
        }

    def search(self, params: dict[str, Any]) -> dict[str, Any]:
        body = self.client.request_read("GET", "/api/v1/monitor/search", params=params)
        if not isinstance(body, dict) or not isinstance(body.get("monitors"), list):
            raise ApiError("Datadog Monitor 搜索返回格式无效", error_code="invalid_response")
        _validate_search_metadata(body.get("metadata"))
        for monitor in body["monitors"]:
            _validate_monitor_summary(monitor)
        return body

    def get(self, monitor_id: int, params: dict[str, Any] | None = None) -> dict[str, Any]:
        monitor = self.client.request_read("GET", monitor_path(monitor_id), params=params)
        _validate_monitor_summary(monitor)
        if monitor["id"] != monitor_id:
            raise ApiError("Datadog Monitor ID 回读不匹配", error_code="invalid_response")
        return monitor
