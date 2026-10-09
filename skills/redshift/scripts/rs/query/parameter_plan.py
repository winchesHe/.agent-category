"""One parsed parameter plan rendered safely for Wire or Redshift Data API."""
from __future__ import annotations

import json
import math
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from ..errors import SkillError
from .guard import SqlToken, scan_sql, tokenize_sql


_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


@dataclass(frozen=True)
class Placeholder:
    name: str
    start: int
    end: int


@dataclass(frozen=True)
class DataApiParameterPlan:
    sql: str
    parameters: tuple[dict[str, str], ...]


@dataclass(frozen=True)
class ParameterPlan:
    sql: str
    params: Mapping[str, Any]
    placeholders: tuple[Placeholder, ...]
    spans: tuple[SqlToken, ...]

    def for_wire(self) -> tuple[str, dict[str, Any]]:
        significant = tokenize_sql(self.sql)
        opaque = {
            span.start: span
            for span in self.spans
            if span.kind in {"COMMENT", "QUOTED", "QUOTED_IDENTIFIER"}
        }
        by_start = {placeholder.start: placeholder for placeholder in self.placeholders}
        occurrence_count: dict[str, int] = {}
        for placeholder in self.placeholders:
            occurrence_count[placeholder.name] = occurrence_count.get(placeholder.name, 0) + 1
        expanded_count: dict[str, int] = {}
        sequence_names: dict[str, tuple[str, ...]] = {}
        wire_params = dict(self.params)
        used_names = set(wire_params)
        output: list[str] = []
        index = 0
        while index < len(self.sql):
            span = opaque.get(index)
            if span is not None:
                output.append(_escape_psycopg_opaque(self.sql[span.start : span.end]))
                index = span.end
                continue
            placeholder = by_start.get(index)
            if placeholder is not None:
                value = self.params[placeholder.name]
                valid, already_parenthesized = _sequence_context(
                    placeholder,
                    significant,
                )
                if isinstance(value, (list, tuple)) and valid:
                    if not value or any(
                        isinstance(item, (list, tuple, Mapping))
                        or item is None
                        or item == ""
                        for item in value
                    ):
                        raise _unsupported_shape()
                    names = sequence_names.get(placeholder.name)
                    if names is None:
                        generated: list[str] = []
                        for item_index, item in enumerate(value):
                            name = f"__moego_in_{placeholder.name}_{item_index}"
                            while name in used_names:
                                name = f"_{name}"
                            used_names.add(name)
                            wire_params[name] = item
                            generated.append(name)
                        names = tuple(generated)
                        sequence_names[placeholder.name] = names
                    rendered = ",".join(f"%({name})s" for name in names)
                    output.append(
                        rendered if already_parenthesized else f"({rendered})"
                    )
                    expanded_count[placeholder.name] = (
                        expanded_count.get(placeholder.name, 0) + 1
                    )
                else:
                    output.append(self.sql[placeholder.start : placeholder.end])
                index = placeholder.end
                continue
            output.append(self.sql[index])
            index += 1
        for name, count in expanded_count.items():
            if count == occurrence_count[name]:
                wire_params.pop(name, None)
        return "".join(output), wire_params

    def for_data_api(self) -> DataApiParameterPlan:
        significant = tokenize_sql(self.sql)
        opaque = {
            span.start: span
            for span in self.spans
            if span.kind in {"COMMENT", "QUOTED", "QUOTED_IDENTIFIER"}
        }
        by_start = {placeholder.start: placeholder for placeholder in self.placeholders}
        emitted_parameters: set[str] = set()
        output: list[str] = []
        parameters: list[dict[str, str]] = []
        index = 0
        while index < len(self.sql):
            span = opaque.get(index)
            if span is not None:
                output.append(self.sql[span.start : span.end].replace("%%", "%"))
                index = span.end
                continue
            placeholder = by_start.get(index)
            if placeholder is not None:
                rendered, definitions = _render_value(
                    placeholder,
                    self.params[placeholder.name],
                    significant,
                )
                if placeholder.name not in emitted_parameters:
                    parameters.extend(definitions)
                    emitted_parameters.add(placeholder.name)
                output.append(rendered)
                index = placeholder.end
                continue
            if self.sql.startswith("%%", index):
                output.append("%")
                index += 2
                continue
            output.append(self.sql[index])
            index += 1
        return DataApiParameterPlan(sql="".join(output), parameters=tuple(parameters))


def _invalid(reason: str, **details: Any) -> SkillError:
    return SkillError(
        category="query",
        code="invalid_parameters",
        retry_class="after_change",
        details={"reason": reason, **details},
    )


