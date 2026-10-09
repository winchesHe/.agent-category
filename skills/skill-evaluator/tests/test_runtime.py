from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from scripts.eval_runtime.executors import (
    RunRequest,
    _count_pi_turns,
    _pi_cli_command,
    _pi_tool_names,
    _write_pi_replay_extension,
)
from scripts.eval_runtime.replay import ReplayError, ReplayRegistry
from scripts.eval_runtime.trajectory import match_trajectory
from tests.fixture_skills import temporary_skill_fixture


class TemporarySkillFixtureTest(unittest.TestCase):
    def test_materializes_pi_skills_outside_repository_and_removes_them(self) -> None:
        expected_names = {
            "pi-skill": "pi-smoke",
            "pi-replay-skill": "pi-replay-smoke",
            "pi-replay-negative": "pi-replay-negative",
        }
        fixture_root = Path(__file__).parent / "fixtures"

        for fixture_name, expected_name in expected_names.items():
            with self.subTest(fixture_name=fixture_name):
                self.assertFalse((fixture_root / fixture_name / "SKILL.md").exists())
                with temporary_skill_fixture(fixture_name) as skill_path:
                    temporary_root = skill_path.parent
                    self.assertFalse(skill_path.is_relative_to(fixture_root))
                    self.assertTrue((skill_path / "evals" / "evals.json").is_file())
                    self.assertFalse((skill_path / "skill.json").exists())
                    skill_markdown = (skill_path / "SKILL.md").read_text()
                    self.assertIn(f"name: {expected_name}", skill_markdown)
                self.assertFalse(temporary_root.exists())

    def test_removes_temporary_skill_when_test_raises(self) -> None:
        temporary_root: Path | None = None

        with self.assertRaisesRegex(RuntimeError, "expected failure"):
            with temporary_skill_fixture("pi-skill") as skill_path:
                temporary_root = skill_path.parent
                raise RuntimeError("expected failure")

        self.assertIsNotNone(temporary_root)
        self.assertFalse(temporary_root.exists())


