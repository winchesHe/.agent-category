from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))

from mfc.commands.collect import run as collect_run
from mfc.commands.publish import run as publish_run
from mfc.errors import AuthError, BusinessError
from mfc.jira import (
    JIRA_SEARCH_FIELDS,
    FixtureTransport,
    JiraCollector,
    JiraTransport,
    build_jql,
)

FIXTURE = Path(__file__).parent / "fixtures" / "jira.json"
GROOMING_SCOPE_FIXTURE = (
    Path(__file__).parent / "fixtures" / "jira_grooming_scope_week.json"
)
START = date(2026, 8, 17)
END = date(2026, 8, 23)


class StaticTransport:
    def __init__(self, pages):
        self.pages = list(pages)
        self.calls = []

    def search(self, jql, fields, page_token):
        self.calls.append((jql, fields, page_token))
        return self.pages.pop(0)


def issue(
    key,
    *,
    created="2026-08-20T08:00:00Z",
    issue_type="Feature Request",
    summary="Example",
    squad="Grooming",
    components=None,
):
    return {
        "key": key,
        "summary": summary,
        "issue_type": issue_type,
        "status": "Open",
        "squad": squad,
        "components": components or [],
        "created": created,
        "links": [],
    }


def envelope(issues, *, token=None, is_last=True, jql=None):
    return {
        "schema_version": 1,
        "command": "search",
        "ok": True,
        "jql": jql or build_jql(START, END, "Grooming"),
        "fields": list(JIRA_SEARCH_FIELDS),
        "count": len(issues),
        "total": len(issues),
        "is_last": is_last,
        "next_page_token": token,
        "issues": issues,
    }


