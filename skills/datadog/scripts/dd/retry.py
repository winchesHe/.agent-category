"""HTTP retry helpers with Datadog 429 header support."""
from __future__ import annotations

import math
import sys
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

DEFAULT_MAX_RETRIES = 4
DEFAULT_MAX_DELAY_SECONDS = 30


def _parse_retry_after(value: str | None) -> int | None:
    if not value:
        return None
    text = value.strip()
    try:
        return max(int(float(text)), 0)
    except ValueError:
        pass
    try:
        retry_at = parsedate_to_datetime(text)
    except (TypeError, ValueError, IndexError, OverflowError):
        return None
    if retry_at.tzinfo is None:
        retry_at = retry_at.replace(tzinfo=timezone.utc)
    seconds = (retry_at - datetime.now(timezone.utc)).total_seconds()
    return max(int(math.ceil(seconds)), 0)


def _parse_rate_limit_reset(value: str | None) -> int | None:
    if not value:
        return None
    try:
        return max(int(float(value.strip())), 0)
    except ValueError:
        return None


def get_retry_delay_seconds(headers, attempt: int, max_delay: int = DEFAULT_MAX_DELAY_SECONDS) -> int:
    retry_after = _parse_retry_after(headers.get("Retry-After"))
    if retry_after is not None:
        return retry_after
    rate_limit_reset = _parse_rate_limit_reset(headers.get("X-RateLimit-Reset"))
    if rate_limit_reset is not None:
        return rate_limit_reset
    return min(2 ** attempt, max_delay)


def request_with_retry(
    method: str,
    url: str,
    *,
    session=None,
    max_retries: int = DEFAULT_MAX_RETRIES,
    **kwargs,
):
    import requests

    max_retries = max(max_retries, 0)
    requester = session.request if session is not None else requests.request

    response = None
    for attempt in range(max_retries + 1):
        response = requester(method, url, **kwargs)
        if response.status_code != 429:
            return response
        if attempt == max_retries:
            return response
        wait = get_retry_delay_seconds(response.headers, attempt)
        sys.stderr.write(f"[datadog] 429 rate-limited, retry in {wait}s ({attempt + 1}/{max_retries})\n")
        sys.stderr.flush()
        time.sleep(wait)
    return response
