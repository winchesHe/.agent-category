from __future__ import annotations

import io
import sys
import tempfile
import unittest
from email.message import Message
from pathlib import Path
from unittest import mock
from urllib.error import HTTPError, URLError

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from sk.client import SlackClient  # noqa: E402
from sk.errors import RateLimitBudgetExceeded, SlackAPIError, WriteResultUnknown  # noqa: E402
from sk.write_client import SlackWriteClient  # noqa: E402


class FakeResponse:
    def __init__(self, body: bytes):
        self.body = body
        self.headers = Message()

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return self.body


class WriteClientTests(unittest.TestCase):
    def test_500_is_unknown_and_never_retried(self) -> None:
        error = HTTPError("https://slack.com", 500, "boom", Message(), io.BytesIO(b""))
        with mock.patch("urllib.request.urlopen", side_effect=error) as opened:
            with self.assertRaises(WriteResultUnknown):
                SlackWriteClient("fixture", max_retries=3).call(
                    "chat.postMessage", channel="C1", text="hello"
                )
        self.assertEqual(opened.call_count, 1)

    def test_url_error_is_unknown_and_never_retried(self) -> None:
        with mock.patch("urllib.request.urlopen", side_effect=URLError("lost")) as opened:
            with self.assertRaises(WriteResultUnknown):
                SlackWriteClient("fixture", max_retries=3).call(
                    "chat.postMessage", channel="C1", text="hello"
                )
        self.assertEqual(opened.call_count, 1)

    def test_internal_error_payload_is_unknown(self) -> None:
        response = FakeResponse(b'{"ok":false,"error":"internal_error"}')
        with mock.patch("urllib.request.urlopen", return_value=response):
            with self.assertRaises(WriteResultUnknown):
                SlackWriteClient("fixture").call(
                    "chat.postMessage", channel="C1", text="hello"
                )

    def test_non_object_write_response_is_unknown_and_not_retryable(self) -> None:
        response = FakeResponse(b"[]")
        with mock.patch("urllib.request.urlopen", return_value=response):
            with self.assertRaises(WriteResultUnknown) as caught:
                SlackWriteClient("fixture").call(
                    "chat.postMessage", channel="C1", text="hello"
                )
        self.assertEqual(caught.exception.payload["reason"], "invalid_json_shape")
        self.assertFalse(caught.exception.payload["retry_safe"])

    def test_non_object_read_response_is_slack_error(self) -> None:
        response = FakeResponse(b"null")
        with mock.patch("urllib.request.urlopen", return_value=response):
            with self.assertRaises(SlackAPIError) as caught:
                SlackClient("fixture").call("auth.test")
        self.assertEqual(caught.exception.error, "invalid_response_shape")

    def test_retry_after_is_not_truncated(self) -> None:
        headers = Message()
        headers["Retry-After"] = "90"
        error = HTTPError("https://slack.com", 429, "slow", headers, io.BytesIO(b""))
        with mock.patch("urllib.request.urlopen", side_effect=error), mock.patch("time.sleep") as sleep:
            with self.assertRaises(RateLimitBudgetExceeded) as caught:
                SlackWriteClient("fixture", retry_wait_budget=30).call(
                    "chat.postMessage", channel="C1", text="hello"
                )
        self.assertEqual(caught.exception.retry_after_seconds, 90)
        sleep.assert_not_called()

    def test_missing_retry_after_is_not_guessed_or_retried(self) -> None:
        error = HTTPError("https://slack.com", 429, "slow", Message(), io.BytesIO(b""))
        with mock.patch("urllib.request.urlopen", side_effect=error) as opened, mock.patch(
            "time.sleep"
        ) as sleep:
            with self.assertRaises(RateLimitBudgetExceeded) as caught:
                SlackWriteClient("fixture", retry_wait_budget=30).call(
                    "chat.postMessage", channel="C1", text="hello"
                )

        self.assertIsNone(caught.exception.retry_after_seconds)
        self.assertEqual(opened.call_count, 1)
        sleep.assert_not_called()

    def test_read_transport_exhaustion_is_wrapped_without_raw_exception(self) -> None:
        with mock.patch("urllib.request.urlopen", side_effect=URLError("secret-url")), mock.patch(
            "time.sleep"
        ):
            with self.assertRaises(SlackAPIError) as caught:
                SlackClient("fixture", max_retries=2).call("auth.test")

        self.assertEqual(caught.exception.error, "transport_error")
        self.assertNotIn("secret-url", str(caught.exception))

    def test_write_dispatch_interrupt_is_unknown(self) -> None:
        client = SlackWriteClient("fixture")
        with mock.patch.object(client, "_post_form", side_effect=KeyboardInterrupt):
            with self.assertRaises(WriteResultUnknown) as caught:
                client.call("chat.postMessage", channel="C1", text="hello")

        self.assertEqual(caught.exception.payload["delivery_phase"], "request_sent")
        self.assertFalse(caught.exception.payload["retry_safe"])

    def test_bytes_upload_interrupt_is_unknown(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "file.txt"
            path.write_text("hello", encoding="utf-8")
            with mock.patch("urllib.request.urlopen", side_effect=KeyboardInterrupt):
                with self.assertRaises(WriteResultUnknown) as caught:
                    SlackWriteClient("fixture").put_bytes("https://upload.test", path)

        self.assertEqual(caught.exception.payload["delivery_phase"], "bytes_upload")
        self.assertFalse(caught.exception.payload["retry_safe"])


if __name__ == "__main__":
    unittest.main()
