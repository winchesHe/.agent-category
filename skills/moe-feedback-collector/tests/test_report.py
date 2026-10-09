import json
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))

from mfc.report import (
    apply_quick_win_rule,
    choose_report_rows,
    intercom_report_titles,
    load_quick_win_review,
    parse_period,
    render_intercom_source_documents,
    render_intercom_weekly_report,
    render_source_documents,
    render_weekly_report,
    report_titles,
    select_intercom_rows,
)
from mfc.errors import BusinessError, ConfigError


class ReportTests(unittest.TestCase):
    def setUp(self):
        self.posts = [
            {
                "sourceObjectId": "in-week",
                "objectType": "post",
                "title": "批量操作预约",
                "createdAt": "2026-08-20T08:00:00Z",
                "sourceUrl": "https://moego.canny.io/feature-request/p/batch",
                "voteCount": 12,
                "commentCount": 2,
                "status": "open",
                "changeKind": "baseline",
                "quickWinPrefilter": True,
                "quickWinSignals": ["Vote 12 ≥ 3"],
            },
            {
                "sourceObjectId": "old",
                "objectType": "post",
                "title": "历史需求",
                "createdAt": "2026-08-01T08:00:00Z",
                "sourceUrl": "https://moego.canny.io/feature-request/p/old",
                "voteCount": 3,
                "commentCount": 0,
                "status": "open",
                "changeKind": "baseline",
                "quickWinPrefilter": False,
                "quickWinSignals": [],
            },
        ]

    def test_partial_period_requires_explicit_opt_in(self):
        with self.assertRaisesRegex(ConfigError, "正好为 7 天"):
            parse_period("2026-08-24", "2026-08-28")

        self.assertEqual(
            (date(2026, 8, 24), date(2026, 8, 28)),
            parse_period(
                "2026-08-24",
                "2026-08-28",
                allow_partial_period=True,
            ),
        )

    def test_partial_period_must_start_on_monday_and_not_cross_week(self):
        for start, end in (
            ("2026-08-25", "2026-08-28"),
            ("2026-08-24", "2026-08-31"),
        ):
            with self.subTest(start=start, end=end):
                with self.assertRaisesRegex(ConfigError, "不能跨自然周"):
                    parse_period(start, end, allow_partial_period=True)

    def test_month_segment_accepts_only_exact_month_week_intersection(self):
        self.assertEqual(
            (date(2026, 8, 1), date(2026, 8, 2)),
            parse_period(
                "2026-08-01",
                "2026-08-02",
                month_segment="2026-08",
            ),
        )
        self.assertEqual(
            (date(2026, 8, 31), date(2026, 8, 31)),
            parse_period(
                "2026-08-31",
                "2026-08-31",
                month_segment="2026-08",
            ),
        )
        with self.assertRaisesRegex(ConfigError, "精确等于"):
            parse_period(
                "2026-08-24",
                "2026-08-28",
                month_segment="2026-08",
            )

    def test_month_segment_cannot_combine_with_legacy_partial_flag(self):
        with self.assertRaisesRegex(ConfigError, "不能与"):
            parse_period(
                "2026-08-01",
                "2026-08-02",
                allow_partial_period=True,
                month_segment="2026-08",
            )

    def test_report_only_returns_period_rows_and_marks_them_as_weekly_new(self):
        weekly = choose_report_rows(
            {
                "baseline": False,
                "period": {"start": "2026-08-17", "end": "2026-08-23"},
            },
            self.posts,
            [self.posts[1]],
            date(2026, 8, 17),
            date(2026, 8, 23),
        )

        self.assertEqual(["in-week"], [item["sourceObjectId"] for item in weekly])
        self.assertTrue(weekly[0]["isNew"])
        self.assertEqual("new", weekly[0]["changeKind"])

    def test_canny_manifest_period_must_match_requested_week(self):
        with self.assertRaisesRegex(BusinessError, "Canny manifest 采集周期不一致"):
            choose_report_rows(
                {
                    "baseline": False,
                    "period": {"start": "2026-08-10", "end": "2026-08-16"},
                },
                self.posts,
                self.posts,
                date(2026, 8, 17),
                date(2026, 8, 23),
            )

    def test_current_quick_win_rule_recomputes_old_artifact(self):
        rows = apply_quick_win_rule(self.posts)

        self.assertTrue(rows[1]["quickWinPrefilter"])
        self.assertEqual(["Vote 3 ≥ 3"], rows[1]["quickWinSignals"])

    def test_quick_win_review_requires_reason_and_candidate(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "review.json"
            path.write_text(
                json.dumps(
                    [
                        {
                            "sourceObjectId": "in-week",
                            "selected": True,
                            "reason": "需求明确且范围集中",
                        }
                    ]
                ),
                encoding="utf-8",
            )
            selected = load_quick_win_review(path, [self.posts[0]])

        self.assertEqual({"in-week": "需求明确且范围集中"}, selected)

    def test_render_contains_weekly_sections_and_baseline_notice(self):
        _, _, title = report_titles(date(2026, 8, 17), date(2026, 8, 23))
        content = render_weekly_report(
            manifest={"baseline": True},
            weekly_rows=[self.posts[0]],
            decisions={"in-week": "需求明确且范围集中"},
            start=date(2026, 8, 17),
            end=date(2026, 8, 23),
            week_title=title,
        )

        self.assertIn("Quick Win 候选", content)
        self.assertIn("Canny 源数据", content)
        self.assertNotIn("规则信号", content)
        self.assertNotIn("初始全量基线", content)
        self.assertIn("无法还原老 Post", content)

    def test_large_source_can_split_into_readable_child_documents(self):
        documents = render_source_documents(
            self.posts,
            "2026-W34｜Canny 用户反馈",
            label="上周新增",
            chunk_size=1,
        )

        self.assertEqual(2, len(documents))
        self.assertIn("源数据｜上周新增", documents[0]["title"])
        self.assertNotIn("初始全量基线", "".join(item["title"] for item in documents))
        self.assertIn("blockquote", documents[0]["content"])
        self.assertIn("查看原文", documents[0]["content"])

    def test_intercom_selection_uses_exact_squad_and_feature_types(self):
        feedback = [
            {
                "sourceObjectId": "feedback",
                "objectType": "feedback",
                "createdAt": "2026-08-20T08:00:00Z",
                "requirement": "反馈现有功能不好用",
                "squad": "grooming",
                "feedbackType": "feature_feedback",
            },
            {
                "sourceObjectId": "request",
                "objectType": "feedback",
                "createdAt": "2026-08-21T08:00:00Z",
                "requirement": "希望增加批量预约",
                "squad": "Grooming",
                "feedbackType": "feature_request",
            },
            {
                "sourceObjectId": "bug",
                "objectType": "feedback",
                "createdAt": "2026-08-22T08:00:00Z",
                "requirement": "页面报错",
                "squad": "Grooming",
                "feedbackType": "bug",
            },
            {
                "sourceObjectId": "boarding",
                "objectType": "feedback",
                "createdAt": "2026-08-22T08:00:00Z",
                "requirement": "Boarding 需求",
                "squad": "Boarding",
                "feedbackType": "feature_request",
            },
        ]
        manifest = {
            "sourceKey": "intercom",
            "mode": "period",
            "period": {"start": "2026-08-17", "end": "2026-08-23"},
        }

        selected, counts = select_intercom_rows(
            manifest,
            feedback,
            "Grooming",
            date(2026, 8, 17),
            date(2026, 8, 23),
        )

        self.assertEqual(
            ["feedback", "request"],
            [item["sourceObjectId"] for item in selected],
        )
        self.assertEqual(
            {
                "inputRows": 4,
                "squadRows": 3,
                "selectedRows": 2,
                "excludedBySquad": 1,
                "excludedByType": 1,
                "featureFeedback": 1,
                "featureRequest": 1,
            },
            counts,
        )

    def test_intercom_report_has_two_sections_and_traceable_filter(self):
        rows = [
            {
                "createdAt": "2026-08-20T08:00:00Z",
                "requirement": "希望支持批量预约",
                "domain": "Grooming Calendar",
                "sentiment": "negative",
                "businessType": "Grooming",
                "role": "Owner",
                "stripePlan": "Growth",
                "feedbackType": "feature_request",
            }
        ]
        counts = {
            "inputRows": 10,
            "squadRows": 8,
            "selectedRows": 1,
            "excludedBySquad": 2,
            "excludedByType": 7,
            "featureFeedback": 0,
            "featureRequest": 1,
        }
        _, _, title = intercom_report_titles(
            date(2026, 8, 17), date(2026, 8, 23), "Grooming"
        )

        content = render_intercom_weekly_report(
            rows=rows,
            counts=counts,
            squad="Grooming",
            start=date(2026, 8, 17),
            end=date(2026, 8, 23),
            week_title=title,
        )

        self.assertIn("一、功能反馈", content)
        self.assertIn("二、功能需求", content)
        self.assertIn("Squad 精确匹配", content)
        self.assertIn("feature_feedback", content)
        self.assertIn("希望支持批量预约", content)
        self.assertIn("Intercom 用户反馈｜Grooming", title)

    def test_intercom_large_report_splits_documents_by_feedback_type(self):
        rows = [
            {
                "createdAt": "2026-08-20T08:00:00Z",
                "requirement": f"需求 {index}",
                "feedbackType": (
                    "feature_feedback" if index < 2 else "feature_request"
                ),
            }
            for index in range(5)
        ]

        documents = render_intercom_source_documents(
            rows,
            "2026-W34｜Intercom 用户反馈｜Grooming",
            "Grooming",
            chunk_size=2,
        )

        self.assertEqual(3, len(documents))
        self.assertEqual("Intercom｜Grooming｜功能反馈｜1-2", documents[0]["title"])
        self.assertEqual("Intercom｜Grooming｜功能需求｜1-2", documents[1]["title"])
        self.assertEqual("Intercom｜Grooming｜功能需求｜3-3", documents[2]["title"])


if __name__ == "__main__":
    unittest.main()
