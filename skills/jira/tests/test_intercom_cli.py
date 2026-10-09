from __future__ import annotations

import io
import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from ji.commands import intercom
from ji.config import Config


class FakeResponse:
    def __init__(self, payload, *, status=200):
        self.payload = payload
        self.status = status
        self.headers = {"Content-Type": "application/json"}

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self, *_args):
        if isinstance(self.payload, bytes):
            return self.payload
        return json.dumps(self.payload).encode("utf-8")


def config() -> Config:
    return Config(
        jira_base_url="https://moego.atlassian.net",
        jira_login="agent@example.com",
        jira_token="jira-token",
        jira_timeout=5.0,
        max_attachment_bytes=1024 * 1024,
        intercom_jwt=None,
        intercom_jwt_command=None,
        intercom_graphql_url="https://intercom-for-jira-production.toolsplus.app/api/intercom/graphql",
        intercom_referrer=None,
        intercom_timeout=5.0,
    )


class IntercomCliTests(unittest.TestCase):
    def test_issue_field_to_servlet_jwt_to_graphql(self):
        requests = []

        def fake_urlopen(req, timeout=0):
            requests.append((req.get_method(), req.full_url, dict(req.header_items()), req.data))
            if "/rest/api/3/field" in req.full_url:
                return FakeResponse(
                    [
                        {"id": "customfield_20001", "name": "Linked Intercom conversation IDs"},
                        {"id": "customfield_20002", "name": "Number of linked Intercom conversations"},
                    ]
                )
            if "/rest/api/3/issue/CS-45306?" in req.full_url:
                self.assertIn("customfield_20001", req.full_url)
                return FakeResponse(
                    {
                        "id": "127184",
                        "key": "CS-45306",
                        "names": {
                            "customfield_20001": "Linked Intercom conversation IDs",
                            "customfield_20002": "Number of linked Intercom conversations",
                        },
                        "fields": {
                            "summary": "Need help",
                            "status": {"name": "Open"},
                            "project": {"key": "CS", "id": "10001", "name": "CS"},
                            "issuetype": {"id": "10004", "name": "Bug"},
                            "created": "2026-04-25T00:00:00.000+0000",
                            "updated": "2026-04-25T00:00:00.000+0000",
                            "attachment": [],
                            "issuelinks": [],
                            "description": {"type": "doc", "content": []},
                            "customfield_20001": "215474005156281",
                            "customfield_20002": 1,
                        },
                    }
                )
            if "/rest/api/3/issue/CS-45306/comment?" in req.full_url:
                return FakeResponse({"comments": [], "total": 0, "isLast": True})
            if "/rest/api/3/issue/CS-45306/remotelink" in req.full_url:
                return FakeResponse([])
            if "/plugins/servlet/ac/io.toolsplus.atlassian.connect.jira.intercom/conversation-details-dialog" in req.full_url:
                body = req.data.decode("utf-8")
                self.assertIn("ac.selectedConversationId=215474005156281", body)
                return FakeResponse(
                    {
                        "contextJwt": "servlet-jwt",
                        "url": "https://intercom-for-jira-production.toolsplus.app/dialog",
                    }
                )
            if "intercom-for-jira-production.toolsplus.app/api/intercom/graphql" in req.full_url:
                self.assertEqual(dict(req.header_items())["Authorization"], "JWT servlet-jwt")
                body = json.loads(req.data.decode("utf-8"))
                self.assertEqual(body["variables"]["id"], "215474005156281")
                return FakeResponse(
                    {
                        "data": {
                            "conversation": {
                                "id": "215474005156281",
                                "state": "open",
                                "created_at": 1777124208,
                                "contacts": [{"role": "user", "id": "c1", "name": "Customer"}],
                                "source": {
                                    "id": "s1",
                                    "body": "<p>Customer issue</p>",
                                    "author": {"type": "user", "id": "u1", "author_name": "Alice"},
                                },
                                "conversation_parts": [
                                    {
                                        "id": "p1",
                                        "part_type": "comment",
                                        "body": "<p>Support reply</p>",
                                        "created_at": 1777124300,
                                        "author": {"type": "admin", "author_name": "Support"},
                                    }
                                ],
                            }
                        }
                    }
                )
            raise AssertionError(f"unexpected request: {req.full_url}")

        args = SimpleNamespace(
            issue="CS-45306",
            conversation_id=[],
            comment_limit="50",
            fields="summary,status,project,issuetype,created,updated,description,attachment,issuelinks",
            format="json",
        )
        stdout = io.StringIO()
        with patch("urllib.request.urlopen", side_effect=fake_urlopen), patch("sys.stdout", stdout):
            self.assertEqual(intercom.run(args, config()), 0)

        result = json.loads(stdout.getvalue())
        linked = result["linked_conversations"]
        self.assertEqual(linked[0]["source"], "jira_app_field")
        self.assertEqual(linked[0]["id"], "215474005156281")
        self.assertEqual(linked[0]["details"]["source"]["body_text"], "Customer issue")
        self.assertEqual(linked[0]["details"]["conversation_parts"][0]["body_text"], "Support reply")
        urls = [item[1] for item in requests]
        self.assertTrue(any("/rest/api/3/field" in url for url in urls))
        self.assertTrue(any("/plugins/servlet/ac/" in url for url in urls))
        self.assertTrue(any("intercom/graphql" in url for url in urls))


if __name__ == "__main__":
    unittest.main()
