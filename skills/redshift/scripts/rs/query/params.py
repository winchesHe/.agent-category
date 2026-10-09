"""Strict JSON and psycopg named-parameter preflight."""
from __future__ import annotations

import json
import re
from collections.abc import Mapping
from typing import Any

from ..errors import SkillError


_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class _DuplicateKey(ValueError):
    def __init__(self, name: str) -> None:
        super().__init__(name)
        self.name = name


def _invalid(reason: str, **details: Any) -> SkillError:
    return SkillError(
        category="query",
        code="invalid_parameters",
        retry_class="after_change",
        details={"reason": reason, **details},
    )


def _object_without_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for name, value in pairs:
        if name in result:
            raise _DuplicateKey(name)
        result[name] = value
    return result


def _reject_json_constant(_: str) -> None:
    raise ValueError("non-standard JSON constant")


def parse_params_json(raw: str | None) -> dict[str, Any]:
    """Parse a JSON object while rejecting duplicate keys and non-standard JSON."""

    if raw is None:
        return {}
    try:
        value = json.loads(
            raw,
            object_pairs_hook=_object_without_duplicates,
            parse_constant=_reject_json_constant,
        )
    except _DuplicateKey as exc:
        raise _invalid("duplicate_key", name=exc.name) from exc
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise _invalid("invalid_json") from exc
    if not isinstance(value, dict):
        raise _invalid("object_required")
    return value


def _placeholder_names(sql: str) -> set[str]:
    names: set[str] = set()
    index = 0
    while index < len(sql):
        if sql[index] != "%":
            index += 1
            continue
        if index + 1 >= len(sql):
            raise _invalid("literal_percent_must_be_escaped")
        marker = sql[index + 1]
        if marker == "%":
            index += 2
            continue
        if marker == "s":
            raise _invalid("positional_placeholder")
        if marker != "(":
            raise _invalid("literal_percent_must_be_escaped")
        close = sql.find(")", index + 2)
        if close < 0 or close + 1 >= len(sql) or sql[close + 1] != "s":
            raise _invalid("invalid_placeholder")
        name = sql[index + 2 : close]
        if not _NAME.fullmatch(name):
            raise _invalid("invalid_placeholder", name=name)
        names.add(name)
        index = close + 2
    return names


def _contains_mapping(value: Any) -> bool:
    if isinstance(value, Mapping):
        return True
    if isinstance(value, (list, tuple)):
        return any(_contains_mapping(item) for item in value)
    return False


def validate_params(
    sql: str,
    params: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Validate placeholder syntax and exact parameter-name coverage."""

    from .parameter_plan import build_parameter_plan

    return dict(build_parameter_plan(sql, params).params)
