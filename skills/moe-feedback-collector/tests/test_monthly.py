from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))

from mfc.analysis_input import BUSINESS_CATEGORIES, WEEKLY_ANALYSIS_RULE_VERSION
from mfc.errors import ConfigError
from mfc.monthly import (
    MONTHLY_ANALYSIS_RULE_VERSION,
    build_monthly_analysis,
    build_monthly_analysis_input,
    build_monthly_audit,
    coverage_status,
    expected_month_segments,
    load_monthly_analysis,
    render_monthly_dashboard,
)


class MonthlyTests(unittest.TestCase):
    def _page(self, segment, *, end=None):
        actual_end = end or segment["end"]
        title = segment["title"]
        if end:
            title = title.replace(segment["end"][5:].replace("-", "."), end[5:].replace("-", "."))
        return {
            "title": title,
            "isoWeek": segment["isoWeek"],
            "start": segment["start"],
            "end": actual_end,
            "nodeToken": f"node-{segment['isoWeek']}-{actual_end}",
            "documentToken": f"doc-{segment['isoWeek']}-{actual_end}",
            "url": f"https://example.test/wiki/{segment['isoWeek']}-{actual_end}",
            "managed": True,
        }

    def _weekly_analysis(self, segment, count):
        category_counts = {
            category: count + index
            for index, category in enumerate(BUSINESS_CATEGORIES)
        }
        review_count = count % 3
        return {
            "schemaVersion": 3,
            "analysisRule": WEEKLY_ANALYSIS_RULE_VERSION,
            "scope": "Grooming",
            "currentPeriod": {
                "start": segment["start"],
                "end": segment["end"],
            },
            "baselineExport": {
                "artifactId": f"weekly-analysis:grooming:{segment['isoWeek'].lower()}:v4",
                "period": {
                    "start": segment["start"],
                    "end": segment["end"],
                },
                "scope": "Grooming",
                "categories": [
                    {
                        "businessCategory": category,
                        "count": category_counts[category],
                        "representativeEvidence": [],
                    }
                    for category in BUSINESS_CATEGORIES
                ],
                "reviewCount": review_count,
            },
            "categoryOverview": [
                {
                    "businessCategory": category,
                    "currentCount": category_counts[category],
                }
                for category in BUSINESS_CATEGORIES
            ],
            "reviewQueue": {"currentCount": review_count, "previousCount": None},
            "quickWinCandidates": [
                {
                    "title": f"候选 {index}",
                    "businessCategory": BUSINESS_CATEGORIES[
                        index % (len(BUSINESS_CATEGORIES) - 1)
                    ],
                }
                for index in range(count)
            ],
            "summary": [{"text": f"{segment['isoWeek']} 摘要"}],
            "themes": [{"name": "预约", "summary": "预约主题"}],
            "insights": [{"title": "洞察", "observation": "观察"}],
            "recommendations": [{"title": "建议", "action": "行动"}],
        }

    def _ready_audit(self):
        segments = expected_month_segments(
            "2026-08", "Grooming", excluded_dates=["2026-08-31"]
        )
        return build_monthly_audit(
            "2026-08",
            "Grooming",
            [self._page(segment) for segment in segments],
            excluded_dates=["2026-08-31"],
            today=date(2026, 8, 31),
        )

    def test_august_segments_close_at_explicit_exception(self):
        segments = expected_month_segments(
            "2026-08", "Grooming", excluded_dates=["2026-08-31"]
        )

        self.assertEqual(5, len(segments))
        self.assertEqual("2026-08-01", segments[0]["start"])
        self.assertEqual("2026-08-02", segments[0]["end"])
        self.assertEqual("2026-08-24", segments[-1]["start"])
        self.assertEqual("2026-08-30", segments[-1]["end"])
        self.assertEqual(
            "closed-with-exceptions",
            coverage_status(
                "2026-08", ["2026-08-31"], today=date(2026, 8, 31)
            )["status"],
        )

    def test_exclusions_must_be_contiguous_month_suffix(self):
        with self.assertRaisesRegex(ConfigError, "月份末尾连续日期"):
            expected_month_segments(
                "2026-08", "Grooming", excluded_dates=["2026-08-30"]
            )

    def test_leap_month_and_cross_iso_year_segments(self):
        february = expected_month_segments("2028-02", "Grooming")
        december = expected_month_segments("2025-12", "Grooming")

        self.assertEqual("2028-02-29", february[-1]["end"])
        self.assertEqual("2026-W01", december[-1]["isoWeek"])
        self.assertEqual("2025-12-31", december[-1]["end"])

    def test_open_month_is_not_ready_without_covering_exception(self):
        segments = expected_month_segments("2026-08", "Grooming")
        audit = build_monthly_audit(
            "2026-08",
            "Grooming",
            [self._page(segment) for segment in segments],
            today=date(2026, 8, 31),
        )

        self.assertEqual("open-month", audit["coverage"]["status"])
        self.assertFalse(audit["ready"])

    def test_audit_reports_missing_w31_and_incomplete_w35(self):
        segments = expected_month_segments(
            "2026-08", "Grooming", excluded_dates=["2026-08-31"]
        )
        pages = [self._page(item) for item in segments[1:4]]
        pages.append(self._page(segments[4], end="2026-08-28"))

        audit = build_monthly_audit(
            "2026-08",
            "Grooming",
            pages,
            excluded_dates=["2026-08-31"],
            today=date(2026, 8, 31),
        )

        self.assertFalse(audit["ready"])
        self.assertEqual(["2026-W31"], [item["isoWeek"] for item in audit["missingSegments"]])
        self.assertEqual("2026-W35", audit["incompleteSegments"][0]["expected"]["isoWeek"])

    def test_build_and_render_monthly_analysis(self):
        audit = self._ready_audit()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = []
            for index, segment in enumerate(audit["expectedSegments"], start=1):
                path = root / f"week-{index}.json"
                path.write_text(
                    json.dumps(self._weekly_analysis(segment, index), ensure_ascii=False),
                    encoding="utf-8",
                )
                paths.append(str(path))
            monthly_input = build_monthly_analysis_input(paths, audit)
            input_path = root / "monthly-input.json"
            input_path.write_text(
                json.dumps(monthly_input, ensure_ascii=False), encoding="utf-8"
            )
            segment_ids = [
                item["segmentId"] for item in monthly_input["weeklySegments"]
            ]
            model = {
                "schemaVersion": 2,
                "analysisRule": MONTHLY_ANALYSIS_RULE_VERSION,
                "month": "2026-08",
                "scope": "Grooming",
                "executiveSummary": {
                    "headline": "本月预约规则是最持续的产品问题",
                    "points": [
                        {
                            "text": "预约与经营反馈持续出现",
                            "confidence": "high",
                            "segmentIds": segment_ids,
                        },
                        {
                            "text": "Quick Win 需要按分类下钻",
                            "confidence": "medium",
                            "segmentIds": segment_ids[1:],
                        },
                    ],
                },
                "focusItems": [
                    {
                        "title": f"重点 {index}",
                        "observation": "多个周片段持续出现预约规则问题",
                        "whyItMatters": "规则分散会造成跨入口结果不一致",
                        "action": "建立跨入口规则矩阵",
                        "businessCategories": ["scheduling"],
                        "confidence": "high",
                        "segmentIds": segment_ids,
                    }
                    for index in range(1, 4)
                ],
                "weeklyHighlights": [
                    {
                        "segmentId": segment_id,
                        "headline": f"{segment_id.split(':')[0]} 重点",
                        "summary": "本周重点反馈摘要",
                        "confidence": "high",
                    }
                    for segment_id in segment_ids
                ],
            }
            model_path = root / "model.json"
            model_path.write_text(json.dumps(model, ensure_ascii=False), encoding="utf-8")
            analysis = build_monthly_analysis(str(input_path), str(model_path))
            analysis_path = root / "analysis.json"
            analysis_path.write_text(
                json.dumps(analysis, ensure_ascii=False), encoding="utf-8"
            )

            verified = load_monthly_analysis(str(analysis_path), monthly_input)
            content = render_monthly_dashboard(monthly_input, verified)

            tampered = dict(analysis)
            tampered["totalSignals"] += 1
            analysis_path.write_text(
                json.dumps(tampered, ensure_ascii=False), encoding="utf-8"
            )
            with self.assertRaisesRegex(ConfigError, "确定性字段"):
                load_monthly_analysis(str(analysis_path), monthly_input)

        self.assertEqual(5, len(verified["weeklySegments"]))
        self.assertEqual(sum(range(1, 6)), verified["quickWinCandidateOccurrences"])
        self.assertEqual(
            verified["quickWinCandidateOccurrences"],
            sum(verified["quickWinCategoryOccurrences"].values()),
        )
        self.assertEqual(
            verified["totalSignals"],
            verified["classifiedSignals"] + verified["reviewQueueTotal"],
        )
        self.assertIn("MFC_MANAGED_MONTHLY_V1", content)
        self.assertIn("2026-08-31", content)
        self.assertIn("本月最重要的三件事", content)
        self.assertIn("周度脉络", content)
        self.assertIn("分类与 Quick Win", content)
        self.assertIn("周报入口与口径", content)
        self.assertNotIn(segment_ids[0], content)
        self.assertGreater(
            content.index("MFC_MANAGED_MONTHLY_V1"),
            content.index("周报入口与口径"),
        )

    def test_monthly_highlights_must_cover_each_segment_in_order(self):
        audit = self._ready_audit()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = []
            for index, segment in enumerate(audit["expectedSegments"], start=1):
                path = root / f"week-{index}.json"
                path.write_text(
                    json.dumps(self._weekly_analysis(segment, index), ensure_ascii=False),
                    encoding="utf-8",
                )
                paths.append(str(path))
            monthly_input = build_monthly_analysis_input(paths, audit)
            input_path = root / "monthly-input.json"
            input_path.write_text(
                json.dumps(monthly_input, ensure_ascii=False), encoding="utf-8"
            )
            segment_ids = [
                item["segmentId"] for item in monthly_input["weeklySegments"]
            ]
            model = {
                "schemaVersion": 2,
                "analysisRule": MONTHLY_ANALYSIS_RULE_VERSION,
                "month": "2026-08",
                "scope": "Grooming",
                "executiveSummary": {
                    "headline": "月度结论",
                    "points": [
                        {
                            "text": "结论一",
                            "confidence": "high",
                            "segmentIds": segment_ids,
                        },
                        {
                            "text": "结论二",
                            "confidence": "medium",
                            "segmentIds": segment_ids,
                        },
                    ],
                },
                "focusItems": [
                    {
                        "title": f"重点 {index}",
                        "observation": "观察",
                        "whyItMatters": "原因",
                        "action": "动作",
                        "businessCategories": ["scheduling"],
                        "confidence": "high",
                        "segmentIds": segment_ids,
                    }
                    for index in range(1, 4)
                ],
                "weeklyHighlights": [
                    {
                        "segmentId": segment_id,
                        "headline": "重点",
                        "summary": "摘要",
                        "confidence": "high",
                    }
                    for segment_id in reversed(segment_ids)
                ],
            }
            model_path = root / "model.json"
            model_path.write_text(json.dumps(model, ensure_ascii=False), encoding="utf-8")

            with self.assertRaisesRegex(ConfigError, "顺序或覆盖"):
                build_monthly_analysis(str(input_path), str(model_path))


if __name__ == "__main__":
    unittest.main()
