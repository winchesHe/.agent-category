from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from st.config import Config
from st.errors import UsageError
from st.commands import fetch_event, get_issue, list_issue_events, list_issues, list_projects, tag_values

SKILL_DIR = Path(__file__).resolve().parents[1]
CLI = SKILL_DIR / "scripts" / "sentry.py"


def config() -> Config:
    return Config(
        auth_token="test-token",
        base_url="https://sentry.io",
        default_org_slug="moego",
        default_project=None,
        timeout=5.0,
        max_retries=0,
    )


def issue_payload() -> dict[str, object]:
    return {
        "id": "12345",
        "shortId": "WEB-1",
        "title": "TypeError: bad",
        "status": "unresolved",
        "level": "error",
        "count": "5",
        "userCount": 2,
        "project": {"id": "1", "slug": "web", "name": "Web", "platform": "javascript"},
    }


def event_payload(event_id: str = "evt1") -> dict[str, object]:
    return {
        "id": event_id,
        "title": "TypeError: bad",
        "type": "error",
        "platform": "javascript",
        "tags": [{"key": "release", "value": "1.0.0"}],
        "entries": [
            {
                "type": "exception",
                "data": {
                    "values": [
                        {
                            "type": "TypeError",
                            "value": "bad",
                            "stacktrace": {
                                "frames": [
                                    {
                                        "filename": "app.js",
                                        "lineno": 10,
                                        "function": "render",
                                        "in_app": True,
                                    }
                                ]
                            },
                        }
                    ]
                },
            },
            {
                "type": "breadcrumbs",
                "data": {
                    "values": [
                        {"timestamp": "2026-01-01T00:00:00Z", "category": "http", "message": "GET /api"}
                    ]
                },
            },
        ],
    }


class FakeClient:
    def __init__(self, responses: dict[str, object]) -> None:
        self.responses = responses
        self.calls: list[tuple[str, dict[str, object] | None]] = []

    def get(self, path: str, *, params=None):
        self.calls.append((path, params))
        if path not in self.responses:
            raise AssertionError(f"unexpected Sentry path: {path}")
        return self.responses[path]

    def get_issue_resource(self, org, issue_id, suffix="", *, params=None):
        return self.get(f"/api/0/organizations/{org}/issues/{issue_id}/{suffix}", params=params)