class TrajectoryTest(unittest.TestCase):
    def test_ordered_allows_unrelated_calls_between_expected_calls(self) -> None:
        result = match_trajectory(
            {
                "mode": "ordered",
                "calls": [
                    {"tool": "search", "args_contain": {"q": "GRM-123"}},
                    {"tool": "read", "args_contain": {"id": "GRM-123"}},
                ],
            },
            [
                {"tool": "noop", "args": {}},
                {"tool": "search", "args": {"q": "GRM-123", "limit": 10}},
                {"tool": "read", "args": {"id": "GRM-123"}},
            ],
        )
        self.assertEqual(result["status"], "passed")

    def test_exact_rejects_wrong_order_and_extra_call(self) -> None:
        result = match_trajectory(
            {"mode": "exact", "calls": [{"tool": "search"}, {"tool": "read"}]},
            [{"tool": "read", "args": {}}, {"tool": "search", "args": {}}, {"tool": "read", "args": {}}],
        )
        self.assertEqual(result["status"], "failed")
        self.assertTrue(any(item["type"] == "call_count_mismatch" for item in result["failures"]))

    def test_exact_rejects_boolean_number_confusion(self) -> None:
        result = match_trajectory(
            {
                "mode": "exact",
                "calls": [
                    {
                        "tool": "write",
                        "args_exact": {"execute": True, "patch": {"version": 1}},
                    }
                ],
            },
            [{"tool": "write", "args": {"execute": 1, "patch": {"version": True}}}],
        )
        self.assertEqual(result["status"], "failed")

    def test_exact_uses_json_number_semantics_for_signed_zero(self) -> None:
        result = match_trajectory(
            {"mode": "exact", "calls": [{"tool": "write", "args_exact": {"offset": -0.0}}]},
            [{"tool": "write", "args": {"offset": 0.0}}],
        )
        self.assertEqual(result["status"], "passed")

    def test_args_contain_rejects_boolean_number_confusion(self) -> None:
        result = match_trajectory(
            {"mode": "exact", "calls": [{"tool": "write", "args_contain": {"execute": True}}]},
            [{"tool": "write", "args": {"execute": 1}}],
        )
        self.assertEqual(result["status"], "failed")

    def test_args_contain_uses_json_number_semantics_for_signed_zero(self) -> None:
        result = match_trajectory(
            {"mode": "exact", "calls": [{"tool": "write", "args_contain": {"offset": -0.0}}]},
            [{"tool": "write", "args": {"offset": 0.0}}],
        )
        self.assertEqual(result["status"], "passed")

    def test_path_suffix_matches_portable_absolute_reference_path(self) -> None:
        result = match_trajectory(
            {
                "mode": "exact",
                "calls": [
                    {
                        "tool": "read",
                        "args_end_with": {"path": "moe-opc/references/stages/prd.md"},
                    }
                ],
            },
            [{"tool": "read", "args": {"path": "/tmp/worktree/moe-opc/references/stages/prd.md"}}],
        )
        self.assertEqual(result["status"], "passed")

    def test_path_suffix_rejects_different_reference(self) -> None:
        result = match_trajectory(
            {
                "mode": "exact",
                "calls": [
                    {
                        "tool": "read",
                        "args_end_with": {"path": "moe-opc/references/stages/prd.md"},
                    }
                ],
            },
            [{"tool": "read", "args": {"path": "/tmp/worktree/moe-opc/references/stages/release.md"}}],
        )
        self.assertEqual(result["status"], "failed")

    def test_path_suffix_rejects_lookalike_directory(self) -> None:
        result = match_trajectory(
            {
                "mode": "exact",
                "calls": [
                    {
                        "tool": "read",
                        "args_end_with": {"path": "moe-opc/references/stages/prd.md"},
                    }
                ],
            },
            [{"tool": "read", "args": {"path": "/tmp/not-moe-opc/references/stages/prd.md"}}],
        )
        self.assertEqual(result["status"], "failed")

    def test_max_calls_is_a_failure(self) -> None:
        result = match_trajectory({"mode": "ordered", "calls": [], "max_calls": 1}, [{"tool": "a"}, {"tool": "b"}])
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["failures"][0]["type"], "max_calls_exceeded")


