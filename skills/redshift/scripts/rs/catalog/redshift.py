"""Readonly Redshift metadata adapters for catalog build and live describe."""
from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Mapping, Sequence
from types import TracebackType
from typing import Any

from ..errors import SkillError
from .identifiers import (
    parse_object_name,
    qualified_sql_name as _qualified,
    render_object_name,
)
from .live import MetadataRead


ConnectionFactory = Callable[..., Any]
_SYSTEM_SCHEMAS = {"information_schema", "pg_catalog", "pg_internal"}
_SHOW_ROW_LIMIT = 10_000
_CATALOG_SVV_ROW_LIMIT = 100_000
_DESCRIBE_ROW_LIMIT = 100_000
_METADATA_TEXT_MAX_UTF8_BYTES = 4_096


def _reject_catalog_show_ceiling(rows: Sequence[Mapping[str, Any]]) -> None:
    if len(rows) >= _SHOW_ROW_LIMIT:
        raise SkillError("metadata", "limit_exceeded", "after_change")


def _column_names(cursor: Any) -> tuple[str, ...]:
    names: list[str] = []
    for item in cursor.description or ():
        names.append(str(getattr(item, "name", item[0])))
    return tuple(names)


def _rows(cursor: Any, *, row_limit: int) -> tuple[tuple[dict[str, Any], ...], bool]:
    names = _column_names(cursor)
    result: list[dict[str, Any]] = []
    remaining = row_limit + 1
    while remaining > 0:
        batch = cursor.fetchmany(min(1_024, remaining))
        if not batch:
            break
        for raw in batch:
            if len(result) == row_limit:
                return tuple(result), True
            values = tuple(raw)
            if len(names) != len(values):
                raise SkillError("metadata", "incomplete", "transient")
            result.append(dict(zip(names, values)))
        remaining -= len(batch)
    return tuple(result), False


def _metadata_error(exc: BaseException, *, show_operation: bool) -> SkillError:
    sqlstate = getattr(exc, "pgcode", None) or getattr(exc, "sqlstate", None)
    if sqlstate == "57014":
        return SkillError("metadata", "timeout", "transient")
    if sqlstate == "42501":
        return SkillError("metadata", "permission_denied", "never")
    if sqlstate == "3D000":
        return SkillError("connection", "database_not_found", "after_change")
    if isinstance(sqlstate, str) and sqlstate.startswith("08"):
        return SkillError("connection", "unavailable", "transient")
    if show_operation and sqlstate == "0A000":
        return SkillError(
            "capability",
            "show_metadata_unavailable",
            "after_change",
        )
    return SkillError("internal", "unexpected", "never")


def _normalize_database_type(value: Any) -> str:
    normalized = str(value or "").strip().casefold()
    if normalized == "local":
        return "local"
    if normalized in {"shared", "share", "datashare"} or "share" in normalized:
        return "datashare"
    if "catalog" in normalized:
        return "catalog"
    if "external" in normalized:
        return "external"
    return "unknown"


def _normalize_relation_type(value: Any) -> str:
    normalized = str(value or "").strip().casefold()
    if normalized in {"table", "base table", "external table"}:
        return "table"
    if normalized in {"view", "materialized view"}:
        return "view"
    raise SkillError("metadata", "incomplete", "transient")


