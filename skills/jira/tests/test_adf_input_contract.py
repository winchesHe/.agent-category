from __future__ import annotations

import hashlib
import json
import re
import unittest
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
FIXTURE_ROOT = ROOT / "tests" / "fixtures" / "adf-input-v1"
MANIFEST_PATH = FIXTURE_ROOT / "manifest.json"
CONTRACT_PATH = ROOT / "tests" / "contracts" / "adf-input-v1.md"

EXPECTED_ERROR_CODES = {
    "adf_invalid",
    "markdown_unsupported",
    "markdown_residual",
    "unsafe_link",
    "adf_unsupported_transport",
}


def _walk_adf(node: Any):
    if isinstance(node, dict):
        yield node
        for child in node.get("content", []):
            yield from _walk_adf(child)
    elif isinstance(node, list):
        for child in node:
            yield from _walk_adf(child)


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


class JiraAdfInputContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = _load_json(MANIFEST_PATH)

    def fixture_path(self, relative: str) -> Path:
        path = (FIXTURE_ROOT / relative).resolve()
        path.relative_to(FIXTURE_ROOT.resolve())
        return path

    def test_contract_freezes_adf_first_explicit_dual_input(self):
        interfaces = self.manifest["interfaces"]
        self.assertEqual(self.manifest["contract_version"], "jira-adf-input-v1")
        self.assertEqual(self.manifest["status"], "implemented")
        self.assertEqual(self.manifest["canonical_format"], "adf")
        self.assertEqual(self.manifest["markdown_profile"], "jira-md-v1")
        self.assertTrue(interfaces["adf"]["preferred"])
        self.assertEqual(interfaces["adf"]["flag"], "--description-adf-file")
        self.assertFalse(interfaces["markdown"]["preferred"])
        self.assertFalse(interfaces["auto_detection"])
        self.assertTrue(interfaces["mutually_exclusive"])
        self.assertEqual(interfaces["adf"]["transport"], ["api"])
        self.assertEqual(interfaces["markdown"]["transport"], ["api"])
        self.assertEqual(interfaces["automation_text"]["transport"], ["automation"])
        self.assertFalse(interfaces["automation_text"]["rich_text_guarantee"])

    def test_runtime_reference_describes_only_current_adf_first_path(self):
        runtime_reference = (ROOT / self.manifest["runtime_reference"]).read_text(encoding="utf-8")
        contract = (ROOT / self.manifest["implementation_contract"]).read_text(encoding="utf-8")

        self.assertIn("优先提交完整 ADF", runtime_reference)
        self.assertIn("--additional-fields", runtime_reference)
        self.assertIn("--description-file", runtime_reference)
        self.assertIn("PARAGRAPH", runtime_reference)
        self.assertIn("--description-adf-file", runtime_reference)

        self.assertIn("API create 已实现", contract)
        self.assertIn("--description-adf-file", contract)
        self.assertIn("OPC 继续维护统一 Markdown 内容源", contract)

    def test_support_matrix_has_complete_golden_coverage(self):
        supported = self.manifest["supported_syntax"]
        supported_ids = {
            item["id"]
            for group in (supported["block"], supported["inline"])
            for item in group
        }
        self.assertEqual(
            len(supported_ids),
            len(supported["block"]) + len(supported["inline"]),
        )

        golden = next(case for case in self.manifest["cases"] if case["id"] == "markdown_supported_golden")
        self.assertEqual(set(golden["coverage"]), supported_ids)

        adf = _load_json(self.fixture_path(golden["expected_adf"]))
        nodes = list(_walk_adf(adf))
        node_types = {node.get("type") for node in nodes}
        marks = {
            mark.get("type")
            for node in nodes
            for mark in node.get("marks", [])
            if isinstance(mark, dict)
        }
        self.assertTrue(
            {
                "doc",
                "heading",
                "paragraph",
                "hardBreak",
                "blockquote",
                "bulletList",
                "orderedList",
                "listItem",
                "table",
                "tableRow",
                "tableHeader",
                "tableCell",
                "codeBlock",
                "text",
            }.issubset(node_types)
        )
        self.assertTrue({"strong", "em", "strike", "code", "link"}.issubset(marks))
        ordered = next(node for node in nodes if node.get("type") == "orderedList")
        self.assertEqual(ordered["attrs"]["order"], 3)

    def test_manifest_cases_are_resolvable_and_cover_every_error(self):
        cases = self.manifest["cases"]
        case_ids = [case["id"] for case in cases]
        self.assertEqual(len(case_ids), len(set(case_ids)))

        for case in cases:
            for key in ("input", "expected_adf", "candidate_adf"):
                if key in case:
                    with self.subTest(case=case["id"], field=key):
                        self.assertTrue(self.fixture_path(case[key]).is_file())

        declared_errors = {item["code"] for item in self.manifest["error_codes"]}
        covered_errors = {case["error"] for case in cases if case.get("outcome") == "reject"}
        self.assertEqual(declared_errors, EXPECTED_ERROR_CODES)
        self.assertEqual(covered_errors, EXPECTED_ERROR_CODES)
        self.assertTrue(all(item["exit"] in {2, 4} for item in self.manifest["error_codes"]))

    def test_json_fixtures_express_structural_and_forward_compatibility_boundaries(self):
        valid = _load_json(self.fixture_path("valid-rich.adf.json"))
        unknown = _load_json(self.fixture_path("structurally-valid-unknown.adf.json"))
        invalid_root = _load_json(self.fixture_path("invalid-adf-root.json"))

        for document in (valid, unknown):
            self.assertEqual(document["type"], "doc")
            self.assertEqual(document["version"], 1)
            self.assertIsInstance(document["content"], list)
        self.assertEqual(unknown["content"][0]["type"], "futureNode")
        self.assertNotEqual(invalid_root.get("type"), "doc")
        with self.assertRaises(json.JSONDecodeError):
            _load_json(self.fixture_path("malformed-adf.txt"))

    def test_large_adf_is_locally_accepted_and_service_authoritative(self):
        case = next(
            case
            for case in self.manifest["cases"]
            if case["id"] == "large_adf_service_authoritative"
        )
        self.assertGreater(case["minimum_serialized_bytes"], 1024 * 1024)
        self.assertEqual(case["outcome"], "accept_locally_service_authoritative")

    def test_opc_snapshot_and_expected_structure_are_stable(self):
        snapshot = self.manifest["source_snapshots"][0]
        fixture = self.fixture_path(snapshot["fixture"])
        body = fixture.read_bytes()
        self.assertEqual(hashlib.sha256(body).hexdigest(), snapshot["sha256"])

        lines = body.decode("utf-8").splitlines()
        heading_levels: dict[str, int] = {}
        for line in lines:
            match = re.match(r"^(#{1,6}) ", line)
            if match:
                level = str(len(match.group(1)))
                heading_levels[level] = heading_levels.get(level, 0) + 1

        def count_groups(pattern: str) -> int:
            groups = 0
            inside = False
            for line in lines:
                matched = re.match(pattern, line) is not None
                if matched and not inside:
                    groups += 1
                inside = matched
            return groups

        expected = next(
            case["expected_structure"]
            for case in self.manifest["cases"]
            if case["id"] == "opc_lightweight_prd_acceptance"
        )
        self.assertEqual(heading_levels, expected["heading_levels"])
        self.assertEqual(count_groups(r"^> "), expected["blockquote"])
        self.assertEqual(count_groups(r"^- "), expected["bullet_list"])
        self.assertEqual(sum(1 for line in lines if re.match(r"^- ", line)), expected["list_item"])
        self.assertEqual(sum(1 for line in lines if re.match(r"^\|(?:---\|)+$", line)), expected["table"])


if __name__ == "__main__":
    unittest.main()
