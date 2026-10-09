from __future__ import annotations

import json
import subprocess
import time
import urllib.error
import urllib.request
import uuid
from typing import Any

from .config import Config
from .errors import EXIT_API, EXIT_AUTH, EXIT_TIMEOUT, CapabilityUnavailable, MeterSphereError


class Client:
    def __init__(self, config: Config, timeout: int = 60):
        self.config = config
        self.timeout = timeout

    def _signature(self) -> str:
        plain = f"{self.config.access_key}|{uuid.uuid4()}|{int(time.time() * 1000)}"
        try:
            result = subprocess.run(
                [
                    "openssl", "enc", "-aes-128-cbc",
                    "-K", self.config.secret_key.encode().hex(),
                    "-iv", self.config.access_key.encode().hex(),
                    "-base64", "-A", "-nosalt",
                ],
                input=plain.encode(), capture_output=True, check=True,
            )
        except (OSError, subprocess.CalledProcessError) as exc:
            raise MeterSphereError(f"生成签名失败: {exc}", EXIT_AUTH) from exc
        return result.stdout.decode().strip()

    def _headers(self, project_id: str = "", content_type: str = "application/json") -> dict[str, str]:
        headers = {
            "Content-Type": content_type,
            "accessKey": self.config.access_key,
            "signature": self._signature(),
        }
        if self.config.workspace_id:
            headers["WORKSPACE"] = self.config.workspace_id
        if project_id or self.config.project_id:
            headers["PROJECT"] = project_id or self.config.project_id
        if self.config.headers_json:
            try:
                headers.update(json.loads(self.config.headers_json))
            except json.JSONDecodeError as exc:
                raise MeterSphereError(f"METERSPHERE_HEADERS_JSON 不是有效 JSON: {exc}", 2) from exc
        return headers

    def request(self, method: str, path: str, body: Any = None, *, project_id: str = "", capability: str = "") -> Any:
        encoded = None if body is None else json.dumps(body, ensure_ascii=False).encode()
        request = urllib.request.Request(
            self.config.base_url + path,
            data=encoded,
            headers=self._headers(project_id),
            method=method.upper(),
        )
        return self._open(request, capability)

    def multipart(self, path: str, payload: dict[str, Any], *, project_id: str) -> Any:
        boundary = f"----MeterSphereCodex{uuid.uuid4().hex}"
        payload_bytes = json.dumps(payload, ensure_ascii=False).encode()
        body = b"".join([
            f"--{boundary}\r\n".encode(),
            b'Content-Disposition: form-data; name="request"\r\n',
            b"Content-Type: application/json\r\n\r\n",
            payload_bytes,
            b"\r\n",
            f"--{boundary}--\r\n".encode(),
        ])
        request = urllib.request.Request(
            self.config.base_url + path,
            data=body,
            headers=self._headers(project_id, f"multipart/form-data; boundary={boundary}"),
            method="POST",
        )
        return self._open(request)

    def _open(self, request: urllib.request.Request, capability: str = "") -> Any:
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                raw = response.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            detail_lower = detail.lower()
            if capability and (
                exc.code == 404
                or "No static resource" in detail
                or "服务调用出错" in detail
                or '"status":404' in detail
            ):
                raise CapabilityUnavailable(f"当前实例未提供 {capability}: HTTP {exc.code}", EXIT_API) from exc
            auth_failure = exc.code in (401, 403) or any(
                marker in detail_lower
                for marker in ("invalid accesskey", "invalid signature", "unauthorized", "forbidden", "authentication failed")
            )
            if auth_failure:
                raise MeterSphereError(f"认证或权限错误: HTTP {exc.code}", EXIT_AUTH) from exc
            compact_detail = " ".join(detail.split())
            if len(compact_detail) > 500:
                compact_detail = compact_detail[:500] + "..."
            raise MeterSphereError(f"HTTP {exc.code}: {compact_detail}", EXIT_API) from exc
        except (TimeoutError, urllib.error.URLError) as exc:
            if isinstance(exc, urllib.error.URLError) and not isinstance(exc.reason, TimeoutError):
                raise MeterSphereError(f"网络错误: {exc.reason}", EXIT_API) from exc
            raise MeterSphereError(f"请求超时: {exc}", EXIT_TIMEOUT) from exc

        if not raw:
            return None
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            parsed = raw
        if isinstance(parsed, dict) and parsed.get("success") is False:
            message = parsed.get("message") or "MeterSphere 返回 success=false"
            if capability and ("No static resource" in message or "服务调用出错" in message):
                raise CapabilityUnavailable(f"当前实例未提供 {capability}: {message}", EXIT_API)
            raise MeterSphereError(message, EXIT_API)
        if isinstance(parsed, dict) and parsed.get("status") in (401, 403):
            raise MeterSphereError(f"认证或权限错误: {parsed}", EXIT_AUTH)
        if isinstance(parsed, dict) and int(parsed.get("status") or 0) >= 400:
            if capability and int(parsed["status"]) == 404:
                raise CapabilityUnavailable(f"当前实例未提供 {capability}: HTTP 404", EXIT_API)
            raise MeterSphereError(f"API 错误: {parsed}", EXIT_API)
        return parsed
