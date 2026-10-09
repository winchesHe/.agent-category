import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))

from mfc.config import _find_moe_mis, load_config
from mfc.errors import ConfigError
from mfc.schema import describe_schema

SKILL_ROOT = Path(__file__).parents[1]
DEFAULT_WIKI_URL = (
    "https://mengshikeji.feishu.cn/wiki/OjbbwLwfPikMF7kQBPWcEE0Lnjb"
)


class ConfigSchemaTests(unittest.TestCase):
    def test_invalid_explicit_moe_mis_root_is_fail_closed(self):
        with patch.dict(
            os.environ,
            {"MOE_MIS_SKILL": "/definitely/missing/moe-mis"},
            clear=False,
        ), self.assertRaisesRegex(ConfigError, "MOE_MIS_SKILL"):
            _find_moe_mis(SKILL_ROOT)

    def test_env_example_contains_publish_configuration(self):
        lines = (SKILL_ROOT / ".env.example").read_text(encoding="utf-8").splitlines()

        self.assertEqual(
            [
                f"MFC_LARK_WIKI_URL={DEFAULT_WIKI_URL}",
                "MFC_SQUAD=Grooming",
                "MFC_DOMAIN=grooming",
                "MFC_FACEBOOK_SLACK_CHANNEL=C0BEL8Y0Y74",
            ],
            lines,
        )

    def test_legacy_environment_settings_do_not_override_internal_defaults(self):
        environment = {
            "MFC_LARK_WIKI_URL": DEFAULT_WIKI_URL,
            "MFC_CANNY_BOARD_URL": "https://example.com/board",
            "MFC_CANNY_MIN_VOTE": "999",
            "MFC_CANNY_PAGE_CAP": "1",
            "MFC_SQUAD": "  Grooming  ",
            "MFC_DOMAIN": "scheduling",
            "MFC_FACEBOOK_SLACK_CHANNEL": "C012ABCDEF",
        }
        with patch.dict(os.environ, environment, clear=False):
            config = load_config()

        self.assertEqual("https://moego.canny.io/feature-request", config.canny_board_url)
        self.assertEqual(3, config.min_vote)
        self.assertEqual(32, config.page_cap)
        self.assertFalse(hasattr(config, "lark_base_url"))
        self.assertFalse(hasattr(config, "canny_account_ref"))
        self.assertTrue(str(config.datadog_script).endswith("datadog/scripts/datadog.py"))
        self.assertEqual("Grooming", config.squad)
        self.assertEqual("scheduling", config.feedback_domain)
        self.assertEqual("C012ABCDEF", config.facebook_slack_channel)
        self.assertTrue(str(config.slack_script).endswith("slack/scripts/slack.py"))

    def test_empty_process_squad_overrides_nonempty_cwd_env(self):
        with tempfile.TemporaryDirectory() as directory:
            Path(directory, ".env").write_text(
                "MFC_SQUAD=Grooming\n",
                encoding="utf-8",
            )
            with (
                patch("mfc.config.Path.cwd", return_value=Path(directory)),
                patch.dict(os.environ, {"MFC_SQUAD": ""}, clear=False),
            ):
                config = load_config()

        self.assertEqual("", config.squad)

    def test_legacy_intercom_squad_is_not_supported(self):
        with patch.dict(
            os.environ,
            {
                "MFC_LARK_WIKI_URL": DEFAULT_WIKI_URL,
                "MFC_INTERCOM_SQUAD": "Grooming",
            },
            clear=True,
        ):
            config = load_config()

        self.assertEqual("", config.squad)

    def test_empty_process_domain_does_not_fall_back_to_cwd_env(self):
        with tempfile.TemporaryDirectory() as directory:
            Path(directory, ".env").write_text(
                "MFC_DOMAIN=grooming\n",
                encoding="utf-8",
            )
            with (
                patch("mfc.config.Path.cwd", return_value=Path(directory)),
                patch.dict(os.environ, {"MFC_DOMAIN": ""}, clear=False),
                self.assertRaisesRegex(ConfigError, "MFC_DOMAIN"),
            ):
                load_config()

    def test_rejects_invalid_facebook_channel_id(self):
        with patch.dict(
            os.environ,
            {"MFC_FACEBOOK_SLACK_CHANNEL": "community-pending-posts"},
            clear=False,
        ), self.assertRaisesRegex(ConfigError, "Slack 频道 ID"):
            load_config()

    def test_schema_exposes_week_dashboard_with_four_source_children(self):
        design = describe_schema()

        self.assertEqual(17, design["schemaVersion"])
        self.assertEqual(
            [
                "<年份>",
                "<月份>",
                "<YYYY-MM｜范围 反馈重点汇总>",
                "<ISO 周反馈总览｜范围>",
                "<Canny|Intercom|Jira|Facebook 来源看板>",
                "<分类与主题明细>",
            ],
            design["wikiStructure"],
        )
        self.assertEqual("wiki-weekly-documents", design["storage"])
        self.assertEqual(
            "来源入选数相加，跨来源未去重",
            design["dashboard"]["totalPolicy"],
        )
        self.assertEqual(
            ["canny", "intercom", "jira", "facebook"],
            design["dashboard"]["sourceChildren"],
        )
        self.assertEqual(
            ["category"],
            design["dashboard"]["analysisChildren"],
        )
        self.assertEqual(
            "四源均有入选数据 + AI analysis + 四个来源子看板；Canny 来源子看板包含来源专用 AI 复筛",
            design["dashboard"]["formalCompleteness"],
        )
        self.assertEqual(
            "cross-source-dashboard-v10", design["dashboard"]["ruleVersion"]
        )
        self.assertIn("parent", design["dashboard"]["readingLayers"])
        self.assertEqual(
            [
                "周环比",
                "本周反馈概览",
                "产品/设计关注点",
                "Quick Win 候选",
                "原始证据",
            ],
            design["dashboard"]["sections"],
        )
        self.assertEqual(2, design["dashboard"]["analysis"]["schemaVersion"])
        self.assertEqual(1, design["dashboard"]["analysisInput"]["schemaVersion"])
        self.assertEqual(
            "analysis-input", design["dashboard"]["analysisInput"]["command"]
        )
        self.assertEqual(
            [
                "quickWinSelected",
                "businessCategory",
                "auxiliaryCategories",
                "classificationConfidence",
            ],
            design["dashboard"]["analysisInput"]["excludedFields"],
        )
        self.assertEqual(
            "analysis-prompt", design["dashboard"]["analysisBuild"]["promptCommand"]
        )
        self.assertEqual(
            "analysis-build", design["dashboard"]["analysisBuild"]["buildCommand"]
        )
        self.assertEqual(3, design["dashboard"]["analysisBuild"]["finalSchemaVersion"])
        self.assertEqual(
            "逐条覆盖本周四源全部 records",
            design["dashboard"]["analysisBuild"]["quickWin"]["coverage"],
        )
        self.assertEqual(
            ["本周概览", "Quick Win 候选", "Canny 源数据"],
            design["weeklyDocument"]["sections"],
        )
        self.assertNotIn("tables", design)
        self.assertEqual("canny-qw-v2", design["weeklyDocument"]["quickWin"]["ruleVersion"])
        self.assertEqual(
            "只展示周期内新增；全量基线仅保存在本地状态",
            design["weeklyDocument"]["sourcePolicy"]["firstRun"],
        )
        self.assertEqual(
            ["email", "conversation_id", "quote"],
            design["sources"]["intercom"]["forbiddenFields"],
        )
        self.assertEqual(
            ["feature_feedback", "feature_request"],
            design["sources"]["intercom"]["publish"]["feedbackTypes"],
        )
        self.assertEqual(
            "MFC_SQUAD",
            design["sources"]["intercom"]["publish"]["squadConfig"],
        )
        self.assertEqual(
            "MFC_SQUAD",
            design["sources"]["jira"]["publish"]["squadConfig"],
        )
        self.assertEqual(
            {"project": "DES", "issueType": "Design Issue"},
            design["sources"]["jira"]["publish"]["selection"]["designTarget"],
        )
        self.assertEqual(
            "channel-summary", design["sources"]["facebook"]["coverage"]
        )
        self.assertEqual(
            "同周期周总看板",
            design["sources"]["facebook"]["publish"]["parent"],
        )
        self.assertEqual(
            [
                "group_post",
                "campaign_comment_summary",
                "group_comment_summary",
            ],
            design["sources"]["facebook"]["feeds"],
        )
        self.assertEqual("monthly-dashboard", design["monthlyDocument"]["command"])
        self.assertEqual(
            "MFC_MANAGED_MONTHLY_V1",
            design["monthlyDocument"]["managedMarker"],
        )
        self.assertEqual(
            "grooming-monthly-analysis-v2",
            design["monthlyDocument"]["ruleVersion"],
        )
        self.assertEqual(
            [
                "本月结论",
                "本月最重要的三件事",
                "周度脉络",
                "分类与 Quick Win",
                "周报入口与口径",
            ],
            design["monthlyDocument"]["sections"],
        )
        self.assertFalse(
            design["monthlyDocument"]["deduplication"]["crossWeek"]
        )


if __name__ == "__main__":
    unittest.main()
