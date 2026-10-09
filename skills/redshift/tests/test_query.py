from __future__ import annotations

from contextlib import nullcontext
from dataclasses import dataclass
import signal

import pytest

from scripts.rs.errors import Interrupted, SkillError, output_error
from scripts.rs.query.execute import (
    ARTIFACT_MAX_LIMIT,
    JSON_MAX_LIMIT,
    execute_query,
    map_query_exception,
    open_query_stream,
)


MISSING = object()


@dataclass(frozen=True)
class Description:
    name: str
    type_code: int


class FakeCursor:
    def __init__(self, columns: tuple[tuple[str, int], ...], rows: list[tuple[object, ...]]) -> None:
        self.description = tuple(Description(*column) for column in columns)
        self.rows = rows
        self.executed_sql: str | None = None
        self.executed_params: object = MISSING

    def __enter__(self) -> "FakeCursor":
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def execute(self, sql: str, params: object = MISSING) -> None:
        self.executed_sql = sql
        self.executed_params = params

    def fetchall(self) -> list[tuple[object, ...]]:
        return list(self.rows)


class FailingCursor(FakeCursor):
    def execute(self, sql: str, params: object = MISSING) -> None:
        raise RuntimeError("private driver detail: SELECT secret_value")


class DriverDiagnostic:
    schema_name = "public"
    table_name = "appointments"
    column_name = "missing_column"
    statement_position = "42"
    message_primary = "private SQL text must not be exposed"


class UndefinedColumnError(Exception):
    pgcode = "42703"
    diag = DriverDiagnostic()

    def __str__(self) -> str:
        return "private driver detail: SELECT customer_email"


class UndefinedColumnCursor(FakeCursor):
    def execute(self, sql: str, params: object = MISSING) -> None:
        raise UndefinedColumnError()


class FakeConnection:
    def __init__(self, cursor: FakeCursor) -> None:
        self._cursor = cursor

    def cursor(self) -> FakeCursor:
        return self._cursor


class FakeConnectionFactory:
    def __init__(self, cursor: FakeCursor) -> None:
        self.cursor = cursor
        self.calls: list[dict[str, object]] = []

    def __call__(self, *, database: str, statement_timeout_ms: int):
        self.calls.append(
            {"database": database, "statement_timeout_ms": statement_timeout_ms}
        )
        return nullcontext(FakeConnection(self.cursor))


class StreamingCursor(FakeCursor):
    def __init__(self, columns: tuple[tuple[str, int], ...], rows: list[tuple[object, ...]]) -> None:
        super().__init__(columns, rows)
        self.fetch_sizes: list[int] = []
        self.closed = False

    def fetchall(self) -> list[tuple[object, ...]]:
        raise AssertionError("artifact streaming must never call fetchall")

    def fetchmany(self, size: int) -> list[tuple[object, ...]]:
        self.fetch_sizes.append(size)
        batch = self.rows[:size]
        del self.rows[:size]
        return batch

    def close(self) -> None:
        self.closed = True


class StreamingConnection:
    def __init__(self, cursor: StreamingCursor) -> None:
        self._cursor = cursor
        self.cursor_names: list[str] = []

    def cursor(self, *, name: str) -> StreamingCursor:
        self.cursor_names.append(name)
        return self._cursor


class StreamingConnectionFactory:
    def __init__(self, cursor: StreamingCursor) -> None:
        self.cursor = cursor
        self.connection = StreamingConnection(cursor)
        self.calls: list[dict[str, object]] = []

    def __call__(self, *, database: str, statement_timeout_ms: int):
        self.calls.append(
            {"database": database, "statement_timeout_ms": statement_timeout_ms}
        )
        return nullcontext(self.connection)


class FailingStreamingCursor(StreamingCursor):
    def __init__(self, failure: BaseException) -> None:
        super().__init__((("id", 20),), [])
        self.failure = failure
        self.close_failure = RuntimeError("cursor cleanup detail")

    def fetchmany(self, size: int) -> list[tuple[object, ...]]:
        self.fetch_sizes.append(size)
        raise self.failure

    def close(self) -> None:
        self.closed = True
        raise self.close_failure


