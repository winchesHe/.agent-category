"""Custom exceptions + token-redaction helpers."""

from __future__ import annotations

import re


_TOKEN_RE = re.compile(r"xox[abposr]-[A-Za-z0-9-]{10,}")


def redact(text: str) -> str:
    """Replace any Slack token-looking substring with ``xox*-***redacted***``."""
    if not text:
        return text
    return _TOKEN_RE.sub(lambda m: m.group(0)[:4] + "***redacted***", text)


class SlackSkillError(RuntimeError):
    """Base class for every user-visible error raised by the skill."""

    exit_code: int = 1


class TokenMissingError(SlackSkillError):
    """Required env var(s) not set."""

    exit_code = 2


class ActorConfigError(SlackSkillError):
    """Token 身份、默认 actor 或 workspace 配置错误。"""

    exit_code = 2


class ReadOnlyViolation(SlackSkillError):
    """Attempt to call a Slack method not in the read-only whitelist."""

    exit_code = 3


class InvalidArgument(SlackSkillError):
    exit_code = 4


class MentionResolutionError(InvalidArgument):
    """Mention 在当前 actor 可见域内无法唯一解析。"""


class ActorSelectionError(SlackSkillError):
    """写前预检无法安全锁定 actor。"""

    exit_code = 4


class WriteResultUnknown(SlackSkillError):
    """写请求可能已生效，但客户端无法取得确定结果。"""

    exit_code = 5

    def __init__(self, payload: dict):
        self.payload = payload
        super().__init__(str(payload.get("reason") or "write_result_unknown"))


class RateLimitBudgetExceeded(SlackSkillError):
    """429 的完整 Retry-After 超出本次等待预算。"""

    exit_code = 4

    def __init__(self, method: str, retry_after_seconds: int | None):
        self.method = method
        self.retry_after_seconds = retry_after_seconds
        detail = (
            f"Retry-After={retry_after_seconds}s 超出等待预算"
            if retry_after_seconds is not None
            else "Retry-After 缺失或非法，拒绝猜测等待时间"
        )
        super().__init__(f"{method}: ratelimited; {detail}")


class SlackAPIError(SlackSkillError):
    """Slack responded with ``ok: false`` or HTTP error."""

    def __init__(self, method: str, error: str, *, http_status: int | None = None, detail: str | None = None):
        self.method = method
        self.error = error
        self.http_status = http_status
        self.detail = detail
        message = f"{method}: {error}"
        if http_status:
            message = f"HTTP {http_status} {message}"
        if detail:
            message = f"{message} | {redact(detail)[:500]}"
        super().__init__(message)


__all__ = [
    "SlackSkillError",
    "TokenMissingError",
    "ActorConfigError",
    "ReadOnlyViolation",
    "InvalidArgument",
    "MentionResolutionError",
    "ActorSelectionError",
    "WriteResultUnknown",
    "RateLimitBudgetExceeded",
    "SlackAPIError",
    "redact",
]
