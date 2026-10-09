import importlib.util
import json
import re
import unittest
from copy import deepcopy
from pathlib import Path


SCRIPT_PATH = Path(__file__).parents[1] / "scripts" / "render_grooming_ops_review.py"
SPEC = importlib.util.spec_from_file_location("render_grooming_ops_review", SCRIPT_PATH)
RENDERER = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(RENDERER)


class OverallSummaryRenderingTest(unittest.TestCase):
    def setUp(self) -> None:
        self.pack = {
            "report": {
                "title": "Grooming Ops Review",
                "period": "2026-07-11 至 2026-07-24",
                "target_business": "Grooming only",
                "generated_at": "2026-07-25T15:30:00+08:00",
            },
            "overall_summary": [
                "增长承压：new signup 较上一双周下降 9.3%。",
                {
                    "conclusion": "客户处理队列从 10 增至 14，需要优先收敛。",
                    "emphasis": [
                        {"text": "从 10 增至 14", "color": "red"},
                        {"text": "优先收敛", "color": "orange"},
                    ],
                },
                {
                    "conclusion": "New signup dropped 9.3% and needs review.",
                    "emphasis": [{"text": "dropped 9.3%", "color": "red"}],
                },
            ],
            "sections": {key: {} for key in RENDERER.REQUIRED_SECTIONS},
            "traceability": [],
            "meeting_notes": [],
            "open_questions": [],
        }

    def test_markdown_starts_with_summary_without_internal_report_header(self) -> None:
        rendered = RENDERER.render_markdown(self.pack)

        self.assertTrue(rendered.startswith("## Overall Summary / 总览"))
        self.assertNotIn("# Grooming Ops Review", rendered)
        self.assertNotIn("目标：", rendered)
        self.assertNotIn("生成时间：", rendered)
        self.assertIn("- **增长承压：**new signup 较上一双周下降 9.3%。", rendered)
        self.assertIn("**从 10 增至 14**", rendered)
        self.assertIn("**优先收敛**", rendered)
        self.assertIn("New signup **dropped 9.3%** and needs review.", rendered)

    def test_xml_keeps_page_title_and_removes_duplicate_intro(self) -> None:
        rendered = RENDERER.render_xml(self.pack)

        self.assertTrue(rendered.startswith("<title>Grooming Ops Review - 2026-07-11 至 2026-07-24</title>"))
        self.assertNotIn("<h1>", rendered)
        self.assertNotIn("目标：", rendered)
        self.assertNotIn("生成时间：", rendered)
        self.assertIn(
            '<b><span text-color="blue">增长承压：</span></b>',
            rendered,
        )
        self.assertIn(
            '<b><span text-color="red">从 10 增至 14</span></b>',
            rendered,
        )
        self.assertIn(
            '<b><span text-color="orange">优先收敛</span></b>',
            rendered,
        )

    def test_every_markdown_h2_is_followed_by_one_section_description(self) -> None:
        rendered = RENDERER.render_markdown(self.pack)
        matches = re.findall(r"^## (.+)\n> (.+)$", rendered, flags=re.MULTILINE)

        self.assertEqual(len(matches), 11)
        self.assertEqual(
            [title for title, _description in matches],
            list(RENDERER.SECTION_DESCRIPTIONS),
        )
        self.assertIn(
            (
                "Onboarding / 激活",
                "观察新注册或新订阅商家从初始设置到首次获得业务价值的效率，定位激活过程中的阻塞环节。",
            ),
            matches,
        )

    def test_every_xml_h2_is_followed_by_one_gray_section_description(self) -> None:
        rendered = RENDERER.render_xml(self.pack)
        matches = re.findall(
            r"<h2>(.*?)</h2><p><span text-color=\"gray\">(.*?)</span></p>",
            rendered,
        )

        self.assertEqual(len(matches), 11)
        self.assertEqual(
            [title.replace("&amp;", "&") for title, _description in matches],
            list(RENDERER.SECTION_DESCRIPTIONS),
        )
        self.assertIn(
            (
                "Onboarding / 激活",
                "观察新注册或新订阅商家从初始设置到首次获得业务价值的效率，定位激活过程中的阻塞环节。",
            ),
            matches,
        )

    def test_traceability_is_the_last_section_in_both_formats(self) -> None:
        markdown = RENDERER.render_markdown(self.pack)
        markdown_titles = re.findall(r"^## (.+)$", markdown, flags=re.MULTILINE)
        self.assertEqual(
            markdown_titles[-2:],
            [
                "Meeting Notes / Open Questions / 会议讨论与待开放问题",
                "Data Source & Traceability / 数据源与可追溯性",
            ],
        )

        xml = RENDERER.render_xml(self.pack)
        xml_titles = [title.replace("&amp;", "&") for title in re.findall(r"<h2>(.*?)</h2>", xml)]
        self.assertEqual(
            xml_titles[-2:],
            [
                "Meeting Notes / Open Questions / 会议讨论与待开放问题",
                "Data Source & Traceability / 数据源与可追溯性",
            ],
        )