class JiraCollectorTests(unittest.TestCase):
    def test_jql_uses_padded_window_without_squad_pre_filter(self):
        self.assertEqual(
            'project = CS AND created >= "2026-08-16" '
            'AND created < "2026-08-25" ORDER BY created DESC',
            build_jql(START, END, 'Gro"oming'),
        )

    def test_fixture_filters_exact_period_and_classifies_union(self):
        result = JiraCollector(FixtureTransport(FIXTURE)).collect(
            START, END, "Grooming"
        )

        self.assertEqual(5, result["observed"])
        self.assertEqual(4, result["inPeriod"])
        self.assertEqual(3, result["selected"])
        self.assertEqual(2, result["featureRequest"])
        self.assertEqual(2, result["designLinked"])
        by_key = {item["sourceObjectId"]: item for item in result["evidence"]}
        self.assertNotIn("CS-1004", by_key)
        self.assertNotIn("CS-1005", by_key)
        self.assertEqual(
            ["feature_request", "design_linked"],
            by_key["CS-1003"]["feedbackKinds"],
        )
        self.assertEqual("希望支持批量预约 [EMAIL]", by_key["CS-1001"]["title"])
        serialized = json.dumps(result, ensure_ascii=False)
        self.assertNotIn("customer@example.com", serialized)
        self.assertNotIn("description", serialized)
        self.assertNotIn("reporter", serialized)

    def test_grooming_scope_baseline_selects_eight_reviews_two_excludes_two(self):
        result = JiraCollector(FixtureTransport(GROOMING_SCOPE_FIXTURE)).collect(
            date(2026, 8, 24), date(2026, 8, 30), "Grooming"
        )

        self.assertEqual(12, result["feedbackCandidates"])
        self.assertEqual(8, result["selected"])
        self.assertEqual(2, result["manualReview"])
        self.assertEqual(2, result["excludedScope"])
        selected = {item["sourceObjectId"]: item for item in result["evidence"]}
        self.assertEqual(
            {
                "CS-50369",
                "CS-50431",
                "CS-50441",
                "CS-50460",
                "CS-50468",
                "CS-50476",
                "CS-50601",
                "CS-50602",
            },
            set(selected),
        )
        self.assertEqual("fulfillment", selected["CS-50460"]["businessCategory"])
        self.assertEqual(
            "van-staff-shift-management",
            selected["CS-50431"]["businessCategory"],
        )
        review = {
            item["sourceObjectId"]
            for item in result["reportRows"]
            if item["scopeDecision"] == "review"
        }
        excluded = {
            item["sourceObjectId"]: item["scopeReasons"]
            for item in result["reportRows"]
            if item["scopeDecision"] == "excluded"
        }
        self.assertEqual({"CS-50487", "CS-50598"}, review)
        self.assertEqual(
            {
                "CS-50520": ["non_grooming_service"],
                "CS-50603": ["non_grooming_service"],
            },
            excluded,
        )
        self.assertNotIn("CS-50520", selected)
        self.assertNotIn("CS-50603", selected)

    def test_business_classification_uses_whole_terms(self):
        result = JiraCollector(
            StaticTransport(
                [
                    envelope(
                        [
                            issue("CS-1", summary="Advance booking window"),
                            issue("CS-2", summary="Update booking context"),
                            issue("CS-3", summary="Update multiple appointments"),
                        ]
                    )
                ]
            )
        ).collect(START, END, "Grooming")

        categories = {
            item["sourceObjectId"]: item["businessCategory"]
            for item in result["evidence"]
        }
        self.assertEqual(
            {"CS-1": "scheduling", "CS-2": "scheduling", "CS-3": "scheduling"},
            categories,
        )

    def test_conflicting_strong_and_exclusion_signals_require_review(self):
        result = JiraCollector(
            StaticTransport(
                [envelope([issue("CS-1", summary="Daycare booking issue")])]
            )
        ).collect(START, END, "Grooming")

        self.assertEqual(0, result["selected"])
        self.assertEqual(1, result["manualReview"])
        self.assertEqual(0, result["excludedScope"])
        self.assertEqual("review", result["reportRows"][0]["scopeDecision"])
        self.assertEqual(
            ["squad_exact", "conflict:non_grooming_service"],
            result["reportRows"][0]["scopeReasons"],
        )

    def test_collector_consumes_all_pages_and_rejects_duplicates(self):
        jql = build_jql(START, END, "Grooming")
        transport = StaticTransport(
            [
                envelope([issue("CS-1")], token="next-1", is_last=False, jql=jql),
                envelope([issue("CS-2")], jql=jql),
            ]
        )
        result = JiraCollector(transport).collect(START, END, "Grooming")

        self.assertEqual(2, result["selected"])
        self.assertEqual([None, "next-1"], [call[2] for call in transport.calls])

        duplicate = StaticTransport(
            [
                envelope([issue("CS-1")], token="next-1", is_last=False, jql=jql),
                envelope([issue("CS-1")], jql=jql),
            ]
        )
        with self.assertRaisesRegex(BusinessError, "重复工单"):
            JiraCollector(duplicate).collect(START, END, "Grooming")

    def test_incomplete_paging_and_wrong_contract_fail(self):
        with self.assertRaisesRegex(BusinessError, "分页未完成"):
            JiraCollector(
                StaticTransport([envelope([issue("CS-1")], is_last=False)])
            ).collect(START, END, "Grooming")

        wrong = envelope([issue("CS-1")])
        wrong["fields"] = ["summary"]
        with self.assertRaisesRegex(BusinessError, "合同不匹配"):
            JiraCollector(StaticTransport([wrong])).collect(START, END, "Grooming")

    def test_des_link_without_issue_type_fails_closed(self):
        value = issue("CS-1", issue_type="Bug Report")
        value["links"] = [{"key": "DES-1", "project_key": "DES"}]
        with self.assertRaisesRegex(BusinessError, "缺少 issue type"):
            JiraCollector(StaticTransport([envelope([value])])).collect(
                START, END, "Grooming"
            )

    def test_transport_maps_auth_error_without_leaking_stderr(self):
        config = SimpleNamespace(
            jira_script=Path("/tmp/jira/scripts/jira.py"),
            timeout=60,
        )
        completed = SimpleNamespace(returncode=3, stdout="", stderr="secret")
        with patch("mfc.jira.subprocess.run", return_value=completed):
            with self.assertRaisesRegex(AuthError, "鉴权或权限不足"):
                JiraTransport(config).search("project = CS", JIRA_SEARCH_FIELDS, None)

    def test_offline_collect_writes_squad_bound_run_without_checkpoint(self):
        with tempfile.TemporaryDirectory() as directory:
            config = SimpleNamespace(output_root=Path(directory), squad="Grooming")
            args = SimpleNamespace(
                source="jira",
                mode="period",
                sink="local",
                account_ref="",
                headed=False,
                fixture=str(FIXTURE),
                period_start="2026-08-17",
                period_end="2026-08-23",
            )

            result = collect_run(args, config)

            self.assertEqual(3, result["counts"]["selected"])
            self.assertEqual("Grooming", result["squad"])
            self.assertFalse((Path(directory) / "state" / "jira.json").exists())
            manifest = json.loads(Path(result["manifest"]).read_text(encoding="utf-8"))
            self.assertEqual("Grooming", manifest["squad"])
            self.assertEqual("jira-grooming-journey-v2", manifest["selectionRule"])
            run = json.loads(Path(manifest["runArtifact"]).read_text(encoding="utf-8"))
            self.assertEqual([], run["reportRows"])

    def test_scope_baseline_renders_review_counts_and_business_categories(self):
        with tempfile.TemporaryDirectory() as directory:
            config = SimpleNamespace(output_root=Path(directory), squad="Grooming")
            collect_args = SimpleNamespace(
                source="jira",
                mode="period",
                sink="local",
                account_ref="",
                headed=False,
                fixture=str(GROOMING_SCOPE_FIXTURE),
                period_start="2026-08-24",
                period_end="2026-08-30",
            )
            collected = collect_run(collect_args, config)
            publish_args = SimpleNamespace(
                source="jira",
                manifest=collected["manifest"],
                quick_win_review="",
                period_start="",
                period_end="",
                dry_run=True,
            )

            preview = publish_run(publish_args, config)

        self.assertEqual(8, preview["counts"]["selectedRows"])
        self.assertEqual(2, preview["counts"]["manualReview"])
        self.assertEqual(2, preview["counts"]["excludedScope"])
        self.assertIn("待人工复核", preview["content"])
        self.assertIn("CS-50487", preview["content"])
        self.assertIn("范围排除审计", preview["content"])
        self.assertIn("CS-50520", preview["content"])
        self.assertIn("non_grooming_service", preview["content"])
        self.assertIn("van-staff-shift-management", preview["content"])


if __name__ == "__main__":
    unittest.main()
