from __future__ import annotations

import argparse
import json
from pathlib import Path

from scripts.rs.contract import (
    COMMAND_SPECS,
    command_names,
    commands_for_option,
    contract_replay_fixture,
    render_command_matrix,
)


def test_public_command_set_is_exactly_the_nine_accepted_commands() -> None:
    assert command_names() == (
        "databases",
        "schemas",
        "relations",
        "search",
        "describe",
        "query",
        "explain",
        "recipe",
        "doctor",
    )


def test_every_command_spec_builds_an_argparse_leaf() -> None:
    for spec in COMMAND_SPECS:
        parser = argparse.ArgumentParser(add_help=False, allow_abbrev=False)
        spec.configure_args(parser)


def test_option_introspection_has_one_contract_source() -> None:
    assert commands_for_option("--database") == ("search", "query", "explain")
    assert commands_for_option("--connection") == (
        "databases",
        "schemas",
        "relations",
        "describe",
        "query",
        "explain",
        "recipe",
        "doctor",
    )
    assert commands_for_option("--connect") == ("doctor",)
    assert commands_for_option("--list-connections") == ("doctor",)
    assert commands_for_option("--unknown") == ()


def test_command_matrix_is_generated_from_command_specs() -> None:
    block = render_command_matrix()
    for spec in COMMAND_SPECS:
        assert f"`{spec.name}`" in block
        assert f"`{spec.canonical_usage}`" in block


def test_skill_generated_command_matrix_has_zero_drift() -> None:
    skill = (Path(__file__).parents[1] / "SKILL.md").read_text(encoding="utf-8")
    start = "<!-- BEGIN GENERATED COMMAND MATRIX -->\n"
    end = "\n<!-- END GENERATED COMMAND MATRIX -->"
    assert start in skill and end in skill
    published = skill.split(start, 1)[1].split(end, 1)[0]
    assert published == render_command_matrix()


def test_contract_replay_fixture_is_generated_from_the_contract_source() -> None:
    fixture_path = (
        Path(__file__).parent / "fixtures" / "contract-cases.json"
    )
    assert json.loads(fixture_path.read_text(encoding="utf-8")) == contract_replay_fixture()
