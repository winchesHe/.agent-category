from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))

from mfc.commands.doctor import run


def config(
    output_root, *, canny=True, intercom=False, jira=False, facebook=False, squad=""
):
    return SimpleNamespace(
        output_root=Path(output_root),
        agent_browser=sys.executable if canny else "/missing/agent-browser",
        lark_cli=sys.executable,
        moe_mis_script=Path("/tmp/moe-mis.py") if canny else None,
        moe_mis_workdir=Path("/tmp") if canny else None,
        datadog_script=Path("/tmp/datadog.py") if intercom else None,
        jira_script=Path("/tmp/jira.py") if jira else None,
        slack_script=Path("/tmp/slack.py") if facebook else None,
        facebook_slack_channel="C0BEL8Y0Y74",
        squad=squad,
    )


class DoctorTests(unittest.TestCase):
    def test_canny_only_install_is_healthy_without_intercom_configuration(self):
        with tempfile.TemporaryDirectory() as directory, patch(
            "mfc.commands.doctor.resolve_wiki", return_value={"title": "反馈根目录"}
        ):
            result = run(None, config(directory))

        self.assertTrue(result["ok"])
        self.assertTrue(result["sources"]["canny"])
        self.assertFalse(result["sources"]["intercom"])
        self.assertFalse(result["checks"]["squadConfigured"])

    def test_intercom_collection_can_be_ready_before_publish_squad_is_configured(self):
        with tempfile.TemporaryDirectory() as directory, patch(
            "mfc.commands.doctor.resolve_wiki", return_value={"title": "反馈根目录"}
        ):
            result = run(None, config(directory, canny=False, intercom=True))

        self.assertTrue(result["ok"])
        self.assertTrue(result["sources"]["intercom"])
        self.assertFalse(result["intercomPublish"]["enabled"])

    def test_jira_collection_and_publish_require_squad(self):
        with tempfile.TemporaryDirectory() as directory, patch(
            "mfc.commands.doctor.resolve_wiki", return_value={"title": "反馈根目录"}
        ):
            without_squad = run(
                None, config(directory, canny=False, jira=True)
            )
            with_squad = run(
                None, config(directory, canny=False, jira=True, squad="Grooming")
            )

        self.assertTrue(without_squad["sources"]["jira"])
        self.assertFalse(without_squad["jiraPublish"]["enabled"])
        self.assertTrue(with_squad["jiraPublish"]["enabled"])

    def test_facebook_collection_is_ready_with_slack_skill(self):
        with tempfile.TemporaryDirectory() as directory, patch(
            "mfc.commands.doctor.resolve_wiki", return_value={"title": "反馈根目录"}
        ):
            result = run(None, config(directory, canny=False, facebook=True))

        self.assertTrue(result["ok"])
        self.assertTrue(result["sources"]["facebook"])
        self.assertTrue(result["checks"]["slackSkill"])


if __name__ == "__main__":
    unittest.main()
