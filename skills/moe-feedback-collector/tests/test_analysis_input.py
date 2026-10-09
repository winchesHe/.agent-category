from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))

from mfc.analysis_input import build_weekly_analysis_input
from mfc.errors import ConfigError
from mfc.jira import JIRA_SEARCH_FIELDS, build_jql


class AnalysisInputTests(unittest.TestCase):
    def _write_run(self, root, name, manifest, evidence, report_rows=None):
        run_path = root / f"{name}-run.json"
        manifest_path = root / f"{name}-manifest.json"
        run_path.write_text(
            json.dumps(
                {
                    "manifest": manifest,
                    "evidence": evidence,
                    "reportRows": report_rows or [],
                }
            ),
            encoding="utf-8",
        )
        manifest_path.write_text(
            json.dumps({**manifest, "runArtifact": str(run_path)}),
            encoding="utf-8",
        )
        return manifest_path

    def _manifests(self, root):
        period = {"start": "2026-08-24", "end": "2026-08-30"}
        canny_evidence = [
            {
                "sourceKey": "canny",
                "objectType": "post",
                "sourceObjectId": "post-1",
                "evidenceId": "canny:post-1",
                "createdAt": "2026-08-25T08:00:00Z",
                "title": "批量预约",
                "content": "希望一次调整多条预约",
                "sourceUrl": "https://example.invalid/canny/post-1",
                "voteCount": 5,
                "commentCount": 1,
                "status": "open",
                "changeKind": "baseline",
            }
        ]
        canny = self._write_run(
            root,
            "canny",
            {
                "runId": "canny-w35",
                "sourceKey": "canny",
                "mode": "full",
                "status": "succeeded",
                "fetchedCount": 1,
                "baseline": True,
                "period": period,
            },
            canny_evidence,
        )
        intercom_evidence = [
            {
                "sourceKey": "intercom",
                "objectType": "feedback",
                "sourceObjectId": "feedback-1",
                "evidenceId": "intercom:feedback-1",
                "createdAt": "2026-08-26T08:00:00Z",
                "requirement": "客户希望预约提醒按时送达",
                "domain": "Appointment",
                "feedbackType": "feature_request",
                "sentiment": "negative",
                "squad": "Grooming",
                "role": "Owner",
                "sourceUrl": "",
            }
        ]
        intercom = self._write_run(
            root,
            "intercom",
            {
                "runId": "intercom-w35",
                "sourceKey": "intercom",
                "mode": "period",
                "status": "succeeded",
                "fetchedCount": 1,
                "period": period,
                "privacyPolicy": "intercom-safe-v1",
            },
            intercom_evidence,
        )
        jira_evidence = [
            {
                "sourceKey": "jira",
                "objectType": "feedback",
                "sourceObjectId": "CS-1001",
                "evidenceId": "jira:CS-1001",
                "createdAt": "2026-08-27T08:00:00Z",
                "title": "同一车辆被分配给重叠班次",
                "squad": "Grooming",
                "components": ["Staff/Shift"],
                "issueType": "Feature Request",
                "status": "Open",
                "feedbackKinds": ["feature_request"],
                "scopeDecision": "selected",
                "scopeReasons": ["squad_exact"],
                "businessCategory": "van-staff-shift-management",
                "auxiliaryCategories": [],
                "classificationConfidence": "high",
                "relatedTickets": [],
                "sourceUrl": "https://moego.atlassian.net/browse/CS-1001",
            }
        ]
        jira = self._write_run(
            root,
            "jira",
            {
                "runId": "jira-w35",
                "sourceKey": "jira",
                "mode": "period",
                "status": "succeeded",
                "fetchedCount": 1,
                "observedCount": 1,
                "inPeriodCount": 1,
                "feedbackCandidateCount": 1,
                "manualReviewCount": 0,
                "excludedScopeCount": 0,
                "period": period,
                "squad": "Grooming",
                "privacyPolicy": "jira-safe-v1",
                "selectionRule": "jira-grooming-journey-v2",
                "query": {
                    "jql": build_jql(
                        date(2026, 8, 24), date(2026, 8, 30), "Grooming"
                    ),
                    "fields": list(JIRA_SEARCH_FIELDS),
                },
            },
            jira_evidence,
        )
        facebook_evidence = [
            {
                "sourceKey": "facebook",
                "objectType": "feedback",
                "sourceObjectId": "facebook-1",
                "evidenceId": "facebook:facebook-1",
                "createdAt": "2026-08-28T08:00:00Z",
                "title": "客户希望预约间隔更灵活",
                "content": "希望可以按宠物情况设置不同预约间隔",
                "domain": "grooming",
                "feedType": "group_post",
                "coverage": "channel-summary",
                "sourceUrl": "https://example.invalid/facebook/post-1",
                "slackUrl": "https://example.invalid/slack/post-1",
            }
        ]
        facebook = self._write_run(
            root,
            "facebook",
            {
                "runId": "facebook-w35",
                "sourceKey": "facebook",
                "mode": "period",
                "status": "succeeded",
                "fetchedCount": 1,
                "newCount": 1,
                "period": period,
                "domain": "grooming",
                "coverage": "channel-summary",
                "privacyPolicy": "facebook-slack-safe-v1",
            },
            facebook_evidence,
        )
        return [canny, intercom, jira, facebook]

    def _previous_analysis(self, root, *, scope="Grooming", start="2026-08-17"):
        end = "2026-08-23" if start == "2026-08-17" else "2026-08-16"
        period = {"start": start, "end": end}
        payload = json.loads(
            (
                Path(__file__).parents[2]
                / "docs/specs/examples/moe-feedback-weekly-analysis-v3.example.json"
            ).read_text(encoding="utf-8")
        )
        payload["analysisRule"] = "grooming-weekly-analysis-v3"
        payload["scope"] = scope
        payload["currentPeriod"] = period
        payload["comparisonPeriod"] = None
        payload["comparisonBaseline"] = {
            "status": "unavailable",
            "reason": "测试基线。",
            "analysisArtifactId": None,
        }
        payload["baselineExport"]["artifactId"] = (
            "weekly-analysis:grooming:previous:v3"
        )
        payload["baselineExport"]["period"] = period
        payload["baselineExport"]["scope"] = scope
        for item in payload["categoryOverview"]:
            item["previousCount"] = None
            item["delta"] = None
            item["volumeTrend"] = "not-comparable"
        payload["reviewQueue"]["previousCount"] = None
        payload["weekComparison"] = {
            "status": "unavailable",
            "headline": "测试基线。",
            "improvements": [],
            "attentionItems": [],
        }
        path = root / f"previous-analysis-{scope.lower()}-{start}.json"
        path.write_text(
            json.dumps(payload),
            encoding="utf-8",
        )
        return path

    def _build(self, manifests, previous_analysis=""):
        return build_weekly_analysis_input(
            [str(path) for path in manifests],
            squad="Grooming",
            domain="grooming",
            start=date(2026, 8, 24),
            end=date(2026, 8, 30),
            scope="Grooming",
            previous_analysis=str(previous_analysis) if previous_analysis else "",
        )

    def test_builds_current_week_input_without_quick_win_or_old_classification(self):
        with tempfile.TemporaryDirectory() as directory:
            result = self._build(self._manifests(Path(directory)))

        self.assertEqual(1, result["schemaVersion"])
        self.assertEqual(
            ["canny", "intercom", "jira", "facebook"],
            [item["sourceKey"] for item in result["currentSourceRuns"]],
        )
        self.assertEqual(4, len(result["records"]))
        self.assertEqual("unavailable", result["previousBaseline"]["status"])
        payload = json.dumps(result, ensure_ascii=False)
        self.assertNotIn("quickWinSelected", payload)
        self.assertNotIn('"businessCategory"', payload)
        self.assertNotIn('"classificationConfidence"', payload)
        self.assertIn("希望一次调整多条预约", payload)
        self.assertIn("Staff/Shift", payload)
        self.assertEqual(
            {
                "evidenceId",
                "sourceKey",
                "sourceObjectId",
                "title",
                "normalizedText",
                "sourceCategory",
                "createdAt",
                "sourceUrl",
                "contextTags",
            },
            set(result["records"][0]),
        )

    def test_uses_only_published_previous_baseline_summary(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result = self._build(
                self._manifests(root), self._previous_analysis(root)
            )

        baseline = result["previousBaseline"]
        self.assertEqual("available", baseline["status"])
        self.assertEqual("weekly-analysis:grooming:previous:v3", baseline["artifactId"])
        self.assertEqual(7, len(baseline["categories"]))
        self.assertEqual(1, baseline["reviewCount"])
        self.assertNotIn("classifications", baseline)
        self.assertNotIn("records", baseline)

    def test_non_adjacent_or_other_scope_baseline_degrades_explicitly(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifests = self._manifests(root)
            cases = (
                (self._previous_analysis(root, scope="Boarding"), "scope"),
                (self._previous_analysis(root, start="2026-08-10"), "紧邻"),
            )
            for previous, reason in cases:
                with self.subTest(reason=reason):
                    baseline = self._build(manifests, previous)["previousBaseline"]
                    self.assertEqual("unavailable", baseline["status"])
                    self.assertIn(reason, baseline["reason"])
                    self.assertEqual([], baseline["categories"])

    def test_malformed_previous_analysis_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            previous = root / "invalid.json"
            previous.write_text(
                json.dumps(
                    {
                        "schemaVersion": 3,
                        "analysisRule": "grooming-weekly-analysis-v3",
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ConfigError, "baselineExport"):
                self._build(self._manifests(root), previous)

    def test_rejects_previous_baseline_counts_not_derived_from_classifications(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            previous = self._previous_analysis(root)
            payload = json.loads(previous.read_text(encoding="utf-8"))
            payload["baselineExport"]["categories"][0]["count"] += 1
            previous.write_text(json.dumps(payload), encoding="utf-8")

            with self.assertRaisesRegex(ConfigError, "baselineExport 与 classifications"):
                self._build(self._manifests(root), previous)

    def test_rejects_incomplete_or_misclassified_previous_artifact(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            previous = self._previous_analysis(root)
            payload = json.loads(previous.read_text(encoding="utf-8"))
            payload["summary"] = []
            previous.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(ConfigError, "summary 无效"):
                self._build(self._manifests(root), previous)

            previous = self._previous_analysis(root)
            payload = json.loads(previous.read_text(encoding="utf-8"))
            representative = payload["baselineExport"]["categories"][0][
                "representativeEvidence"
            ][0]
            representative["evidenceId"] = payload["classifications"][1][
                "evidenceId"
            ]
            previous.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(ConfigError, "代表证据与 classifications"):
                self._build(self._manifests(root), previous)

    def test_previous_artifact_uses_same_auxiliary_and_human_review_contract(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            previous = self._previous_analysis(root)
            payload = json.loads(previous.read_text(encoding="utf-8"))
            payload["classifications"][0]["auxiliaryCategories"] = ["others"]
            previous.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(ConfigError, "分类字段无效"):
                self._build(self._manifests(root), previous)

            previous = self._previous_analysis(root)
            payload = json.loads(previous.read_text(encoding="utf-8"))
            classification = payload["classifications"][0]
            classification["classificationSource"] = "human"
            classification["confidence"] = "low"
            classification["reviewMetadata"] = {
                "reviewedBy": "tester",
                "reviewedAt": "2026-08-24T09:00:00+08:00",
            }
            previous.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(ConfigError, "人工分类身份无效"):
                self._build(self._manifests(root), previous)

            classification["confidence"] = "high"
            classification["reviewMetadata"]["reviewedAt"] = "not-a-date"
            previous.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(ConfigError, "日期时间无效"):
                self._build(self._manifests(root), previous)

    def test_previous_comparison_requires_both_periods_and_derived_metrics(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            previous = self._previous_analysis(root)
            payload = json.loads(previous.read_text(encoding="utf-8"))
            payload["comparisonPeriod"] = {
                "start": "2026-08-10",
                "end": "2026-08-16",
            }
            payload["comparisonBaseline"] = {
                "status": "available",
                "reason": "测试可比基线。",
                "analysisArtifactId": "weekly-analysis:grooming:older:v3",
            }
            payload["reviewQueue"]["previousCount"] = 0
            for item in payload["categoryOverview"]:
                item["previousCount"] = item["currentCount"]
                item["delta"] = 0
                item["volumeTrend"] = "flat"
            current_id = payload["classifications"][0]["evidenceId"]
            payload["weekComparison"] = {
                "status": "available",
                "headline": "测试环比。",
                "improvements": [
                    {
                        "businessCategory": "scheduling",
                        "title": "测试改善",
                        "summary": "测试改善摘要。",
                        "confidence": "high",
                        "evidenceRefs": [
                            {"period": "current", "evidenceId": current_id}
                        ],
                    }
                ],
                "attentionItems": [],
            }
            previous.write_text(json.dumps(payload), encoding="utf-8")

            with self.assertRaisesRegex(ConfigError, "evidenceRefs 无效"):
                self._build(self._manifests(root), previous)

            payload["weekComparison"]["improvements"][0]["evidenceRefs"].append(
                {"period": "previous", "evidenceId": "canny:older-scheduling"}
            )
            payload["comparisonPeriod"] = {
                "start": "2020-01-06",
                "end": "2020-01-12",
            }
            previous.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(ConfigError, "不是紧邻周期"):
                self._build(self._manifests(root), previous)

            payload["comparisonPeriod"] = {
                "start": "2026-08-10",
                "end": "2026-08-16",
            }
            payload["reviewQueue"]["previousCount"] = "invalid"
            previous.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(ConfigError, "previousCount 无效"):
                self._build(self._manifests(root), previous)

    def test_requires_all_four_current_sources(self):
        with tempfile.TemporaryDirectory() as directory:
            manifests = self._manifests(Path(directory))
            with self.assertRaisesRegex(ConfigError, "facebook"):
                self._build(manifests[:-1])


if __name__ == "__main__":
    unittest.main()
