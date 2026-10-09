from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))

from mfc.commands.publish import run as publish_run
from mfc.errors import BusinessError, ConfigError


class IntercomPublishTests(unittest.TestCase):
    def _artifacts(self, directory, *, mode="period"):
        root = Path(directory)
        run_path = root / "run.json"
        manifest_path = root / "manifest.json"
        evidence = [
            {
                "objectType": "feedback",
                "sourceObjectId": "feedback",
                "createdAt": "2026-08-20T08:00:00Z",
                "requirement": "现有日历筛选不够清晰",
                "domain": "Grooming Calendar",
                "feedbackType": "feature_feedback",
                "sentiment": "negative",
                "squad": "Grooming",
                "businessType": "Grooming",
                "role": "Owner",
                "stripePlan": "Growth",
            },
            {
                "objectType": "feedback",
                "sourceObjectId": "request",
                "createdAt": "2026-08-21T08:00:00Z",
                "requirement": "希望支持批量预约",
                "domain": "Appointment",
                "feedbackType": "feature_request",
                "sentiment": "neutral",
                "squad": "grooming",
                "businessType": "Grooming",
                "role": "Manager",
                "stripePlan": "Ultimate",
            },
            {
                "objectType": "feedback",
                "sourceObjectId": "bug",
                "createdAt": "2026-08-22T08:00:00Z",
                "requirement": "保存失败",
                "domain": "Appointment",
                "feedbackType": "bug",
                "squad": "Grooming",
            },
            {
                "objectType": "feedback",
                "sourceObjectId": "boarding",
                "createdAt": "2026-08-22T08:00:00Z",
                "requirement": "Boarding 需求",
                "domain": "Boarding",
                "feedbackType": "feature_request",
                "squad": "Boarding",
            },
        ]
        run_manifest = {
            "schemaVersion": 1,
            "collectorVersion": "0.2.0",
            "runId": f"intercom-test-{mode}",
            "sourceKey": "intercom",
            "mode": mode,
            "status": "succeeded",
            "startedAt": "2026-08-24T00:00:00Z",
            "finishedAt": "2026-08-24T00:01:00Z",
            "fetchedCount": len(evidence),
            "baseline": False,
            "baselineCount": 0,
            "newCount": len(evidence),
            "changedCount": 0,
            "period": {"start": "2026-08-17", "end": "2026-08-23"},
            "transport": "fixture",
            "privacyPolicy": "intercom-safe-v1",
        }
        run_path.write_text(
            json.dumps(
                {
                    "manifest": run_manifest,
                    "evidence": evidence,
                    "reportRows": [],
                }
            ),
            encoding="utf-8",
        )
        manifest_path.write_text(
            json.dumps(
                {
                    **run_manifest,
                    "runArtifact": str(run_path),
                }
            ),
            encoding="utf-8",
        )
        return manifest_path

    @staticmethod
    def _args(manifest):
        return SimpleNamespace(
            source="intercom",
            manifest=str(manifest),
            quick_win_review="",
            period_start="",
            period_end="",
            dry_run=True,
        )

    def test_dry_run_uses_manifest_period_and_reports_filter_counts(self):
        with tempfile.TemporaryDirectory() as directory:
            manifest = self._artifacts(directory)

            result = publish_run(
                self._args(manifest), SimpleNamespace(squad="Grooming")
            )

        self.assertTrue(result["dryRun"])
        self.assertEqual({"start": "2026-08-17", "end": "2026-08-23"}, result["period"])
        self.assertEqual("Grooming", result["filter"]["squad"])
        self.assertEqual(4, result["counts"]["inputRows"])
        self.assertEqual(3, result["counts"]["squadRows"])
        self.assertEqual(2, result["counts"]["selectedRows"])
        self.assertEqual(1, result["counts"]["featureFeedback"])
        self.assertEqual(1, result["counts"]["featureRequest"])
        self.assertIn("Intercom 用户反馈｜Grooming", result["title"])
        self.assertIn("现有日历筛选不够清晰", result["content"])
        self.assertIn("希望支持批量预约", result["content"])
        self.assertNotIn("保存失败", result["content"])
        self.assertNotIn("Boarding 需求", result["content"])

    def test_same_period_uses_distinct_titles_for_each_squad(self):
        with tempfile.TemporaryDirectory() as directory:
            manifest = self._artifacts(directory)

            grooming = publish_run(
                self._args(manifest), SimpleNamespace(squad="Grooming")
            )
            boarding = publish_run(
                self._args(manifest), SimpleNamespace(squad="Boarding")
            )

        self.assertNotEqual(grooming["title"], boarding["title"])
        self.assertTrue(grooming["title"].endswith("Intercom 用户反馈｜Grooming"))
        self.assertTrue(boarding["title"].endswith("Intercom 用户反馈｜Boarding"))
        self.assertEqual(2, grooming["counts"]["selectedRows"])
        self.assertEqual(1, boarding["counts"]["selectedRows"])

    def test_missing_squad_and_probe_manifest_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            manifest = self._artifacts(directory)
            with self.assertRaisesRegex(ConfigError, "MFC_SQUAD"):
                publish_run(self._args(manifest), SimpleNamespace(squad=""))

            probe_manifest = self._artifacts(directory, mode="probe")
            with self.assertRaisesRegex(BusinessError, "period 模式"):
                publish_run(
                    self._args(probe_manifest),
                    SimpleNamespace(squad="Grooming"),
                )

    def test_manifest_must_match_embedded_run_contract(self):
        with tempfile.TemporaryDirectory() as directory:
            manifest = self._artifacts(directory)
            payload = json.loads(manifest.read_text(encoding="utf-8"))
            payload["fetchedCount"] = 999
            manifest.write_text(json.dumps(payload), encoding="utf-8")

            with self.assertRaisesRegex(BusinessError, "采集结果不一致"):
                publish_run(
                    self._args(manifest),
                    SimpleNamespace(squad="Grooming"),
                )

    def test_fetched_count_must_match_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            manifest = self._artifacts(directory)
            outer = json.loads(manifest.read_text(encoding="utf-8"))
            run_path = Path(outer["runArtifact"])
            run = json.loads(run_path.read_text(encoding="utf-8"))
            run["evidence"].pop()
            run_path.write_text(json.dumps(run), encoding="utf-8")

            with self.assertRaisesRegex(BusinessError, "数量与 manifest 不一致"):
                publish_run(
                    self._args(manifest),
                    SimpleNamespace(squad="Grooming"),
                )