class TraceabilityRenderingTest(unittest.TestCase):
    def setUp(self) -> None:
        self.items = [
            {
                "source_id": "posthog_daily_metrics_upload",
                "source_type": "posthog_hogql",
                "title": "dailyMetricsUpload aggregation",
                "source_url": "https://example.com/posthog",
                "query_or_filter": "current biweekly window",
                "retrieved_at": "2026-07-25T15:10:00+08:00",
                "owner": "PostHog dashboard",
            },
            {
                "source_id": "manual_nps_collection_policy",
                "source_type": "manual_policy",
                "title": "Grooming-only NPS collection policy",
                "source_url": "",
                "query_or_filter": "NPS official is collected manually",
                "retrieved_at": "2026-07-25T15:25:00+08:00",
                "owner": "PM / CS",
            },
        ]

    def test_markdown_hides_internal_source_columns(self) -> None:
        rendered = RENDERER.md_traceability(self.items)

        self.assertIn("| 标题 | 查询 / 过滤条件 | 拉取时间 | Owner |", rendered)
        self.assertIn("2026-07-25 15:10", rendered)
        self.assertNotIn("2026-07-25T15:10:00+08:00", rendered)
        self.assertNotIn("Source ID", rendered)
        self.assertNotIn("| 类型 |", rendered)
        self.assertNotIn("posthog_daily_metrics_upload", rendered)
        self.assertNotIn("posthog_hogql", rendered)
        self.assertNotIn("Grooming-only NPS collection policy", rendered)

    def test_xml_hides_internal_source_columns(self) -> None:
        rendered = RENDERER.render_traceability(self.items)

        self.assertIn('<th background-color="light-gray">标题</th>', rendered)
        self.assertIn("<td>2026-07-25 15:10</td>", rendered)
        self.assertNotIn("2026-07-25T15:10:00+08:00", rendered)
        self.assertNotIn("Source ID", rendered)
        self.assertNotIn(">类型<", rendered)
        self.assertNotIn("posthog_daily_metrics_upload", rendered)
        self.assertNotIn("posthog_hogql", rendered)
        self.assertNotIn("Grooming-only NPS collection policy", rendered)
        self.assertIn('<a href="https://example.com/posthog">dailyMetricsUpload aggregation</a>', rendered)

    def test_retrieved_at_is_converted_to_beijing_time(self) -> None:
        self.assertEqual(RENDERER.format_retrieved_at("2026-07-25T07:10:00Z"), "2026-07-25 15:10")
        self.assertEqual(RENDERER.format_retrieved_at("2026-07-25T15:10:00+08:00"), "2026-07-25 15:10")


