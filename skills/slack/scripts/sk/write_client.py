"""Slack 写客户端：窄白名单、429 完整等待、未知结果零重试。"""

from __future__ import annotations

import hashlib
import json
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Optional
from urllib.error import HTTPError, URLError

from .errors import (
    RateLimitBudgetExceeded,
    ReadOnlyViolation,
    SlackAPIError,
    WriteResultUnknown,
    redact,
)
from .version import USER_AGENT


API_BASE = "https://slack.com/api/"
WRITE_METHODS: frozenset[str] = frozenset(
    {
        "files.getUploadURLExternal",
        "files.completeUploadExternal",
        "chat.postMessage",
        "chat.update",
        "chat.delete",
        "reactions.add",
        "reactions.remove",
    }
)

_SAFE_FAILURE_ERRORS = {
    "access_denied", "accesslimited", "account_inactive", "already_reacted",
    "as_user_not_supported", "block_mismatch", "blocked_file_type",
    "cant_broadcast_message", "cant_delete_message", "cant_update_message",
    "channel_not_found", "deprecated_endpoint", "edit_window_closed",
    "ekm_access_denied", "enterprise_is_restricted", "file_deleted",
    "file_is_deleted", "file_not_found", "file_share_limit_reached",
    "invalid_arg_name", "invalid_arguments", "invalid_array_arg",
    "invalid_attachments", "invalid_auth", "invalid_blocks",
    "invalid_blocks_format", "invalid_charset", "invalid_form_data",
    "invalid_metadata_format", "invalid_metadata_schema", "invalid_name",
    "invalid_post_type", "is_inactive", "markdown_text_conflict",
    "max_file_sharing_exceeded", "message_limit_exceeded", "message_not_found",
    "metadata_must_be_sent_from_app", "metadata_too_large", "method_deprecated",
    "missing_post_type", "missing_scope", "msg_too_long",
    "no_dual_broadcast_content_update", "no_permission", "no_reaction", "no_text",
    "not_allowed_token_type", "not_authed", "not_in_channel",
    "org_login_required", "posting_to_channel_denied", "ratelimited",
    "request_timeout", "team_access_not_granted", "team_not_found",
    "token_expired", "token_revoked", "too_many_attachments",
    "too_many_emoji", "two_factor_setup_required", "unable_to_share_files",
}


