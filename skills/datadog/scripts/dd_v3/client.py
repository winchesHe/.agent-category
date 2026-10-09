"""Bounded Datadog transport for read and single-write operations."""
from __future__ import annotations

import json
from typing import Any
from urllib.parse import quote, urlparse

import requests

from dd_v3.config import DATADOG_API_TO_UI_HOST, Config, get_headers
from dd_v3.errors import (
    ApiError,
    AuthError,
    ConflictError,
    DatadogTimeoutError,
    PermissionDeniedError,
    WriteOutcomeUnknownError,
)
from dd_v3.retry import request_with_retry

_UI_READ_PATH = "/api/v1/logs-analytics/list"


class _LocalRuntimeState:
    def __init__(self) -> None:
        self.write_attempts = 0
        self.operation_state = "not_started"
        self.write_authorized = False

    def begin_write(self) -> None:
        if not self.write_authorized:
            raise ApiError(
                "This client is not authorized to write",
                error_code="write_policy_violation",
                category="permission",
            )
        if self.write_attempts:
            raise ConflictError(
                "Only one write request is allowed per invocation",
                error_code="multiple_writes_blocked",
            )
        self.write_attempts = 1
        self.operation_state = "dispatched"

    def mark_write_succeeded(self) -> None:
        self.operation_state = "succeeded"

    def mark_write_rejected(self) -> None:
        self.operation_state = "rejected"

    def mark_write_unknown(self) -> None:
        self.operation_state = "unknown"


def _origin_host(origin: str) -> str | None:
    parsed = urlparse(origin)
    try:
        port = parsed.port
    except ValueError:
        return None
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or port is not None
        or parsed.path
        or parsed.params
        or parsed.query
        or parsed.fragment
    ):
        return None
    return parsed.hostname.lower()


def _validate_transport(config: Config) -> None:
    api_host = _origin_host(config.api_base_url)
    ui_host = _origin_host(config.ui_base_url)
    if api_host is None or ui_host != DATADOG_API_TO_UI_HOST.get(api_host):
        raise ApiError(
            "DD_SITE and DD_UI_SITE must use the approved Datadog HTTPS mapping",
            error_code="unsafe_destination",
            category="config",
        )


def _validate_path(path: str) -> None:
    if not path.startswith("/") or path.startswith("//") or "://" in path:
        raise ApiError("Datadog request path must be relative", error_code="unsafe_destination")


class DatadogClient:
    def __init__(self, config: Config, *, session=None, state=None) -> None:
        self.config = config
        self.session = session
        self.state = state or _LocalRuntimeState()

    def request_read(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
        surface: str = "api",
    ) -> Any:
        method = method.upper()
        if method not in {"GET", "POST"}:
            raise ApiError("Read transport supports GET and POST only", error_code="invalid_transport")
        if surface not in {"api", "ui"}:
            raise ApiError("Unknown Datadog surface", error_code="invalid_transport")
        _validate_path(path)
        _validate_transport(self.config)
        if surface == "ui" and (method != "POST" or path != _UI_READ_PATH):
            raise ApiError(
                "UI reads are limited to the slow SQL endpoint",
                error_code="unsafe_destination",
            )
        kwargs: dict[str, Any] = {}
        if params is not None:
            kwargs["params"] = params
        if json_body is not None:
            kwargs["json"] = json_body
        base_url = self.config.api_base_url if surface == "api" else self.config.ui_base_url
        return self._request(
            method,
            f"{base_url}{path}",
            path=path,
            **kwargs,
        )

    def request_write_once(
        self,
        path: str,
        *,
        params: dict[str, Any] | None = None,
    ) -> Any:
        _validate_path(path)
        _validate_transport(self.config)
        headers = get_headers(self.config)
        self.state.begin_write()
        kwargs: dict[str, Any] = {
            "headers": headers,
            "timeout": self.config.timeout,
            "allow_redirects": False,
        }
        if params is not None:
            kwargs["params"] = params
        try:
            response = request_with_retry(
                "POST",
                f"{self.config.api_base_url}{path}",
                session=self.session,
                max_retries=0,
                **kwargs,
            )
        except requests.RequestException as exc:
            self.state.mark_write_unknown()
            raise WriteOutcomeUnknownError("Datadog write outcome is unknown") from exc

        status = response.status_code
        if status in {408, 429} or status >= 500:
            self.state.mark_write_unknown()
            raise WriteOutcomeUnknownError("Datadog write outcome is unknown")
        if status == 401:
            self.state.mark_write_rejected()
            raise AuthError("Datadog API rejected the write with status 401", operation_state="rejected")
        if status == 403:
            self.state.mark_write_rejected()
            raise PermissionDeniedError(
                "Datadog API rejected the write with status 403",
                operation_state="rejected",
            )
        if status >= 300:
            self.state.mark_write_rejected()
            raise ApiError(
                f"Datadog API rejected the write with status {status}",
                operation_state="rejected",
            )
        self.state.mark_write_succeeded()
        return {"status_code": status}

    def _request(self, method: str, url: str, *, path: str, **kwargs) -> Any:
        kwargs.setdefault("headers", get_headers(self.config))
        kwargs.setdefault("timeout", self.config.timeout)
        kwargs.setdefault("allow_redirects", False)
        try:
            response = request_with_retry(
                method,
                url,
                session=self.session,
                max_retries=self.config.max_retries,
                **kwargs,
            )
        except requests.Timeout as exc:
            raise DatadogTimeoutError(f"Datadog read timed out: {method} {path}") from exc
        except requests.ConnectionError as exc:
            raise ApiError(
                f"Datadog read connection failed: {method} {path}",
                error_code="connection_failed",
                category="transient",
                retry_class="safe",
            ) from exc
        except requests.RequestException as exc:
            raise ApiError(f"HTTP request failed: {method} {path}") from exc

        status = response.status_code
        if status == 401:
            raise AuthError("Datadog API returned status 401")
        if status == 403:
            raise PermissionDeniedError("Datadog API returned status 403")
        if status in {408, 504}:
            raise DatadogTimeoutError(f"Datadog API timed out with status {status}")
        if status == 429:
            raise ApiError(
                "Datadog API rate limit remained after bounded retries",
                error_code="rate_limited",
                category="transient",
                retry_class="safe",
            )
        if status >= 500:
            raise ApiError(
                f"Datadog API returned status {status}",
                error_code="server_error",
                category="transient",
                retry_class="safe",
            )
        if status >= 300:
            raise ApiError(f"Datadog API returned status {status}")
        if not response.text:
            return {}
        try:
            return response.json()
        except (json.JSONDecodeError, ValueError) as exc:
            raise ApiError("Datadog API returned non-JSON content") from exc


def path_quote(value: str) -> str:
    return quote(value, safe="")