class OnboardingValidationTest(unittest.TestCase):
    def setUp(self) -> None:
        example_path = SCRIPT_PATH.parents[1] / "assets" / "grooming-evidence.example.json"
        self.pack = json.loads(example_path.read_text(encoding="utf-8"))
        source = next(
            item
            for item in self.pack["traceability"]
            if item["source_id"] == "posthog_grooming_dashboard"
        )
        source["title"] = "dailyMetricsUpload onboarding aggregation"
        source["query_or_filter"] = "event=dailyMetricsUpload; company-level onboarding cohort"

    def test_daily_metrics_onboarding_cannot_fall_back_to_proxy_only(self) -> None:
        self.pack["sections"]["onboarding"]["proxy_only"] = True

        errors = RENDERER.validate_pack(self.pack)

        self.assertIn(
            "sections.onboarding must set proxy_only=false when dailyMetricsUpload onboarding metrics are available",
            errors,
        )

    def test_daily_metrics_onboarding_requires_three_primary_metric_groups(self) -> None:
        self.pack["sections"]["onboarding"]["metrics"] = []

        errors = RENDERER.validate_pack(self.pack)

        self.assertIn("sections.onboarding is missing primary metric: Days to first value", errors)
        self.assertIn("sections.onboarding is missing primary metric: Go-live rate", errors)
        self.assertIn("sections.onboarding is missing primary metric: Key feature first-use rate", errors)


class CustomerExampleRenderingAndValidationTest(unittest.TestCase):
    def setUp(self) -> None:
        example_path = SCRIPT_PATH.parents[1] / "assets" / "grooming-evidence.example.json"
        self.pack = json.loads(example_path.read_text(encoding="utf-8"))

    def test_customer_feedback_and_bug_tables_have_separate_example_column_and_links(self) -> None:
        markdown = RENDERER.render_markdown(self.pack)
        xml = RENDERER.render_xml(self.pack)

        markdown_header = "| 主题 | 数据 | 洞察 | 客户原话 example（匿名） | 团队关注 |"
        xml_header = '<th background-color="light-gray">客户原话 example（匿名）</th>'
        self.assertEqual(markdown.count(markdown_header), 2)
        self.assertEqual(xml.count(xml_header), 2)
        self.assertIn(
            "出处：[CS-46790（客户工单）](https://moego.atlassian.net/browse/CS-46790)",
            markdown,
        )
        self.assertIn(
            '<a href="https://moego.atlassian.net/browse/GRM-2244">GRM-2244（修复单）</a>',
            xml,
        )

    def test_other_sections_keep_the_standard_four_column_insight_table(self) -> None:
        insight = deepcopy(self.pack["sections"]["growth"]["insights"])

        markdown = RENDERER.md_insights(insight)
        xml = RENDERER.render_insights(insight)

        self.assertIn("| 主题 | 数据 | 洞察 | 团队关注 |", markdown)
        self.assertNotIn("客户原话 example", markdown)
        self.assertNotIn("客户原话 example", xml)

    def test_customer_feedback_insight_requires_a_customer_example(self) -> None:
        del self.pack["sections"]["customer_feedback"]["insights"][0]["customer_examples"]

        errors = RENDERER.validate_pack(self.pack)

        self.assertIn(
            "sections.customer_feedback.insights[1].customer_examples must be a non-empty list",
            errors,
        )

    def test_each_customer_example_requires_a_valid_source_link(self) -> None:
        example = self.pack["sections"]["bug_tickets"]["insights"][0]["customer_examples"][0]
        example["sources"] = [{"label": "CS-49541", "url": "CS-49541"}]

        errors = RENDERER.validate_pack(self.pack)

        self.assertIn(
            "sections.bug_tickets.insights[1].customer_examples[1].sources[1].url must be an http(s) link",
            errors,
        )

    def test_paraphrase_is_explicitly_labeled_in_both_formats(self) -> None:
        insight = self.pack["sections"]["bug_tickets"]["insights"]

        markdown = RENDERER.md_insights(insight, include_customer_examples=True)
        xml = RENDERER.render_insights(insight, include_customer_examples=True)

        self.assertIn("匿名转述：", markdown)
        self.assertIn("匿名转述：", xml)


if __name__ == "__main__":
    unittest.main()