class DeferredDescriptionCursor(StreamingCursor):
    def __init__(self) -> None:
        super().__init__((('id', 20),), [(1,)])
        self._resolved_description = self.description
        self.description = None

    def fetchmany(self, size: int) -> list[tuple[object, ...]]:
        self.description = self._resolved_description
        return super().fetchmany(size)


class CloseFailingStreamingCursor(StreamingCursor):
    def __init__(self) -> None:
        super().__init__((('id', 20),), [])

    def close(self) -> None:
        self.closed = True
        raise RuntimeError("cursor cleanup detail")


def test_query_wraps_unchanged_user_sql_with_limit_plus_one_and_returns_objects() -> None:
    rows = [(index, f"row-{index}") for index in range(JSON_MAX_LIMIT + 1)]
    cursor = FakeCursor((("id", 20), ("name", 21)), rows)
    factory = FakeConnectionFactory(cursor)
    user_sql = "SELECT id, name FROM db.schema.items ORDER BY id LIMIT 5"

    result = execute_query(
        database="selected_db",
        sql=user_sql,
        statement_timeout_ms=2500,
        connection_factory=factory,
    )

    assert factory.calls == [{"database": "selected_db", "statement_timeout_ms": 2500}]
    assert cursor.executed_sql == (
        "SELECT * FROM (\n"
        f"{user_sql}\n"
        f") AS _moego_result LIMIT {JSON_MAX_LIMIT + 1}"
    )
    assert cursor.executed_params is MISSING
    assert result.row_count == JSON_MAX_LIMIT
    assert result.truncated is True
    assert result.records[0] == {"id": 0, "name": "row-0"}
    assert result.records[-1] == {"id": JSON_MAX_LIMIT - 1, "name": f"row-{JSON_MAX_LIMIT - 1}"}
    assert [column.to_payload() for column in result.columns] == [
        {"name": "id", "dataType": "bigint"},
        {"name": "name", "dataType": "smallint"},
    ]
    assert result.connection_database == "selected_db"


def test_artifact_query_streams_in_batches_and_observes_one_extra_row() -> None:
    rows = [(index, f"row-{index}") for index in range(66)]
    cursor = StreamingCursor((("id", 20), ("name", 25)), rows)
    factory = StreamingConnectionFactory(cursor)

    with open_query_stream(
        database="selected_db",
        sql="SELECT id, name FROM selected_db.public.items ORDER BY id",
        limit=65,
        statement_timeout_ms=2500,
        connection_factory=factory,
    ) as stream:
        records = tuple(stream)

    assert factory.calls == [{"database": "selected_db", "statement_timeout_ms": 2500}]
    assert len(factory.connection.cursor_names) == 1
    assert factory.connection.cursor_names[0].startswith("moego_artifact_")
    assert cursor.executed_sql is not None
    assert cursor.executed_sql.endswith("LIMIT 66")
    assert cursor.fetch_sizes == [64, 64]
    assert cursor.closed is True
    assert len(records) == 65
    assert records[0] == {"id": 0, "name": "row-0"}
    assert records[-1] == {"id": 64, "name": "row-64"}
    assert stream.row_count == 65
    assert stream.truncated is True


def test_artifact_query_resolves_columns_after_the_first_server_fetch() -> None:
    cursor = DeferredDescriptionCursor()

    with open_query_stream(
        database="selected_db",
        sql="SELECT id FROM selected_db.public.items",
        limit=1,
        statement_timeout_ms=2500,
        connection_factory=StreamingConnectionFactory(cursor),
    ) as stream:
        assert tuple(stream) == ({"id": 1},)

    assert tuple(column.name for column in stream.columns) == ("id",)
    assert cursor.fetch_sizes == [64, 64]


def test_artifact_query_closes_named_cursor_after_fetch_error() -> None:
    cursor = FailingStreamingCursor(RuntimeError("private fetch detail"))

    with pytest.raises(SkillError) as caught:
        with open_query_stream(
            database="selected_db",
            sql="SELECT id FROM selected_db.public.items",
            limit=1,
            statement_timeout_ms=2500,
            connection_factory=StreamingConnectionFactory(cursor),
        ) as stream:
            tuple(stream)

    assert caught.value.full_code == "internal.unexpected"
    assert caught.value.__cause__.__cause__ is cursor.failure
    assert cursor.closed is True


