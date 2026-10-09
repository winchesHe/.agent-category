"""Parsing and canonical rendering for complete Redshift object names."""
from __future__ import annotations

import re
import unicodedata

from ..errors import usage_error


_UNQUOTED_IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_$]*\Z")
_IDENTIFIER_MAX_UTF8_BYTES = 127


def _invalid_object(argument: str = "object"):
    return usage_error("invalid_value", details={"argument": argument})


def _validate_identifier(value: str, *, argument: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or len(value.encode("utf-8")) > _IDENTIFIER_MAX_UTF8_BYTES
        or any(unicodedata.category(char).startswith("C") for char in value)
    ):
        raise _invalid_object(argument)
    return value


def _parse_identifier_parts(
    value: str, *, argument: str = "object"
) -> tuple[tuple[str, bool], ...]:
    if not isinstance(value, str):
        raise _invalid_object(argument)
    length = len(value)
    index = 0
    parts: list[tuple[str, bool]] = []
    while index < length:
        while index < length and value[index].isspace():
            index += 1
        if index >= length:
            break
        if value[index] == '"':
            index += 1
            content: list[str] = []
            while index < length:
                char = value[index]
                if char == '"':
                    if index + 1 < length and value[index + 1] == '"':
                        content.append('"')
                        index += 2
                        continue
                    index += 1
                    break
                content.append(char)
                index += 1
            else:
                raise _invalid_object(argument)
            part = "".join(content)
            quoted = True
            while index < length and value[index].isspace():
                index += 1
            if index < length and value[index] != ".":
                raise _invalid_object(argument)
        else:
            start = index
            while index < length and value[index] != ".":
                index += 1
            part = value[start:index].strip()
            quoted = False
            if not _UNQUOTED_IDENTIFIER.fullmatch(part):
                raise _invalid_object(argument)
            part = part.lower()
        _validate_identifier(part, argument=argument)
        parts.append((part, quoted))
        if index < length:
            index += 1
            if index >= length:
                raise _invalid_object(argument)
    return tuple(parts)


def parse_object_name(value: str) -> tuple[str, str, str]:
    """Parse one complete database.schema.relation name without SQL inference."""

    parts = _parse_identifier_parts(value, argument="object")
    if len(parts) != 3:
        raise _invalid_object()
    return tuple(part for part, _quoted in parts)  # type: ignore[return-value]


def parse_database_name(value: str) -> str:
    """Parse one database identifier without treating it as a SQL expression."""

    parts = _parse_identifier_parts(value, argument="database")
    if len(parts) != 1:
        raise usage_error("invalid_value", details={"argument": "database"})
    return parts[0][0]


def parse_database_schema_name(value: str) -> tuple[str, str]:
    """Parse a database.schema identifier with quoted-name round trips."""

    parts = _parse_identifier_parts(value, argument="target")
    if len(parts) != 2:
        raise usage_error("invalid_value", details={"argument": "target"})
    return parts[0][0], parts[1][0]


def quote_identifier(value: str) -> str:
    selected = _validate_identifier(value, argument="object")
    return '"' + selected.replace('"', '""') + '"'


def render_identifier(value: str) -> str:
    """Return one stable identifier while preserving case-sensitive semantics."""

    selected = _validate_identifier(value, argument="object")
    if _UNQUOTED_IDENTIFIER.fullmatch(selected) and selected == selected.lower():
        return selected
    return quote_identifier(selected)


def render_object_name(database: str, schema: str, relation: str) -> str:
    """Return a canonical, round-trippable database.schema.relation name."""

    return ".".join(render_identifier(part) for part in (database, schema, relation))


def render_database_name(database: str) -> str:
    return render_identifier(database)


def render_database_schema_name(database: str, schema: str) -> str:
    return ".".join(render_identifier(part) for part in (database, schema))


def qualified_sql_name(*parts: str) -> str:
    return ".".join(quote_identifier(part) for part in parts)
