from __future__ import annotations

import pytest

from scripts.rs.errors import SkillError
from scripts.rs.query.parameter_plan import build_parameter_plan


def test_data_api_rendering_ignores_quoted_and_commented_placeholder_text() -> None:
    plan = build_parameter_plan(
        """
SELECT 'ignored %(inside)s', value
FROM items
WHERE id = %(item_id)s
  AND note LIKE '100%%'
  -- %(commented)s
  AND active = %(active)s
""".strip(),
        {"item_id": 7, "active": True},
    )

    rendered = plan.for_data_api()

    assert "'ignored %(inside)s'" in rendered.sql
    assert "-- %(commented)s" in rendered.sql
    assert "id = :p_item_id" in rendered.sql
    assert "active = :p_active" in rendered.sql
    assert "LIKE '100%'" in rendered.sql
    assert rendered.parameters == (
        {"name": "p_item_id", "value": "7"},
        {"name": "p_active", "value": "true"},
    )


def test_data_api_rendering_uses_fixed_tokens_for_null_and_empty_string() -> None:
    plan = build_parameter_plan(
        "SELECT %(missing)s AS missing, %(empty)s AS empty",
        {"missing": None, "empty": ""},
    )

    rendered = plan.for_data_api()

    assert rendered.sql == "SELECT NULL AS missing, '' AS empty"
    assert rendered.parameters == ()


def test_data_api_sequence_expands_only_as_complete_in_rhs() -> None:
    plan = build_parameter_plan(
        "SELECT 1 WHERE id IN %(ids)s OR parent_id NOT IN %(ids)s",
        {"ids": [1, 2]},
    )

    rendered = plan.for_data_api()

    assert rendered.sql == (
        "SELECT 1 WHERE id IN (:p_ids_0,:p_ids_1) "
        "OR parent_id NOT IN (:p_ids_0,:p_ids_1)"
    )
    assert rendered.parameters == (
        {"name": "p_ids_0", "value": "1"},
        {"name": "p_ids_1", "value": "2"},
    )

    unsupported = build_parameter_plan("SELECT %(ids)s", {"ids": [1, 2]})
    with pytest.raises(SkillError) as caught:
        unsupported.for_data_api()
    assert caught.value.full_code == "capability.parameter_shape_unavailable"


def test_data_api_sequence_renders_each_occurrence_parentheses_independently() -> None:
    rendered = build_parameter_plan(
        "SELECT 1 WHERE id IN %(ids)s OR parent_id IN (%(ids)s)",
        {"ids": [1, 2]},
    ).for_data_api()

    assert rendered.sql == (
        "SELECT 1 WHERE id IN (:p_ids_0,:p_ids_1) "
        "OR parent_id IN (:p_ids_0,:p_ids_1)"
    )
    assert rendered.parameters == (
        {"name": "p_ids_0", "value": "1"},
        {"name": "p_ids_1", "value": "2"},
    )


def test_data_api_sequence_rejects_a_placeholder_that_is_not_the_complete_rhs() -> None:
    plan = build_parameter_plan(
        "SELECT 1 WHERE id IN %(ids)s + 1",
        {"ids": [1, 2]},
    )

    with pytest.raises(SkillError) as caught:
        plan.for_data_api()

    assert caught.value.full_code == "capability.parameter_shape_unavailable"


def test_wire_sequence_expands_only_as_complete_in_rhs() -> None:
    plan = build_parameter_plan(
        "SELECT '100%%' AS label WHERE id IN %(ids)s",
        {"ids": [1, 2]},
    )

    assert plan.for_wire() == (
        "SELECT '100%%' AS label WHERE id IN "
        "(%(__moego_in_ids_0)s,%(__moego_in_ids_1)s)",
        {"__moego_in_ids_0": 1, "__moego_in_ids_1": 2},
    )


def test_wire_sequence_reuses_expansion_for_not_in_and_parenthesized_rhs() -> None:
    rendered = build_parameter_plan(
        "SELECT 1 WHERE id NOT IN %(ids)s OR parent_id IN (%(ids)s)",
        {"ids": (1, 2)},
    ).for_wire()

    assert rendered == (
        "SELECT 1 WHERE id NOT IN "
        "(%(__moego_in_ids_0)s,%(__moego_in_ids_1)s) "
        "OR parent_id IN (%(__moego_in_ids_0)s,%(__moego_in_ids_1)s)",
        {"__moego_in_ids_0": 1, "__moego_in_ids_1": 2},
    )


def test_wire_sequence_keeps_v2_array_value_outside_complete_in_rhs() -> None:
    rendered = build_parameter_plan(
        "SELECT 1 WHERE id IN %(ids)s OR id = ANY(%(ids)s)",
        {"ids": [1, 2]},
    ).for_wire()

    assert rendered == (
        "SELECT 1 WHERE id IN "
        "(%(__moego_in_ids_0)s,%(__moego_in_ids_1)s) "
        "OR id = ANY(%(ids)s)",
        {
            "ids": [1, 2],
            "__moego_in_ids_0": 1,
            "__moego_in_ids_1": 2,
        },
    )


def test_wire_rendering_escapes_ignored_placeholder_text_for_psycopg() -> None:
    plan = build_parameter_plan(
        "SELECT '%(ignored)s', id FROM items WHERE id = %(item_id)s",
        {"item_id": 7},
    )

    assert plan.for_wire() == (
        "SELECT '%%(ignored)s', id FROM items WHERE id = %(item_id)s",
        {"item_id": 7},
    )
