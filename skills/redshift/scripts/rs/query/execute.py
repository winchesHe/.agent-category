"""Bounded readonly query execution with stable typed results."""
from __future__ import annotations

import time
import uuid
from collections import Counter
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any

from ..errors import Interrupted, SkillError, config_error, usage_error
from ..models import Column, QueryResult
from .guard import validate_read_only_sql
from .parameter_plan import build_parameter_plan


JSON_DEFAULT_LIMIT = 200
JSON_MAX_LIMIT = 200
ARTIFACT_MAX_LIMIT = 100_000
DEFAULT_STATEMENT_TIMEOUT_MS = 30_000
STREAM_FETCH_BATCH_SIZE = 64
_TYPE_NAMES = {
    16: "boolean",
    17: "bytea",
    18: "char",
    19: "name",
    20: "bigint",
    21: "smallint",
    23: "integer",
    25: "text",
    26: "oid",
    114: "json",
    700: "real",
    701: "double precision",
    1042: "character",
    1043: "character varying",
    1082: "date",
    1083: "time without time zone",
    1114: "timestamp without time zone",
    1184: "timestamp with time zone",
    1186: "interval",
    1266: "time with time zone",
    1560: "bit",
    1562: "bit varying",
    1700: "numeric",
    2950: "uuid",
    3802: "jsonb",
}


def require_database(database: str | None) -> str:
    if not database:
        raise config_error("missing", key="connection.database")
    return database


def validate_statement_timeout(statement_timeout_ms: int) -> int:
    if isinstance(statement_timeout_ms, bool) or statement_timeout_ms <= 0:
        raise usage_error(
            "invalid_value",
            details={"argument": "--timeout-ms"},
        )
    return statement_timeout_ms


def _bounded_limit(limit: int | None, fmt: str) -> int:
    if fmt not in {"json", "csv", "ndjson"}:
        raise usage_error("invalid_value", details={"argument": "--format"})
    value = JSON_DEFAULT_LIMIT if limit is None else limit
    maximum = JSON_MAX_LIMIT if fmt == "json" else ARTIFACT_MAX_LIMIT
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0 or value > maximum:
        raise SkillError(
            category="query",
            code="limit_out_of_range",
            retry_class="after_change",
            details={"maximum": maximum},
        )
    return value


def _diagnostic_attribute(diagnostic: Any, name: str) -> Any:
    try:
        return getattr(diagnostic, name, None)
    except Exception:
        return None


def _safe_identifier(value: Any) -> str | None:
    if not isinstance(value, str) or not value or not value.strip():
        return None
    if len(value) > 256 or any(
        ord(character) < 32 or ord(character) == 127 for character in value
    ):
        return None
    return value