def test_artifact_query_closes_named_cursor_after_signal() -> None:
    interrupted = Interrupted(signal.SIGTERM)
    cursor = FailingStreamingCursor(interrupted)

    with pytest.raises(Interrupted) as caught:
        with open_query_stream(
            database="selected_db",
            sql="SELECT id FROM selected_db.public.items",
            limit=1,
            statement_timeout_ms=2500,
            connection_factory=StreamingConnectionFactory(cursor),
        ) as stream:
            tuple(stream)

    assert caught.value is interrupted
    assert cursor.closed is True


def test_artifact_query_cursor_cleanup_never_replaces_writer_error() -> None:
    cursor = CloseFailingStreamingCursor()

    with pytest.raises(SkillError) as caught:
        with open_query_stream(
            database="selected_db",
            sql="SELECT id FROM selected_db.public.items",
            limit=1,
            statement_timeout_ms=2500,
            connection_factory=StreamingConnectionFactory(cursor),
        ):
            raise output_error("size_limit_exceeded")

    assert caught.value.full_code == "output.size_limit_exceeded"
    assert cursor.closed is True


def test_query_rejects_bare_cr_comment_escape_before_opening_connection() -> None:
    cursor = FakeCursor((("value", 20),), [(1,)])
    factory = FakeConnectionFactory(cursor)

    with pytest.raises(SkillError) as caught:
        execute_query(
            database="db",
            sql="SELECT 1 --\r) AS x; SELECT 2 AS bypass; --",
            statement_timeout_ms=1000,
            connection_factory=factory,
        )

    assert caught.value.full_code == "safety.multiple_statements"
    assert factory.calls == []


def test_query_marks_exact_limit_without_an_extra_row_as_not_truncated() -> None:
    cursor = FakeCursor((('id', 20),), [(index,) for index in range(JSON_MAX_LIMIT)])
    result = execute_query(
        database="db",
        sql="SELECT id FROM items",
        statement_timeout_ms=1000,
        connection_factory=FakeConnectionFactory(cursor),
    )
    assert result.row_count == JSON_MAX_LIMIT
    assert result.truncated is False


def test_query_preserves_an_unknown_driver_oid_without_guessing() -> None:
    cursor = FakeCursor((("value", 987654),), [(1,)])

    result = execute_query(
        database="db",
        sql="SELECT value FROM items",
        statement_timeout_ms=1000,
        connection_factory=FakeConnectionFactory(cursor),
    )

    assert result.columns[0].to_payload() == {
        "name": "value",
        "dataType": "oid:987654",
    }


def test_query_passes_validated_named_params_to_driver() -> None:
    cursor = FakeCursor((('id', 20),), [(1,)])
    params = {"item_id": 1}
    result = execute_query(
        database="db",
        sql="SELECT id FROM items WHERE id = %(item_id)s",
        params=params,
        statement_timeout_ms=1000,
        connection_factory=FakeConnectionFactory(cursor),
    )
    assert cursor.executed_params == params
    assert result.records == ({"id": 1},)


def test_query_escapes_ignored_placeholder_text_before_psycopg() -> None:
    cursor = FakeCursor((("id", 20),), [(1,)])
    execute_query(
        database="db",
        sql="SELECT '%(ignored)s', id FROM items WHERE id = %(item_id)s",
        params={"item_id": 1},
        statement_timeout_ms=1000,
        connection_factory=FakeConnectionFactory(cursor),
    )

    assert "SELECT '%%(ignored)s', id" in cursor.executed_sql
    assert cursor.executed_params == {"item_id": 1}


def test_stream_query_escapes_ignored_placeholder_text_before_psycopg() -> None:
    cursor = StreamingCursor((("id", 20),), [(1,)])
    with open_query_stream(
        database="db",
        sql="SELECT '%(ignored)s', id FROM items WHERE id = %(item_id)s",
        params={"item_id": 1},
        limit=1,
        statement_timeout_ms=1000,
        connection_factory=StreamingConnectionFactory(cursor),
    ) as stream:
        assert tuple(stream) == ({"id": 1},)

    assert "SELECT '%%(ignored)s', id" in cursor.executed_sql
    assert cursor.executed_params == {"item_id": 1}


