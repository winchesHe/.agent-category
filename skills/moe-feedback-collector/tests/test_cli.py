import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))

from moe_feedback_collector import build_parser


class CliTests(unittest.TestCase):
    def test_collect_contract(self):
        args = build_parser().parse_args(
            ["collect", "--source", "canny", "--mode", "incremental"]
        )
        self.assertEqual("canny", args.source)
        self.assertEqual("local", args.sink)

    def test_intercom_collect_contract(self):
        args = build_parser().parse_args(
            [
                "collect",
                "--source",
                "intercom",
                "--mode",
                "period",
                "--period-start",
                "2026-08-17",
                "--period-end",
                "2026-08-23",
            ]
        )
        self.assertEqual("intercom", args.source)
        self.assertEqual("period", args.mode)
        self.assertEqual("2026-08-17", args.period_start)

    def test_publish_contract(self):
        args = build_parser().parse_args(
            [
                "publish",
                "--source",
                "canny",
                "--manifest",
                "/tmp/run.json",
                "--quick-win-review",
                "/tmp/review.json",
            ]
        )
        self.assertEqual("canny", args.source)
        self.assertFalse(args.dry_run)

    def test_intercom_publish_contract_does_not_require_quick_win_review(self):
        args = build_parser().parse_args(
            [
                "publish",
                "--source",
                "intercom",
                "--manifest",
                "/tmp/run.json",
                "--dry-run",
            ]
        )

        self.assertEqual("intercom", args.source)
        self.assertEqual("", args.quick_win_review)
        self.assertTrue(args.dry_run)

    def test_jira_collect_and_publish_contract(self):
        collected = build_parser().parse_args(
            ["collect", "--source", "jira", "--mode", "period"]
        )
        published = build_parser().parse_args(
            [
                "publish",
                "--source",
                "jira",
                "--manifest",
                "/tmp/run.json",
                "--dry-run",
            ]
        )

        self.assertEqual("jira", collected.source)
        self.assertEqual("period", collected.mode)
        self.assertEqual("jira", published.source)
        self.assertEqual("", published.quick_win_review)

    def test_facebook_collect_contract(self):
        args = build_parser().parse_args(
            [
                "collect",
                "--source",
                "facebook",
                "--mode",
                "period",
                "--period-start",
                "2026-08-17",
                "--period-end",
                "2026-08-23",
            ]
        )

        self.assertEqual("facebook", args.source)
        self.assertEqual("period", args.mode)
        self.assertEqual("2026-08-17", args.period_start)

    def test_dashboard_accepts_multiple_manifests(self):
        args = build_parser().parse_args(
            [
                "dashboard",
                "--manifest",
                "/tmp/canny.json",
                "--manifest",
                "/tmp/intercom.json",
                "--quick-win-review",
                "/tmp/review.json",
                "--analysis",
                "/tmp/analysis.json",
                "--analysis-input",
                "/tmp/analysis-input.json",
                "--dry-run",
            ]
        )

        self.assertEqual(["/tmp/canny.json", "/tmp/intercom.json"], args.manifest)
        self.assertEqual("/tmp/review.json", args.quick_win_review)
        self.assertEqual("/tmp/analysis.json", args.analysis)
        self.assertEqual("/tmp/analysis-input.json", args.analysis_input)
        self.assertTrue(args.dry_run)

    def test_analysis_input_contract_does_not_accept_quick_win_review(self):
        args = build_parser().parse_args(
            [
                "analysis-input",
                "--manifest",
                "/tmp/canny.json",
                "--manifest",
                "/tmp/intercom.json",
                "--manifest",
                "/tmp/jira.json",
                "--manifest",
                "/tmp/facebook.json",
                "--previous-analysis",
                "/tmp/previous-analysis.json",
                "--period-start",
                "2026-08-24",
                "--period-end",
                "2026-08-30",
            ]
        )

        self.assertEqual(4, len(args.manifest))
        self.assertEqual("/tmp/previous-analysis.json", args.previous_analysis)
        self.assertFalse(hasattr(args, "quick_win_review"))

    def test_analysis_prompt_and_build_contracts(self):
        prompted = build_parser().parse_args(
            ["analysis-prompt", "--input", "/tmp/input.json"]
        )
        built = build_parser().parse_args(
            [
                "analysis-build",
                "--input",
                "/tmp/input.json",
                "--model-output",
                "/tmp/model.json",
                "--human-review",
                "/tmp/review.json",
            ]
        )

        self.assertEqual("/tmp/input.json", prompted.input)
        self.assertEqual("/tmp/model.json", built.model_output)
        self.assertEqual("/tmp/review.json", built.human_review)

    def test_facebook_publish_contract(self):
        args = build_parser().parse_args(
            [
                "publish",
                "--source",
                "facebook",
                "--manifest",
                "/tmp/facebook.json",
                "--dry-run",
            ]
        )

        self.assertEqual("facebook", args.source)
        self.assertTrue(args.dry_run)

    def test_monthly_commands_contract(self):
        audit = build_parser().parse_args(
            [
                "monthly-audit",
                "--month",
                "2026-08",
                "--exclude-date",
                "2026-08-31",
            ]
        )
        monthly_input = build_parser().parse_args(
            [
                "monthly-analysis-input",
                "--month",
                "2026-08",
                "--exclude-date",
                "2026-08-31",
                "--analysis",
                "/tmp/w31.json",
                "--analysis",
                "/tmp/w32.json",
            ]
        )
        dashboard = build_parser().parse_args(
            [
                "monthly-dashboard",
                "--input",
                "/tmp/month-input.json",
                "--analysis",
                "/tmp/month-analysis.json",
                "--dry-run",
            ]
        )

        self.assertEqual(["2026-08-31"], audit.exclude_date)
        self.assertEqual(2, len(monthly_input.analysis))
        self.assertTrue(dashboard.dry_run)

    def test_collect_accepts_explicit_month_boundary_segment(self):
        args = build_parser().parse_args(
            [
                "collect",
                "--source",
                "intercom",
                "--mode",
                "period",
                "--period-start",
                "2026-08-01",
                "--period-end",
                "2026-08-02",
                "--month-segment",
                "2026-08",
            ]
        )

        self.assertEqual("2026-08", args.month_segment)


if __name__ == "__main__":
    unittest.main()