def _safe_statement_position(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value > 0 else None
    if isinstance(value, str) and value.isascii() and value.isdigit():
        parsed = int(value)
        return parsed if parsed > 0 else None
    return None


def _safe_sqlstate(value: Any) -> str | None:
    if not isinstance(value, str) or len(value) != 5 or not value.isascii():
        return None
    if not value.isalnum() or value != value.upper():
        return None
    return value


def _safe_query_diagnostics(exc: BaseException) -> dict[str, Any]:
    diagnostic = _diagnostic_attribute(exc, "diag")
    if diagnostic is None:
        return {}

    details: dict[str, Any] = {}
    for source_name, output_name in (
        ("schema_name", "schema"),
        ("table_name", "table"),
        ("column_name", "column"),
    ):
        value = _safe_identifier(_diagnostic_attribute(diagnostic, source_name))
        if value is not None:
            details[output_name] = value

    position = _safe_statement_position(
        _diagnostic_attribute(diagnostic, "statement_position")
    )
    if position is not None:
        details["position"] = position
    return details


def map_query_exception(exc: BaseException) -> SkillError:
    sqlstate = getattr(exc, "pgcode", None) or getattr(exc, "sqlstate", None)
    safe_sqlstate = _safe_sqlstate(sqlstate)
    diagnostics = {"sqlState": safe_sqlstate} if safe_sqlstate else {}
    if sqlstate == "57014":
        return SkillError(
            category="query",
            code="timeout",
            retry_class="transient",
            diagnostics=diagnostics,
        )
    if sqlstate == "42P01":
        return SkillError(
            category="query",
            code="undefined_table",
            retry_class="after_change",
            details=_safe_query_diagnostics(exc),
            suggestion="search_object",
            diagnostics=diagnostics,
        )
    if sqlstate == "42703":
        return SkillError(
            category="query",
            code="undefined_column",
            retry_class="after_change",
            details=_safe_query_diagnostics(exc),
            suggestion="describe_object",
            diagnostics=diagnostics,
        )
    if sqlstate == "42601":
        return SkillError(
            category="query",
            code="syntax_error",
            retry_class="after_change",
            details=_safe_query_diagnostics(exc),
            suggestion="inspect_sql_position",
            diagnostics=diagnostics,
        )
    if sqlstate == "42846":
        return SkillError(
            category="query",
            code="cannot_coerce",
            retry_class="after_change",
            details=_safe_query_diagnostics(exc),
            suggestion="inspect_types",
            diagnostics=diagnostics,
        )
    if sqlstate == "42883":
        return SkillError(
            category="query",
            code="undefined_function",
            retry_class="after_change",
            details=_safe_query_diagnostics(exc),
            suggestion="inspect_function_signature",
            diagnostics=diagnostics,
        )
    if sqlstate == "42501":
        return SkillError(
            category="query",
            code="permission_denied",
            retry_class="never",
            diagnostics=diagnostics,
        )
    if isinstance(sqlstate, str) and sqlstate.startswith("08"):
        return SkillError(
            category="connection",
            code="unavailable",
            retry_class="transient",
            diagnostics=diagnostics,
        )
    if sqlstate == "25006":
        return SkillError(
            category="capability",
            code="cross_database_read_unavailable",
            retry_class="never",
            diagnostics=diagnostics,
        )
    return SkillError(
        category="internal",
        code="unexpected",
        retry_class="never",
        diagnostics=diagnostics,
    )


def _with_connection_database(error: SkillError, database: str) -> SkillError:
    meta = dict(error.meta)
    meta["connectionDatabase"] = database
    return SkillError(
        category=error.category,
        code=error.code,
        retry_class=error.retry_class,
        message=error.message,
        details=error.details,
        suggestion=error.suggestion,
        exit_code_override=error.exit_code_override,
        meta=meta,
        diagnostics=error.diagnostics,
    )


def _columns(cursor: Any) -> tuple[Column, ...]:
    columns: list[Column] = []
    for item in cursor.description or ():
        if hasattr(item, "name"):
            name = item.name
            type_code = item.type_code
        else:
            name = item[0]
            type_code = item[1]
        data_type = (
            _TYPE_NAMES.get(type_code, f"oid:{type_code}")
            if type(type_code) is int
            else str(type_code)
        )
        columns.append(Column(name=str(name), data_type=data_type))
    duplicates = sorted(
        name for name, count in Counter(column.name for column in columns).items() if count > 1
    )
    if duplicates:
        raise SkillError(
            category="query",
            code="duplicate_output_column",
            retry_class="after_change",
            details={"columns": duplicates},
        )
    return tuple(columns)


@dataclass
class StreamingQuery:
    columns: tuple[Column, ...]
    connection_database: str
    statement_timeout_ms: int
    elapsed_ms: int
    _cursor: Any
    _limit: int
    _initial_batch: list[Any]
    row_count: int = 0
    truncated: bool = False

    def _fetchmany(self) -> list[Any]:
        try:
            return self._cursor.fetchmany(STREAM_FETCH_BATCH_SIZE)
        except Interrupted:
            raise
        except SkillError:
            raise
        except Exception as exc:
            raise map_query_exception(exc) from exc

    def __iter__(self) -> Iterator[dict[str, Any]]:
        names = tuple(column.name for column in self.columns)
        batch = self._initial_batch
        self._initial_batch = []
        while True:
            if not batch:
                return
            for row in batch:
                if self.row_count >= self._limit:
                    self.truncated = True
                    return
                values = tuple(row)
                if len(values) != len(names):
                    raise SkillError(
                        category="internal",
                        code="unexpected",
                        retry_class="never",
                    )
                self.row_count += 1
                yield dict(zip(names, values))
            started = time.monotonic()
            batch = self._fetchmany()
            self.elapsed_ms += int((time.monotonic() - started) * 1000)


@contextmanager
def open_query_stream(
    *,
    database: str,
    sql: str,
    params: Mapping[str, Any] | None = None,
    limit: int | None = None,
    statement_timeout_ms: int = DEFAULT_STATEMENT_TIMEOUT_MS,
    connection_factory: Callable[..., Any],
) -> Iterator[StreamingQuery]:
    """Open one bounded artifact query backed by a named server-side cursor."""

    selected_database = require_database(database)
    try:
        timeout = validate_statement_timeout(statement_timeout_ms)
        bounded_limit = _bounded_limit(limit, "ndjson")
        readonly_sql = validate_read_only_sql(sql)
        wire_sql, validated_params = build_parameter_plan(
            readonly_sql, params
        ).for_wire()
        wrapped_sql = (
            "SELECT * FROM (\n"
            f"{wire_sql}\n"
            f") AS _moego_result LIMIT {bounded_limit + 1}"
        )
        started = time.monotonic()
        try:
            with connection_factory(
                database=selected_database,
                statement_timeout_ms=timeout,
            ) as conn:
                cursor = None
                primary_error: BaseException | None = None
                try:
                    cursor = conn.cursor(name=f"moego_artifact_{uuid.uuid4().hex}")
                    if validated_params:
                        cursor.execute(wrapped_sql, validated_params)
                    elif "%%" in wire_sql:
                        cursor.execute(wrapped_sql, ())
                    else:
                        cursor.execute(wrapped_sql)
                    initial_batch = cursor.fetchmany(STREAM_FETCH_BATCH_SIZE)
                    columns = _columns(cursor)
                    if not columns:
                        raise SkillError(
                            category="internal",
                            code="unexpected",
                            retry_class="never",
                        )
                    stream = StreamingQuery(
                        columns=columns,
                        connection_database=selected_database,
                        statement_timeout_ms=timeout,
                        elapsed_ms=int((time.monotonic() - started) * 1000),
                        _cursor=cursor,
                        _limit=bounded_limit,
                        _initial_batch=initial_batch,
                    )
                    yield stream
                except BaseException as exc:
                    primary_error = exc
                    raise
                finally:
                    if cursor is not None:
                        try:
                            cursor.close()
                        except Interrupted:
                            if primary_error is None:
                                raise
                        except Exception:
                            pass
        except Interrupted:
            raise
        except SkillError:
            raise
        except Exception as exc:
            raise map_query_exception(exc) from exc
    except Interrupted:
        raise
    except SkillError as exc:
        raise _with_connection_database(exc, selected_database) from exc


def execute_query(
    *,
    database: str,
    sql: str,
    params: Mapping[str, Any] | None = None,
    limit: int | None = None,
    statement_timeout_ms: int = DEFAULT_STATEMENT_TIMEOUT_MS,
    connection_factory: Callable[..., Any],
) -> QueryResult:
    """Execute one bounded SELECT using the explicitly supplied connection database."""

    selected_database = require_database(database)
    try:
        timeout = validate_statement_timeout(statement_timeout_ms)
        bounded_limit = _bounded_limit(limit, "json")
        readonly_sql = validate_read_only_sql(sql)
        wire_sql, validated_params = build_parameter_plan(
            readonly_sql, params
        ).for_wire()
        wrapped_sql = (
            "SELECT * FROM (\n"
            f"{wire_sql}\n"
            f") AS _moego_result LIMIT {bounded_limit + 1}"
        )
        started = time.monotonic()
        try:
            with connection_factory(
                database=selected_database,
                statement_timeout_ms=timeout,
            ) as conn:
                with conn.cursor() as cursor:
                    try:
                        if validated_params:
                            cursor.execute(wrapped_sql, validated_params)
                        elif "%%" in wire_sql:
                            cursor.execute(wrapped_sql, ())
                        else:
                            cursor.execute(wrapped_sql)
                        columns = _columns(cursor)
                        rows = list(cursor.fetchall())
                    except SkillError:
                        raise
                    except Exception as exc:
                        raise map_query_exception(exc) from exc
        except SkillError:
            raise

        truncated = len(rows) > bounded_limit
        visible_rows = rows[:bounded_limit]
        names = tuple(column.name for column in columns)
        records_list: list[dict[str, Any]] = []
        for row in visible_rows:
            values = tuple(row)
            if len(values) != len(names):
                raise SkillError(
                    category="internal",
                    code="unexpected",
                    retry_class="never",
                )
            records_list.append(dict(zip(names, values)))
        records = tuple(records_list)
        elapsed_ms = int((time.monotonic() - started) * 1000)
        return QueryResult(
            columns=columns,
            records=records,
            row_count=len(records),
            truncated=truncated,
            elapsed_ms=elapsed_ms,
            connection_database=selected_database,
            statement_timeout_ms=timeout,
        )
    except SkillError as exc:
        raise _with_connection_database(exc, selected_database) from exc