def test_query_uses_driver_percent_processing_for_literal_percent_without_named_params() -> None:
    cursor = FakeCursor((('ratio', 25),), [("100%",)])
    execute_query(
        database="db",
        sql="SELECT '100%%' AS ratio",
        statement_timeout_ms=1000,
        connection_factory=FakeConnectionFactory(cursor),
    )
    assert cursor.executed_sql is not None
    assert "SELECT '100%%' AS ratio" in cursor.executed_sql
    assert cursor.executed_params == ()


def test_query_database_is_explicit_and_is_not_inferred_from_sql() -> None:
    cursor = FakeCursor((('value', 20),), [(1,)])
    factory = FakeConnectionFactory(cursor)
    result = execute_query(
        database="control_db",
        sql="SELECT value FROM another_db.public.items",
        statement_timeout_ms=1000,
        connection_factory=factory,
    )
    assert factory.calls[0]["database"] == "control_db"
    assert not hasattr(result, "referenced_databases")


@pytest.mark.parametrize("database", ["", None])
def test_query_requires_an_explicit_connection_database(database: str | None) -> None:
    with pytest.raises(SkillError) as caught:
        execute_query(
            database=database,  # type: ignore[arg-type]
            sql="SELECT 1",
            statement_timeout_ms=1000,
            connection_factory=FakeConnectionFactory(FakeCursor((('one', 20),), [(1,)])),
        )
    assert caught.value.full_code == "config.missing"
    assert caught.value.details == {"key": "connection.database"}


def test_query_rejects_duplicate_output_columns_before_building_records() -> None:
    cursor = FakeCursor((('id', 20), ('id', 20)), [(1, 2)])
    with pytest.raises(SkillError) as caught:
        execute_query(
            database="db",
            sql="SELECT left_id AS id, right_id AS id FROM items",
            statement_timeout_ms=1000,
            connection_factory=FakeConnectionFactory(cursor),
        )
    assert caught.value.full_code == "query.duplicate_output_column"
    assert caught.value.details == {"columns": ["id"]}
    assert caught.value.meta == {"connectionDatabase": "db"}


def test_preflight_error_after_database_resolution_carries_connection_meta() -> None:
    with pytest.raises(SkillError) as caught:
        execute_query(
            database="control_db",
            sql="SELECT %(required)s",
            params={},
            statement_timeout_ms=1000,
            connection_factory=FakeConnectionFactory(FakeCursor((('value', 20),), [])),
        )
    assert caught.value.full_code == "query.invalid_parameters"
    assert caught.value.meta == {"connectionDatabase": "control_db"}
    assert "referencedDatabases" not in caught.value.meta


def test_unknown_driver_error_is_internal_and_does_not_expose_raw_text() -> None:
    cursor = FailingCursor((("value", 20),), [])
    with pytest.raises(SkillError) as caught:
        execute_query(
            database="control_db",
            sql="SELECT value FROM items",
            statement_timeout_ms=1000,
            connection_factory=FakeConnectionFactory(cursor),
        )
    assert caught.value.full_code == "internal.unexpected"
    assert caught.value.retry_class == "never"
    assert caught.value.meta == {"connectionDatabase": "control_db"}
    assert "private driver detail" not in str(caught.value.to_payload())
    assert "secret_value" not in str(caught.value.to_payload())


def test_unclassified_sqlstate_is_private_diagnostic_not_public_error_data() -> None:
    error = RuntimeError("private driver text")
    error.pgcode = "XX123"  # type: ignore[attr-defined]

    mapped = map_query_exception(error)

    assert mapped.full_code == "internal.unexpected"
    assert mapped.diagnostics == {"sqlState": "XX123"}
    assert mapped.to_payload() == {
        "category": "internal",
        "code": "unexpected",
        "retryClass": "never",
    }


def test_undefined_column_returns_only_allowlisted_diagnostics_and_action() -> None:
    cursor = UndefinedColumnCursor((("value", 20),), [])

    with pytest.raises(SkillError) as caught:
        execute_query(
            database="control_db",
            sql="SELECT missing_column FROM appointments",
            statement_timeout_ms=1000,
            connection_factory=FakeConnectionFactory(cursor),
        )

    assert caught.value.to_payload() == {
        "category": "query",
        "code": "undefined_column",
        "retryClass": "after_change",
        "details": {
            "schema": "public",
            "table": "appointments",
            "column": "missing_column",
            "position": 42,
        },
        "suggestion": "describe_object",
    }
    assert caught.value.meta == {"connectionDatabase": "control_db"}
    assert caught.value.diagnostics == {"sqlState": "42703"}
    assert "private" not in repr(caught.value.to_payload())
    assert "customer_email" not in repr(caught.value.to_payload())


