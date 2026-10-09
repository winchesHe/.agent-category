from __future__ import annotations

from contextlib import nullcontext
from dataclasses import dataclass

import pytest

from scripts.rs.errors import SkillError
from scripts.rs.query.explain import execute_explain


MISSING = object()


@dataclass(frozen=True)
class Description:
    name: str
    type_code: int


class FakeCursor:
    description = (Description("QUERY PLAN", 25),)

    def __init__(self, rows: list[tuple[str]]) -> None:
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

    def fetchall(self) -> list[tuple[str]]:
        return list(self.rows)


class FakeConnection:
    def __init__(self, cursor: FakeCursor) -> None:
        self.cursor_value = cursor

    def cursor(self) -> FakeCursor:
        return self.cursor_value


class FakeFactory:
    def __init__(self, cursor: FakeCursor) -> None:
        self.cursor = cursor
        self.calls: list[dict[str, object]] = []

    def __call__(self, *, database: str, statement_timeout_ms: int):
        self.calls.append(
            {"database": database, "statement_timeout_ms": statement_timeout_ms}
        )
        return nullcontext(FakeConnection(self.cursor))


def test_explain_returns_hard_plan_and_deterministic_select_star_advisory() -> None:
    cursor = FakeCursor([("XN Seq Scan on items",), ("  Filter: true",)])
    factory = FakeFactory(cursor)
    params = {"active": True}

    result = execute_explain(
        database="warehouse",
        sql="SELECT * FROM items WHERE active = %(active)s",
        params=params,
        statement_timeout_ms=5000,
        connection_factory=factory,
    )

    assert factory.calls == [{"database": "warehouse", "statement_timeout_ms": 5000}]
    assert cursor.executed_sql == "EXPLAIN\nSELECT * FROM items WHERE active = %(active)s"
    assert cursor.executed_params == params
    assert result.plan == ("XN Seq Scan on items", "  Filter: true")
    assert result.advisories == (
        {
            "code": "query.select_star",
            "severity": "info",
            "message": "查询使用 SELECT *",
        },
    )
    assert result.connection_database == "warehouse"
    assert not hasattr(result, "referenced_databases")


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT count(*) FROM items",
        "SELECT 'SELECT * FROM secret' AS text",
        "SELECT '2' * 3 AS value",
        "-- SELECT * FROM secret\nSELECT id FROM items",
    ],
)
def test_explain_does_not_guess_select_star_from_ambiguous_text(sql: str) -> None:
    result = execute_explain(
        database="db",
        sql=sql,
        statement_timeout_ms=1000,
        connection_factory=FakeFactory(FakeCursor([("plan",)])),
    )
    assert result.advisories == ()


def test_explain_recognizes_a_qualified_select_star() -> None:
    result = execute_explain(
        database="db",
        sql="SELECT items.* FROM items",
        statement_timeout_ms=1000,
        connection_factory=FakeFactory(FakeCursor([("plan",)])),
    )
    assert result.advisories[0]["code"] == "query.select_star"


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT id, * FROM items",
        "SELECT id, items.* FROM items",
    ],
)
def test_explain_recognizes_select_star_after_an_earlier_projection(sql: str) -> None:
    result = execute_explain(
        database="db",
        sql=sql,
        statement_timeout_ms=1000,
        connection_factory=FakeFactory(FakeCursor([("plan",)])),
    )
    assert result.advisories[0]["code"] == "query.select_star"


def test_advisory_failure_never_discards_a_valid_redshift_plan(monkeypatch) -> None:
    def fail_advisory(_: str) -> tuple[dict[str, str], ...]:
        raise RuntimeError("injected advisory failure")

    monkeypatch.setattr("scripts.rs.query.explain._build_advisories", fail_advisory)
    result = execute_explain(
        database="db",
        sql="SELECT * FROM items",
        statement_timeout_ms=1000,
        connection_factory=FakeFactory(FakeCursor([("hard plan",)])),
    )
    assert result.plan == ("hard plan",)
    assert result.advisories == ()


def test_explain_uses_driver_percent_processing_without_named_params() -> None:
    cursor = FakeCursor([("plan",)])
    execute_explain(
        database="db",
        sql="SELECT '100%%' AS ratio",
        statement_timeout_ms=1000,
        connection_factory=FakeFactory(cursor),
    )
    assert cursor.executed_params == ()


def test_explain_escapes_ignored_placeholder_text_before_psycopg() -> None:
    cursor = FakeCursor([("plan",)])
    execute_explain(
        database="db",
        sql="SELECT '%(ignored)s' FROM items WHERE id = %(item_id)s",
        params={"item_id": 1},
        statement_timeout_ms=1000,
        connection_factory=FakeFactory(cursor),
    )

    assert cursor.executed_sql == (
        "EXPLAIN\nSELECT '%%(ignored)s' FROM items WHERE id = %(item_id)s"
    )
    assert cursor.executed_params == {"item_id": 1}


def test_explain_uses_the_same_readonly_guard() -> None:
    with pytest.raises(SkillError) as caught:
        execute_explain(
            database="db",
            sql="DELETE FROM items",
            statement_timeout_ms=1000,
            connection_factory=FakeFactory(FakeCursor([])),
        )
    assert caught.value.full_code == "safety.write_blocked"
    assert caught.value.meta == {"connectionDatabase": "db"}
    assert "referencedDatabases" not in caught.value.meta
