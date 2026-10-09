from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from sk.config import Config  # noqa: E402
from sk.errors import ActorConfigError  # noqa: E402


class SlackPackageLocalConfigTests(unittest.TestCase):
    def test_default_cache_and_files_directories_are_package_local(self) -> None:
        with mock.patch.dict(
            os.environ,
            {"SLACK_BOT_TOKEN": "fixture-token"},
            clear=True,
        ):
            config = Config()

        self.assertEqual(config.cache_dir, ROOT / "cache")
        self.assertEqual(config.files_dir, ROOT / "cache" / "files")

    def test_invalid_numeric_configuration_is_actionable(self) -> None:
        for name, value in (
            ("SLACK_SKILL_TIMEOUT", "slow"),
            ("SLACK_SKILL_TIMEOUT", "0"),
            ("SLACK_SKILL_WRITE_RETRY_BUDGET", "later"),
            ("SLACK_SKILL_WRITE_RETRY_BUDGET", "-1"),
        ):
            with self.subTest(name=name, value=value), mock.patch.dict(
                os.environ, {name: value}, clear=True
            ):
                with self.assertRaises(ActorConfigError) as caught:
                    Config()
            self.assertIn(name, str(caught.exception))


if __name__ == "__main__":
    unittest.main()
