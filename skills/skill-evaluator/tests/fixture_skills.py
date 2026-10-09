from __future__ import annotations

import json
import shutil
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path


_FIXTURES_ROOT = Path(__file__).parent / "fixtures"


@contextmanager
def temporary_skill_fixture(fixture_name: str) -> Iterator[Path]:
    """在系统临时目录中生成测试 Skill，并在退出上下文时删除。"""
    fixture_root = _FIXTURES_ROOT / fixture_name
    definition_path = fixture_root / "skill.json"
    if not definition_path.is_file():
        raise ValueError(f"Unknown skill fixture: {fixture_name}")
    if (fixture_root / "SKILL.md").exists():
        raise ValueError(f"Skill fixture must not contain a static SKILL.md: {fixture_root}")

    definition = json.loads(definition_path.read_text())
    expected_keys = {"name", "description", "instructions"}
    if set(definition) != expected_keys:
        raise ValueError(f"Invalid skill fixture definition: {definition_path}")

    skill_markdown = (
        "---\n"
        f"name: {definition['name']}\n"
        f"description: {definition['description']}\n"
        "---\n\n"
        f"{definition['instructions']}\n"
    )

    with tempfile.TemporaryDirectory(prefix=f"skill-evaluator-{fixture_name}-") as temp_dir:
        skill_path = Path(temp_dir) / fixture_name
        shutil.copytree(fixture_root, skill_path, ignore=shutil.ignore_patterns("skill.json"))
        (skill_path / "SKILL.md").write_text(skill_markdown)
        yield skill_path