class ReplayTest(unittest.TestCase):
    def test_fixture_matches_subset_of_args(self) -> None:
        registry = ReplayRegistry([{"tool": "read", "args_contain": {"id": "1"}, "result": {"status": "done"}}])
        self.assertEqual(registry.call("read", {"id": "1", "fields": ["status"]}), {"status": "done"})

    def test_fixture_miss_is_explicit(self) -> None:
        registry = ReplayRegistry([{"tool": "read", "args_contain": {"id": "1"}, "result": {}}])
        with self.assertRaises(ReplayError):
            registry.call("read", {"id": "2"})

    def test_fixture_exact_args_rejects_extra_fields(self) -> None:
        registry = ReplayRegistry([{"tool": "write", "args_exact": {"id": "1"}, "result": {"ok": True}}])
        self.assertEqual(registry.call("write", {"id": "1"}), {"ok": True})
        with self.assertRaises(ReplayError):
            registry.call("write", {"id": "1", "status": "Closed"})

    def test_fixture_exact_args_rejects_boolean_number_confusion(self) -> None:
        registry = ReplayRegistry(
            [
                {
                    "tool": "write",
                    "args_exact": {"execute": True, "patch": {"version": 1}},
                    "result": {"ok": True},
                }
            ]
        )
        with self.assertRaises(ReplayError):
            registry.call("write", {"execute": 1, "patch": {"version": True}})

    def test_javascript_fixture_match_uses_same_strict_cases(self) -> None:
        matcher = Path(__file__).parents[1] / "scripts" / "eval_runtime" / "fixture_match.mjs"
        script = f"""
import {{ fixtureArgsMatch }} from {json.dumps(matcher.as_uri())};
const fixture = {{ args_exact: {{ execute: true, patch: {{ version: 1 }} }} }};
if (!fixtureArgsMatch(fixture, {{ execute: true, patch: {{ version: 1 }} }})) process.exit(1);
if (fixtureArgsMatch(fixture, {{ execute: true, patch: {{ version: 1 }}, status: "Closed" }})) process.exit(2);
if (fixtureArgsMatch(fixture, {{ execute: 1, patch: {{ version: true }} }})) process.exit(3);
if (!fixtureArgsMatch({{ args_exact: {{ offset: -0 }} }}, {{ offset: 0 }})) process.exit(4);
if (fixtureArgsMatch({{ args_contain: {{ execute: true }} }}, {{ execute: 1 }})) process.exit(5);
if (!fixtureArgsMatch({{ args_contain: {{ offset: -0 }} }}, {{ offset: 0 }})) process.exit(6);
const candidates = [
  {{ args_contain: {{ patch: {{ version: 1 }} }}, result: "wrong" }},
  {{ args_contain: {{ patch: "ready" }}, result: "right" }},
];
const matched = candidates.find((candidate) => fixtureArgsMatch(candidate, {{ patch: "ready" }}));
if (matched?.result !== "right") process.exit(7);
"""
        result = subprocess.run(
            ["node", "--input-type=module", "--eval", script],
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_pi_cli_fixture_tools_keep_builtin_read(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            fixture = Path(raw) / "fixture.json"
            fixture.write_text(json.dumps([{"tool": "write", "args_exact": {"id": "1"}, "result": {}}]))
            request = RunRequest(
                run_id="tools",
                prompt="",
                configuration="with_skill",
                workspace=Path(raw),
                tools=["bash"],
                fixtures=[str(fixture)],
            )
            self.assertEqual(_pi_tool_names(request), ["read", "write"])

    def test_pi_cli_disables_discovered_skills_and_only_injects_target_skill(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            skill = Path(raw) / "target-skill"
            skill.mkdir()
            (skill / "SKILL.md").write_text("本次目标 Skill 指令")
            request = RunRequest("isolated", "run", "with_skill", Path(raw), skill_path=skill)
            command = _pi_cli_command(request, "/usr/local/bin/pi")
            self.assertIn("--no-skills", command)
            self.assertEqual(command[command.index("--skill") + 1], str(skill))
            self.assertIn("本次目标 Skill 指令", command[-1])
            request.configuration = "without_skill"
            request.skill_path = None
            baseline_command = _pi_cli_command(request, "/usr/local/bin/pi")
            self.assertIn("--no-skills", baseline_command)
            self.assertNotIn("--skill", baseline_command)
            self.assertNotIn("本次目标 Skill 指令", baseline_command[-1])

    def test_pi_sdk_loader_disables_discovered_skills(self) -> None:
        bridge = Path(__file__).parents[1] / "scripts" / "eval_runtime" / "pi_sdk_bridge.mjs"
        source = bridge.read_text()
        self.assertIn("noSkills: true", source)
        self.assertIn("additionalSkillPaths: input.skill_path", source)
        self.assertIn('event.type === "turn_end"', source)
        self.assertIn("total_turns: totalTurns", source)

    def test_executor_turn_counts_use_agent_turn_events(self) -> None:
        pi_events = [
            {"type": "agent_start"},
            {"type": "message_update"},
            {"type": "tool_execution_start"},
            {"type": "turn_end"},
            {"type": "message_update"},
            {"type": "turn_end"},
            {"type": "agent_end"},
        ]
        self.assertEqual(_count_pi_turns(pi_events), 2)

    @unittest.skipUnless(shutil.which("pi"), "需要本地 Pi CLI")
    def test_pi_cli_replay_extension_resolves_installed_package_root(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            fixture = Path(raw) / "fixture.json"
            fixture.write_text(json.dumps([{"tool": "write", "args_exact": {"id": "1"}, "result": {}}]))
            request = RunRequest(
                run_id="extension",
                prompt="",
                configuration="with_skill",
                workspace=Path(raw),
                fixtures=[str(fixture)],
            )
            extension = _write_pi_replay_extension(request, shutil.which("pi") or "")
            self.assertTrue(extension.is_file())
            checked = subprocess.run(["node", "--check", str(extension)], capture_output=True, text=True)
            self.assertEqual(checked.returncode, 0, checked.stderr)


class CiIntegrationTest(unittest.TestCase):
    def test_fake_ci_generates_compatible_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            skill = root / "demo-skill"
            (skill / "evals").mkdir(parents=True)
            (skill / "SKILL.md").write_text("---\nname: demo-skill\ndescription: demo\n---\n")
            (skill / "evals" / "evals.json").write_text(
                json.dumps(
                    {
                        "skill_name": "demo-skill",
                        "evals": [
                            {
                                "id": 1,
                                "name": "ordered-demo",
                                "prompt": "summarize",
                                "mock_result": {
                                    "final_answer": "Done",
                                    "tool_calls": [{"tool": "read", "args": {"id": "1"}}],
                                },
                                "assertions": [{"type": "contains", "text": "has status", "value": "Done"}],
                                "trajectory": {"mode": "ordered", "calls": [{"tool": "read", "args_contain": {"id": "1"}}]},
                            }
                        ],
                    }
                )
            )
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "scripts.run_ci",
                    "--skill-path",
                    str(skill),
                    "--executor",
                    "fake",
                    "--strict",
                    "--output-dir",
                    str(root / "results"),
                ],
                cwd=Path(__file__).parents[1],
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            output_root = next((root / "results").iterdir()) / "attempt-1-fake"
            self.assertTrue((output_root / "summary.json").exists())
            self.assertTrue((output_root / "report.html").exists())
            report = (output_root / "report.html").read_text()
            self.assertIn("Skill Description Optimization", report)
            self.assertIn("with_skill vs without_skill", report)
            self.assertIn('failures="0"', (output_root / "junit.xml").read_text())
            benchmark = json.loads((output_root / "iteration-1" / "benchmark.json").read_text())
            self.assertEqual(benchmark["runs"][0]["configuration"], "with_skill")
            grading = json.loads(next((output_root / "iteration-1").glob("eval-1/with_skill/run-1/grading.json")).read_text())
            self.assertEqual(grading["trajectory"]["status"], "passed")

    def test_strict_ci_returns_one_for_trajectory_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            skill = root / "demo-skill"
            (skill / "evals").mkdir(parents=True)
            (skill / "SKILL.md").write_text("---\nname: demo-skill\ndescription: demo\n---\n")
            (skill / "evals" / "evals.json").write_text(
                json.dumps(
                    {
                        "skill_name": "demo-skill",
                        "evals": [
                            {
                                "id": 1,
                                "prompt": "run",
                                "mock_result": {"final_answer": "ok", "tool_calls": [{"tool": "wrong"}]},
                                "trajectory": {"mode": "exact", "calls": [{"tool": "expected"}]},
                            }
                        ],
                    }
                )
            )
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "scripts.run_ci",
                    "--skill-path",
                    str(skill),
                    "--executor",
                    "fake",
                    "--strict",
                    "--output-dir",
                    str(root / "results"),
                ],
                cwd=Path(__file__).parents[1],
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 1, result.stderr + result.stdout)

    def test_global_max_turns_is_enforced_by_grading(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            skill = root / "demo-skill"
            (skill / "evals").mkdir(parents=True)
            (skill / "SKILL.md").write_text("---\nname: demo-skill\ndescription: demo\n---\n")
            (skill / "evals" / "evals.json").write_text(
                json.dumps(
                    {
                        "skill_name": "demo-skill",
                        "evals": [
                            {
                                "id": 1,
                                "prompt": "run",
                                "mock_result": {"final_answer": "ok", "tool_calls": [], "total_turns": 2},
                            }
                        ],
                    }
                )
            )
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "scripts.run_ci",
                    "--skill-path",
                    str(skill),
                    "--executor",
                    "fake",
                    "--strict",
                    "--max-turns",
                    "1",
                    "--output-dir",
                    str(root / "results"),
                ],
                cwd=Path(__file__).parents[1],
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 1, result.stderr + result.stdout)
            output_root = next((root / "results").iterdir()) / "attempt-1-fake"
            grading = json.loads(
                (output_root / "iteration-1" / "eval-1" / "with_skill" / "run-1" / "grading.json").read_text()
            )
            self.assertEqual(grading["trajectory"]["failures"][0]["type"], "max_turns_exceeded")
            self.assertEqual(grading["summary"]["total"], 1)

    def test_case_max_turns_is_stricter_than_global_limit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            skill = root / "demo-skill"
            (skill / "evals").mkdir(parents=True)
            (skill / "SKILL.md").write_text("---\nname: demo-skill\ndescription: demo\n---\n")
            (skill / "evals" / "evals.json").write_text(
                json.dumps(
                    {
                        "skill_name": "demo-skill",
                        "evals": [
                            {
                                "id": 1,
                                "prompt": "run",
                                "mock_result": {"final_answer": "ok", "tool_calls": [], "total_turns": 2},
                                "trajectory": {"mode": "exact", "calls": [], "max_turns": 1},
                            }
                        ],
                    }
                )
            )
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "scripts.run_ci",
                    "--skill-path",
                    str(skill),
                    "--executor",
                    "fake",
                    "--strict",
                    "--max-turns",
                    "3",
                    "--output-dir",
                    str(root / "results"),
                ],
                cwd=Path(__file__).parents[1],
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 1, result.stderr + result.stdout)
            output_root = next((root / "results").iterdir()) / "attempt-1-fake"
            grading = json.loads(
                (output_root / "iteration-1" / "eval-1" / "with_skill" / "run-1" / "grading.json").read_text()
            )
            failure = grading["trajectory"]["failures"][0]
            self.assertEqual(failure["type"], "max_turns_exceeded")
            self.assertEqual(failure["maximum"], 1)

    def test_baseline_quality_failure_does_not_block_default_gate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            skill = root / "demo-skill"
            (skill / "evals").mkdir(parents=True)
            (skill / "SKILL.md").write_text("---\nname: demo-skill\ndescription: demo\n---\n")
            (skill / "evals" / "evals.json").write_text(
                json.dumps(
                    {
                        "skill_name": "demo-skill",
                        "evals": [
                            {
                                "id": 1,
                                "prompt": "run",
                                "assertions": [{"type": "contains", "text": "done", "value": "Done"}],
                                "trajectory": {"mode": "ordered", "calls": [{"tool": "expected"}]},
                                "mock_results_by_configuration": {
                                    "with_skill": {
                                        "final_answer": "Done",
                                        "tool_calls": [{"tool": "expected", "args": {}}],
                                    },
                                    "without_skill": {
                                        "final_answer": "baseline",
                                        "tool_calls": [{"tool": "wrong", "args": {}}],
                                    },
                                },
                            }
                        ],
                    }
                )
            )

            default_gate = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "scripts.run_ci",
                    "--skill-path",
                    str(skill),
                    "--executor",
                    "fake",
                    "--strict",
                    "--output-dir",
                    str(root / "default-results"),
                ],
                cwd=Path(__file__).parents[1],
                capture_output=True,
                text=True,
            )
            self.assertEqual(default_gate.returncode, 0, default_gate.stderr + default_gate.stdout)
            default_root = next((root / "default-results").iterdir()) / "attempt-1-fake"
            default_summary = json.loads((default_root / "summary.json").read_text())
            self.assertEqual(default_summary["status"], "passed")
            self.assertEqual(default_summary["failures"], [])
            self.assertEqual(len(default_summary["non_gating_failures"]), 1)
            self.assertIn("skipped", (default_root / "junit.xml").read_text())

            both_gate = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "scripts.run_ci",
                    "--skill-path",
                    str(skill),
                    "--executor",
                    "fake",
                    "--gate-configuration",
                    "both",
                    "--strict",
                    "--output-dir",
                    str(root / "both-results"),
                ],
                cwd=Path(__file__).parents[1],
                capture_output=True,
                text=True,
            )
            self.assertEqual(both_gate.returncode, 1, both_gate.stderr + both_gate.stdout)


if __name__ == "__main__":
    unittest.main()
