"""Thin Sentry HTTP client used by all command modules."""
from __future__ import annotations

import json
import sys
import time
from typing import Any
from urllib.parse import quote

import requests

from st.config import Config, get_headers
from st.errors import ApiError, AuthError, TimeoutError

_RETRY_STATUSES = {429, 500, 502, 503, 504}
_MAX_RETRY_AFTER_SECONDS = 30


class SentryClient:
    def __init__(self, config: Config, *, session=None) -> None:
        self.config = config
        self.session = session

    def get(self, path: str, *, params: dict[str, Any] | None = None) -> Any:
        return self.request("GET", path, params=params)

    def request(self, method: str, path: str, **kwargs) -> Any:
        url = f"{self.config.base_url}{path}"
        kwargs.setdefault("headers", get_headers(self.config))
        kwargs.setdefault("timeout", self.config.timeout)
        requester = self.session.request if self.session is not None else requests.request

        response = None
        for attempt in range(max(self.config.max_retries, 0) + 1):
            try:
                response = requester(method, url, **kwargs)
            except requests.Timeout as exc:
                raise TimeoutError(f"请求超时: {method} {path}") from exc
            except requests.RequestException as exc:
                raise ApiError(f"HTTP 请求失败: {method} {path}: {exc}") from exc

            if response.status_code not in _RETRY_STATUSES or attempt >= self.config.max_retries:
                break
            wait = _retry_delay_seconds(response, attempt)
            sys.stderr.flush()
            time.sleep(wait)

        if response is None:
            raise ApiError(f"HTTP 请求失败: {method} {path}")
        if response.status_code in (401, 403):
            raise AuthError(f"认证/权限错误 {response.status_code}: {_safe_body(response)}")
        if response.status_code in (408, 504):
            raise TimeoutError(
                f"Sentry API 超时 {response.status_code}: {_safe_body(response)}",
                status_code=response.status_code,
            )
        if not response.ok:
            raise ApiError(
                f"Sentry API 错误 {response.status_code}: {_safe_body(response)}",
                status_code=response.status_code,
            )
        if not response.text:
            return {}
        try:
            return response.json()
        except json.JSONDecodeError as exc:
            raise ApiError(f"Sentry API 返回非 JSON: {response.text[:500]}") from exc

    def get_issue_resource(
        self,
        org: str,
        issue_id: str,
        suffix: str = "",
        *,
        params: dict[str, Any] | None = None,
    ) -> Any:
        """Fetch an issue-scoped resource, tolerating instances where the
        documented org-scoped issue route is broken.

        The documented endpoint is
        ``/api/0/organizations/{org}/issues/{id}/{suffix}``. On some Sentry
        deployments (observed on the MoeGo EU region) the org-scoped issue
        detail/events/tags routes return a server-side HTTP 5xx while the
        legacy bare ``/api/0/issues/{id}/{suffix}`` route still serves the
        same data. Prefer the documented route; fall back to the bare route
        only on 5xx so auth (401/403) and not-found (404) still surface.
        """
        org_path = (
            f"/api/0/organizations/{path_quote(org)}/issues/{path_quote(issue_id)}/{suffix}"
        )
        try:
            return self.request("GET", org_path, params=params)
        except (ApiError, TimeoutError) as exc:
            # HTTP 504 可按服务端错误回退；无状态码的网络超时仍直接报错。
            if exc.status_code is not None and exc.status_code >= 500:
                sys.stderr.write("[sentry] org-scoped 端点暂不可用，正在使用回退端点\n")
                sys.stderr.flush()
                bare_path = f"/api/0/issues/{path_quote(issue_id)}/{suffix}"
                return self.request("GET", bare_path, params=params)
            raise


def _retry_delay_seconds(response, attempt: int) -> int:
    retry_after = response.headers.get("Retry-After")
    if retry_after:
        try:
            return min(max(int(float(retry_after)), 0), _MAX_RETRY_AFTER_SECONDS)
        except ValueError:
            pass
    return min(2 ** attempt, _MAX_RETRY_AFTER_SECONDS)


def _safe_body(response) -> str:
    text = response.text or ""
    return text[:1000]


def path_quote(value: str) -> str:
    return quote(value, safe="")
