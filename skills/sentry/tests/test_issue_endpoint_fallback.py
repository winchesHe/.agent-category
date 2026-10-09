import json
import sys
import unittest
from dataclasses import replace
from pathlib import Path
from unittest import mock

import requests

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from st.client import SentryClient
from st.config import Config
from st.errors import ApiError, AuthError, TimeoutError


def make_config():
    return Config(
        auth_token="token",
        base_url="https://moego-ey.sentry.io",
        default_org_slug="moego",
        default_project=None,
        timeout=1.0,
        max_retries=0,
    )


class _FakeResponse:
    def __init__(self, status_code, payload=None, *, text=None):
        self.status_code = status_code
        self._payload = payload
        self.headers = {}
        self.ok = status_code < 400
        if text is not None:
            self.text = text
        else:
            self.text = json.dumps(payload) if payload is not None else ""

    def json(self):
        if self._payload is None:
            raise json.JSONDecodeError("no json", "", 0)
        return self._payload


class IssueEndpointFallbackTests(unittest.TestCase):
    def test_http_504_falls_back_after_retries_with_same_suffix_and_params(self):
        session = mock.Mock()
        session.request.side_effect = [
            _FakeResponse(504, text="gateway timeout"),
            _FakeResponse(504, text="gateway timeout"),
            _FakeResponse(200, {"topValues": []}),
        ]
        client = SentryClient(replace(make_config(), max_retries=1), session=session)
        params = {"per_page": "1"}
        with mock.patch("st.client.time.sleep") as sleep:
            result = client.get_issue_resource("moego", "123", "tags/release/", params=params)
        self.assertEqual(result, {"topValues": []})
        self.assertEqual([call.args[1] for call in session.request.call_args_list], [
            "https://moego-ey.sentry.io/api/0/organizations/moego/issues/123/tags/release/",
            "https://moego-ey.sentry.io/api/0/organizations/moego/issues/123/tags/release/",
            "https://moego-ey.sentry.io/api/0/issues/123/tags/release/",
        ])
        self.assertTrue(all(call.kwargs["params"] == params for call in session.request.call_args_list))
        sleep.assert_called_once_with(1)

    def test_network_timeout_and_4xx_do_not_fall_back(self):
        for status, error in ((401, AuthError), (403, AuthError), (404, ApiError), (408, TimeoutError)):
            with self.subTest(status=status):
                session = mock.Mock()
                session.request.return_value = _FakeResponse(status, text="request failed")
                client = SentryClient(make_config(), session=session)
                with self.assertRaises(error):
                    client.get_issue_resource("moego", "123")
                self.assertEqual(session.request.call_count, 1)
        session = mock.Mock()
        session.request.side_effect = requests.Timeout("network timeout")
        with self.assertRaises(TimeoutError) as raised:
            SentryClient(make_config(), session=session).get_issue_resource("moego", "123")
        self.assertEqual(raised.exception.code, 5)
        self.assertEqual(session.request.call_count, 1)

    def test_bare_endpoint_504_preserves_timeout_exit_code_without_another_fallback(self):
        session = mock.Mock()
        session.request.side_effect = [
            _FakeResponse(500, text="server error"),
            _FakeResponse(504, text="gateway timeout"),
        ]
        with self.assertRaises(TimeoutError) as raised:
            SentryClient(make_config(), session=session).get_issue_resource("moego", "123")
        self.assertEqual(raised.exception.code, 5)
        self.assertEqual(session.request.call_count, 2)

    def test_org_scoped_500_falls_back_to_bare_issue_endpoint(self):
        calls = []

        class FakeSession:
            def request(self, method, url, **kwargs):
                calls.append(url)
                if "/organizations/" in url:
                    return _FakeResponse(500, text="<!doctype html>Server Error (500)")
                return _FakeResponse(200, {"id": "123", "title": "boom"})

        client = SentryClient(make_config(), session=FakeSession())
        result = client.get_issue_resource("moego", "123")

        self.assertEqual(result, {"id": "123", "title": "boom"})
        self.assertEqual(len(calls), 2)
        self.assertIn("/organizations/moego/issues/123/", calls[0])
        self.assertEqual(calls[1], "https://moego-ey.sentry.io/api/0/issues/123/")

    def test_org_scoped_200_does_not_call_bare_endpoint(self):
        calls = []

        class FakeSession:
            def request(self, method, url, **kwargs):
                calls.append(url)
                return _FakeResponse(200, {"id": "123", "title": "ok"})

        client = SentryClient(make_config(), session=FakeSession())
        result = client.get_issue_resource("moego", "123", "events/", params={"per_page": "1"})

        self.assertEqual(result, {"id": "123", "title": "ok"})
        self.assertEqual(len(calls), 1)
        self.assertIn("/organizations/moego/issues/123/events/", calls[0])

    def test_4xx_does_not_fall_back(self):
        calls = []

        class FakeSession:
            def request(self, method, url, **kwargs):
                calls.append(url)
                return _FakeResponse(404, {"detail": "not found"})

        client = SentryClient(make_config(), session=FakeSession())
        with self.assertRaises(ApiError):
            client.get_issue_resource("moego", "123")
        self.assertEqual(len(calls), 1)

    def test_suffix_is_preserved_in_both_attempts(self):
        calls = []

        class FakeSession:
            def request(self, method, url, **kwargs):
                calls.append(url)
                if "/organizations/" in url:
                    return _FakeResponse(503, text="busy")
                return _FakeResponse(200, {"topValues": []})

        client = SentryClient(make_config(), session=FakeSession())
        result = client.get_issue_resource("moego", "123", "tags/release/")

        self.assertEqual(result, {"topValues": []})
        self.assertTrue(calls[0].endswith("/organizations/moego/issues/123/tags/release/"))
        self.assertTrue(calls[1].endswith("/api/0/issues/123/tags/release/"))


if __name__ == "__main__":
    unittest.main()
