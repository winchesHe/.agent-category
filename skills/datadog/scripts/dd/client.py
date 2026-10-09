"""Thin Datadog HTTP client used by all command modules."""
from __future__ import annotations

import json
from typing import Any
from urllib.parse import quote

import requests

from dd.config import Config, get_headers
from dd.errors import ApiError, AuthError, TimeoutError
from dd.retry import request_with_retry


class DatadogClient:
    def __init__(self, config: Config, *, session=None) -> None:
        self.config = config
        self.session = session

    def get(self, path: str, *, params: dict[str, Any] | None = None) -> Any:
        return self.request("GET", path, params=params)

    def post(self, path: str, *, json_body: dict[str, Any]) -> Any:
        return self.request("POST", path, json=json_body)

    def request(self, method: str, path: str, **kwargs) -> Any:
        url = f"{self.config.api_base_url}{path}"
        kwargs.setdefault("headers", get_headers(self.config))
        kwargs.setdefault("timeout", self.config.timeout)
        try:
            response = request_with_retry(
                method,
                url,
                session=self.session,
                max_retries=self.config.max_retries,
                **kwargs,
            )
        except requests.Timeout as exc:
            raise TimeoutError(f"请求超时: {method} {path}") from exc
        except requests.RequestException as exc:
            raise ApiError(f"HTTP 请求失败: {method} {path}: {exc}") from exc

        if response.status_code in (401, 403):
            raise AuthError(f"认证/权限错误 {response.status_code}: {response.text}")
        if response.status_code in (408, 504):
            raise TimeoutError(f"Datadog API 超时 {response.status_code}: {response.text}")
        if not response.ok:
            raise ApiError(f"Datadog API 错误 {response.status_code}: {response.text}")
        if not response.text:
            return {}
        try:
            return response.json()
        except json.JSONDecodeError as exc:
            raise ApiError(f"Datadog API 返回非 JSON: {response.text[:500]}") from exc


def path_quote(value: str) -> str:
    return quote(value, safe="")
