from __future__ import annotations

import copy
import json
import re
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))

from mfc.commands.dashboard import run as dashboard_run
from mfc.analysis_v3 import load_weekly_analysis_v3
from mfc.dashboard import (
    CATEGORY_LABELS,
    DASHBOARD_DETAIL_MARKER,
    build_dashboard_snapshot,
    dashboard_titles,
    load_weekly_analysis,
    render_dashboard_detail_documents,
    render_dashboard_weekly,
    weekly_analysis_schema_version,
    _v3_item_categories,
    _v3_theme_owner,
    _v3_evidence_links,
)
from mfc.errors import ConfigError

REPO_ROOT = Path(__file__).parents[2]
EXAMPLES = REPO_ROOT / "docs" / "specs" / "examples"


class DashboardTests(unittest.TestCase):
    def test_category_labels_use_product_english_names(self):
        self.assertEqual(
            {
                "scheduling": "scheduling",
                "fulfillment": "fulfillment",
                "communication": "communication",
                "management": "management",
                "payment": "payment",
                "van-staff-shift-management": "van-staff-shift management",
                "others": "others",
            },
            CATEGORY_LABELS,
        )

    def test_compact_evidence_link_keeps_full_id_when_source_url_is_missing(self):
        evidence_id = "canny:" + "very-long-evidence-identity-" * 4
        analysis = {
            "_analysisInput": {
                "records": [
                    {
                        "evidenceId": evidence_id,
                        "sourceKey": "canny",
                        "title": "无链接证据",
                        "sourceUrl": "",
                    }
                ],
                "previousBaseline": {"categories": []},
            }
        }

        rendered = _v3_evidence_links(
            [{"period": "current", "evidenceId": evidence_id}],
            analysis,
            maximum=1,
            compact=True,
        )

        self.assertIn(evidence_id, rendered)

    def _v3_snapshot(self):
        analysis_input = json.loads(
            (EXAMPLES / "moe-feedback-weekly-analysis-input-v1.example.json").read_text(
                encoding="utf-8"
            )
        )
        records = []
        for index, item in enumerate(analysis_input["records"]):
            records.append(
                {
                    "evidenceId": item["evidenceId"],
                    "sourceKey": item["sourceKey"],
                    "sourceObjectId": item["sourceObjectId"],
                    "title": item["title"],
                    "category": item["sourceCategory"],
                    "createdAt": item["createdAt"],
                    "sourceUrl": item["sourceUrl"],
                    "context": " / ".join(item["contextTags"]),
                    "quickWinSelected": index == 0,
                    "normalizedText": item["normalizedText"],
                    "contextTags": item["contextTags"],
                }
            )
        runs = analysis_input["currentSourceRuns"]
        summaries = []
        for run in runs:
            summaries.append(
                {
                    "sourceKey": run["sourceKey"],
                    "status": "ready",
                    "collected": run["includedCount"],
                    "included": run["includedCount"],
                    "breakdown": "测试数据",
                    "coverage": run["coverage"],
                    "reportTitle": f"{run['sourceKey']} 周报",
                }
            )
        return {
            "period": analysis_input["currentPeriod"],
            "squad": "Grooming",
            "domain": "grooming",
            "sources": summaries,
            "records": records,
            "providedSources": [item["sourceKey"] for item in runs],
            "missingSources": [],
            "emptySources": [],
            "totalSignals": len(records),
            "ruleVersion": "cross-source-dashboard-v7",
            "sourceRunIds": {
                item["sourceKey"]: item["runId"] for item in runs
            },
        }

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

    def _canny(self, root):
        evidence = [
            {
                "sourceKey": "canny",
                "objectType": "post",
                "sourceObjectId": "post-1",
                "evidenceId": "canny:post-1:2026-08-20",
                "createdAt": "2026-08-20T08:00:00Z",
                "title": "批量预约",
                "voteCount": 5,
                "commentCount": 1,
                "status": "open",
                "changeKind": "baseline",
            }
        ]
        manifest = {
            "runId": "canny-dashboard",
            "sourceKey": "canny",
            "mode": "full",
            "status": "succeeded",
            "fetchedCount": 1,
            "baseline": True,
            "period": {"start": "2026-08-17", "end": "2026-08-23"},
        }
        return self._write_run(root, "canny", manifest, evidence)

    def _facebook(self, root):
        evidence = [
            {
                "sourceKey": "facebook",
                "objectType": "feedback",
                "sourceObjectId": "fb-1",
                "evidenceId": "facebook:fb-1:2026-08-20",
                "createdAt": "2026-08-20T08:00:00Z",
                "title": "客户希望预约间隔更灵活",
                "domain": "grooming",
                "feedType": "group_post",
                "coverage": "channel-summary",
            }
        ]
        manifest = {
            "runId": "facebook-dashboard",
            "sourceKey": "facebook",
            "mode": "period",
            "status": "succeeded",
            "fetchedCount": 2,
            "newCount": 1,
            "period": {"start": "2026-08-17", "end": "2026-08-23"},
            "domain": "grooming",
            "coverage": "channel-summary",
            "privacyPolicy": "facebook-slack-safe-v1",
        }
        return self._write_run(root, "facebook", manifest, evidence)

    def test_snapshot_combines_sources_and_preserves_missing_state(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            canny = self._canny(root)
            facebook = self._facebook(root)
            review = root / "review.json"
            review.write_text(
                json.dumps(
                    [
                        {
                            "sourceObjectId": "post-1",
                            "selected": True,
                            "reason": "需求明确且范围集中",
                        }
                    ]
                ),
                encoding="utf-8",
            )
            snapshot = build_dashboard_snapshot(
                [canny, facebook],
                squad="Grooming",
                domain="grooming",
                start=date(2026, 8, 17),
                end=date(2026, 8, 23),
                quick_win_review=str(review),
            )

        self.assertEqual(["canny", "facebook"], snapshot["providedSources"])
        self.assertEqual(["intercom", "jira"], snapshot["missingSources"])
        self.assertEqual([], snapshot["emptySources"])
        self.assertEqual(2, snapshot["totalSignals"])
        self.assertEqual(2, len(snapshot["records"]))
        self.assertNotIn("normalizedText", snapshot["records"][0])
        self.assertNotIn("contextTags", snapshot["records"][0])
        self.assertIn("AI 入选 1", snapshot["sources"][0]["breakdown"])
        self.assertIn("Slack 频道", snapshot["sources"][3]["coverage"])

    def test_snapshot_marks_ready_source_without_selected_rows_as_empty(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = {
                "runId": "facebook-empty-dashboard",
                "sourceKey": "facebook",
                "mode": "period",
                "status": "succeeded",
                "fetchedCount": 0,
                "newCount": 0,
                "period": {"start": "2026-08-17", "end": "2026-08-23"},
                "domain": "grooming",
                "coverage": "channel-summary",
                "privacyPolicy": "facebook-slack-safe-v1",
            }
            facebook = self._write_run(root, "facebook-empty", manifest, [])
            snapshot = build_dashboard_snapshot(
                [facebook],
                squad="Grooming",
                domain="grooming",
                start=date(2026, 8, 17),
                end=date(2026, 8, 23),
            )

        self.assertEqual(["facebook"], snapshot["emptySources"])
        self.assertEqual(0, snapshot["sources"][3]["included"])

    def test_v3_snapshot_exposes_run_ids_without_mixing_quick_win_into_category(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            canny = self._canny(root)
            review = root / "review.json"
            review.write_text(
                json.dumps(
                    [
                        {
                            "sourceObjectId": "post-1",
                            "selected": True,
                            "reason": "需求明确且范围集中",
                        }
                    ]
                ),
                encoding="utf-8",
            )
            snapshot = build_dashboard_snapshot(
                [canny],
                squad="Grooming",
                domain="grooming",
                start=date(2026, 8, 17),
                end=date(2026, 8, 23),
                quick_win_review=str(review),
                include_analysis_fields=True,
            )

        self.assertEqual("canny-dashboard", snapshot["sourceRunIds"]["canny"])
        self.assertEqual("Canny 反馈", snapshot["records"][0]["category"])
        self.assertTrue(snapshot["records"][0]["quickWinSelected"])
        self.assertIn("normalizedText", snapshot["records"][0])

    def test_analysis_requires_known_evidence_and_renders_rich_sections(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            canny = self._canny(root)
            review = root / "review.json"
            review.write_text(
                json.dumps(
                    [
                        {
                            "sourceObjectId": "post-1",
                            "selected": True,
                            "reason": "范围小且需求明确",
                        }
                    ]
                ),
                encoding="utf-8",
            )
            snapshot = build_dashboard_snapshot(
                [canny],
                squad="Grooming",
                domain="grooming",
                start=date(2026, 8, 17),
                end=date(2026, 8, 23),
                quick_win_review=str(review),
            )
            analysis_path = root / "analysis.json"
            analysis_path.write_text(
                json.dumps(
                    {
                        "schemaVersion": 2,
                        "period": snapshot["period"],
                        "scope": "Grooming",
                        "summary": [
                            {
                                "text": "批量预约是本周最明确的 Quick Win。",
                                "confidence": "high",
                                "evidenceIds": ["canny:post-1:2026-08-20"],
                            }
                        ],
                        "themes": [
                            {
                                "name": "预约效率",
                                "summary": "用户希望减少重复操作。",
                                "confidence": "high",
                                "evidenceIds": ["canny:post-1:2026-08-20"],
                            }
                        ],
                        "featuredEvidenceIds": ["canny:post-1:2026-08-20"],
                        "insights": [
                            {
                                "title": "效率诉求集中",
                                "observation": "反馈指向批量处理。",
                                "whyItMatters": "可降低前台操作成本。",
                                "confidence": "medium",
                                "evidenceIds": ["canny:post-1:2026-08-20"],
                            }
                        ],
                        "recommendations": [
                            {
                                "title": "验证批量预约",
                                "action": "访谈三位高频用户并拆分最小范围。",
                                "confidence": "medium",
                                "evidenceIds": ["canny:post-1:2026-08-20"],
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            analysis = load_weekly_analysis(
                str(analysis_path), snapshot, scope="Grooming"
            )
            _year, _month, week = dashboard_titles(
                date(2026, 8, 17), date(2026, 8, 23), "Grooming"
            )
            content = render_dashboard_weekly(snapshot, week, analysis)

            self.assertIn("本周 AI 摘要", content)
            self.assertIn("跨渠道主题", content)
            self.assertIn("重点反馈", content)
            self.assertIn("AI 洞察", content)
            self.assertIn("建议动作", content)
            self.assertIn("批量预约", content)
            self.assertIn("证据：", content)

            payload = json.loads(analysis_path.read_text(encoding="utf-8"))
            payload["themes"][0]["evidenceIds"] = ["unknown:evidence"]
            analysis_path.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(ConfigError, "未知 evidence ID"):
                load_weekly_analysis(str(analysis_path), snapshot, scope="Grooming")

            payload["themes"][0]["evidenceIds"] = ["canny:post-1:2026-08-20"]
            payload["summary"][0].pop("evidenceIds")
            analysis_path.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(ConfigError, r"summary\[0\].evidenceIds"):
                load_weekly_analysis(str(analysis_path), snapshot, scope="Grooming")

    def test_v3_analysis_is_bound_to_input_snapshot_and_renders_five_sections(self):
        snapshot = self._v3_snapshot()
        analysis_path = EXAMPLES / "moe-feedback-weekly-analysis-v3.example.json"
        input_path = EXAMPLES / "moe-feedback-weekly-analysis-input-v1.example.json"
        analysis = load_weekly_analysis_v3(
            str(analysis_path), str(input_path), snapshot, scope="Grooming"
        )
        content = render_dashboard_weekly(
            snapshot, "2026-W35｜08.24–08.30｜Grooming 反馈总览", analysis
        )
        detail_documents = render_dashboard_detail_documents(
            snapshot,
            "2026-W35｜08.24–08.30｜Grooming 反馈总览",
            analysis,
        )

        headings = [
            "周环比",
            "本周反馈概览",
            "产品/设计关注点",
            "Quick Win 候选",
            "原始证据",
        ]
        positions = [content.index(f"<h1>{heading}</h1>") for heading in headings]
        self.assertEqual(sorted(positions), positions)
        self.assertEqual(5, content.count("<h1>"))
        self.assertLess(
            content.index("<h1>周环比</h1>"),
            content.index('<callout emoji="📊"'),
        )
        self.assertEqual(
            1,
            content.count("预约改期诉求连续出现；预约提醒出现明确改善信号。"),
        )
        self.assertNotIn("<h1>本周结论</h1>", content)
        self.assertNotIn("<h1>建议动作</h1>", content)
        self.assertNotIn("<h1>分类总览</h1>", content)
        self.assertIn("预约提醒出现改善信号", content)
        for category_label in (
            "scheduling",
            "fulfillment",
            "communication",
            "management",
            "payment",
            "van-staff-shift management",
            "others",
        ):
            self.assertIn(category_label, content)
        for translated_category_label in (
            "预约排期",
            "服务履约",
            "沟通触达",
            "经营管理",
            "支付结算",
            "车辆与员工排班管理",
            "其他",
        ):
            self.assertNotIn(translated_category_label, content)
        self.assertIn("已逐条筛选四源全部 7 条反馈", content)
        self.assertIn("Intercom 2", content)
        self.assertIn("Jira CS 2", content)
        self.assertIn("共归并出 <b>3</b> 个候选", content)
        self.assertEqual(2, content.count("__CATEGORY_DETAIL_REPORT__"))
        self.assertNotIn("__QUICK_WIN_DETAIL_REPORT__", content)
        self.assertNotIn("批量调整预约时间", content)
        self.assertLess(len(content), 12000)
        self.assertIn("__SOURCE_REPORTS__", content)
        self.assertNotIn("<h1>本周总览</h1>", content)

        self.assertEqual(1, len(detail_documents))
        details_by_key = {item["key"]: item for item in detail_documents}
        category_content = details_by_key["category"]["content"]
        self.assertIn(DASHBOARD_DETAIL_MARKER, category_content)
        detail_headings = [
            "分类导航",
            "需优先关注",
            "scheduling",
            "fulfillment",
            "communication",
            "management",
            "payment",
            "van-staff-shift management",
            "others",
            "跨分类事项",
            "待人工复核",
            "原始证据入口",
        ]
        detail_positions = [
            category_content.index(f"<h1>{heading}</h1>")
            for heading in detail_headings
        ]
        self.assertEqual(sorted(detail_positions), detail_positions)
        self.assertEqual(len(detail_headings), category_content.count("<h1>"))
        self.assertNotIn("<h1>周环比</h1>", category_content)
        self.assertNotIn("<h1>产品/设计关注点</h1>", category_content)
        self.assertNotIn("<h1>分类与主题明细</h1>", category_content)
        self.assertEqual(1, category_content.count("前台效率与资源冲突"))
        self.assertEqual(2, category_content.count("批量调整预约时间"))
        self.assertIn("分类理由：", category_content)
        self.assertIn("原始证据：", category_content)
        self.assertIn("完整分析摘要", category_content)
        for item in analysis["summary"]:
            self.assertIn(item["text"], category_content)
        self.assertIn(
            '<th background-color="light-gray">来源</th>', category_content
        )
        self.assertIn(
            '<th background-color="light-gray">反馈</th>', category_content
        )
        self.assertIn("__SOURCE_REPORTS__", category_content)
        self.assertIn("同一车辆被分配", category_content)
        self.assertLess(len(category_content), 18000)

        duplicate_analysis = copy.deepcopy(analysis)
        representative = duplicate_analysis["baselineExport"]["categories"][0][
            "representativeEvidence"
        ][0]
        evidence_id = representative["evidenceId"]
        matching_record = next(
            item
            for item in duplicate_analysis["_analysisInput"]["records"]
            if item["evidenceId"] == evidence_id
        )
        matching_record["title"] = "标题与摘要完全相同"
        representative["summary"] = "标题与摘要完全相同"
        duplicate_category_content = {
            item["key"]: item["content"]
            for item in render_dashboard_detail_documents(
                snapshot,
                "2026-W35｜08.24–08.30｜Grooming 反馈总览",
                duplicate_analysis,
            )
        }["category"]
        self.assertEqual(1, duplicate_category_content.count("标题与摘要完全相同"))
        self.assertIn("批量调整预约时间", category_content)
        self.assertIn("员工数据访问权限配置", category_content)
        self.assertIn("服务完成状态记录", category_content)
        self.assertIn(
            "诉求明确 ✓｜范围集中 ✓｜预估改动较小 ✓",
            category_content,
        )
        self.assertIn("诉求明确且范围集中；实现成本仍需产品和工程确认。", category_content)
        quick_win_content = category_content
        self.assertEqual(3, quick_win_content.count('<checkbox done="false">'))
        self.assertNotIn('<checkbox done="true">', quick_win_content)
        self.assertEqual(7, quick_win_content.count("<h2>Quick Win 候选（"))
        self.assertEqual(
            3,
            quick_win_content.count(
                '<th background-color="light-gray">入选判断</th>'
            ),
        )
        self.assertEqual(
            3,
            quick_win_content.count(
                '<th background-color="light-gray">原始证据</th>'
            ),
        )
        self.assertEqual(
            3,
            quick_win_content.count(
                '<colgroup><col width="130"/><col width="220"/>'
                '<col width="300"/><col width="180"/></colgroup>'
            ),
        )
        self.assertRegex(
            quick_win_content,
            r'<td vertical-align="top"><checkbox done="false">\[QW-[A-F0-9]{8}\]</checkbox></td>',
        )
        self.assertIn("本阶段不会自动创建 Jira", quick_win_content)
        candidate_ids = re.findall(r"\[(QW-[A-F0-9]{8})\]", quick_win_content)
        self.assertEqual(3, len(candidate_ids))
        self.assertEqual(3, len(set(candidate_ids)))
        rerendered_category = {
            item["key"]: item["content"]
            for item in render_dashboard_detail_documents(
                snapshot,
                "2026-W35｜08.24–08.30｜Grooming 反馈总览",
                analysis,
            )
        }["category"]
        self.assertEqual(
            candidate_ids,
            re.findall(r"\[(QW-[A-F0-9]{8})\]", rerendered_category),
        )
        scheduling_section = category_content[
            category_content.index("<h1>scheduling</h1>") : category_content.index(
                "<h1>fulfillment</h1>"
            )
        ]
        self.assertLess(
            scheduling_section.index("<h2>代表反馈</h2>"),
            scheduling_section.index("<h2>产品/设计动作</h2>"),
        )
        self.assertLess(
            scheduling_section.index("<h2>产品/设计动作</h2>"),
            scheduling_section.index("<h2>Quick Win 候选（"),
        )

    def test_v3_analysis_rejects_tampered_derived_data_and_different_run(self):
        snapshot = self._v3_snapshot()
        input_payload = json.loads(
            (EXAMPLES / "moe-feedback-weekly-analysis-input-v1.example.json").read_text(
                encoding="utf-8"
            )
        )
        analysis_payload = json.loads(
            (EXAMPLES / "moe-feedback-weekly-analysis-v3.example.json").read_text(
                encoding="utf-8"
            )
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            input_path = root / "input.json"
            analysis_path = root / "analysis.json"
            input_path.write_text(json.dumps(input_payload), encoding="utf-8")
            analysis_payload["categoryOverview"][0]["currentCount"] += 1
            analysis_path.write_text(json.dumps(analysis_payload), encoding="utf-8")
            with self.assertRaisesRegex(ConfigError, "categoryOverview 不是确定性结果"):
                load_weekly_analysis_v3(
                    str(analysis_path), str(input_path), snapshot, scope="Grooming"
                )

            analysis_payload["categoryOverview"][0]["currentCount"] -= 1
            analysis_path.write_text(json.dumps(analysis_payload), encoding="utf-8")
            snapshot["sourceRunIds"]["jira"] = "another-run"
            with self.assertRaisesRegex(ConfigError, "jira runId"):
                load_weekly_analysis_v3(
                    str(analysis_path), str(input_path), snapshot, scope="Grooming"
                )

    def test_v3_category_assignment_distinguishes_same_id_across_periods(self):
        snapshot = self._v3_snapshot()
        analysis = load_weekly_analysis_v3(
            str(EXAMPLES / "moe-feedback-weekly-analysis-v3.example.json"),
            str(EXAMPLES / "moe-feedback-weekly-analysis-input-v1.example.json"),
            snapshot,
            scope="Grooming",
        )
        analysis = copy.deepcopy(analysis)
        current_payment = next(
            item
            for item in analysis["classifications"]
            if item["primaryCategory"] == "payment"
        )
        evidence_id = current_payment["evidenceId"]
        previous_scheduling = analysis["_analysisInput"]["previousBaseline"][
            "categories"
        ][0]
        previous_scheduling["representativeEvidence"][0]["evidenceId"] = evidence_id

        self.assertEqual(
            ["payment"],
            _v3_item_categories(
                {"evidenceRefs": [{"period": "current", "evidenceId": evidence_id}]},
                analysis,
            ),
        )
        self.assertEqual(
            ["scheduling"],
            _v3_item_categories(
                {"evidenceRefs": [{"period": "previous", "evidenceId": evidence_id}]},
                analysis,
            ),
        )
        self.assertEqual(
            "payment",
            _v3_theme_owner(
                {
                    "businessCategories": ["scheduling", "payment"],
                    "evidenceRefs": [
                        {"period": "current", "evidenceId": evidence_id}
                    ],
                },
                analysis,
            ),
        )

    def test_v3_parent_and_category_detail_avoid_repeating_long_summary(self):
        snapshot = self._v3_snapshot()
        analysis = load_weekly_analysis_v3(
            str(EXAMPLES / "moe-feedback-weekly-analysis-v3.example.json"),
            str(EXAMPLES / "moe-feedback-weekly-analysis-input-v1.example.json"),
            snapshot,
            scope="Grooming",
        )
        analysis = copy.deepcopy(analysis)
        full_summary = "完整分析" * 250
        analysis["summary"][0]["text"] = full_summary
        analysis["insights"][0]["observation"] = "完整洞察" * 250
        analysis["insights"][0]["whyItMatters"] = "完整影响" * 250
        analysis["recommendations"][0]["action"] = "完整动作" * 250
        analysis["weekComparison"]["headline"] = "完整环比" * 250
        week_title = "2026-W35｜08.24–08.30｜Grooming 反馈总览"

        content = render_dashboard_weekly(snapshot, week_title, analysis)
        category_detail = render_dashboard_detail_documents(
            snapshot, week_title, analysis
        )[0]["content"]

        self.assertLess(len(content), 12000)
        self.assertNotIn(full_summary, content)
        self.assertIn(full_summary, category_detail)
        self.assertIn("完整洞察" * 250, category_detail)
        self.assertIn("完整影响" * 250, category_detail)
        self.assertIn("完整动作" * 250, category_detail)

    def test_v3_quick_win_detail_keeps_all_evidence_links(self):
        snapshot = self._v3_snapshot()
        analysis = load_weekly_analysis_v3(
            str(EXAMPLES / "moe-feedback-weekly-analysis-v3.example.json"),
            str(EXAMPLES / "moe-feedback-weekly-analysis-input-v1.example.json"),
            snapshot,
            scope="Grooming",
        )
        analysis = copy.deepcopy(analysis)
        candidate = analysis["quickWinCandidates"][0]
        base_record = analysis["_analysisInput"]["records"][0]
        base_assessment = analysis["quickWinAssessments"][0]
        for index in range(9):
            evidence_id = f"canny:quick-win-extra-{index}"
            analysis["_analysisInput"]["records"].append(
                dict(
                    base_record,
                    evidenceId=evidence_id,
                    title=f"额外 Quick Win 证据 {index}",
                    sourceUrl=f"https://example.invalid/quick-win/{index}",
                )
            )
            analysis["quickWinAssessments"].append(
                dict(base_assessment, evidenceId=evidence_id)
            )
            candidate["evidenceRefs"].append(
                {"period": "current", "evidenceId": evidence_id}
            )

        category_content = {
            item["key"]: item["content"]
            for item in render_dashboard_detail_documents(
                snapshot,
                "2026-W35｜08.24–08.30｜Grooming 反馈总览",
                analysis,
            )
        }["category"]

        for index in range(9):
            self.assertIn(f"canny:quick-win-extra-{index}", category_content)
        self.assertNotIn(f"等 {len(candidate['evidenceRefs'])} 条", category_content)

    def test_weekly_analysis_schema_version_accepts_v2_and_v3_only(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "analysis.json"
            for version in (2, 3):
                path.write_text(json.dumps({"schemaVersion": version}), encoding="utf-8")
                self.assertEqual(version, weekly_analysis_schema_version(str(path)))
            path.write_text(json.dumps({"schemaVersion": 4}), encoding="utf-8")
            with self.assertRaisesRegex(ConfigError, "不受支持"):
                weekly_analysis_schema_version(str(path))

    def test_dashboard_command_loads_v3_with_matching_analysis_input(self):
        snapshot = self._v3_snapshot()
        args = SimpleNamespace(
            manifest=["canny.json", "intercom.json", "jira.json", "facebook.json"],
            quick_win_review="",
            analysis=str(EXAMPLES / "moe-feedback-weekly-analysis-v3.example.json"),
            analysis_input=str(
                EXAMPLES / "moe-feedback-weekly-analysis-input-v1.example.json"
            ),
            allow_partial=False,
            allow_partial_period=False,
            period_start="2026-08-24",
            period_end="2026-08-30",
            dry_run=True,
        )
        config = SimpleNamespace(squad="Grooming", feedback_domain="grooming")
        with patch(
            "mfc.commands.dashboard.build_dashboard_snapshot",
            return_value=snapshot,
        ) as build_snapshot:
            result = dashboard_run(args, config)

        self.assertTrue(result["ok"])
        self.assertEqual(3, result["analysis"]["featured"])
        self.assertEqual(3, result["analysis"]["quickWinCandidates"])
        self.assertIn("<h1>周环比</h1>", result["content"])
        self.assertIn("<h1>产品/设计关注点</h1>", result["content"])
        self.assertEqual(1, len(result["detailDocuments"]))
        self.assertNotIn("__CATEGORY_DETAIL_REPORT__", result["content"])
        self.assertNotIn("__QUICK_WIN_DETAIL_REPORT__", result["content"])
        self.assertLess(result["readability"]["parentCharacters"], 12000)
        self.assertGreater(
            result["readability"]["detailCharacters"]["category"], 0
        )
        self.assertTrue(build_snapshot.call_args.kwargs["include_analysis_fields"])
        self.assertFalse(build_snapshot.call_args.kwargs["require_quick_win_review"])

    def test_canny_requires_review_and_duplicate_source_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            canny = self._canny(Path(directory))
            with self.assertRaisesRegex(ConfigError, "quick-win-review"):
                build_dashboard_snapshot(
                    [canny],
                    squad="Grooming",
                    domain="grooming",
                    start=date(2026, 8, 17),
                    end=date(2026, 8, 23),
                )
            with self.assertRaisesRegex(ConfigError, "重复数据源"):
                build_dashboard_snapshot(
                    [canny, canny],
                    squad="Grooming",
                    domain="grooming",
                    start=date(2026, 8, 17),
                    end=date(2026, 8, 23),
                    quick_win_review="missing.json",
                )

    def test_render_marks_missing_sources_and_non_deduplicated_total(self):
        snapshot = {
            "period": {"start": "2026-08-17", "end": "2026-08-23"},
            "squad": "Grooming",
            "domain": "grooming",
            "totalSignals": 3,
            "ruleVersion": "cross-source-dashboard-v7",
            "records": [],
            "sources": [
                {
                    "sourceKey": source,
                    "status": "ready" if source == "canny" else "missing",
                    "collected": 3 if source == "canny" else None,
                    "included": 3 if source == "canny" else None,
                    "breakdown": "Quick Win AI 入选 1"
                    if source == "canny"
                    else "未提供本周期 manifest",
                    "coverage": "测试口径",
                    "reportTitle": None,
                }
                for source in ("canny", "intercom", "jira", "facebook")
            ],
        }
        _year, _month, week = dashboard_titles(
            date(2026, 8, 17), date(2026, 8, 23), "Grooming"
        )
        content = render_dashboard_weekly(snapshot, week)

        self.assertIn("Grooming 反馈总览", content)
        self.assertIn("跨渠道语义去重", content)
        self.assertIn("未提供", content)
        self.assertIn("__SOURCE_REPORTS__", content)

    def test_formal_dashboard_rejects_missing_canny_and_analysis(self):
        args = SimpleNamespace(
            manifest=["intercom.json", "jira.json", "facebook.json"],
            quick_win_review="",
            analysis="",
            analysis_input="",
            allow_partial=False,
            allow_partial_period=False,
            period_start="2026-08-17",
            period_end="2026-08-23",
            dry_run=True,
        )
        snapshot = {
            "period": {"start": "2026-08-17", "end": "2026-08-23"},
            "missingSources": ["canny"],
            "emptySources": [],
        }
        config = SimpleNamespace(squad="Grooming", feedback_domain="grooming")
        with (
            patch(
                "mfc.commands.dashboard.build_dashboard_snapshot",
                return_value=snapshot,
            ),
            self.assertRaisesRegex(ConfigError, "canny"),
        ):
            dashboard_run(args, config)

        snapshot["missingSources"] = []
        snapshot["emptySources"] = ["jira"]
        with (
            patch(
                "mfc.commands.dashboard.build_dashboard_snapshot",
                return_value=snapshot,
            ),
            self.assertRaisesRegex(ConfigError, "无数据：jira"),
        ):
            dashboard_run(args, config)

        snapshot["emptySources"] = []
        with (
            patch(
                "mfc.commands.dashboard.build_dashboard_snapshot",
                return_value=snapshot,
            ),
            self.assertRaisesRegex(ConfigError, "--analysis"),
        ):
            dashboard_run(args, config)

    def test_partial_mode_is_dry_run_only(self):
        args = SimpleNamespace(
            manifest=["canny.json"],
            quick_win_review="review.json",
            analysis="",
            analysis_input="",
            allow_partial=True,
            allow_partial_period=False,
            period_start="2026-08-17",
            period_end="2026-08-23",
            dry_run=False,
        )
        with self.assertRaisesRegex(ConfigError, "只能与 --dry-run"):
            dashboard_run(
                args,
                SimpleNamespace(squad="Grooming", feedback_domain="grooming"),
            )

    def test_month_segment_keeps_present_zero_source_in_formal_dashboard(self):
        args = SimpleNamespace(
            manifest=["canny.json", "intercom.json", "jira.json", "facebook.json"],
            quick_win_review="",
            analysis="",
            analysis_input="",
            allow_partial=False,
            allow_partial_period=False,
            month_segment="2026-08",
            period_start="2026-08-01",
            period_end="2026-08-02",
            dry_run=True,
        )
        snapshot = {
            "period": {"start": "2026-08-01", "end": "2026-08-02"},
            "missingSources": [],
            "emptySources": ["jira"],
        }
        config = SimpleNamespace(squad="Grooming", feedback_domain="grooming")
        with (
            patch(
                "mfc.commands.dashboard.build_dashboard_snapshot",
                return_value=snapshot,
            ),
            self.assertRaisesRegex(ConfigError, "--analysis"),
        ):
            dashboard_run(args, config)


if __name__ == "__main__":
    unittest.main()
