from __future__ import annotations

import pytest

from scripts.rs.errors import SkillError
from scripts.rs.query.guard import validate_read_only_sql


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT 1",
        "WITH x AS (SELECT 1) SELECT * FROM x",
        "WITH RECURSIVE x AS (SELECT 1 UNION ALL SELECT 2) SELECT * FROM x",
        "-- DELETE FROM private_table\nSELECT 'DROP TABLE x' AS text",
        'SELECT "update" FROM "delete"',
        "SELECT $$ INSERT INTO hidden VALUES (1) $$ AS text",
        "SELECT $tag$ UPDATE hidden SET value = 1 $tag$ AS text",
        r"SELECT E'it\'s safe' AS text",
    ],
)
def test_guard_accepts_single_select_statements(sql: str) -> None:
    assert validate_read_only_sql(sql) == sql


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT count(*), avg(value), coalesce(max(value), 0) FROM metrics",
        "SELECT pg_catalog.date_part('year', current_date)",
        'SELECT "date_part"(\'year\', current_date)',
        "SELECT pg_terminate_backend FROM audit_log",
    ],
)
def test_guard_preserves_read_only_analytics_functions_and_columns(sql: str) -> None:
    assert validate_read_only_sql(sql) == sql


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT 'a\rb' AS text",
        'SELECT "a\rb" FROM "table\rname"',
        "SELECT $$a\r\nb$$ AS text",
        "SELECT $tag$a\rb$tag$ AS text",
    ],
)
def test_guard_preserves_carriage_returns_inside_quoted_content(sql: str) -> None:
    assert validate_read_only_sql(sql) == sql


def test_guard_removes_only_one_allowed_trailing_semicolon() -> None:
    sql = "SELECT 1; -- trailing comment"
    assert validate_read_only_sql(sql) == "SELECT 1 -- trailing comment"


@pytest.mark.parametrize(
    "sql",
    [
        "INSERT INTO t VALUES (1)",
        "UPDATE t SET a = 1",
        "DELETE FROM t",
        "DROP TABLE t",
        "CREATE TABLE t (id int)",
        "COPY t FROM 's3://bucket/key'",
        "UNLOAD ('SELECT 1') TO 's3://bucket/key'",
        "CALL procedure_name()",
        "VACUUM t",
        "ANALYZE t",
        "MERGE INTO t USING s ON t.id = s.id WHEN MATCHED THEN DELETE",
        "REFRESH MATERIALIZED VIEW v",
        "SELECT * INTO new_table FROM old_table",
        "WITH changed AS (DELETE FROM t RETURNING *) SELECT * FROM changed",
        "EXPLAIN ANALYZE DELETE FROM t",
        "SET statement_timeout TO 0",
        "BEGIN",
    ],
)
def test_guard_has_no_write_or_session_control_bypass(sql: str) -> None:
    with pytest.raises(SkillError) as caught:
        validate_read_only_sql(sql)
    assert caught.value.full_code == "safety.write_blocked"


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT pg_terminate_backend(123)",
        "SELECT PG_CANCEL_BACKEND (123)",
        "SELECT Pg_TeRmInAtE_BaCkEnD\n\t(123)",
        "SELECT pg_catalog.pg_cancel_backend(123)",
        "SELECT pg_catalog . pg_terminate_backend /* target */ (123)",
        'SELECT "pg_terminate_backend"(123)',
        'SELECT "pg_catalog" . "pg_cancel_backend" (123)',
    ],
)
def test_guard_rejects_session_control_function_calls(sql: str) -> None:
    with pytest.raises(SkillError) as caught:
        validate_read_only_sql(sql)
    assert caught.value.full_code == "safety.write_blocked"


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT 1; SELECT 2",
        "SELECT 1;;",
        "SELECT 1; /* comment */ SELECT 2",
    ],
)
def test_guard_rejects_multiple_statements_even_when_all_are_read_only(sql: str) -> None:
    with pytest.raises(SkillError) as caught:
        validate_read_only_sql(sql)
    assert caught.value.full_code == "safety.multiple_statements"


def test_bare_carriage_return_ends_line_comment_and_cannot_hide_statements() -> None:
    sql = "SELECT 1 --\r) AS x; SELECT * FROM huge_table; --"

    with pytest.raises(SkillError) as caught:
        validate_read_only_sql(sql)

    assert caught.value.full_code == "safety.multiple_statements"


@pytest.mark.parametrize("sql", ["", "-- only a comment", "SHOW TABLES", "EXPLAIN SELECT 1"])
def test_guard_rejects_unsupported_statement_families(sql: str) -> None:
    with pytest.raises(SkillError) as caught:
        validate_read_only_sql(sql)
    assert caught.value.full_code == "safety.write_blocked"


@pytest.mark.parametrize(
    "sql",
    [
        "WITH x AS (SELECT 1) TABLE x",
        "WITH x AS (SELECT 1) VALUES (2)",
    ],
)
def test_with_requires_a_top_level_select_as_the_main_statement(sql: str) -> None:
    with pytest.raises(SkillError) as caught:
        validate_read_only_sql(sql)
    assert caught.value.full_code == "safety.write_blocked"


@pytest.mark.parametrize("sql", ["SELECT 'unterminated", "SELECT /* unterminated", "SELECT $tag$unterminated"])
def test_guard_reports_malformed_lexical_input_as_query_syntax_error(sql: str) -> None:
    with pytest.raises(SkillError) as caught:
        validate_read_only_sql(sql)
    assert caught.value.full_code == "query.syntax_error"


def test_plain_string_backslash_cannot_hide_a_following_statement() -> None:
    with pytest.raises(SkillError) as caught:
        validate_read_only_sql(r"SELECT 'safe\'; DELETE FROM t'")
    assert caught.value.full_code == "query.syntax_error"
