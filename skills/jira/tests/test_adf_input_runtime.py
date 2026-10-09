from __future__ import annotations

import copy
import io
import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
FIXTURES = ROOT / "tests" / "fixtures" / "adf-input-v1"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import jira
from ji.adf_input import (
    adf_semantically_equal,
    ensure_no_markdown_residual,
    markdown_to_adf_v1,
    parse_adf_json,
    validate_adf_document,
    validate_safe_url,
)
from ji.commands import create
from ji.config import Config
from ji.errors import JiraCliError


def config() -> Config:
    return Config(
        jira_base_url="https://moego.atlassian.net",
        jira_login="agent@example.com",
        jira_token="jira-token",
        jira_timeout=5.0,
        max_attachment_bytes=1024 * 1024,
        intercom_jwt=None,
        intercom_jwt_command=None,
        intercom_graphql_url="https://intercom.example.com/graphql",
        intercom_referrer=None,
        intercom_timeout=5.0,
    )


def base_args(**overrides):
    values = {
        "mode": "api",
        "project": "CS",
        "issue_type": "Task",
        "summary": "ADF contract",
        "description": "",
        "description_file": None,
        "description_adf_file": None,
        "components": None,
        "labels": None,
        "assignee": None,
        "parent": None,
        "additional_fields": None,
        "automation_object": None,
        "automation_rule": None,
        "workspace_uuid": None,
        "automation_body_file": None,
        "objects_issue_id": None,
        "execute": False,
        "confirm": None,
        "confirmed_current": None,
        "format": "json",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


class FakeCreateClient:
    def __init__(self, _config):
        self.created_fields = None

    def get_project(self, project):
        return {"id": "100", "key": project, "name": "Customer Support"}

    def list_issue_types(self, project_id=None):
        return [{"id": "10001", "name": "Task", "subtask": False}]

    def get_create_fields(self, project, issue_type_id):
        return [
            {
                "fieldId": "summary",
                "required": True,
                "schema": {"type": "string"},
                "operations": ["set"],
            },
            {
                "fieldId": "description",
                "required": False,
                "schema": {"type": "string"},
                "operations": ["set"],
            },
        ]

    def create_issue_api(self, fields):
        self.created_fields = copy.deepcopy(fields)
        return {"key": "CS-900", "id": "900"}

    def get_issue(self, key, *, fields, expand):
        description = copy.deepcopy((self.created_fields or {}).get("description"))
        if isinstance(description, dict) and description.get("content"):
            attrs = description["content"][0].setdefault("attrs", {})
            attrs["localId"] = "jira-generated"
        return {
            "key": key,
            "fields": {
                "summary": (self.created_fields or {}).get("summary"),
                "project": {"key": "CS"},
                "issuetype": {"id": "10001", "name": "Task"},
                "description": description,
            },
        }


class FakeMismatchedCreateClient(FakeCreateClient):
    def get_issue(self, key, *, fields, expand):
        issue = super().get_issue(key, fields=fields, expand=expand)
        issue["fields"]["description"]["content"][0]["type"] = "paragraph"
        return issue


class JiraAdfInputRuntimeTests(unittest.TestCase):
    def assert_error_code(self, expected: str, invoke):
        with self.assertRaises(JiraCliError) as raised:
            invoke()
        self.assertEqual(raised.exception.error_code, expected)
        self.assertEqual(raised.exception.operation_state, "not_started")
        return raised.exception

    def test_supported_markdown_matches_golden_adf(self):
        markdown = (FIXTURES / "supported.md").read_text(encoding="utf-8")
        expected = json.loads((FIXTURES / "supported.adf.json").read_text(encoding="utf-8"))
        result = markdown_to_adf_v1(markdown)
        self.assertEqual(result.adf, expected)
        ensure_no_markdown_residual(result, expected)

    def test_opc_lightweight_prd_is_accepted_with_expected_structure(self):
        markdown = (FIXTURES / "opc-lightweight-prd.md").read_text(encoding="utf-8")
        adf = markdown_to_adf_v1(markdown).adf

        def walk(node):
            if isinstance(node, dict):
                yield node
                for child in node.get("content", []):
                    yield from walk(child)

        nodes = list(walk(adf))
        counts = {}
        for node in nodes:
            counts[node["type"]] = counts.get(node["type"], 0) + 1
        heading_levels = {}
        for node in nodes:
            if node["type"] == "heading":
                level = str(node["attrs"]["level"])
                heading_levels[level] = heading_levels.get(level, 0) + 1
        self.assertEqual(heading_levels, {"1": 1, "2": 7, "3": 2})
        self.assertEqual(counts["blockquote"], 2)
        self.assertEqual(counts["bulletList"], 7)
        self.assertEqual(counts["listItem"], 19)
        self.assertEqual(counts["table"], 1)

    def test_plain_text_placeholders_and_nonsequential_ordered_list_are_supported(self):
        result = markdown_to_adf_v1(
            "<需求名称> [Resource Context]\n\n3. first\n9. second"
        ).adf
        self.assertEqual(result["content"][0]["content"][0]["text"], "<需求名称> [Resource Context]")
        ordered = result["content"][1]
        self.assertEqual(ordered["attrs"]["order"], 3)
        self.assertEqual(len(ordered["content"]), 2)

    def test_nested_inline_marks_are_structural_and_code_combination_is_rejected(self):
        adf = markdown_to_adf_v1("**粗 *斜体* 粗**").adf
        marked = adf["content"][0]["content"][1]
        self.assertEqual({mark["type"] for mark in marked["marks"]}, {"strong", "em"})
        self.assert_error_code(
            "markdown_unsupported",
            lambda: markdown_to_adf_v1("**`code`**"),
        )

    def test_unsupported_markdown_fails_closed(self):
        cases = {
            "task_list": "- [ ] todo",
            "nested_list": "- parent\n  - child",
            "ordered_task_list": "1. [x] done",
            "definition_list": "Term\n: definition",
            "image": "![alt](https://example.com/image.png)",
            "reference_link": "[label][ref]",
            "reference_link_with_space": "[label] [ref]",
            "autolink": "<https://example.com>",
            "footnote": "[^note]",
            "raw_html": "<details>text</details>",
            "mdx": "{component}",
            "emoji_shortcode": ":smile:",
            "jira_wiki_markup": "{panel}",
            "aligned_table": "| A |\n|:---|\n| B |",
            "malformed_table": "| A | B |\n|---|\n| C |",
            "unclosed_mark": "**bold",
            "unclosed_code": "`code",
            "unclosed_fence": "```python\nprint(1)",
            "unsupported_tilde_fence": "~~~python\nprint(1)\n~~~",
            "blockquote_table": "> | A |\n> |---|",
        }
        for name, markdown in cases.items():
            with self.subTest(name=name):
                self.assert_error_code(
                    "markdown_unsupported",
                    lambda markdown=markdown: markdown_to_adf_v1(markdown),
                )

    def test_sensitive_links_fail_without_echoing_url(self):
        unsafe = [
            "javascript:alert",
            "data:text/plain,secret",
            "https://user:password@example.com/file",
            "https://example.com/file?token=secret-value",
            "https://example.com/%0Aheader",
        ]
        for url in unsafe:
            with self.subTest(url=url):
                error = self.assert_error_code("unsafe_link", lambda url=url: validate_safe_url(url))
                self.assertNotIn("secret-value", error.message)
                self.assertNotIn("password", json.dumps(error.details))
        validate_safe_url("https://example.com/docs?q=adf")
        validate_safe_url("mailto:owner@example.com")

    def test_adf_validation_and_forward_compatibility_fixtures(self):
        valid = json.loads((FIXTURES / "valid-rich.adf.json").read_text(encoding="utf-8"))
        unknown = json.loads(
            (FIXTURES / "structurally-valid-unknown.adf.json").read_text(encoding="utf-8")
        )
        self.assertIs(validate_adf_document(valid), valid)
        self.assertIs(validate_adf_document(unknown), unknown)
        self.assert_error_code(
            "adf_invalid",
            lambda: validate_adf_document(
                json.loads((FIXTURES / "invalid-adf-root.json").read_text(encoding="utf-8"))
            ),
        )
        self.assert_error_code(
            "adf_invalid",
            lambda: parse_adf_json((FIXTURES / "malformed-adf.txt").read_text(encoding="utf-8")),
        )
        self.assert_error_code(
            "adf_invalid",
            lambda: parse_adf_json('{"type":"doc","type":"doc","version":1,"content":[]}'),
        )
        self.assert_error_code(
            "adf_invalid",
            lambda: parse_adf_json('{"type":"doc","version":NaN,"content":[]}'),
        )
        self.assert_error_code(
            "adf_invalid",
            lambda: validate_adf_document({"type": "doc", "version": True, "content": []}),
        )
        self.assert_error_code(
            "adf_invalid",
            lambda: validate_adf_document({"type": "doc", "version": 1, "content": ["text"]}),
        )
        self.assert_error_code(
            "adf_invalid",
            lambda: validate_adf_document(
                {
                    "type": "doc",
                    "version": 1,
                    "content": [
                        {
                            "type": "paragraph",
                            "content": [{"type": "text", "text": "x", "marks": [{"type": ""}]}],
                        }
                    ],
                }
            ),
        )
        self.assert_error_code(
            "unsafe_link",
            lambda: validate_adf_document(
                {
                    "type": "doc",
                    "version": 1,
                    "content": [
                        {
                            "type": "futureNode",
                            "attrs": {"url": "javascript:alert(1)"},
                        }
                    ],
                }
            ),
        )
        self.assert_error_code(
            "unsafe_link",
            lambda: validate_adf_document(
                json.loads((FIXTURES / "unsafe-link.adf.json").read_text(encoding="utf-8"))
            ),
        )

    def test_large_adf_has_no_local_size_limit(self):
        document = {
            "type": "doc",
            "version": 1,
            "content": [
                {
                    "type": "paragraph",
                    "content": [{"type": "text", "text": "x" * (1024 * 1024 + 1)}],
                }
            ],
        }
        raw = json.dumps(document, ensure_ascii=False, separators=(",", ":"))
        self.assertGreater(len(raw.encode("utf-8")), 1024 * 1024)
        self.assertEqual(parse_adf_json(raw), document)

    def test_residual_guard_rejects_literalized_heading(self):
        source = (FIXTURES / "residual-source.md").read_text(encoding="utf-8")
        candidate = json.loads(
            (FIXTURES / "residual-output.adf.json").read_text(encoding="utf-8")
        )
        parsed = markdown_to_adf_v1(source)
        self.assert_error_code(
            "markdown_residual",
            lambda: ensure_no_markdown_residual(parsed, candidate),
        )

    def test_semantic_projection_ignores_jira_local_ids_but_not_structure(self):
        expected = markdown_to_adf_v1("# Heading").adf
        actual = copy.deepcopy(expected)
        actual["content"][0]["attrs"]["localId"] = "jira-generated"
        self.assertTrue(adf_semantically_equal(expected, actual))
        actual["content"][0]["localId"] = "caller-owned"
        self.assertFalse(adf_semantically_equal(expected, actual))
        del actual["content"][0]["localId"]
        actual["content"][0]["type"] = "paragraph"
        self.assertFalse(adf_semantically_equal(expected, actual))

    def test_create_markdown_dry_run_reports_profile_and_native_adf(self):
        stdout = io.StringIO()
        args = base_args(description="# 标题")
        with patch("ji.commands.create.JiraClient", FakeCreateClient), patch("sys.stdout", stdout):
            self.assertEqual(create.run(args, config()), 0)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["description_input_format"], "markdown")
        self.assertEqual(payload["markdown_profile"], "jira-md-v1")
        self.assertEqual(
            payload["payload"]["fields"]["description"]["content"][0]["type"],
            "heading",
        )

    def test_automation_markdown_remains_plain_paragraph_transport(self):
        stdout = io.StringIO()
        args = base_args(
            mode="automation",
            description="# 标题",
            automation_rule=(
                "https://moego.atlassian.net/gateway/api/automation/internal-api/jira/"
                "00000000-0000-0000-0000-000000000000/pro/rest/v1/rules/manual/"
                "invocation/ffffffff-ffff-ffff-ffff-ffffffffffff"
            ),
        )
        with patch("sys.stdout", stdout):
            self.assertEqual(create.run(args, config()), 0)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["description_input_format"], "markdown")
        self.assertEqual(payload["description_transport"], "paragraph-string")
        self.assertEqual(
            payload["payload"]["userInputs"]["description"]["value"],
            "# 标题",
        )

    def test_create_adf_file_and_legacy_path_are_preserved(self):
        expected = json.loads((FIXTURES / "valid-rich.adf.json").read_text(encoding="utf-8"))
        cases = (
            base_args(description_adf_file=str(FIXTURES / "valid-rich.adf.json")),
            base_args(additional_fields=json.dumps({"description": expected}, ensure_ascii=False)),
        )
        for args in cases:
            with self.subTest(args=args):
                stdout = io.StringIO()
                with patch("ji.commands.create.JiraClient", FakeCreateClient), patch(
                    "sys.stdout", stdout
                ):
                    self.assertEqual(create.run(args, config()), 0)
                payload = json.loads(stdout.getvalue())
                self.assertEqual(payload["description_input_format"], "adf")
                self.assertEqual(payload["payload"]["fields"]["description"], expected)

    def test_create_description_inputs_are_explicit_and_transport_safe(self):
        expected = json.loads((FIXTURES / "valid-rich.adf.json").read_text(encoding="utf-8"))
        self.assert_error_code(
            "invalid_usage",
            lambda: create.run(
                base_args(
                    description="text",
                    additional_fields=json.dumps({"description": expected}),
                ),
                config(),
            ),
        )
        self.assert_error_code(
            "adf_unsupported_transport",
            lambda: create.run(
                base_args(
                    mode="automation",
                    description_adf_file=str(FIXTURES / "valid-rich.adf.json"),
                ),
                config(),
            ),
        )
        stdout = io.StringIO()
        adf_looking_markdown = '{"type":"doc","version":1,"content":[]}'
        with patch("ji.commands.create.JiraClient", FakeCreateClient), patch("sys.stdout", stdout):
            self.assertEqual(create.run(base_args(description=adf_looking_markdown), config()), 0)
        description = json.loads(stdout.getvalue())["payload"]["fields"]["description"]
        self.assertEqual(description["content"][0]["type"], "paragraph")
        self.assertEqual(description["content"][0]["content"][0]["text"], adf_looking_markdown)

    def test_cli_parser_enforces_explicit_description_input(self):
        parser = jira._build_parser()
        with patch("sys.stderr", io.StringIO()):
            with self.assertRaises(SystemExit):
                parser.parse_args(
                    [
                        "create",
                        "--mode",
                        "api",
                        "--project",
                        "CS",
                        "--issue-type",
                        "Task",
                        "--summary",
                        "ADF",
                        "--description",
                        "text",
                        "--description-adf-file",
                        "description.json",
                    ]
                )

    def test_unsafe_markdown_fixture_is_rejected(self):
        markdown = (FIXTURES / "unsafe-link.md").read_text(encoding="utf-8")
        self.assert_error_code("unsafe_link", lambda: markdown_to_adf_v1(markdown))

    def test_cli_surfaces_stable_adf_error_code(self):
        stdout = io.StringIO()
        stderr = io.StringIO()
        with patch("jira.load_config", return_value=config()), patch(
            "sys.stdout", stdout
        ), patch("sys.stderr", stderr):
            exit_code = jira.main(
                [
                    "create",
                    "--mode",
                    "api",
                    "--project",
                    "CS",
                    "--issue-type",
                    "Task",
                    "--summary",
                    "ADF",
                    "--description-adf-file",
                    str(FIXTURES / "malformed-adf.txt"),
                ]
            )
        self.assertEqual(exit_code, 4)
        self.assertEqual(stdout.getvalue(), "")
        self.assertIn("[jira] adf_invalid:", stderr.getvalue())

    def test_execute_readback_verifies_description_semantics(self):
        execute_stdout = io.StringIO()
        with patch("ji.commands.create.JiraClient", FakeCreateClient), patch(
            "sys.stdout", execute_stdout
        ):
            self.assertEqual(
                create.run(
                    base_args(
                        description="# Heading",
                        execute=True,
                    ),
                    config(),
                ),
                0,
            )
        payload = json.loads(execute_stdout.getvalue())
        self.assertEqual(payload["verification"]["status"], "verified")
        self.assertTrue(
            payload["verification"]["description_semantically_matched"]
        )

    def test_execute_readback_mismatch_is_reported_as_completed_write(self):
        with patch("ji.commands.create.JiraClient", FakeMismatchedCreateClient):
            with self.assertRaises(JiraCliError) as raised:
                create.run(
                    base_args(description="# Heading", execute=True),
                    config(),
                )
        error = raised.exception
        self.assertEqual(error.error_code, "adf_postcondition_failed")
        self.assertEqual(error.operation_state, "completed")


if __name__ == "__main__":
    unittest.main()
