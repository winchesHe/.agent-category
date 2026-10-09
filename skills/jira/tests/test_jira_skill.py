from __future__ import annotations

import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from ji.client import JiraClient, build_api_create_fields, media_id_from_url
from ji.config import Config
from ji.intercom import build_linked_conversations, html_to_text, simplify_conversation
from ji.parsing import detect_supported_image_mimetype, parse_issue_key
from ji.commands import create, create_meta, download_attachment, link, read, search, transition, update, upload_attachment


class FakeResponse:
    def __init__(self, payload, *, status=200, headers=None):
        self.payload = payload
        self.status = status
        self.headers = headers or {"Content-Type": "application/json"}

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self, *_args):
        if isinstance(self.payload, bytes):
            return self.payload
        return json.dumps(self.payload).encode("utf-8")


RULE_URL = (
    "https://moego.atlassian.net/gateway/api/automation/internal-api/jira/"
    "00000000-0000-0000-0000-000000000000/pro/rest/v1/rules/manual/invocation/"
    "ffffffff-ffff-ffff-ffff-ffffffffffff"
)


def config() -> Config:
    return Config(
        jira_base_url="https://moego.atlassian.net",
        jira_login="agent@example.com",
        jira_token="jira-token",
        jira_timeout=5.0,
        max_attachment_bytes=1024 * 1024,
        intercom_jwt="fake-jwt",
        intercom_jwt_command=None,
        intercom_graphql_url="https://intercom-for-jira-production.toolsplus.app/api/intercom/graphql",
        intercom_referrer=None,
        intercom_timeout=5.0,
    )