class SlackWriteClient:
    def __init__(
        self,
        token: str,
        *,
        timeout: int = 60,
        max_retries: int = 3,
        retry_wait_budget: int = 30,
        user_agent: str = USER_AGENT,
    ) -> None:
        self._token = token
        self._timeout = timeout
        self._max_retries = max(1, max_retries)
        self._retry_wait_budget = max(0, retry_wait_budget)
        self._user_agent = user_agent

    def call(self, method: str, **params: Any) -> dict[str, Any]:
        if method not in WRITE_METHODS:
            raise ReadOnlyViolation(
                f"method {method!r} is not in the write whitelist; "
                f"allowed methods: {', '.join(sorted(WRITE_METHODS))}."
            )

        body = urllib.parse.urlencode(
            {k: _stringify(v) for k, v in params.items() if v is not None}
        ).encode("utf-8")
        digest = "sha256:" + hashlib.sha256(body).hexdigest()
        waited = 0
        for attempt in range(self._max_retries):
            try:
                payload = self._post_form(API_BASE + method, body, method=method)
            except KeyboardInterrupt:
                raise WriteResultUnknown(
                    _unknown_payload(
                        method=method,
                        params=params,
                        digest=digest,
                        reason="interrupted_during_dispatch",
                        request_id=None,
                        phase="request_sent",
                    )
                ) from None
            except _RateLimited as exc:
                if (
                    exc.seconds is None
                    or attempt + 1 >= self._max_retries
                    or waited + exc.seconds > self._retry_wait_budget
                ):
                    raise RateLimitBudgetExceeded(method, exc.seconds) from None
                time.sleep(exc.seconds)
                waited += exc.seconds
                continue
            except _TransportUnknown as exc:
                raise WriteResultUnknown(
                    _unknown_payload(
                        method=method,
                        params=params,
                        digest=digest,
                        reason=exc.reason,
                        request_id=exc.request_id,
                        phase="request_sent",
                    )
                ) from None

            if payload.get("ok", False):
                return payload
            error = str(payload.get("error") or "unknown_error")
            if error not in _SAFE_FAILURE_ERRORS:
                raise WriteResultUnknown(
                    _unknown_payload(
                        method=method,
                        params=params,
                        digest=digest,
                        reason=error,
                        request_id=payload.get("_slack_request_id"),
                        phase="response_ambiguous",
                    )
                )
            raise SlackAPIError(method, error, detail=_truncate_detail(payload))
        raise AssertionError("unreachable")

    def put_bytes(
        self,
        upload_url: str,
        file_path: Path,
        *,
        content_type: str = "application/octet-stream",
        verified_bytes: Optional[bytes] = None,
    ) -> None:
        """Send *file_path* or the already verified byte buffer via HTTP POST.

        Slack expects POST, not PUT, on the presigned URL — the doc name is
        misleading.  ``verified_bytes`` keeps the bytes checked by an upstream
        hash gate identical to the bytes handed to the HTTP request.
        """
        size = len(verified_bytes) if verified_bytes is not None else file_path.stat().st_size
        waited = 0
        for attempt in range(self._max_retries):
            try:
                if verified_bytes is not None:
                    req = urllib.request.Request(
                        upload_url,
                        data=verified_bytes,
                        method="POST",
                        headers={
                            "Content-Type": content_type,
                            "Content-Length": str(size),
                            "User-Agent": self._user_agent,
                        },
                    )
                    with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                        resp.read()
                    return
                with file_path.open("rb") as fp:
                    req = urllib.request.Request(
                        upload_url,
                        data=fp,
                        method="POST",
                        headers={
                            "Content-Type": content_type,
                            "Content-Length": str(size),
                            "User-Agent": self._user_agent,
                        },
                    )
                    with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                        resp.read()
                return
            except HTTPError as exc:
                if exc.code == 429:
                    seconds = _parse_retry_after(exc.headers.get("Retry-After"))
                    if (
                        seconds is None
                        or attempt + 1 >= self._max_retries
                        or waited + seconds > self._retry_wait_budget
                    ):
                        raise RateLimitBudgetExceeded("files.upload_bytes", seconds) from None
                    time.sleep(seconds)
                    waited += seconds
                    continue
                if exc.code >= 500:
                    raise WriteResultUnknown(
                        {
                            "status": "unknown",
                            "retry_safe": False,
                            "delivery_phase": "bytes_upload",
                            "reason": f"http_{exc.code}",
                            "file_name": file_path.name,
                            "file_size": size,
                        }
                    ) from None
                raise SlackAPIError(
                    "files.upload_bytes",
                    f"http_{exc.code}",
                    http_status=exc.code,
                    detail=redact(str(exc.reason)),
                ) from None
            except (URLError, TimeoutError, OSError) as exc:
                raise WriteResultUnknown(
                    {
                        "status": "unknown",
                        "retry_safe": False,
                        "delivery_phase": "bytes_upload",
                        "reason": redact(exc.__class__.__name__),
                        "file_name": file_path.name,
                        "file_size": size,
                    }
                ) from None
            except KeyboardInterrupt:
                raise WriteResultUnknown(
                    {
                        "status": "unknown",
                        "retry_safe": False,
                        "delivery_phase": "bytes_upload",
                        "reason": "interrupted_during_dispatch",
                        "file_name": file_path.name,
                        "file_size": size,
                    }
                ) from None

    def _post_form(self, url: str, body: bytes, *, method: str) -> dict[str, Any]:
        req = urllib.request.Request(
            url,
            data=body,
            method="POST",
            headers={
                "Authorization": f"Bearer {self._token}",
                "Content-Type": "application/x-www-form-urlencoded; charset=utf-8",
                "User-Agent": self._user_agent,
                "Accept": "application/json",
            },
        )
        request_id: Optional[str] = None
        try:
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                raw = resp.read()
                request_id = resp.headers.get("x-slack-req-id")
        except HTTPError as exc:
            request_id = exc.headers.get("x-slack-req-id")
            if exc.code == 429:
                raise _RateLimited(_parse_retry_after(exc.headers.get("Retry-After"))) from None
            if exc.code >= 500:
                raise _TransportUnknown(f"http_{exc.code}", request_id=request_id) from None
            detail = exc.read().decode("utf-8", errors="replace")
            raise SlackAPIError(
                method,
                f"http_{exc.code}",
                http_status=exc.code,
                detail=redact(detail),
            ) from None
        except (URLError, TimeoutError, OSError) as exc:
            raise _TransportUnknown(exc.__class__.__name__, request_id=request_id) from None

        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            raise _TransportUnknown("invalid_json", request_id=request_id) from None
        if not isinstance(payload, dict):
            raise _TransportUnknown("invalid_json_shape", request_id=request_id)
        if request_id:
            payload["_slack_request_id"] = request_id
        return payload


class _RateLimited(Exception):
    def __init__(self, seconds: Optional[int]) -> None:
        self.seconds = seconds


class _TransportUnknown(Exception):
    def __init__(self, reason: str, *, request_id: Optional[str]) -> None:
        self.reason = reason
        self.request_id = request_id


def _parse_retry_after(value: Optional[str]) -> Optional[int]:
    if not value:
        return None
    try:
        return max(1, int(value))
    except ValueError:
        return None


def _unknown_payload(
    *, method: str, params: dict[str, Any], digest: str, reason: str,
    request_id: Optional[str], phase: str,
) -> dict[str, Any]:
    return {
        "status": "unknown",
        "retry_safe": False,
        "method": method,
        "channel": params.get("channel") or params.get("channel_id"),
        "thread_ts": params.get("thread_ts"),
        "delivery_phase": phase,
        "payload_digest": digest,
        "slack_request_id": request_id,
        "reason": reason,
    }


def _stringify(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (list, tuple)):
        return json.dumps(list(value), ensure_ascii=False)
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


def _truncate_detail(payload: dict[str, Any]) -> str:
    try:
        blob = json.dumps(payload, ensure_ascii=False)
    except Exception:  # noqa: BLE001
        return ""
    return redact(blob[:500])


__all__ = ["SlackWriteClient", "WRITE_METHODS"]
