import importlib.util
import io
import os
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
CLI = SCRIPTS / "sentry.py"

if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))


def load_cli_module():
    spec = importlib.util.spec_from_file_location("sentry_cli", CLI)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


class CliContractTests(unittest.TestCase):
    def test_missing_requests_fails_fast_instead_of_stub_help(self):
        env = dict(os.environ)
        env["SENTRY_DISABLE_DOTENV"] = "1"
        proc = subprocess.run(
            ["python3", "-S", str(CLI), "list-projects", "--help"],
            capture_output=True,
            text=True,
            env=env,
        )

        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("requests", proc.stderr)
        self.assertNotIn("usage: sentry list-projects [-h]", proc.stdout)

    def test_analyze_help_does_not_advertise_format(self):
        env = dict(os.environ)
        env["SENTRY_DISABLE_DOTENV"] = "1"
        proc = subprocess.run(
            ["python3", str(CLI), "analyze", "--help"],
            capture_output=True,
            text=True,
            env=env,
        )

        self.assertEqual(proc.returncode, 0)
        self.assertNotIn("--format", proc.stdout)

    def test_analyze_parser_rejects_format_flag(self):
        cli = load_cli_module()
        parser = cli._build_parser()

        with self.assertRaises(SystemExit) as ctx, mock.patch("sys.stderr", new=io.StringIO()):
            parser.parse_args(["analyze", "--format", "json", "--issue-id", "ISSUE-1"])

        self.assertEqual(ctx.exception.code, 2)

    def test_analyze_source_contains_no_placeholder_markers(self):
        analyze_path = SCRIPTS / "st" / "commands" / "analyze.py"
        source = analyze_path.read_text(encoding="utf-8")

        self.assertNotIn("PLACEHOLDER_RESULT_BUILD", source)


if __name__ == "__main__":
    unittest.main()
