from __future__ import annotations

import pytest

from scripts.rs.errors import SkillError
from scripts.rs.query.params import parse_params_json, validate_params


def test_params_json_accepts_only_an_object_and_preserves_json_values() -> None:
    assert parse_params_json(
        '{"text":"x","number":2,"flag":true,"nothing":null,"items":[1,2],"nested":{"a":1}}'
    ) == {
        "text": "x",
        "number": 2,
        "flag": True,
        "nothing": None,
        "items": [1, 2],
        "nested": {"a": 1},
    }
    assert parse_params_json(None) == {}


@pytest.mark.parametrize("raw", ["null", "[]", '"value"', "1", "true"])
def test_params_json_rejects_non_object_roots(raw: str) -> None:
    with pytest.raises(SkillError) as caught:
        parse_params_json(raw)
    assert caught.value.full_code == "query.invalid_parameters"
    assert caught.value.details == {"reason": "object_required"}


@pytest.mark.parametrize("raw", ['{"a":1,"a":2}', '{"outer":{"a":1,"a":2}}'])
def test_params_json_rejects_duplicate_keys_at_any_depth(raw: str) -> None:
    with pytest.raises(SkillError) as caught:
        parse_params_json(raw)
    assert caught.value.full_code == "query.invalid_parameters"
    assert caught.value.details == {"reason": "duplicate_key", "name": "a"}


def test_params_json_rejects_invalid_json_without_exposing_input() -> None:
    with pytest.raises(SkillError) as caught:
        parse_params_json('{"secret":"unterminated}')
    assert caught.value.full_code == "query.invalid_parameters"
    assert caught.value.details == {"reason": "invalid_json"}
    assert "secret" not in str(caught.value.to_payload())


def test_named_placeholders_and_literal_percent_are_validated() -> None:
    params = {"email": "person@example.invalid", "limit_value": 10}
    assert validate_params(
        "SELECT '100%%' AS ratio WHERE email = %(email)s LIMIT %(limit_value)s",
        params,
    ) == params


def test_placeholder_validation_ignores_quoted_and_commented_text() -> None:
    assert validate_params(
        "SELECT '%(ignored)s' AS literal, %(real)s -- %(commented)s",
        {"real": 1},
    ) == {"real": 1}


@pytest.mark.parametrize(
    ("sql", "reason"),
    [
        ("SELECT * FROM t WHERE id = %s", "positional_placeholder"),
        ("SELECT 10 % 3", "literal_percent_must_be_escaped"),
        ("SELECT %(bad-name)s", "invalid_placeholder"),
        ("SELECT %(missing_end", "invalid_placeholder"),
        ("SELECT %x", "literal_percent_must_be_escaped"),
    ],
)
def test_invalid_placeholder_forms_are_rejected(sql: str, reason: str) -> None:
    with pytest.raises(SkillError) as caught:
        validate_params(sql, {})
    assert caught.value.full_code == "query.invalid_parameters"
    assert caught.value.details["reason"] == reason


def test_missing_and_extra_parameters_are_rejected_before_execution() -> None:
    with pytest.raises(SkillError) as missing:
        validate_params("SELECT %(a)s, %(b)s, %(a)s", {"a": 1})
    assert missing.value.full_code == "query.invalid_parameters"
    assert missing.value.details == {"reason": "missing", "names": ["b"]}

    with pytest.raises(SkillError) as extra:
        validate_params("SELECT %(a)s", {"a": 1, "unused": "private"})
    assert extra.value.full_code == "query.invalid_parameters"
    assert extra.value.details == {"reason": "extra", "names": ["unused"]}


@pytest.mark.parametrize(
    "value",
    [{"nested": 1}, [1, {"nested": 2}], ("ok", {"nested": 3})],
)
def test_mapping_parameter_values_are_rejected_before_driver_binding(value) -> None:
    with pytest.raises(SkillError) as caught:
        validate_params("SELECT %(payload)s", {"payload": value})

    assert caught.value.full_code == "query.invalid_parameters"
    assert caught.value.details == {"reason": "unsupported_value", "name": "payload"}


def test_scalar_and_array_parameter_values_remain_supported() -> None:
    params = {"items": [1, 2], "flag": True, "nothing": None}
    assert validate_params(
        "SELECT %(items)s, %(flag)s, %(nothing)s",
        params,
    ) == params


def test_parameter_names_must_be_valid_named_placeholder_identifiers() -> None:
    with pytest.raises(SkillError) as caught:
        validate_params("SELECT 1", {"bad-name": "private"})
    assert caught.value.full_code == "query.invalid_parameters"
    assert caught.value.details == {"reason": "invalid_name", "name": "bad-name"}