def _nullable(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    normalized = value.strip().casefold() if isinstance(value, str) else ""
    if normalized in {"yes", "true", "t", "1"}:
        return True
    if normalized in {"no", "false", "f", "0"}:
        return False
    raise SkillError("metadata", "incomplete", "transient")


def _column(row: Mapping[str, Any]) -> dict[str, Any]:
    required = {"column_name", "ordinal_position", "is_nullable", "data_type"}
    if not required.issubset(row):
        raise SkillError("metadata", "incomplete", "transient")
    ordinal = row["ordinal_position"]
    if type(ordinal) is not int or ordinal <= 0:
        raise SkillError("metadata", "incomplete", "transient")
    name = row["column_name"]
    data_type = row["data_type"]
    if not isinstance(name, str) or not name or not isinstance(data_type, str) or not data_type:
        raise SkillError("metadata", "incomplete", "transient")
    return {
        "name": name,
        "dataType": data_type,
        "nullable": _nullable(row["is_nullable"]),
        "ordinal": ordinal,
    }


class _RedshiftMetadataBase:
    def __init__(
        self,
        *,
        control_database: str,
        statement_timeout_ms: int,
        connection_factory: ConnectionFactory,
    ) -> None:
        self.control_database = control_database
        self.statement_timeout_ms = statement_timeout_ms
        self.connection_factory = connection_factory

    def _execute_on_connection(
        self,
        conn: Any,
        *,
        sql: str,
        params: Mapping[str, Any] | None,
        show_operation: bool,
        row_limit: int,
        overflow_policy: str,
    ) -> tuple[tuple[dict[str, Any], ...], bool, bool]:
        notices = getattr(conn, "notices", None)
        if isinstance(notices, list):
            notices.clear()
        configure = getattr(conn, "configure_metadata", None)
        if callable(configure):
            configure(row_limit=row_limit, overflow_policy=overflow_policy)
        with conn.cursor() as cursor:
            try:
                cursor.execute(sql, params)
                records, overflow = _rows(cursor, row_limit=row_limit)
                overflow = overflow or bool(getattr(cursor, "metadata_overflow", False))
            except SkillError:
                raise
            except Exception as exc:
                raise _metadata_error(
                    exc,
                    show_operation=show_operation,
                ) from exc
        if overflow and overflow_policy == "raise":
            raise SkillError("metadata", "limit_exceeded", "after_change")
        return records, bool(getattr(conn, "notices", ())), overflow

    def _execute(
        self,
        *,
        database: str,
        sql: str,
        params: Mapping[str, Any] | None = None,
        show_operation: bool,
        row_limit: int,
        overflow_policy: str,
    ) -> tuple[tuple[dict[str, Any], ...], bool, bool]:
        try:
            with self.connection_factory(
                database=database,
                statement_timeout_ms=self.statement_timeout_ms,
            ) as conn:
                return self._execute_on_connection(
                    conn,
                    sql=sql,
                    params=params,
                    show_operation=show_operation,
                    row_limit=row_limit,
                    overflow_policy=overflow_policy,
                )
        except SkillError:
            raise


class RedshiftCatalogSource(_RedshiftMetadataBase):
    """Bounded live metadata source used to build one catalog snapshot."""

    def __enter__(self) -> "RedshiftCatalogSource":
        self._control_context = self.connection_factory(
            database=self.control_database,
            statement_timeout_ms=self.statement_timeout_ms,
        )
        self._control_connection = self._control_context.__enter__()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool | None:
        context = getattr(self, "_control_context", None)
        self._control_connection = None
        self._control_context = None
        if context is None:
            return None
        return context.__exit__(exc_type, exc, traceback)

    def _execute_control(
        self,
        *,
        sql: str,
        params: Mapping[str, Any] | None = None,
        show_operation: bool,
        row_limit: int,
        overflow_policy: str,
    ) -> tuple[tuple[dict[str, Any], ...], bool, bool]:
        conn = getattr(self, "_control_connection", None)
        if conn is None:
            return self._execute(
                database=self.control_database,
                sql=sql,
                params=params,
                show_operation=show_operation,
                row_limit=row_limit,
                overflow_policy=overflow_policy,
            )
        return self._execute_on_connection(
            conn,
            sql=sql,
            params=params,
            show_operation=show_operation,
            row_limit=row_limit,
            overflow_policy=overflow_policy,
        )

    def show_databases(self) -> Sequence[Mapping[str, Any]]:
        rows, warned, _overflow = self._execute_control(
            sql="SHOW DATABASES",
            show_operation=True,
            row_limit=_SHOW_ROW_LIMIT,
            overflow_policy="raise",
        )
        if warned:
            raise SkillError("metadata", "incomplete", "transient")
        _reject_catalog_show_ceiling(rows)
        result: list[dict[str, str]] = []
        seen: set[str] = set()
        for row in rows:
            name = row.get("database_name")
            if not isinstance(name, str) or not name or name in seen:
                raise SkillError("metadata", "incomplete", "transient")
            seen.add(name)
            result.append(
                {
                    "name": name,
                    "databaseType": _normalize_database_type(row.get("database_type")),
                }
            )
        return tuple(result)

    def show_schemas(self, database: str) -> Sequence[str]:
        rows, warned, _overflow = self._execute_control(
            sql=f"SHOW SCHEMAS FROM DATABASE {_qualified(database)}",
            show_operation=True,
            row_limit=_SHOW_ROW_LIMIT,
            overflow_policy="raise",
        )
        if warned:
            raise SkillError("metadata", "incomplete", "transient")
        _reject_catalog_show_ceiling(rows)
        schemas: list[str] = []
        for row in rows:
            name = row.get("schema_name")
            if not isinstance(name, str) or not name:
                raise SkillError("metadata", "incomplete", "transient")
            if name not in _SYSTEM_SCHEMAS:
                schemas.append(name)
        if len(schemas) != len(set(schemas)):
            raise SkillError("metadata", "incomplete", "transient")
        return tuple(schemas)

    def show_relations(
        self,
        database: str,
    ) -> Mapping[str, Sequence[Mapping[str, Any]]]:
        sql = """
SELECT database_name, schema_name, table_name, table_type, remarks
FROM SVV_ALL_TABLES
WHERE database_name = %(database)s
ORDER BY schema_name, table_name
""".strip()
        rows, warned, _overflow = self._execute_control(
            sql=sql,
            params={"database": database},
            show_operation=False,
            row_limit=_CATALOG_SVV_ROW_LIMIT,
            overflow_policy="raise",
        )
        if warned:
            raise SkillError("metadata", "incomplete", "transient")
        grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
        seen: set[tuple[str, str]] = set()
        for row in rows:
            row_database = row.get("database_name")
            schema = row.get("schema_name")
            name = row.get("table_name")
            key = (schema, name)
            if (
                row_database != database
                or not isinstance(schema, str)
                or not schema
                or not isinstance(name, str)
                or not name
                or key in seen
            ):
                raise SkillError("metadata", "incomplete", "transient")
            seen.add(key)
            grouped[schema].append(
                {
                    "name": name,
                    "relationType": _normalize_relation_type(row.get("table_type")),
                    "description": row.get("remarks")
                    if isinstance(row.get("remarks"), str)
                    else None,
                }
            )
        return {schema: tuple(relations) for schema, relations in grouped.items()}

    def show_columns(self, database: str) -> Mapping[str, Sequence[Mapping[str, Any]]]:
        sql = """
SELECT database_name, schema_name, table_name, column_name,
       ordinal_position, is_nullable, data_type
FROM SVV_ALL_COLUMNS
WHERE database_name = %(database)s
ORDER BY schema_name, table_name, ordinal_position
""".strip()
        rows, warned, _overflow = self._execute_control(
            sql=sql,
            params={"database": database},
            show_operation=False,
            row_limit=_CATALOG_SVV_ROW_LIMIT,
            overflow_policy="raise",
        )
        if warned:
            raise SkillError("metadata", "incomplete", "transient")
        grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in rows:
            row_database = row.get("database_name")
            schema = row.get("schema_name")
            table = row.get("table_name")
            if (
                row_database != database
                or not isinstance(schema, str)
                or not schema
                or not isinstance(table, str)
                or not table
            ):
                raise SkillError("metadata", "incomplete", "transient")
            object_name = render_object_name(database, schema, table)
            grouped[object_name].append(_column(row))
        return {name: tuple(columns) for name, columns in grouped.items()}


class RedshiftLiveMetadataSource(_RedshiftMetadataBase):
    """SHOW-only source for one interactive live metadata invocation."""

    def show_schemas(self, database: str) -> MetadataRead:
        rows, warned, overflow = self._execute(
            database=self.control_database,
            sql=(
                f"SHOW SCHEMAS FROM DATABASE {_qualified(database)} "
                f"LIMIT {_SHOW_ROW_LIMIT}"
            ),
            show_operation=True,
            row_limit=_SHOW_ROW_LIMIT,
            overflow_policy="truncate",
        )
        normalized: list[dict[str, Any]] = []
        for row in rows:
            if row.get("database_name") != database:
                raise SkillError("metadata", "incomplete", "transient")
            normalized.append({"name": row.get("schema_name")})
        return MetadataRead(
            rows=tuple(normalized),
            warnings=("redshift_warning",) if warned else (),
            complete=not warned,
            truncated=overflow or len(rows) >= _SHOW_ROW_LIMIT,
        )

    def show_relations(self, database: str, schema: str) -> MetadataRead:
        rows, warned, overflow = self._execute(
            database=self.control_database,
            sql=(
                f"SHOW TABLES FROM SCHEMA {_qualified(database, schema)} "
                f"LIMIT {_SHOW_ROW_LIMIT}"
            ),
            show_operation=True,
            row_limit=_SHOW_ROW_LIMIT,
            overflow_policy="truncate",
        )
        normalized: list[dict[str, Any]] = []
        for row in rows:
            if row.get("database_name") != database or row.get("schema_name") != schema:
                raise SkillError("metadata", "incomplete", "transient")
            table_type = row.get("table_type")
            remarks = row.get("remarks")
            if remarks is not None and (
                not isinstance(remarks, str)
                or len(remarks.encode("utf-8")) > _METADATA_TEXT_MAX_UTF8_BYTES
            ):
                raise SkillError("metadata", "incomplete", "transient")
            if table_type is None:
                normalized.append(
                    {
                        "name": row.get("table_name"),
                        "relationType": None,
                        "description": remarks,
                    }
                )
                continue
            normalized.append(
                {
                    "name": row.get("table_name"),
                    "relationType": _normalize_relation_type(table_type),
                    "description": remarks,
                }
            )
        return MetadataRead(
            rows=tuple(normalized),
            warnings=("redshift_warning",) if warned else (),
            complete=not warned,
            truncated=overflow or len(rows) >= _SHOW_ROW_LIMIT,
        )


class RedshiftDescribeSource(_RedshiftMetadataBase):
    """SHOW-first live describe with one exact system-view fallback."""

    def show_columns(self, object_name: str) -> MetadataRead:
        database, schema, table = parse_object_name(object_name)
        rows, warned, _overflow = self._execute(
            database=database,
            sql=f"SHOW COLUMNS FROM TABLE {_qualified(database, schema, table)}",
            show_operation=True,
            row_limit=_DESCRIBE_ROW_LIMIT,
            overflow_policy="raise",
        )
        return MetadataRead(
            rows=tuple(_column(row) for row in rows),
            warnings=("redshift_warning",) if warned else (),
            complete=not warned,
        )

    def svv_all_columns(self, object_name: str) -> MetadataRead:
        database, schema, table = parse_object_name(object_name)
        sql = """
SELECT column_name, ordinal_position, is_nullable, data_type
FROM SVV_ALL_COLUMNS
WHERE database_name = %(database)s
  AND schema_name = %(schema)s
  AND table_name = %(table)s
ORDER BY ordinal_position
""".strip()
        rows, warned, _overflow = self._execute(
            database=database,
            sql=sql,
            params={"database": database, "schema": schema, "table": table},
            show_operation=False,
            row_limit=_DESCRIBE_ROW_LIMIT,
            overflow_policy="raise",
        )
        return MetadataRead(
            rows=tuple(_column(row) for row in rows),
            warnings=("redshift_warning",) if warned else (),
            complete=not warned,
        )
