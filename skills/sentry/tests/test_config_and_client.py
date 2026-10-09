import io
import json
import os
import sys
import unittest
from types import SimpleNamespace
from unittest import mock
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"

if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from st.config import Config, load_config, normalize_base_url
from st.client import SentryClient
from st.commands import analyze, fetch_event, get_issue, list_issue_events, tag_values
from st.errors import MissingConfigError, UsageError


class ConfigAndHostSafetyTests(unittest.TestCase):
    def make_config(self):
        return Config(
            auth_token="token",
            base_url="https://trusted.sentry.io",
            default_org_slug="moego",
            default_project=None,
            timeout=1.0,
            max_retries=0,
        )

    def test_normalize_base_url_rejects_http(self):
        with self.assertRaises(MissingConfigError):
            normalize_base_url("http://insecure.example.com")

    def test_load_config_clamps_retry_count_into_safe_range(self):
        with mock.patch.dict(
            os.environ,
            {
                "SENTRY_DISABLE_DOTENV": "1",
                "SENTRY_AUTH_TOKEN": "token",
                "SENTRY_BASE_URL": "https://trusted.sentry.io",
                "SENTRY_MAX_RETRIES": "99",
            },
            clear=True,
        ):
            self.assertEqual(load_config().max_retries, 5)

        with mock.patch.dict(
            os.environ,
            {
                "SENTRY_DISABLE_DOTENV": "1",
                "SENTRY_AUTH_TOKEN": "token",
                "SENTRY_BASE_URL": "https://trusted.sentry.io",
                "SENTRY_MAX_RETRIES": "-8",
            },
            clear=True,
        ):
            self.assertEqual(load_config().max_retries, 0)

    def test_load_config_uses_current_moego_org_slug_by_default(self):
        with mock.patch.dict(
            os.environ,
            {
                "SENTRY_DISABLE_DOTENV": "1",
                "SENTRY_AUTH_TOKEN": "token",
            },
            clear=True,
        ):
            self.assertEqual(load_config().default_org_slug, "moego-ey")

    def test_url_parser_rejects_http_issue_urls(self):
        from st.urls import parse_sentry_url

        with self.assertRaises(UsageError):
            parse_sentry_url("http://evil.example.com/organizations/moego/issues/123/")

    def test_url_host_never_overrides_configured_request_host(self):
        config = self.make_config()
        issue_url = "https://evil.example.com/organizations/moego/issues/123/events/evt-1/"

        cases = [
            (
                get_issue,
                SimpleNamespace(
                    url=issue_url,
                    org=None,
                    issue_id=None,
                    event_id=None,
                    include_event="never",
                    include_raw=False,
                    fmt="json",
                ),
                [{"id": "123", "title": "issue"}],
            ),
            (
                fetch_event,
                SimpleNamespace(
                    url=issue_url,
                    org=None,
                    issue_id=None,
                    event_id=None,
                    include_raw=False,
                    fmt="json",
                ),
                [{"id": "evt-1", "eventID": "evt-1"}],
            ),
            (
                list_issue_events,
                SimpleNamespace(
                    url=issue_url,
                    org=None,
                    issue_id=None,
                    query="",
                    sort="-timestamp",
                    stats_period="14d",
                    limit=1,
                    include_raw=False,
                    fmt="json",
                ),
                [[{"id": "evt-1"}]],
            ),
            (
                tag_values,
                SimpleNamespace(
                    url=issue_url,
                    org=None,
                    issue_id=None,
                    tag="release",
                    include_raw=False,
                    fmt="json",
                ),
                [{"key": "release", "values": []}],
            ),
            (
                analyze,
                SimpleNamespace(
                    url=issue_url,
                    org=None,
                    issue_id=None,
                    event_id=None,
                    mode="latest",
                    events=1,
                    target="json",
                ),
                [
                    {"id": "123", "title": "issue", "count": "1", "userCount": 1},
                    {"id": "evt-1", "eventID": "evt-1", "dateCreated": "2026-06-05T10:00:00Z"},
                ],
            ),
        ]

        for module, args, responses in cases:
            with self.subTest(command=module.NAME):
                seen = {}
                queue = list(responses)

                class FakeClient:
                    def __init__(self, client_config, *, session=None):
                        seen["base_url"] = client_config.base_url

                    def get(self, path, *, params=None):
                        return queue.pop(0)

                    def get_issue_resource(self, org, issue_id, suffix="", *, params=None):
                        return self.get(
                            f"/api/0/organizations/{org}/issues/{issue_id}/{suffix}",
                            params=params,
                        )

                with mock.patch.object(module, "SentryClient", FakeClient):
                    if module is analyze:
                        with mock.patch("sys.stdout", new=io.StringIO()):
                            exit_code = module.run(args, config)
                    else:
                        with mock.patch.object(module, "output", lambda *a, **k: None):
                            exit_code = module.run(args, config)

                self.assertEqual(exit_code, 0)
                self.assertEqual(seen["base_url"], config.base_url)


class RetryBehaviorTests(unittest.TestCase):
    def make_config(self, *, max_retries=1):
        return Config(
            auth_token="token",
            base_url="https://trusted.sentry.io",
            default_org_slug="moego",
            default_project=None,
            timeout=1.0,
            max_retries=max_retries,
        )

    def test_retry_after_wait_is_capped(self):
        class FakeResponse:
            def __init__(self, status_code, payload, headers=None):
                self.status_code = status_code
                self._payload = payload
                self.headers = headers or {}
                self.ok = status_code < 400
                self.text = json.dumps(payload)

            def json(self):
                return self._payload

        responses = [
            FakeResponse(429, {"detail": "rate limited"}, {"Retry-After": "120"}),
            FakeResponse(200, {"ok": True}),
        ]

        class FakeSession:
            def request(self, method, url, **kwargs):
                return responses.pop(0)

        client = SentryClient(self.make_config(max_retries=1), session=FakeSession())
        with mock.patch("st.client.time.sleep") as sleep, mock.patch("sys.stderr", new=io.StringIO()):
            result = client.get("/api/0/test")

        self.assertEqual(result, {"ok": True})
        sleep.assert_called_once_with(30)


if __name__ == "__main__":
    unittest.main()