class JiraSkillTests(unittest.TestCase):
    def test_link_dry_run_resolves_live_type(self):
        requests = []

        def fake_urlopen(req, timeout=0):
            requests.append((req.get_method(), req.full_url, req.data))
            return FakeResponse(
                {
                    "issueLinkTypes": [
                        {"id": "10003", "name": "Relates", "inward": "relates to", "outward": "relates to"}
                    ]
                }
            )

        args = SimpleNamespace(
            inward_issue="PR-243",
            outward_issue="https://moego.atlassian.net/browse/GRM-1947",
            link_type="relates",
            execute=False,
            format="json",
        )
        stdout = io.StringIO()
        with patch("urllib.request.urlopen", side_effect=fake_urlopen), patch("sys.stdout", stdout):
            self.assertEqual(link.run(args, config()), 0)
        result = json.loads(stdout.getvalue())
        self.assertTrue(result["dry_run"])
        self.assertEqual(result["link_type"]["name"], "Relates")
        self.assertEqual(result["payload"]["inwardIssue"]["key"], "PR-243")
        self.assertEqual(result["payload"]["outwardIssue"]["key"], "GRM-1947")
        self.assertEqual(len(requests), 1)
        self.assertEqual(requests[0][0], "GET")

    def test_link_execute_posts_issue_link(self):
        requests = []

        def fake_urlopen(req, timeout=0):
            requests.append((req.get_method(), req.full_url, req.data))
            if req.get_method() == "GET":
                return FakeResponse(
                    {
                        "issueLinkTypes": [
                            {"id": "10003", "name": "Relates", "inward": "relates to", "outward": "relates to"}
                        ]
                    }
                )
            self.assertEqual(
                json.loads(req.data.decode("utf-8")),
                {
                    "type": {"name": "Relates"},
                    "inwardIssue": {"key": "PR-243"},
                    "outwardIssue": {"key": "GRM-1947"},
                },
            )
            return FakeResponse(b"", status=201, headers={"Content-Type": ""})

        args = SimpleNamespace(
            inward_issue="PR-243",
            outward_issue="GRM-1947",
            link_type="Relates",
            execute=True,
            format="json",
        )
        stdout = io.StringIO()
        with patch("urllib.request.urlopen", side_effect=fake_urlopen), patch("sys.stdout", stdout):
            self.assertEqual(link.run(args, config()), 0)
        result = json.loads(stdout.getvalue())
        self.assertFalse(result["dry_run"])
        self.assertEqual(requests[-1][0], "POST")
        self.assertTrue(requests[-1][1].endswith("/rest/api/3/issueLink"))

    def test_create_meta_returns_live_fields_and_allowed_values(self):
        def fake_urlopen(req, timeout=0):
            self.assertEqual(req.get_method(), "GET")
            self.assertIn("/issue/createmeta/PR/issuetypes/10889", req.full_url)
            return FakeResponse(
                {
                    "isLast": True,
                    "total": 1,
                    "values": [
                        {
                            "fieldId": "customfield_13901",
                            "name": "Rollout Type",
                            "required": False,
                            "schema": {"type": "option"},
                            "operations": ["set"],
                            "allowedValues": [{"id": "14685", "value": "Full Launch"}],
                        }
                    ],
                }
            )

        args = SimpleNamespace(project="PR", issue_type_id="10889", format="json")
        stdout = io.StringIO()
        with patch("urllib.request.urlopen", side_effect=fake_urlopen), patch("sys.stdout", stdout):
            self.assertEqual(create_meta.run(args, config()), 0)
        result = json.loads(stdout.getvalue())
        self.assertEqual(result["fields"][0]["name"], "Rollout Type")
        self.assertEqual(result["fields"][0]["allowed_values"][0]["value"], "Full Launch")

    def test_read_exposes_explicit_requested_fields(self):
        fields = {
            "summary": "Example",
            "duedate": "2026-08-14",
            "customfield_12242": {"id": "12817", "value": "M"},
            "unused": "hidden",
        }

        self.assertEqual(
            read._requested_fields(fields, "summary,duedate,customfield_12242"),
            {
                "summary": "Example",
                "duedate": "2026-08-14",
                "customfield_12242": "M",
            },
        )
        self.assertEqual(read._requested_fields(fields, "*all"), {})

    def test_parse_issue_key_accepts_url_and_slack_link(self):
        self.assertEqual(parse_issue_key("CS-45306"), "CS-45306")
        self.assertEqual(
            parse_issue_key("<https://moego.atlassian.net/browse/CS-45306|CS-45306>"),
            "CS-45306",
        )

    def test_intercom_helpers_extract_and_simplify_conversation(self):
        links = [
            {
                "url": "https://app.intercom.com/a/inbox/ws/inbox/conversation/215474005156281",
                "title": "Browse linked conversation",
                "relationship": "relates to",
            }
        ]
        linked = build_linked_conversations(texts=[], links=links)
        self.assertEqual(linked[0]["id"], "215474005156281")
        self.assertEqual(linked[0]["source"], "remote_link")
        self.assertEqual(html_to_text("<p>Hello&nbsp;world</p>"), "Hello\xa0world")

        simplified = simplify_conversation(
            {
                "id": "215474005156281",
                "state": "open",
                "created_at": 1777124208,
                "contacts": [{"role": "user", "id": "c1", "name": "Customer"}],
                "source": {
                    "id": "s1",
                    "body": "<p>Source body</p>",
                    "author": {"type": "user", "id": "u1", "author_name": "Alice"},
                    "attachments": [{"name": "a.png", "url": "https://example/a.png", "content_type": "image/png"}],
                },
                "conversation_parts": [
                    {
                        "id": "p1",
                        "part_type": "comment",
                        "body": "<p>Part body</p>",
                        "created_at": 1777124300,
                        "author": {"type": "admin", "id": "a1", "author_name": "Support"},
                    }
                ],
            }
        )
        self.assertEqual(simplified["source"]["body_text"], "Source body")
        self.assertEqual(simplified["conversation_parts"][0]["body_text"], "Part body")

    def test_create_and_update_payloads(self):
        fields = build_api_create_fields(
            project="CS",
            issue_type="Bug",
            summary="Payment failed",
            description="Line 1\nLine 2",
            components=["Payments"],
            labels=["cs"],
            parent=None,
            additional_fields={"customfield_10088": [{"value": "Bug"}]},
        )
        self.assertEqual(fields["project"], {"key": "CS"})
        self.assertEqual(fields["components"], [{"name": "Payments"}])
        self.assertEqual(fields["labels"], ["cs"])
        self.assertEqual(fields["customfield_10088"], [{"value": "Bug"}])

        update_fields = update._build_fields(
            '{"components":["Payments"],"labels":["cs"],"issueCause":"Bug","causeAndSolution":"Fixed"}'
        )
        self.assertEqual(update_fields["components"], [{"name": "Payments"}])
        self.assertEqual(update_fields["customfield_10088"], [{"value": "Bug"}])
        self.assertEqual(update_fields["customfield_10084"], "Fixed")

    def test_image_magic_detection(self):
        self.assertEqual(detect_supported_image_mimetype(b"\x89PNG\r\n\x1a\nabc"), "image/png")
        self.assertEqual(detect_supported_image_mimetype(b"GIF89aabc"), "image/gif")
        self.assertIsNone(detect_supported_image_mimetype(b"<html></html>"))

    def test_upload_attachment_dry_run_and_execute(self):
        png = b"\x89PNG\r\n\x1a\n" + b"image-body"
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as fh:
            fh.write(png)
            image_path = fh.name

        dry_args = SimpleNamespace(
            issue="GRM-1947", image=image_path, execute=False, format="json"
        )
        dry_stdout = io.StringIO()
        with patch("sys.stdout", dry_stdout):
            self.assertEqual(upload_attachment.run(dry_args, config()), 0)
        dry_result = json.loads(dry_stdout.getvalue())
        self.assertTrue(dry_result["dry_run"])
        self.assertEqual(dry_result["image"]["mime_type"], "image/png")

        captured = {}

        def fake_urlopen(req, timeout=0):
            captured["method"] = req.get_method()
            captured["url"] = req.full_url
            captured["headers"] = dict(req.header_items())
            captured["body"] = req.data
            return FakeResponse(
                [{"id": "10001", "filename": "test.png", "mimeType": "image/png"}]
            )

        execute_args = SimpleNamespace(
            issue="GRM-1947", image=image_path, execute=True, format="json"
        )
        execute_stdout = io.StringIO()
        with patch("urllib.request.urlopen", side_effect=fake_urlopen), patch(
            "sys.stdout", execute_stdout
        ):
            self.assertEqual(upload_attachment.run(execute_args, config()), 0)
        execute_result = json.loads(execute_stdout.getvalue())
        self.assertFalse(execute_result["dry_run"])
        self.assertEqual(execute_result["attachments"][0]["id"], "10001")
        self.assertEqual(captured["method"], "POST")
        self.assertTrue(captured["url"].endswith("/rest/api/3/issue/GRM-1947/attachments"))
        self.assertEqual(captured["headers"]["X-atlassian-token"], "no-check")
        self.assertIn(b'name="file"', captured["body"])
        self.assertIn(png, captured["body"])

    def test_upload_attachment_rejects_non_image(self):
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as fh:
            fh.write(b"not-an-image")
            image_path = Path(fh.name)
        from ji.errors import UsageError

        with self.assertRaises(UsageError):
            upload_attachment.inspect_image(image_path, max_bytes=1024)

    def test_read_cs_issue_fetches_intercom_graphql_details(self):
        requests = []

        def fake_urlopen(req, timeout=0):
            requests.append((req.get_method(), req.full_url, dict(req.header_items()), req.data))
            if "/rest/api/3/field" in req.full_url:
                return FakeResponse([])
            if "/rest/api/3/issue/CS-45306?" in req.full_url:
                return FakeResponse(
                    {
                        "id": "127184",
                        "key": "CS-45306",
                        "fields": {
                            "summary": "Need help",
                            "status": {"name": "Open"},
                            "project": {"key": "CS", "name": "CS"},
                            "issuetype": {"name": "Bug"},
                            "created": "2026-04-25T00:00:00.000+0000",
                            "updated": "2026-04-25T00:00:00.000+0000",
                            "attachment": [],
                            "issuelinks": [],
                            "description": {
                                "type": "doc",
                                "content": [{"type": "paragraph", "content": [{"type": "text", "text": "desc"}]}],
                            },
                        },
                    }
                )
            if "/rest/api/3/issue/CS-45306/comment?" in req.full_url:
                return FakeResponse({"comments": [], "total": 0, "isLast": True})
            if "/rest/api/3/issue/CS-45306/remotelink" in req.full_url:
                return FakeResponse(
                    [
                        {
                            "id": "rl1",
                            "relationship": "relates to",
                            "object": {
                                "title": "Browse linked conversation",
                                "url": "https://app.intercom.com/a/inbox/ws/inbox/conversation/215474005156281",
                            },
                        }
                    ]
                )
            if "intercom-for-jira-production.toolsplus.app/api/intercom/graphql" in req.full_url:
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
                                "source": {"id": "s1", "body": "<p>Customer issue</p>", "author": {"type": "user"}},
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
            comment_limit="50",
            download_images=False,
            image_output_dir=None,
            include_intercom="auto",
            fields="summary,status,project,issuetype,created,updated,description,attachment,issuelinks",
            format="json",
        )
        stdout = io.StringIO()
        with patch("urllib.request.urlopen", side_effect=fake_urlopen), patch("sys.stdout", stdout):
            self.assertEqual(read.run(args, config()), 0)

        result = json.loads(stdout.getvalue())
        linked = result["intercom"]["linked_conversations"]
        self.assertEqual(linked[0]["id"], "215474005156281")
        self.assertEqual(linked[0]["details"]["source"]["body_text"], "Customer issue")
        self.assertEqual(linked[0]["details"]["conversation_parts"][0]["body_text"], "Support reply")
        graph_request = [item for item in requests if "intercom-for-jira" in item[1]][0]
        self.assertTrue(graph_request[2]["Authorization"].startswith("JWT "))

    def _automation_args(self, **overrides):
        defaults = dict(
            mode="automation",
            project="GRM",
            issue_type="Task",
            summary="x",
            description="d",
            description_file=None,
            components=None,
            labels=None,
            assignee=None,
            parent="GRM-1729",
            objects_issue_id="128285",
            additional_fields=None,
            automation_object=None,
            automation_rule=RULE_URL,
            workspace_uuid=None,
            automation_body_file=None,
            execute=True,
            format="json",
        )
        defaults.update(overrides)
        return SimpleNamespace(**defaults)

    def test_create_automation_dry_run_builds_objects_and_userinputs(self):
        dry_args = self._automation_args(
            execute=False,
            summary="Payment failed",
            description="Customer reports payment failure",
            automation_object='{"userInputs":{"storyPoint":{"inputType":"NUMBER","value":3}}}',
        )
        stdout = io.StringIO()
        with patch("sys.stdout", stdout):
            self.assertEqual(create.run(dry_args, config()), 0)
        dry_result = json.loads(stdout.getvalue())
        self.assertTrue(dry_result["dry_run"])
        self.assertEqual(dry_result["mode"], "automation")
        self.assertEqual(
            dry_result["payload"]["objects"],
            ["ari:cloud:jira:00000000-0000-0000-0000-000000000000:issue/128285"],
        )
        ui = dry_result["payload"]["userInputs"]
        self.assertEqual(ui["summary"], {"inputType": "TEXT", "value": "Payment failed"})
        self.assertEqual(ui["description"]["value"], "Customer reports payment failure")
        # automation-object deep-merges into userInputs without clobbering summary/description.
        self.assertEqual(ui["storyPoint"], {"inputType": "NUMBER", "value": 3})
        self.assertEqual(dry_result["automation"]["objects_issue_id"], "128285")
        self.assertEqual(dry_result["automation"]["target"], RULE_URL)

    def test_create_api_mode_executes_against_rest_endpoint(self):
        def fake_urlopen(req, timeout=0):
            self.assertIn("/rest/api/3/issue", req.full_url)
            if req.get_method() == "POST":
                body = json.loads(req.data.decode("utf-8"))
                self.assertEqual(body["fields"]["project"], {"key": "ENG"})
                return FakeResponse({"key": "ENG-1", "id": "10001", "self": "https://example/rest/api/3/issue/10001"})
            self.assertEqual(req.get_method(), "GET")
            return FakeResponse(
                {
                    "key": "ENG-1",
                    "fields": {
                        "description": {
                            "type": "doc",
                            "version": 1,
                            "content": [
                                {
                                    "type": "paragraph",
                                    "content": [{"type": "text", "text": "Details"}],
                                }
                            ],
                        }
                    },
                }
            )

        execute_args = SimpleNamespace(
            mode="api",
            project="ENG",
            issue_type="Task",
            summary="Follow up",
            description="Details",
            description_file=None,
            components=None,
            labels=None,
            assignee=None,
            parent=None,
            objects_issue_id=None,
            additional_fields=None,
            automation_object=None,
            automation_rule=None,
            workspace_uuid=None,
            automation_body_file=None,
            execute=True,
            format="json",
        )
        stdout = io.StringIO()
        with patch("urllib.request.urlopen", side_effect=fake_urlopen), patch("sys.stdout", stdout):
            self.assertEqual(create.run(execute_args, config()), 0)
        execute_result = json.loads(stdout.getvalue())
        self.assertFalse(execute_result["dry_run"])
        self.assertEqual(execute_result["issue"]["key"], "ENG-1")

    def test_automation_requires_explicit_rule_url(self):
        from ji.errors import UsageError

        execute_args = self._automation_args(automation_rule=None, execute=False)
        with self.assertRaises(UsageError):
            create.run(execute_args, config())

    def test_automation_workspace_uuid_extracted_from_url(self):
        captured: dict = {}

        def fake_urlopen(req, timeout=0):
            captured["url"] = req.full_url
            captured["body"] = json.loads(req.data.decode("utf-8"))
            return FakeResponse({"invocations": [{"status": "SUCCESS"}]})

        execute_args = self._automation_args()
        stdout = io.StringIO()
        with patch("urllib.request.urlopen", side_effect=fake_urlopen), patch("sys.stdout", stdout):
            self.assertEqual(create.run(execute_args, config()), 0)
        # POSTed straight to the absolute URL the caller supplied.
        self.assertEqual(captured["url"], RULE_URL)
        # Workspace UUID auto-parsed from the URL path.
        self.assertEqual(
            captured["body"]["objects"],
            ["ari:cloud:jira:00000000-0000-0000-0000-000000000000:issue/128285"],
        )

    def test_automation_workspace_uuid_cli_override(self):
        captured: dict = {}

        def fake_urlopen(req, timeout=0):
            captured["body"] = json.loads(req.data.decode("utf-8"))
            return FakeResponse({"invocations": [{"status": "SUCCESS"}]})

        execute_args = self._automation_args(workspace_uuid="11111111-1111-1111-1111-111111111111")
        stdout = io.StringIO()
        with patch("urllib.request.urlopen", side_effect=fake_urlopen), patch("sys.stdout", stdout):
            self.assertEqual(create.run(execute_args, config()), 0)
        self.assertEqual(
            captured["body"]["objects"],
            ["ari:cloud:jira:11111111-1111-1111-1111-111111111111:issue/128285"],
        )

    def test_automation_workspace_uuid_unparseable_url_errors(self):
        from ji.errors import UsageError

        execute_args = self._automation_args(automation_rule="https://example.com/no-uuid-here")
        with self.assertRaises(UsageError):
            create.run(execute_args, config())

    def test_automation_relative_rule_path_resolves_against_base(self):
        captured: dict = {}

        def fake_urlopen(req, timeout=0):
            captured["url"] = req.full_url
            return FakeResponse({"invocations": [{"status": "SUCCESS"}]})

        rel = "gateway/api/automation/internal-api/jira/00000000-0000-0000-0000-000000000000/pro/rest/v1/rules/manual/invocation/abc"
        execute_args = self._automation_args(automation_rule=rel)
        stdout = io.StringIO()
        with patch("urllib.request.urlopen", side_effect=fake_urlopen), patch("sys.stdout", stdout):
            self.assertEqual(create.run(execute_args, config()), 0)
        self.assertEqual(captured["url"], f"https://moego.atlassian.net/{rel}")

    def test_automation_resolves_objects_id_from_parent_on_execute(self):
        calls: list[tuple[str, str]] = []

        def fake_urlopen(req, timeout=0):
            calls.append((req.get_method(), req.full_url))
            if "/rest/api/3/issue/GRM-1729" in req.full_url and req.get_method() == "GET":
                return FakeResponse({"id": "128285", "key": "GRM-1729"})
            return FakeResponse({"invocations": [{"status": "SUCCESS"}]})

        execute_args = self._automation_args(objects_issue_id=None)
        stdout = io.StringIO()
        with patch("urllib.request.urlopen", side_effect=fake_urlopen), patch("sys.stdout", stdout):
            self.assertEqual(create.run(execute_args, config()), 0)
        result = json.loads(stdout.getvalue())
        self.assertEqual(result["automation"]["objects_issue_id"], "128285")
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[0][0], "GET")

    def test_automation_body_file_full_override(self):
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as fh:
            fh.write(json.dumps({"objects": ["ari:custom"], "userInputs": {"k": {"inputType": "TEXT", "value": "v"}}}))
            body_path = fh.name

        captured: dict = {}

        def fake_urlopen(req, timeout=0):
            captured["body"] = json.loads(req.data.decode("utf-8"))
            return FakeResponse({"invocations": [{"status": "SUCCESS"}]})

        execute_args = self._automation_args(
            automation_body_file=body_path,
            objects_issue_id=None,
            parent=None,
            summary="ignored",
            description="ignored",
        )
        stdout = io.StringIO()
        with patch("urllib.request.urlopen", side_effect=fake_urlopen), patch("sys.stdout", stdout):
            self.assertEqual(create.run(execute_args, config()), 0)
        self.assertEqual(captured["body"]["objects"], ["ari:custom"])
        self.assertEqual(captured["body"]["userInputs"]["k"]["value"], "v")
        self.assertNotIn("summary", captured["body"]["userInputs"])

    def test_update_dry_run_and_execute(self):
        dry_args = SimpleNamespace(
            issue="CS-1",
            patch='{"components":["Payments"],"labels":["cs"],"issueCause":"Bug","causeAndSolution":"Fixed"}',
            execute=False,
            format="json",
        )
        stdout = io.StringIO()
        with patch("sys.stdout", stdout):
            self.assertEqual(update.run(dry_args, config()), 0)
        dry_result = json.loads(stdout.getvalue())
        self.assertTrue(dry_result["dry_run"])
        self.assertEqual(dry_result["payload"]["fields"]["components"], [{"name": "Payments"}])

        def fake_urlopen(req, timeout=0):
            self.assertEqual(req.get_method(), "PUT")
            self.assertIn("/rest/api/3/issue/CS-1", req.full_url)
            body = json.loads(req.data.decode("utf-8"))
            self.assertEqual(body["fields"]["labels"], ["cs"])
            return FakeResponse({"ok": True}, status=204)

        execute_args = SimpleNamespace(
            issue="CS-1",
            patch='{"labels":["cs"]}',
            execute=True,
            format="json",
        )
        stdout = io.StringIO()
        with patch("urllib.request.urlopen", side_effect=fake_urlopen), patch("sys.stdout", stdout):
            self.assertEqual(update.run(execute_args, config()), 0)
        execute_result = json.loads(stdout.getvalue())
        self.assertEqual(execute_result["response"]["ok"], True)

    def test_update_appends_description_link_without_replacing_existing_adf(self):
        existing = {
            "type": "doc",
            "version": 1,
            "content": [
                {"type": "paragraph", "content": [{"type": "text", "text": "PRD"}]},
                {"type": "mediaSingle", "content": [{"type": "media", "attrs": {"id": "media-1"}}]},
            ],
        }
        patch_value = {
            "descriptionAppendLinks": {
                "heading": "技术方案",
                "links": [{"text": "技术方案与估时（Approved V1）", "url": "https://example.com/tech"}],
            }
        }
        args = SimpleNamespace(issue="GRM-1", patch=json.dumps(patch_value), execute=True, format="json")

        with patch.object(JiraClient, "get_issue", return_value={"fields": {"description": existing}}), patch.object(
            JiraClient, "update_issue", return_value={"ok": True}
        ) as update_issue, patch("sys.stdout", io.StringIO()):
            self.assertEqual(update.run(args, config()), 0)

        updated = update_issue.call_args.args[1]["description"]
        self.assertEqual(updated["content"][:2], existing["content"])
        self.assertEqual(updated["content"][2]["type"], "heading")
        link = updated["content"][3]["content"][0]
        self.assertEqual(link["marks"][0]["attrs"]["href"], "https://example.com/tech")

    def test_update_description_link_append_is_idempotent(self):
        existing = {
            "type": "doc",
            "version": 1,
            "content": [
                {
                    "type": "paragraph",
                    "content": [
                        {
                            "type": "text",
                            "text": "技术方案与估时",
                            "marks": [{"type": "link", "attrs": {"href": "https://example.com/tech"}}],
                        }
                    ],
                }
            ],
        }
        patch_value = {
            "descriptionAppendLinks": {
                "links": [{"text": "技术方案与估时", "url": "https://example.com/tech"}]
            }
        }
        args = SimpleNamespace(issue="GRM-1", patch=json.dumps(patch_value), execute=True, format="json")

        stdout = io.StringIO()
        with patch.object(JiraClient, "get_issue", return_value={"fields": {"description": existing}}), patch.object(
            JiraClient, "update_issue"
        ) as update_issue, patch("sys.stdout", stdout):
            self.assertEqual(update.run(args, config()), 0)

        update_issue.assert_not_called()
        result = json.loads(stdout.getvalue())
        self.assertTrue(result["response"]["skipped"])
        self.assertEqual(result["description_append"]["skipped_existing"][0]["url"], "https://example.com/tech")

    def test_update_description_link_can_refresh_existing_label(self):
        existing = {
            "type": "doc",
            "version": 1,
            "content": [
                {
                    "type": "paragraph",
                    "content": [
                        {
                            "type": "text",
                            "text": "技术方案与估时（Approved V1）",
                            "marks": [{"type": "link", "attrs": {"href": "https://example.com/tech"}}],
                        }
                    ],
                }
            ],
        }
        config_value = {"heading": "技术方案", "links": [{"text": "技术方案与估时（Draft）", "url": "https://example.com/tech"}]}
        updated, result = update._append_description_links(existing, config_value)

        self.assertEqual(updated["content"][0]["content"][0]["text"], "技术方案与估时（Draft）")
        self.assertEqual(result["updated_existing"], config_value["links"])
        self.assertEqual(result["appended"], [])

    def test_update_description_link_can_move_section_to_top(self):
        link = {"text": "技术方案与估时", "url": "https://example.com/tech"}
        existing = {
            "type": "doc",
            "version": 1,
            "content": [
                {"type": "paragraph", "content": [{"type": "text", "text": "PRD"}]},
                {"type": "mediaSingle", "content": [{"type": "media", "attrs": {"id": "media-1"}}]},
                {"type": "heading", "attrs": {"level": 2}, "content": [{"type": "text", "text": "技术方案"}]},
                {
                    "type": "paragraph",
                    "content": [{"type": "text", "text": link["text"], "marks": [{"type": "link", "attrs": {"href": link["url"]}}]}],
                },
            ],
        }
        config_value = {"heading": "技术方案", "position": "top", "links": [link]}
        updated, result = update._append_description_links(existing, config_value)

        self.assertEqual(updated["content"][0]["type"], "heading")
        self.assertEqual(updated["content"][1]["content"][0]["marks"][0]["attrs"]["href"], link["url"])
        self.assertEqual(updated["content"][2:4], existing["content"][:2])
        self.assertEqual(result["moved_existing"], [link])
        self.assertTrue(result["changed"])

        second, second_result = update._append_description_links(updated, config_value)
        self.assertEqual(second, updated)
        self.assertFalse(second_result["changed"])
        self.assertEqual(second_result["skipped_existing"], [link])

    def test_update_description_link_can_move_into_blockquote_metadata(self):
        link = {"text": "技术方案与估时", "url": "https://example.com/tech"}
        existing = {
            "type": "doc",
            "version": 1,
            "content": [
                {"type": "heading", "attrs": {"level": 2}, "content": [{"type": "text", "text": "技术方案"}]},
                {"type": "paragraph", "content": [{"type": "text", "text": link["text"], "marks": [{"type": "link", "attrs": {"href": link["url"]}}]}]},
                {"type": "heading", "attrs": {"level": 1}, "content": [{"type": "text", "text": "PRD"}]},
                {"type": "blockquote", "content": [{"type": "paragraph", "content": [{"type": "text", "text": "Owner：Winches"}]}]},
                {"type": "mediaSingle", "content": [{"type": "media", "attrs": {"id": "media-1"}}]},
            ],
        }
        config_value = {"heading": "技术方案", "position": "metadata", "links": [link]}
        updated, result = update._append_description_links(existing, config_value)

        self.assertEqual(updated["content"][0]["attrs"]["level"], 1)
        self.assertEqual(updated["content"][1]["type"], "blockquote")
        inline = updated["content"][1]["content"][0]["content"]
        self.assertEqual(inline[-2]["text"], "技术方案：")
        self.assertEqual(inline[-1]["marks"][0]["attrs"]["href"], link["url"])
        self.assertEqual(updated["content"][2], existing["content"][4])
        self.assertEqual(result["moved_existing"], [link])

        second, second_result = update._append_description_links(updated, config_value)
        self.assertEqual(second, updated)
        self.assertFalse(second_result["changed"])

    def test_update_description_link_can_append_table_metadata_row(self):
        link = {"text": "技术方案与估时", "url": "https://example.com/tech"}
        existing = {
            "type": "doc",
            "version": 1,
            "content": [
                {"type": "heading", "attrs": {"level": 1}, "content": [{"type": "text", "text": "PRD"}]},
                {"type": "table", "content": []},
            ],
        }
        config_value = {"heading": "技术方案", "position": "metadata", "links": [link]}
        updated, result = update._append_description_links(existing, config_value)

        row = updated["content"][1]["content"][0]
        self.assertEqual(row["content"][0]["content"][0]["content"][0]["text"], "技术方案")
        link_text = row["content"][1]["content"][0]["content"][0]
        self.assertEqual(link_text["marks"][0]["attrs"]["href"], link["url"])
        self.assertTrue(result["changed"])

    def test_update_description_link_creates_metadata_after_title(self):
        link = {"text": "技术方案与估时", "url": "https://example.com/tech"}
        existing = {
            "type": "doc",
            "version": 1,
            "content": [
                {"type": "heading", "attrs": {"level": 1}, "content": [{"type": "text", "text": "PRD"}]},
                {"type": "heading", "attrs": {"level": 2}, "content": [{"type": "text", "text": "Background"}]},
            ],
        }
        config_value = {"heading": "技术方案", "position": "metadata", "links": [link]}
        updated, result = update._append_description_links(existing, config_value)

        self.assertEqual(updated["content"][1]["type"], "blockquote")
        self.assertEqual(updated["content"][1]["content"][0]["content"][0]["text"], "技术方案：")
        self.assertEqual(updated["content"][2], existing["content"][1])
        self.assertTrue(result["changed"])

    @staticmethod
    def _transition_payload():
        return {
            "transitions": [
                {
                    "id": "81",
                    "name": "Design Submitted",
                    "to": {"id": "10004", "name": "Design Submitted"},
                    "hasScreen": True,
                    "isAvailable": True,
                    "fields": {
                        "assignee": {
                            "name": "Assignee",
                            "required": True,
                            "hasDefaultValue": False,
                            "schema": {"type": "user", "system": "assignee"},
                            "operations": ["set"],
                        }
                    },
                },
                {
                    "id": "91",
                    "name": "Close",
                    "to": {"id": "6", "name": "Closed"},
                    "hasScreen": False,
                    "fields": {},
                },
            ]
        }

    def test_transition_lists_available_transitions(self):
        def fake_urlopen(req, timeout=0):
            self.assertEqual(req.get_method(), "GET")
            self.assertIn("/rest/api/3/issue/GRM-1947/transitions", req.full_url)
            self.assertIn("expand=transitions.fields", req.full_url)
            return FakeResponse(self._transition_payload())

        args = SimpleNamespace(
            issue="GRM-1947",
            transition_selector=None,
            fields="{}",
            execute=False,
            format="json",
        )
        stdout = io.StringIO()
        with patch("urllib.request.urlopen", side_effect=fake_urlopen), patch(
            "sys.stdout", stdout
        ):
            self.assertEqual(transition.run(args, config()), 0)
        result = json.loads(stdout.getvalue())
        self.assertEqual(result["mode"], "list")
        self.assertEqual(result["transitions"][0]["name"], "Design Submitted")
        self.assertEqual(result["transitions"][0]["fields"][0]["id"], "assignee")

    def test_transition_dry_run_reports_missing_required_fields(self):
        args = SimpleNamespace(
            issue="GRM-1947",
            transition_selector="design submitted",
            fields="{}",
            no_fill_current_required=True,
            execute=False,
            format="json",
        )
        stdout = io.StringIO()
        with patch.object(
            transition.JiraClient,
            "get_transitions",
            return_value=self._transition_payload()["transitions"],
        ), patch("sys.stdout", stdout):
            self.assertEqual(transition.run(args, config()), 0)
        result = json.loads(stdout.getvalue())
        self.assertTrue(result["dry_run"])
        self.assertEqual(result["payload"]["transition"]["id"], "81")
        self.assertEqual(result["missing_required_fields"], ["assignee"])

    def test_transition_reuses_current_required_fields(self):
        args = SimpleNamespace(
            issue="GRM-1947",
            transition_selector="Design Submitted",
            fields="{}",
            no_fill_current_required=False,
            execute=False,
            format="json",
        )
        stdout = io.StringIO()
        with patch.object(
            transition.JiraClient,
            "get_transitions",
            return_value=self._transition_payload()["transitions"],
        ), patch.object(
            transition.JiraClient,
            "get_issue",
            return_value={"fields": {"assignee": {"accountId": "syd-account-id", "displayName": "Syd"}}},
        ), patch("sys.stdout", stdout):
            self.assertEqual(transition.run(args, config()), 0)
        result = json.loads(stdout.getvalue())
        self.assertEqual(result["reused_current_fields"], ["assignee"])
        self.assertEqual(result["missing_required_fields"], [])
        self.assertEqual(
            result["payload"]["fields"]["assignee"], {"accountId": "syd-account-id"}
        )

    def test_transition_execute_posts_transition_and_fields(self):
        calls = []

        def fake_urlopen(req, timeout=0):
            calls.append((req.get_method(), req.full_url, req.data))
            if req.get_method() == "GET" and "/transitions" in req.full_url:
                return FakeResponse(self._transition_payload())
            if req.get_method() == "GET":
                return FakeResponse({"fields": {"status": {"name": "Design Submitted"}}})
            self.assertEqual(req.get_method(), "POST")
            body = json.loads(req.data.decode("utf-8"))
            self.assertEqual(body["transition"]["id"], "81")
            self.assertEqual(body["fields"]["assignee"]["accountId"], "syd-account-id")
            return FakeResponse(b"", status=204)

        args = SimpleNamespace(
            issue="GRM-1947",
            transition_selector="81",
            fields='{"assignee":{"accountId":"syd-account-id"}}',
            no_fill_current_required=False,
            execute=True,
            format="json",
        )
        stdout = io.StringIO()
        with patch("urllib.request.urlopen", side_effect=fake_urlopen), patch(
            "sys.stdout", stdout
        ):
            self.assertEqual(transition.run(args, config()), 0)
        result = json.loads(stdout.getvalue())
        self.assertFalse(result["dry_run"])
        self.assertEqual(result["response"]["status"], 204)
        self.assertTrue(result["verification"]["matched"])
        self.assertEqual([call[0] for call in calls], ["GET", "POST", "GET"])

    def test_transition_rejects_unknown_name_and_screen_field(self):
        transitions = self._transition_payload()["transitions"]
        from ji.errors import UsageError

        with self.assertRaisesRegex(UsageError, "transition not found"):
            transition._resolve_transition(transitions, "Not real")
        with self.assertRaisesRegex(UsageError, "not present"):
            transition._validate_fields(transitions[0], {"summary": "Nope"})

    def test_transition_supports_required_field_override(self):
        selected = self._transition_payload()["transitions"][0]
        selected["fields"]["duedate"] = {
            "name": "Due date",
            "required": False,
            "hasDefaultValue": False,
            "schema": {"type": "date", "system": "duedate"},
        }
        self.assertEqual(
            transition._validate_fields(selected, {"assignee": {"accountId": "syd"}}, {"duedate"}),
            ["duedate"],
        )

    def test_transition_waits_for_link_and_repairs_assignee(self):
        source_before = {
            "fields": {
                "status": {"name": "Open"},
                "assignee": {"accountId": "winches"},
                "issuelinks": [],
            }
        }
        source_after = {
            "fields": {
                "status": {"name": "Design Submitted"},
                "assignee": {"accountId": "winches"},
                "issuelinks": [],
            }
        }
        source_linked = {
            "fields": {
                "status": {"name": "Design Submitted"},
                "assignee": {"accountId": "winches"},
                "issuelinks": [{"outwardIssue": {"key": "DES-1041"}}],
            }
        }
        linked_unassigned = {"fields": {"assignee": None}}
        linked_assigned = {"fields": {"assignee": {"accountId": "syd"}}}
        args = SimpleNamespace(
            issue="GRM-1947",
            transition_selector="81",
            fields='{"assignee":{"accountId":"winches"}}',
            no_fill_current_required=False,
            required_fields="",
            wait_linked_project="DES",
            expected_source_assignee="winches",
            expected_linked_assignee="syd",
            repair_linked_assignee=True,
            wait_seconds=0,
            poll_seconds=0.1,
            execute=True,
            format="json",
        )
        stdout = io.StringIO()
        with patch.object(
            transition.JiraClient,
            "get_transitions",
            return_value=self._transition_payload()["transitions"],
        ), patch.object(
            transition.JiraClient,
            "transition_issue",
            return_value={"ok": True, "status": 204},
        ), patch.object(
            transition.JiraClient,
            "get_issue",
            side_effect=[source_before, source_after, source_linked, linked_unassigned, linked_assigned],
        ), patch.object(
            transition.JiraClient,
            "update_issue",
            return_value={"ok": True, "status": 204},
        ) as update_issue, patch("sys.stdout", stdout):
            self.assertEqual(transition.run(args, config()), 0)
        result = json.loads(stdout.getvalue())
        self.assertTrue(result["verification"]["all_matched"])
        self.assertEqual(result["verification"]["linked_issue"]["key"], "DES-1041")
        self.assertTrue(result["verification"]["linked_issue"]["assignee"]["repaired"])
        update_issue.assert_called_once_with("DES-1041", {"assignee": {"accountId": "syd"}})

    def test_download_attachment_success(self):
        media_id = "a8cb2001-55c2-4c1a-b083-81dc024a3b4a"

        class FakeAttachmentResponse:
            status = 200
            headers = {"Content-Type": "image/png", "Content-Length": "11"}

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def read(self, *_args):
                return b"\x89PNG\r\n\x1a\nabc"

            def geturl(self):
                return f"https://api.media.atlassian.com/file/{media_id}/binary?token=secret"

        class FakeOpener:
            def open(self, req, timeout=0):
                self.request = req
                return FakeAttachmentResponse()

        opener = FakeOpener()
        with tempfile.TemporaryDirectory() as tmpdir:
            args = SimpleNamespace(
                attachment_url="https://moego.atlassian.net/rest/api/3/attachment/content/12345/file.png",
                output_dir=tmpdir,
                max_bytes=100,
                format="json",
            )
            stdout = io.StringIO()
            with patch("urllib.request.build_opener", return_value=opener), patch("sys.stdout", stdout):
                self.assertEqual(download_attachment.run(args, config()), 0)
            result = json.loads(stdout.getvalue())
            self.assertTrue(result["ok"])
            self.assertEqual(result["mime_type"], "image/png")
            self.assertEqual(result["media_id"], media_id)
            self.assertTrue(Path(result["local_path"]).is_file())

    def test_media_id_from_url_rejects_numeric_attachment_id(self):
        self.assertIsNone(
            media_id_from_url("https://moego.atlassian.net/rest/api/3/attachment/content/104346")
        )

    def test_search_uses_post_search_jql(self):
        def fake_urlopen(req, timeout=0):
            self.assertEqual(req.get_method(), "POST")
            self.assertIn("/rest/api/3/search/jql", req.full_url)
            body = json.loads(req.data.decode("utf-8"))
            self.assertEqual(body["jql"], "project = CS")
            return FakeResponse(
                {
                    "issues": [
                        {
                            "key": "CS-1",
                            "fields": {
                                "summary": "One",
                                "status": {"name": "Open"},
                                "issuetype": {"name": "Feature Request"},
                                "components": [{"name": "Payments"}],
                                "issuelinks": [
                                    {
                                        "id": "10001",
                                        "type": {
                                            "name": "Defect",
                                            "inward": "is caused by",
                                            "outward": "created",
                                        },
                                        "outwardIssue": {
                                            "key": "DES-1090",
                                            "fields": {
                                                "issuetype": {"name": "Design Issue"},
                                                "status": {"name": "Open"},
                                            },
                                        },
                                    }
                                ],
                            },
                        }
                    ],
                    "isLast": True,
                }
            )

        args = SimpleNamespace(
            jql="project = CS",
            limit=10,
            fields="summary,status,components",
            page_token=None,
            format="json",
        )
        stdout = io.StringIO()
        with patch("urllib.request.urlopen", side_effect=fake_urlopen), patch("sys.stdout", stdout):
            self.assertEqual(search.run(args, config()), 0)
        issue = json.loads(stdout.getvalue())["issues"][0]
        self.assertEqual(issue["key"], "CS-1")
        self.assertEqual(issue["issue_type"], "Feature Request")
        self.assertEqual(issue["url"], "https://moego.atlassian.net/browse/CS-1")
        self.assertEqual(
            issue["links"],
            [
                {
                    "id": "10001",
                    "type": "Defect",
                    "direction": "outward",
                    "relationship": "created",
                    "key": "DES-1090",
                    "project_key": "DES",
                    "issue_type": "Design Issue",
                    "status": "Open",
                    "url": "https://moego.atlassian.net/browse/DES-1090",
                }
            ],
        )


if __name__ == "__main__":
    unittest.main()