class JiraPublishTests(unittest.TestCase):
    def _artifacts(self, directory):
        root = Path(directory)
        run_path = root / "jira-run.json"
        manifest_path = root / "jira-manifest.json"
        evidence = [
            {
                "objectType": "feedback",
                "sourceKey": "jira",
                "sourceObjectId": "CS-1001",
                "sourceUrl": "https://moego.atlassian.net/browse/CS-1001",
                "createdAt": "2026-08-20T08:00:00Z",
                "title": "希望支持批量预约",
                "squad": "Grooming",
                "components": ["Appointment(Grooming)"],
                "issueType": "Feature Request",
                "status": "Open",
                "feedbackKinds": ["feature_request"],
                "scopeDecision": "selected",
                "scopeReasons": ["squad_exact"],
                "businessCategory": "scheduling",
                "auxiliaryCategories": [],
                "classificationConfidence": "high",
                "relatedTickets": [],
            },
            {
                "objectType": "feedback",
                "sourceKey": "jira",
                "sourceObjectId": "CS-1002",
                "sourceUrl": "https://moego.atlassian.net/browse/CS-1002",
                "createdAt": "2026-08-21T08:00:00Z",
                "title": "设计流程反馈",
                "squad": "grooming",
                "components": [],
                "issueType": "Bug Report",
                "status": "In Progress",
                "feedbackKinds": ["design_linked"],
                "scopeDecision": "selected",
                "scopeReasons": ["squad_exact"],
                "businessCategory": "others",
                "auxiliaryCategories": [],
                "classificationConfidence": "low",
                "relatedTickets": [
                    {
                        "key": "DES-1090",
                        "projectKey": "DES",
                        "issueType": "Design Issue",
                        "status": "Open",
                        "url": "https://moego.atlassian.net/browse/DES-1090",
                    }
                ],
            },
            {
                "objectType": "feedback",
                "sourceKey": "jira",
                "sourceObjectId": "CS-1003",
                "sourceUrl": "https://moego.atlassian.net/browse/CS-1003",
                "createdAt": "2026-08-22T08:00:00Z",
                "title": "功能需求且关联设计单",
                "squad": "Grooming",
                "components": [],
                "issueType": "Feature Request",
                "status": "Open",
                "feedbackKinds": ["feature_request", "design_linked"],
                "scopeDecision": "selected",
                "scopeReasons": ["squad_exact"],
                "businessCategory": "others",
                "auxiliaryCategories": [],
                "classificationConfidence": "low",
                "relatedTickets": [
                    {
                        "key": "DES-1091",
                        "projectKey": "DES",
                        "issueType": "Design Issue",
                        "status": "In Progress",
                        "url": "https://moego.atlassian.net/browse/DES-1091",
                    }
                ],
            },
        ]
        run_manifest = {
            "schemaVersion": 1,
            "collectorVersion": "0.3.0",
            "runId": "jira-test-period",
            "sourceKey": "jira",
            "mode": "period",
            "status": "succeeded",
            "startedAt": "2026-08-24T00:00:00Z",
            "finishedAt": "2026-08-24T00:01:00Z",
            "fetchedCount": len(evidence),
            "observedCount": 5,
            "inPeriodCount": 4,
            "baseline": False,
            "baselineCount": 0,
            "newCount": len(evidence),
            "changedCount": 0,
            "period": {"start": "2026-08-17", "end": "2026-08-23"},
            "squad": "Grooming",
            "query": {
                "jql": (
                    'project = CS AND created >= "2026-08-16" '
                    'AND created < "2026-08-25" ORDER BY created DESC'
                ),
                "fields": [
                    "summary",
                    "status",
                    "created",
                    "issuetype",
                    "issuelinks",
                    "components",
                    "customfield_10089",
                ],
            },
            "transport": "fixture",
            "privacyPolicy": "jira-safe-v1",
            "selectionRule": "jira-grooming-journey-v2",
            "feedbackCandidateCount": 3,
            "manualReviewCount": 0,
            "excludedScopeCount": 0,
        }
        run_path.write_text(
            json.dumps(
                {"manifest": run_manifest, "evidence": evidence, "reportRows": []}
            ),
            encoding="utf-8",
        )
        manifest_path.write_text(
            json.dumps({**run_manifest, "runArtifact": str(run_path)}),
            encoding="utf-8",
        )
        return manifest_path

    @staticmethod
    def _args(manifest):
        return SimpleNamespace(
            source="jira",
            manifest=str(manifest),
            quick_win_review="",
            period_start="",
            period_end="",
            dry_run=True,
        )

    def test_dry_run_renders_feature_request_and_design_sections(self):
        with tempfile.TemporaryDirectory() as directory:
            manifest = self._artifacts(directory)
            result = publish_run(
                self._args(manifest), SimpleNamespace(squad="Grooming")
            )

        self.assertTrue(result["dryRun"])
        self.assertEqual(3, result["counts"]["selectedRows"])
        self.assertEqual(2, result["counts"]["featureRequest"])
        self.assertEqual(2, result["counts"]["designLinked"])
        self.assertIn("Jira CS 反馈｜Grooming", result["title"])
        self.assertIn("功能需求（Feature Request）", result["content"])
        self.assertIn("关联设计单反馈", result["content"])
        self.assertIn("DES-1090", result["content"])

    def test_manifest_is_bound_to_current_squad(self):
        with tempfile.TemporaryDirectory() as directory:
            manifest = self._artifacts(directory)
            with self.assertRaisesRegex(BusinessError, "Squad"):
                publish_run(
                    self._args(manifest), SimpleNamespace(squad="Boarding")
                )


