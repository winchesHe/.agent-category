"""Redshift EXPLAIN execution with non-authoritative best-effort advisories."""
from __future__ import annotations

import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from ..errors import SkillError
from .execute import (
    DEFAULT_STATEMENT_TIMEOUT_MS,
    _with_connection_database,
    map_query_exception,
    require_database,
    validate_statement_timeout,
)
from .guard import SqlToken, tokenize_sql, validate_read_only_sql
from .parameter_plan import build_parameter_plan


@dataclass(frozen=True)
class ExplainResult:
    plan: tuple[str, ...]
    advisories: tuple[dict[str, str], ...]
    elapsed_ms: int
    connection_database: str
    statement_timeout_ms: int


def _uses_select_star(tokens: tuple[SqlToken, ...]) -> bool:
    depths: list[int] = []
    depth = 0
    for token in tokens:
        depths.append(depth)
        if token.kind == "SYMBOL" and token.value == "(":
            depth += 1
        elif token.kind == "SYMBOL" and token.value == ")":
            depth -= 1

    for index, token in enumerate(tokens):
        if token.kind != "WORD" or token.value != "SELECT":
            continue
        select_depth = depths[index]
        for candidate in range(index + 1, len(tokens)):
            if depths[candidate] != select_depth:
                continue
            item = tokens[candidate]
            if item.kind == "WORD" and item.value in {
                "EXCEPT",
                "FROM",
                "INTERSECT",
                "UNION",
            }:
                break
            if item.kind != "SYMBOL" or item.value != "*":
                continue
            previous = tokens[candidate - 1]
            if depths[candidate - 1] != select_depth:
                continue
            if previous.kind == "SYMBOL" and previous.value in {",", "."}:
                return True
            if previous.kind == "WORD" and previous.value in {"ALL", "DISTINCT", "SELECT"}:
                return True
    return False


def _build_advisories(sql: str) -> tuple[dict[str, str], ...]:
    if not _uses_select_star(tokenize_sql(sql)):
        return ()
    return (
        {
            "code": "query.select_star",
            "severity": "info",
            "message": "查询使用 SELECT *",
        },
    )


def execute_explain(
    *,
    database: str,
    sql: str,
    params: Mapping[str, Any] | None = None,
    statement_timeout_ms: int = DEFAULT_STATEMENT_TIMEOUT_MS,
    connection_factory: Callable[..., Any],
) -> ExplainResult:
    """Return the Redshift plan even if local advisory generation fails."""

    selected_database = require_database(database)
    try:
        timeout = validate_statement_timeout(statement_timeout_ms)
        readonly_sql = validate_read_only_sql(sql)
        wire_sql, validated_params = build_parameter_plan(
            readonly_sql, params
        ).for_wire()
        explain_sql = f"EXPLAIN\n{wire_sql}"
        started = time.monotonic()
        try:
            with connection_factory(
                database=selected_database,
                statement_timeout_ms=timeout,
            ) as conn:
                with conn.cursor() as cursor:
                    try:
                        if validated_params:
                            cursor.execute(explain_sql, validated_params)
                        elif "%%" in wire_sql:
                            cursor.execute(explain_sql, ())
                        else:
                            cursor.execute(explain_sql)
                        plan = tuple(str(row[0]) for row in cursor.fetchall())
                    except SkillError:
                        raise
                    except Exception as exc:
                        raise map_query_exception(exc) from exc
        except SkillError:
            raise

        try:
            advisories = _build_advisories(readonly_sql)
        except Exception:
            advisories = ()
        elapsed_ms = int((time.monotonic() - started) * 1000)
        return ExplainResult(
            plan=plan,
            advisories=advisories,
            elapsed_ms=elapsed_ms,
            connection_database=selected_database,
            statement_timeout_ms=timeout,
        )
    except SkillError as exc:
        raise _with_connection_database(exc, selected_database) from exc
