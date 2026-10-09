"""Time parsing helpers shared by Datadog commands."""
from __future__ import annotations

import re
import time
from datetime import datetime, timezone

from dd_v3.errors import ApiError

_DURATION_RE = re.compile(
    r"^\s*-?(\d+)\s*(s|sec|secs|second|seconds|m|min|mins|minute|minutes|h|hr|hrs|hour|hours|d|day|days|w|week|weeks)\s*$",
    re.IGNORECASE,
)


def _duration_seconds(value: str) -> int:
    match = _DURATION_RE.match(value)
    if not match:
        raise ApiError(
            f"无法解析时间: {value!r}; 支持 now、15m、1h、7d、RFC3339 或 Unix timestamp"
        )
    amount = int(match.group(1))
    unit = match.group(2).lower()
    if unit in {"s", "sec", "secs", "second", "seconds"}:
        return amount
    if unit in {"m", "min", "mins", "minute", "minutes"}:
        return amount * 60
    if unit in {"h", "hr", "hrs", "hour", "hours"}:
        return amount * 3600
    if unit in {"d", "day", "days"}:
        return amount * 86400
    if unit in {"w", "week", "weeks"}:
        return amount * 7 * 86400
    raise ApiError(f"无法解析时间单位: {unit}")


def now_millis() -> int:
    return int(time.time() * 1000)


def parse_time_to_unix_millis(value: str, *, now_ms: int | None = None) -> int:
    text = value.strip()
    if not text:
        raise ApiError("时间参数不能为空")
    if now_ms is None:
        now_ms = now_millis()
    if text.lower() == "now":
        return now_ms
    if text.isdigit():
        ts = int(text)
        return ts * 1000 if len(text) <= 10 else ts
    if text.startswith("now-"):
        return now_ms - _duration_seconds(text[4:]) * 1000
    if text.startswith("now+"):
        return now_ms + _duration_seconds(text[4:]) * 1000
    if _DURATION_RE.match(text):
        return now_ms - _duration_seconds(text) * 1000
    try:
        normalized = text[:-1] + "+00:00" if text.endswith("Z") else text
        dt = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise ApiError(
            f"无法解析时间: {value!r}; 支持 now、15m、1h、7d、RFC3339 或 Unix timestamp"
        ) from exc
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int(dt.timestamp() * 1000)


def parse_time_to_unix_seconds(value: str, *, now_ms: int | None = None) -> int:
    return parse_time_to_unix_millis(value, now_ms=now_ms) // 1000


def normalize_datadog_time(value: str) -> str:
    text = value.strip()
    if not text:
        raise ApiError("时间参数不能为空")
    if text.lower() == "now" or text.startswith("now-") or text.startswith("now+"):
        return text
    if text.isdigit() or "T" in text:
        return text
    if _DURATION_RE.match(text):
        compact = re.sub(r"\s+", "", text.lstrip("-"))
        return f"now-{compact}"
    raise ApiError(
        f"无法解析时间: {value!r}; 支持 now、15m、1h、7d、RFC3339 或 Unix timestamp"
    )