class FacebookPublishTests(unittest.TestCase):
    def test_dry_run_renders_channel_summary_source_dashboard(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run_path = root / "facebook-run.json"
            manifest_path = root / "facebook-manifest.json"
            evidence = [
                {
                    "objectType": "feedback",
                    "sourceKey": "facebook",
                    "sourceObjectId": "1710000000.000001",
                    "evidenceId": "facebook:slack-summary:1710000000.000001",
                    "createdAt": "2026-08-20T08:00:00Z",
                    "title": "客户希望日历支持更短的预约间隔",
                    "domain": "grooming",
                    "feedType": "campaign_comment_summary",
                    "coverage": "channel-summary",
                    "slackUrl": "https://moego.slack.com/archives/C0BEL8Y0Y74/p1710000000000001",
                }
            ]
            manifest = {
                "runId": "facebook-publish",
                "sourceKey": "facebook",
                "mode": "period",
                "status": "succeeded",
                "fetchedCount": 4,
                "newCount": 1,
                "period": {"start": "2026-08-17", "end": "2026-08-23"},
                "domain": "grooming",
                "coverage": "channel-summary",
                "privacyPolicy": "facebook-slack-safe-v1",
            }
            run_path.write_text(
                json.dumps(
                    {"manifest": manifest, "evidence": evidence, "reportRows": []}
                ),
                encoding="utf-8",
            )
            manifest_path.write_text(
                json.dumps({**manifest, "runArtifact": str(run_path)}),
                encoding="utf-8",
            )
            result = publish_run(
                SimpleNamespace(
                    source="facebook",
                    manifest=str(manifest_path),
                    quick_win_review="",
                    period_start="",
                    period_end="",
                    dry_run=True,
                ),
                SimpleNamespace(squad="Grooming", feedback_domain="grooming"),
            )

        self.assertTrue(result["dryRun"])
        self.assertEqual(4, result["counts"]["observedRows"])
        self.assertEqual(1, result["counts"]["selectedRows"])
        self.assertIn("Facebook Community｜grooming", result["title"])
        self.assertIn("频道汇总反馈", result["content"])
        self.assertIn("客户希望日历支持更短的预约间隔", result["content"])
        self.assertIn("不代表 Facebook 全量", result["content"])


if __name__ == "__main__":
    unittest.main()
