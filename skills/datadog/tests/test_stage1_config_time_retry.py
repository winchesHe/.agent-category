from __future__ import annotations

import io
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from dd import config, retry, timeutil
from dd.errors import MissingConfigError


class FakeResponse:
    def __init__(self, status_code: int, headers: dict[str, str] | None = None) -> None:
        self.status_code = status_code
        self.headers = headers or {}


class FakeSession:
    def __init__(self, responses: list[FakeResponse]) -> None:
        self.responses = list(responses)
        self.calls = 0

    def request(self, method: str, url: str, **kwargs):
        self.calls += 1
        return self.responses.pop(0)


class ConfigTests(unittest.TestCase):
    def test_normalizes_api_and_ui_urls(self) -> None:
        self.assertEqual(config.normalize_api_base_url("us5.datadoghq.com"), "https://api.us5.datadoghq.com")
        self.assertEqual(config.normalize_api_base_url("https://api.us5.datadoghq.com"), "https://api.us5.datadoghq.com")
        self.assertEqual(config.normalize_ui_base_url("https://api.us5.datadoghq.com"), "https://us5.datadoghq.com")

    def test_missing_keys_raise_config_error_without_reading_dotenv(self) -> None:
        with mock.patch.dict(os.environ, {"DD_DISABLE_DOTENV": "1"}, clear=True):
            with self.assertRaises(MissingConfigError) as ctx:
                config.load_config()
        self.assertEqual(ctx.exception.code, 2)


class TimeUtilTests(unittest.TestCase):
    def test_now_millis_preserves_millisecond_precision(self) -> None:
        with mock.patch.object(timeutil.time, "time", return_value=1_700_000_000.123):
            self.assertEqual(timeutil.now_millis(), 1_700_000_000_123)

    def test_parse_relative_time_to_seconds(self) -> None:
        now_ms = 1_700_000_000_000
        self.assertEqual(timeutil.parse_time_to_unix_seconds("1h", now_ms=now_ms), 1_699_996_400)
        self.assertEqual(timeutil.parse_time_to_unix_seconds("now-15m", now_ms=now_ms), 1_699_999_100)

    def test_normalize_datadog_time(self) -> None:
        self.assertEqual(timeutil.normalize_datadog_time("1h"), "now-1h")
        self.assertEqual(timeutil.normalize_datadog_time("now-15m"), "now-15m")
        self.assertEqual(timeutil.normalize_datadog_time("2024-01-01T00:00:00Z"), "2024-01-01T00:00:00Z")


class RetryTests(unittest.TestCase):
    def test_retries_using_retry_after_header(self) -> None:
        session = FakeSession([FakeResponse(429, {"Retry-After": "0"}), FakeResponse(200)])
        stderr = io.StringIO()
        with mock.patch.object(retry.time, "sleep") as sleep, mock.patch("sys.stderr", stderr):
            response = retry.request_with_retry("POST", "https://example.test", session=session)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(session.calls, 2)
        sleep.assert_called_once_with(0)
        self.assertIn("429 rate-limited", stderr.getvalue())

    def test_retries_using_rate_limit_reset_header(self) -> None:
        session = FakeSession([FakeResponse(429, {"X-RateLimit-Reset": "2"}), FakeResponse(200)])
        with mock.patch.object(retry.time, "sleep") as sleep:
            response = retry.request_with_retry("GET", "https://example.test", session=session)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(session.calls, 2)
        sleep.assert_called_once_with(2)

    def test_returns_last_429_after_max_retries(self) -> None:
        session = FakeSession([FakeResponse(429)] * 5)
        with mock.patch.object(retry.time, "sleep") as sleep:
            response = retry.request_with_retry("GET", "https://example.test", session=session)
        self.assertEqual(response.status_code, 429)
        self.assertEqual(session.calls, 5)
        self.assertEqual(sleep.call_count, 4)

    def test_negative_max_retries_still_makes_one_request(self) -> None:
        session = FakeSession([FakeResponse(200)])
        response = retry.request_with_retry(
            "GET",
            "https://example.test",
            session=session,
            max_retries=-1,
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(session.calls, 1)


if __name__ == "__main__":
    unittest.main()