def _unsupported_shape() -> SkillError:
    return SkillError(
        category="capability",
        code="parameter_shape_unavailable",
        retry_class="after_change",
    )


def _escape_psycopg_opaque(value: str) -> str:
    output: list[str] = []
    index = 0
    while index < len(value):
        if value[index] != "%":
            output.append(value[index])
            index += 1
            continue
        if index + 1 < len(value) and value[index + 1] == "%":
            output.append("%%")
            index += 2
            continue
        output.append("%%")
        index += 1
    return "".join(output)


def _contains_mapping(value: Any) -> bool:
    if isinstance(value, Mapping):
        return True
    if isinstance(value, (list, tuple)):
        return any(_contains_mapping(item) for item in value)
    return False


def _placeholders(sql: str, spans: tuple[SqlToken, ...]) -> tuple[Placeholder, ...]:
    opaque = {
        span.start: span
        for span in spans
        if span.kind in {"COMMENT", "QUOTED", "QUOTED_IDENTIFIER"}
    }
    result: list[Placeholder] = []
    index = 0
    while index < len(sql):
        span = opaque.get(index)
        if span is not None:
            index = span.end
            continue
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
        result.append(Placeholder(name=name, start=index, end=close + 2))
        index = close + 2
    return tuple(result)


def _sequence_context(
    placeholder: Placeholder,
    tokens: tuple[SqlToken, ...],
) -> tuple[bool, bool]:
    previous = [token for token in tokens if token.end <= placeholder.start]
    following = [token for token in tokens if token.start >= placeholder.end]
    if previous and previous[-1].kind == "WORD" and previous[-1].value == "IN":
        if not following:
            return True, False
        boundary = following[0]
        if boundary.kind == "SYMBOL" and boundary.value in {")", ",", ";"}:
            return True, False
        if boundary.kind == "WORD" and boundary.value in {
            "AND",
            "OR",
            "GROUP",
            "ORDER",
            "LIMIT",
            "OFFSET",
            "QUALIFY",
            "HAVING",
            "UNION",
            "INTERSECT",
            "EXCEPT",
            "WHEN",
            "THEN",
            "ELSE",
            "END",
        }:
            return True, False
        return False, False
    if (
        len(previous) >= 2
        and previous[-1].kind == "SYMBOL"
        and previous[-1].value == "("
        and previous[-2].kind == "WORD"
        and previous[-2].value == "IN"
        and following
        and following[0].kind == "SYMBOL"
        and following[0].value == ")"
    ):
        return True, True
    return False, False


def _scalar_value(value: Any) -> str:
    if isinstance(value, str):
        if not value:
            raise _unsupported_shape()
        return value
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float) and math.isfinite(value):
        return json.dumps(value, allow_nan=False, separators=(",", ":"))
    raise _unsupported_shape()


def _render_value(
    placeholder: Placeholder,
    value: Any,
    tokens: tuple[SqlToken, ...],
) -> tuple[str, tuple[dict[str, str], ...]]:
    if value is None:
        return "NULL", ()
    if value == "":
        return "''", ()
    if isinstance(value, (list, tuple)):
        valid, already_parenthesized = _sequence_context(placeholder, tokens)
        if not valid or not value or any(
            isinstance(item, (list, tuple, Mapping)) or item is None or item == ""
            for item in value
        ):
            raise _unsupported_shape()
        rendered = tuple(
            {"name": f"p_{placeholder.name}_{index}", "value": _scalar_value(item)}
            for index, item in enumerate(value)
        )
        names = ",".join(f":{item['name']}" for item in rendered)
        return (names if already_parenthesized else f"({names})"), rendered
    name = f"p_{placeholder.name}"
    return f":{name}", ({"name": name, "value": _scalar_value(value)},)


def build_parameter_plan(
    sql: str,
    params: Mapping[str, Any] | None,
) -> ParameterPlan:
    spans = scan_sql(sql)
    placeholders = _placeholders(sql, spans)
    if params is None:
        supplied: dict[str, Any] = {}
    elif isinstance(params, Mapping):
        supplied = dict(params)
    else:
        raise _invalid("object_required")
    for name, value in supplied.items():
        if not isinstance(name, str) or not _NAME.fullmatch(name):
            raise _invalid("invalid_name", name=str(name))
        if _contains_mapping(value):
            raise _invalid("unsupported_value", name=name)
    required = {placeholder.name for placeholder in placeholders}
    provided = set(supplied)
    missing = sorted(required - provided)
    if missing:
        raise _invalid("missing", names=missing)
    extra = sorted(provided - required)
    if extra:
        raise _invalid("extra", names=extra)
    return ParameterPlan(
        sql=sql,
        params=supplied,
        placeholders=placeholders,
        spans=spans,
    )