class SentrySkillTests(unittest.TestCase):
    def run_command(self, module, args, responses):
        fake = FakeClient(responses)
        stdout = io.StringIO()
        stderr = io.StringIO()
        with mock.patch.object(module, "SentryClient", return_value=fake), mock.patch(
            "sys.stdout", stdout
        ), mock.patch("sys.stderr", stderr):
            self.assertEqual(module.run(args, config()), 0)
        return json.loads(stdout.getvalue()), stderr.getvalue(), fake.calls

    def test_get_issue_fetches_issue_and_latest_event_for_issue_url(self) -> None:
        args = SimpleNamespace(
            url="https://moego.sentry.io/organizations/moego/issues/12345/",
            org=None,
            issue_id=None,
            event_id=None,
            include_event="auto",
            include_raw=False,
            fmt="json",
        )
        data, _stderr, calls = self.run_command(
            get_issue,
            args,
            {
                "/api/0/organizations/moego/issues/12345/": issue_payload(),
                "/api/0/organizations/moego/issues/12345/events/latest/": event_payload("latest"),
            },
        )

        self.assertEqual(data["issue"]["shortId"], "WEB-1")
        self.assertEqual(data["event"]["id"], "latest")
        self.assertEqual(calls[0][0], "/api/0/organizations/moego/issues/12345/")
        self.assertEqual(calls[1][0], "/api/0/organizations/moego/issues/12345/events/latest/")

    def test_fetch_event_requires_event_id_when_using_issue_id(self) -> None:
        args = SimpleNamespace(
            url=None,
            org=None,
            issue_id="WEB-1",
            event_id=None,
            include_raw=False,
            fmt="json",
        )

        with self.assertRaises(UsageError):
            fetch_event.run(args, config())

    def test_fetch_event_fetches_explicit_issue_event(self) -> None:
        args = SimpleNamespace(
            url=None,
            org=None,
            issue_id="WEB-1",
            event_id="evt1",
            include_raw=False,
            fmt="json",
        )
        data, _stderr, calls = self.run_command(
            fetch_event,
            args,
            {"/api/0/organizations/moego/issues/WEB-1/events/evt1/": event_payload("evt1")},
        )

        self.assertEqual(data["input"]["event_id"], "evt1")
        self.assertEqual(data["event"]["id"], "evt1")
        self.assertEqual(calls[0][0], "/api/0/organizations/moego/issues/WEB-1/events/evt1/")

    def test_list_issues_requires_query_in_cli(self) -> None:
        env = os.environ.copy()
        env.update({"SENTRY_DISABLE_DOTENV": "1", "PYTHONDONTWRITEBYTECODE": "1"})
        env.pop("SENTRY_AUTH_TOKEN", None)
        result = subprocess.run(
            [sys.executable, str(CLI), "list-issues"],
            cwd=str(SKILL_DIR),
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertEqual(result.returncode, 2)
        self.assertIn("--query", result.stderr)

    def test_list_issues_sends_query_sort_and_limit(self) -> None:
        args = SimpleNamespace(
            org=None,
            project=None,
            query="is:unresolved lastSeen:-24h",
            sort="date",
            limit=20,
            include_raw=False,
            fmt="json",
        )
        data, _stderr, calls = self.run_command(
            list_issues,
            args,
            {"/api/0/organizations/moego/issues/": [issue_payload()]},
        )

        self.assertEqual(data["count"], 1)
        self.assertEqual(calls[0][0], "/api/0/organizations/moego/issues/")
        self.assertEqual(calls[0][1]["query"], "is:unresolved lastSeen:-24h")
        self.assertEqual(calls[0][1]["sort"], "date")
        self.assertEqual(calls[0][1]["per_page"], "20")

    def test_list_issue_events_sends_issue_scoped_event_query(self) -> None:
        args = SimpleNamespace(
            url="https://moego.sentry.io/organizations/moego/issues/12345/",
            org=None,
            issue_id=None,
            query="environment:production",
            sort="-timestamp",
            stats_period="14d",
            limit=50,
            include_raw=False,
            fmt="json",
        )
        data, _stderr, calls = self.run_command(
            list_issue_events,
            args,
            {"/api/0/organizations/moego/issues/12345/events/": [event_payload("evt2")]},
        )

        self.assertEqual(data["items"][0]["id"], "evt2")
        self.assertEqual(calls[0][0], "/api/0/organizations/moego/issues/12345/events/")
        self.assertEqual(calls[0][1]["query"], "environment:production")
        self.assertEqual(calls[0][1]["statsPeriod"], "14d")

    def test_tag_values_fetches_distribution_for_issue_tag(self) -> None:
        args = SimpleNamespace(
            url="https://moego.sentry.io/organizations/moego/issues/12345/",
            org=None,
            issue_id=None,
            tag="release",
            include_raw=False,
            fmt="json",
        )
        data, _stderr, calls = self.run_command(
            tag_values,
            args,
            {
                "/api/0/organizations/moego/issues/12345/tags/release/": {
                    "key": "release",
                    "name": "Release",
                    "topValues": [{"value": "1.0.0", "count": 3}],
                }
            },
        )

        self.assertEqual(data["tag"]["key"], "release")
        self.assertEqual(data["items"][0]["value"], "1.0.0")
        self.assertEqual(calls[0][0], "/api/0/organizations/moego/issues/12345/tags/release/")

    def test_list_projects_fetches_projects_with_query(self) -> None:
        args = SimpleNamespace(org=None, query="web", limit=25, include_raw=False, fmt="json")
        data, _stderr, calls = self.run_command(
            list_projects,
            args,
            {"/api/0/organizations/moego/projects/": [{"id": "1", "slug": "web", "name": "Web"}]},
        )

        self.assertEqual(data["items"][0]["slug"], "web")
        self.assertEqual(calls[0][0], "/api/0/organizations/moego/projects/")
        self.assertEqual(calls[0][1]["query"], "web")


if __name__ == "__main__":
    unittest.main()