@pytest.mark.parametrize(
    ("sqlstate", "code", "suggestion"),
    [
        ("42P01", "undefined_table", "search_object"),
        ("42703", "undefined_column", "describe_object"),
        ("42601", "syntax_error", "inspect_sql_position"),
        ("42846", "cannot_coerce", "inspect_types"),
        ("42883", "undefined_function", "inspect_function_signature"),
    ],
)
def test_correctable_query_errors_return_stable_action_codes(
    sqlstate: str,
    code: str,
    suggestion: str,
) -> None:
    error = RuntimeError("private driver text")
    error.pgcode = sqlstate  # type: ignore[attr-defined]

    assert map_query_exception(error).to_payload() == {
        "category": "query",
        "code": code,
        "retryClass": "after_change",
        "suggestion": suggestion,
    }


def test_malformed_driver_diagnostics_are_omitted_instead_of_normalized() -> None:
    class UnsafeDiagnostic:
        schema_name = "private\nschema"
        table_name = "x" * 257
        column_name = b"private_column"
        statement_position = True
        message_primary = "SELECT private_value"

    error = RuntimeError("private driver text")
    error.pgcode = "42703"  # type: ignore[attr-defined]
    error.diag = UnsafeDiagnostic()  # type: ignore[attr-defined]

    assert map_query_exception(error).to_payload() == {
        "category": "query",
        "code": "undefined_column",
        "retryClass": "after_change",
        "suggestion": "describe_object",
    }


def test_xx000_message_text_never_drives_public_error_classification() -> None:
    class ReadonlyCatalogConflict(Exception):
        pgcode = "XX000"

        def __str__(self) -> str:
            return "transaction is read-only"

    class ReadonlyCatalogCursor(FakeCursor):
        def execute(self, sql: str, params: object = MISSING) -> None:
            raise ReadonlyCatalogConflict()

    cursor = ReadonlyCatalogCursor((("value", 20),), [])
    with pytest.raises(SkillError) as caught:
        execute_query(
            database="control_db",
            sql="SELECT value FROM other.public.items",
            statement_timeout_ms=1000,
            connection_factory=FakeConnectionFactory(cursor),
        )

    assert caught.value.full_code == "internal.unexpected"
    assert caught.value.retry_class == "never"
    assert caught.value.meta == {"connectionDatabase": "control_db"}


def test_structured_readonly_sqlstate_is_a_stable_capability_error() -> None:
    error = RuntimeError("private provider text")
    error.pgcode = "25006"  # type: ignore[attr-defined]

    mapped = map_query_exception(error)

    assert mapped.full_code == "capability.cross_database_read_unavailable"
    assert mapped.retry_class == "never"


@pytest.mark.parametrize("limit", [0, -1, JSON_MAX_LIMIT + 1])
def test_json_limit_must_be_positive_and_at_most_200(limit: int) -> None:
    with pytest.raises(SkillError) as caught:
        execute_query(
            database="db",
            sql="SELECT 1",
            limit=limit,
            statement_timeout_ms=1000,
            connection_factory=FakeConnectionFactory(FakeCursor((('one', 20),), [(1,)])),
        )
    assert caught.value.full_code == "query.limit_out_of_range"


def test_artifact_stream_allows_100000_rows_but_not_more() -> None:
    cursor = StreamingCursor((("id", 20),), [])
    with open_query_stream(
        database="db",
        sql="SELECT id FROM items",
        limit=ARTIFACT_MAX_LIMIT,
        statement_timeout_ms=1000,
        connection_factory=StreamingConnectionFactory(cursor),
    ):
        pass
    assert cursor.executed_sql is not None
    assert cursor.executed_sql.endswith(f"LIMIT {ARTIFACT_MAX_LIMIT + 1}")

    with pytest.raises(SkillError) as caught:
        with open_query_stream(
            database="db",
            sql="SELECT id FROM items",
            limit=ARTIFACT_MAX_LIMIT + 1,
            statement_timeout_ms=1000,
            connection_factory=StreamingConnectionFactory(cursor),
        ):
            pass
    assert caught.value.full_code == "query.limit_out_of_range"
