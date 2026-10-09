from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = SKILL_ROOT / "scripts"
ENTRY = SCRIPT_DIR / "tech_doc_architect.py"
sys.path.insert(0, str(SCRIPT_DIR))

from tda.commands.content_model import validate_model  # noqa: E402
from tda.commands.docset import validate_docset  # noqa: E402
from tda.commands.semantic_checksum import validate_checksum  # noqa: E402


def valid_model() -> dict:
    return {
        "document": {
            "title": "Example Architecture",
            "one_sentence": "A bounded example system",
            "mode": "refactor",
            "audience": ["engineering lead"],
            "reader_questions": ["Where is state owned?"],
            "scope": {"in": ["runtime"], "out": []},
            "evidence": [
                {
                    "claim": "The runtime owns ordering",
                    "status": "verified",
                    "sources": ["src/runtime.ts"],
                    "impacts": ["overview"],
                }
            ],
            "vocabulary": [{"term": "Run", "definition": "One execution"}],
            "overview": {
                "context": "User to runtime",
                "internal_model": "Control and execution",
                "invariants": ["One terminal state"],
                "deployment_boundary": "One process",
            },
            "topics": [
                {
                    "question": "How does a run finish?",
                    "answer": "Exactly once",
                    "diagram": {"question": "How state changes", "type": "state"},
                    "concepts": [],
                    "normal_path": ["Start", "Finish"],
                    "failures": [],
                    "recovery": [],
                    "verification": ["terminal contract test"],
                    "code_entries": [],
                }
            ],
            "outputs": ["feishu", "obsidian", "markdown"],
        }
    }


class ContentModelTests(unittest.TestCase):
    def test_valid_model_passes(self) -> None:
        self.assertEqual(validate_model(valid_model()), [])

    def test_verified_claim_requires_source(self) -> None:
        payload = valid_model()
        payload["document"]["evidence"][0]["sources"] = []
        errors = validate_model(payload)
        self.assertTrue(any("sources" in error for error in errors))

    def test_unknown_output_fails(self) -> None:
        payload = valid_model()
        payload["document"]["outputs"] = ["notion"]
        errors = validate_model(payload)
        self.assertTrue(any("未知载体" in error for error in errors))


class DocsetTests(unittest.TestCase):
    def test_markdown_docset_passes(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "README.md").write_text(
                "# Overview\n\n[Runtime](runtime.md)\n",
                encoding="utf-8",
            )
            (root / "runtime.md").write_text("# Runtime\n", encoding="utf-8")
            self.assertEqual(validate_docset(root, "markdown", None), [])

    def test_markdown_rejects_wikilink_and_absolute_path(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "README.md").write_text(
                "# Overview\n\n[[Runtime]]\n\n[Local](/Users/example/file.md)\n",
                encoding="utf-8",
            )
            (root / "Runtime.md").write_text("# Runtime\n", encoding="utf-8")
            errors = validate_docset(root, "markdown", None)
            self.assertTrue(any("wikilink" in error for error in errors))
            self.assertTrue(any("绝对路径" in error for error in errors))

    def test_obsidian_docset_passes(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            assets = root / "assets"
            assets.mkdir()
            (assets / "runtime.svg").write_text("<svg/>", encoding="utf-8")
            (root / "系统架构概览.md").write_text(
                "# 系统架构概览\n\n[[运行模型]]\n\n![[assets/runtime.svg]]\n",
                encoding="utf-8",
            )
            (root / "运行模型.md").write_text(
                "# 运行模型\n\n[[系统架构概览]]\n",
                encoding="utf-8",
            )
            self.assertEqual(validate_docset(root, "obsidian", None), [])


class SemanticChecksumTests(unittest.TestCase):
    def test_two_outputs_with_same_claims_pass(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "markdown.md").write_text("Target 是顺序边界", encoding="utf-8")
            (root / "obsidian.md").write_text("Target 是顺序边界", encoding="utf-8")
            payload = {
                "claims": ["Target 是顺序边界"],
                "outputs": {
                    "markdown": ["markdown.md"],
                    "obsidian": ["obsidian.md"],
                },
            }
            self.assertEqual(validate_checksum(payload, root), [])

    def test_missing_claim_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "a.md").write_text("Target 是顺序边界", encoding="utf-8")
            (root / "b.md").write_text("另一条结论", encoding="utf-8")
            payload = {
                "claims": ["Target 是顺序边界"],
                "outputs": {"a": ["a.md"], "b": ["b.md"]},
            }
            errors = validate_checksum(payload, root)
            self.assertTrue(any("缺少规范化结论" in error for error in errors))


class CliTests(unittest.TestCase):
    def test_help_lists_all_subcommands(self) -> None:
        result = subprocess.run(
            [sys.executable, str(ENTRY), "--help"],
            check=True,
            capture_output=True,
            text=True,
        )
        self.assertIn("validate-content-model", result.stdout)
        self.assertIn("validate-docset", result.stdout)
        self.assertIn("validate-semantic-checksum", result.stdout)

    def test_content_model_command_returns_json(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "model.json"
            path.write_text(
                json.dumps(valid_model(), ensure_ascii=False),
                encoding="utf-8",
            )
            result = subprocess.run(
                [
                    sys.executable,
                    str(ENTRY),
                    "validate-content-model",
                    str(path),
                ],
                check=True,
                capture_output=True,
                text=True,
            )
            payload = json.loads(result.stdout)
            self.assertTrue(payload["ok"])
            self.assertEqual(payload["errors"], [])

    def test_docset_command_accepts_document_and_output_formats(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "README.md").write_text(
                "# Overview\n\n[Runtime](runtime.md)\n",
                encoding="utf-8",
            )
            (root / "runtime.md").write_text("# Runtime\n", encoding="utf-8")
            result = subprocess.run(
                [
                    sys.executable,
                    str(ENTRY),
                    "validate-docset",
                    "--document-format",
                    "markdown",
                    "--root",
                    str(root),
                    "--format",
                    "summary",
                ],
                check=True,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.stdout, "")
            self.assertIn("通过", result.stderr)

    def test_validation_failure_uses_business_error_exit_code(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "model.json"
            path.write_text("{}", encoding="utf-8")
            result = subprocess.run(
                [
                    sys.executable,
                    str(ENTRY),
                    "validate-content-model",
                    str(path),
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 4)
            self.assertFalse(json.loads(result.stdout)["ok"])


if __name__ == "__main__":
    unittest.main()
