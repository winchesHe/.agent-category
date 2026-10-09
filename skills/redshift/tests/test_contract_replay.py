from __future__ import annotations

import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.run_contract_replay import HarnessError, run_replay


def valid_case() -> dict:
    return {
        "id": "missing-command",
        "networkRequired": False,
        "args": [],
        "expected": {
            "exitCode": 2,
            "jsonPaths": {
                "schemaVersion": 1,
                "ok": False,
                "command": None,
                "error.category": "usage",
                "error.code": "missing_command",
                "error.retryClass": "after_change",
            },
        },
    }


def write_candidate(root: Path, source: str | None = None) -> Path:
    candidate = root / "candidate"
    scripts = candidate / "scripts"
    scripts.mkdir(parents=True)
    if source is not None:
        (scripts / "redshift.py").write_text(source, encoding="utf-8")
    return candidate


def write_fixtures(root: Path, cases: list[dict] | None = None) -> Path:
    fixture_path = root / "fixtures.json"
    fixture_path.write_text(
        json.dumps(
            {
                "schemaVersion": 1,
                "cases": cases if cases is not None else [valid_case()],
            }
        ),
        encoding="utf-8",
    )
    return fixture_path


class ContractReplayTests(unittest.TestCase):
    def test_runner_checks_typed_envelope_without_external_configuration(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            candidate = write_candidate(
                root,
                "import json\n"
                "print(json.dumps({'schemaVersion': 1, 'ok': False, "
                "'command': None, 'error': {'category': 'usage', "
                "'code': 'missing_command', 'retryClass': 'after_change'}}))\n"
                "raise SystemExit(2)\n",
            )
            fixtures = write_fixtures(root)

            result = run_replay(candidate, fixtures, timeout_seconds=2)

            self.assertEqual(
                result["summary"],
                {"total": 1, "passed": 1, "failed": 0},
            )
            self.assertIn("cli_contract_only", result["limitations"])

    def test_runner_reports_process_timeout_without_hanging(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            candidate = write_candidate(root, "import time\ntime.sleep(30)\n")
            case = valid_case()
            case.update(
                {
                    "id": "timeout",
                    "expected": {"exitCode": 0, "jsonPaths": {}},
                }
            )
            fixtures = write_fixtures(root, [case])

            result = run_replay(candidate, fixtures, timeout_seconds=0.05)

            self.assertEqual(result["summary"], {"total": 1, "passed": 0, "failed": 1})
            self.assertEqual(result["cases"][0]["issues"], ["process_timeout"])

    def test_fixture_validation_rejects_invalid_utf8_and_malformed_json(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            candidate = write_candidate(root, "raise SystemExit(0)\n")
            fixture_path = root / "fixtures.json"

            invalid_files = {
                "invalid-utf8": b"\xff\xfe",
                "malformed-json": b'{"schemaVersion": 1,',
            }
            for name, content in invalid_files.items():
                with self.subTest(name=name):
                    fixture_path.write_bytes(content)
                    with self.assertRaisesRegex(HarnessError, "cannot load fixture file"):
                        run_replay(candidate, fixture_path, timeout_seconds=1)

    def test_fixture_validation_rejects_nondeterministic_or_malformed_cases(self) -> None:
        invalid_cases: dict[str, list[dict]] = {}

        duplicate = valid_case()
        duplicate["id"] = "duplicate"
        invalid_cases["duplicate-ids"] = [duplicate, dict(duplicate)]

        network = valid_case()
        network["networkRequired"] = True
        invalid_cases["network-required"] = [network]

        non_string_args = valid_case()
        non_string_args["args"] = [1]
        invalid_cases["non-string-args"] = [non_string_args]

        missing_expected = valid_case()
        del missing_expected["expected"]
        invalid_cases["missing-expected"] = [missing_expected]

        missing_exit = valid_case()
        del missing_exit["expected"]["exitCode"]
        invalid_cases["missing-exit-code"] = [missing_exit]

        wrong_exit = valid_case()
        wrong_exit["expected"]["exitCode"] = True
        invalid_cases["boolean-exit-code"] = [wrong_exit]

        missing_paths = valid_case()
        del missing_paths["expected"]["jsonPaths"]
        invalid_cases["missing-json-paths"] = [missing_paths]

        wrong_paths = valid_case()
        wrong_paths["expected"]["jsonPaths"] = []
        invalid_cases["wrong-json-paths"] = [wrong_paths]

        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            candidate = write_candidate(root, "raise SystemExit(0)\n")
            for name, cases in invalid_cases.items():
                with self.subTest(name=name):
                    fixture_path = write_fixtures(root, cases)
                    with self.assertRaises(HarnessError):
                        run_replay(candidate, fixture_path, timeout_seconds=1)

    def test_runner_rejects_candidate_dotenv(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            candidate = write_candidate(root, "raise SystemExit(0)\n")
            (candidate / ".env").write_text(
                "REDSHIFT_CONNECTIONS_FILE=/operator/connections.json\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(HarnessError, "contains .env"):
                run_replay(candidate, write_fixtures(root), timeout_seconds=1)

    def test_runner_rejects_candidate_connection_registry(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            candidate = write_candidate(root, "raise SystemExit(0)\n")
            (candidate / "connections.json").write_text("{}\n", encoding="utf-8")

            with self.assertRaisesRegex(HarnessError, "contains connections.json"):
                run_replay(candidate, write_fixtures(root), timeout_seconds=1)

    def test_runner_rejects_missing_or_escaping_entrypoint(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            candidate = write_candidate(root)
            fixtures = write_fixtures(root)

            with self.assertRaisesRegex(HarnessError, "scripts/redshift.py is missing"):
                run_replay(candidate, fixtures, timeout_seconds=1)

            outside = root / "outside.py"
            outside.write_text("raise SystemExit(0)\n", encoding="utf-8")
            (candidate / "scripts" / "redshift.py").symlink_to(outside)
            with self.assertRaisesRegex(HarnessError, "entrypoint escapes"):
                run_replay(candidate, fixtures, timeout_seconds=1)

    def test_runner_scrubs_redshift_variables_and_uses_temporary_home(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            candidate = write_candidate(
                root,
                "import json, os\n"
                "home = os.environ['HOME']\n"
                "print(json.dumps({"
                "'schemaVersion': 1, 'ok': True, 'command': 'environment', "
                "'redshiftScrubbed': 'REDSHIFT_SECRET' not in os.environ, "
                "'rsScrubbed': 'RS_SECRET' not in os.environ, "
                "'temporaryHome': os.path.basename(home).startswith('redshift-contract-replay-') "
                "and os.path.isdir(home)}))\n",
            )
            case = valid_case()
            case.update(
                {
                    "id": "isolated-environment",
                    "expected": {
                        "exitCode": 0,
                        "jsonPaths": {
                            "redshiftScrubbed": True,
                            "rsScrubbed": True,
                            "temporaryHome": True,
                        },
                    },
                }
            )
            fixtures = write_fixtures(root, [case])

            with patch.dict(
                os.environ,
                {
                    "HOME": "/host/home",
                    "REDSHIFT_SECRET": "must-not-leak",
                    "RS_SECRET": "must-not-leak",
                },
            ):
                result = run_replay(candidate, fixtures, timeout_seconds=1)

            self.assertEqual(result["summary"], {"total": 1, "passed": 1, "failed": 0})

    def test_real_cli_passes_the_complete_generated_contract(self) -> None:
        source_root = Path(__file__).parents[1]
        with tempfile.TemporaryDirectory() as temporary_directory:
            candidate = Path(temporary_directory) / "source"
            shutil.copytree(
                source_root,
                candidate,
                ignore=shutil.ignore_patterns(
                    ".env",
                    "connections.json",
                    "__pycache__",
                    ".pytest_cache",
                ),
            )

            result = run_replay(
                candidate,
                candidate / "tests" / "fixtures" / "contract-cases.json",
                timeout_seconds=5,
            )

            self.assertEqual(result["summary"], {"total": 13, "passed": 13, "failed": 0})


if __name__ == "__main__":
    unittest.main()
