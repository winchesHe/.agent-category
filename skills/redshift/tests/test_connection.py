from __future__ import annotations

import signal

import pytest

from scripts.rs.connection import ConnectionConfig, connect_config, connect_streaming_config
from scripts.rs.errors import Interrupted, SkillError


class SetupCursor:
    def __init__(self) -> None:
        self.executed: tuple[str, tuple[int]] | None = None
        self.closed = False

    def __enter__(self) -> "SetupCursor":
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def execute(self, sql: str, params: tuple[int]) -> None:
        self.executed = (sql, params)

    def close(self) -> None:
        self.closed = True


class FakeConnection:
    def __init__(self) -> None:
        self.setup_cursor = SetupCursor()
        self.session: dict[str, bool] | None = None
        self.rolled_back = False
        self.closed = False
        self.rollback_error: Exception | None = None
        self.close_error: Exception | None = None
        self.cancelled = False

    def set_session(self, **kwargs: bool) -> None:
        self.session = kwargs

    def cursor(self) -> SetupCursor:
        return self.setup_cursor

    def rollback(self) -> None:
        self.rolled_back = True
        if self.rollback_error is not None:
            raise self.rollback_error

    def close(self) -> None:
        self.closed = True
        if self.close_error is not None:
            raise self.close_error

    def cancel(self) -> None:
        self.cancelled = True


class Driver:
    def __init__(self, connection: FakeConnection) -> None:
        self.connection = connection

    def connect(self, **_: object) -> FakeConnection:
        return self.connection


def test_streaming_connection_is_readonly_transaction_and_rolls_back_before_close(
    monkeypatch,
) -> None:
    config = ConnectionConfig(
        host="redacted",
        port=5439,
        username="redacted",
        password="redacted",
        database="control",
        sslmode="require",
        connect_timeout=1,
        statement_timeout_ms=2500,
    )
    connection = FakeConnection()
    monkeypatch.setattr("scripts.rs.connection._psycopg2", lambda: Driver(connection))

    with connect_streaming_config(config) as opened:
        assert opened is connection

    assert connection.session == {"readonly": True, "autocommit": False}
    assert connection.setup_cursor.executed == (
        "SET statement_timeout TO %s",
        (2500,),
    )
    assert connection.setup_cursor.closed is True
    assert connection.rolled_back is True
    assert connection.closed is True


def test_streaming_connection_cleanup_never_replaces_the_body_error(monkeypatch) -> None:
    config = ConnectionConfig(
        host="redacted",
        port=5439,
        username="redacted",
        password="redacted",
        database="control",
        sslmode="require",
        connect_timeout=1,
        statement_timeout_ms=2500,
    )
    connection = FakeConnection()
    connection.rollback_error = RuntimeError("rollback cleanup detail")
    connection.close_error = RuntimeError("close cleanup detail")
    monkeypatch.setattr("scripts.rs.connection._psycopg2", lambda: Driver(connection))
    original = RuntimeError("writer failure")

    with pytest.raises(RuntimeError) as caught:
        with connect_streaming_config(config):
            raise original

    assert caught.value is original
    assert connection.rolled_back is True
    assert connection.closed is True


def test_streaming_connection_cleanup_interruption_never_replaces_body_error(
    monkeypatch,
) -> None:
    config = ConnectionConfig(
        host="redacted",
        port=5439,
        username="redacted",
        password="redacted",
        database="control",
        sslmode="require",
        connect_timeout=1,
        statement_timeout_ms=2500,
    )
    connection = FakeConnection()
    connection.rollback_error = Interrupted(signal.SIGTERM)
    connection.close_error = Interrupted(signal.SIGINT)
    monkeypatch.setattr("scripts.rs.connection._psycopg2", lambda: Driver(connection))
    original = RuntimeError("writer failure")

    with pytest.raises(RuntimeError) as caught:
        with connect_streaming_config(config):
            raise original

    assert caught.value is original
    assert connection.rolled_back is True
    assert connection.closed is True


def test_streaming_connection_cleanup_failure_does_not_change_known_success(
    monkeypatch,
) -> None:
    config = ConnectionConfig(
        host="redacted",
        port=5439,
        username="redacted",
        password="redacted",
        database="control",
        sslmode="require",
        connect_timeout=1,
        statement_timeout_ms=2500,
    )
    connection = FakeConnection()
    connection.rollback_error = RuntimeError("rollback cleanup detail")
    connection.close_error = RuntimeError("close cleanup detail")
    monkeypatch.setattr("scripts.rs.connection._psycopg2", lambda: Driver(connection))

    with connect_streaming_config(config) as opened:
        assert opened is connection

    assert connection.rolled_back is True
    assert connection.closed is True


def test_streaming_connection_rolls_back_and_closes_after_signal(monkeypatch) -> None:
    config = ConnectionConfig(
        host="redacted",
        port=5439,
        username="redacted",
        password="redacted",
        database="control",
        sslmode="require",
        connect_timeout=1,
        statement_timeout_ms=2500,
    )
    connection = FakeConnection()
    monkeypatch.setattr("scripts.rs.connection._psycopg2", lambda: Driver(connection))
    interrupted = Interrupted(signal.SIGTERM)

    with pytest.raises(Interrupted) as caught:
        with connect_streaming_config(config):
            raise interrupted

    assert caught.value is interrupted
    assert connection.rolled_back is True
    assert connection.closed is True


def test_regular_connection_propagates_cleanup_interruption_without_primary_error(
    monkeypatch,
) -> None:
    config = ConnectionConfig(
        host="redacted",
        port=5439,
        username="redacted",
        password="redacted",
        database="control",
        sslmode="require",
        connect_timeout=1,
        statement_timeout_ms=2500,
    )
    connection = FakeConnection()
    connection.close_error = Interrupted(signal.SIGTERM)
    monkeypatch.setattr("scripts.rs.connection._psycopg2", lambda: Driver(connection))

    with pytest.raises(Interrupted) as caught:
        with connect_config(config) as opened:
            assert opened is connection

    assert caught.value.signum == signal.SIGTERM
    assert connection.closed is True


def test_regular_connection_cleanup_interruption_never_replaces_primary_error(
    monkeypatch,
) -> None:
    config = ConnectionConfig(
        host="redacted",
        port=5439,
        username="redacted",
        password="redacted",
        database="control",
        sslmode="require",
        connect_timeout=1,
        statement_timeout_ms=2500,
    )
    connection = FakeConnection()
    connection.close_error = Interrupted(signal.SIGTERM)
    monkeypatch.setattr("scripts.rs.connection._psycopg2", lambda: Driver(connection))
    original = SkillError("query", "timeout", "transient")

    with pytest.raises(SkillError) as caught:
        with connect_config(config):
            raise original

    assert caught.value is original
    assert connection.closed is True


def test_regular_connection_attempts_cancel_on_user_interruption(monkeypatch) -> None:
    config = ConnectionConfig(
        host="redacted",
        port=5439,
        username="redacted",
        password="redacted",
        database="control",
        sslmode="require",
        connect_timeout=1,
        statement_timeout_ms=2500,
    )
    connection = FakeConnection()
    monkeypatch.setattr("scripts.rs.connection._psycopg2", lambda: Driver(connection))

    with pytest.raises(Interrupted):
        with connect_config(config):
            raise Interrupted(signal.SIGINT)

    assert connection.cancelled is True
    assert connection.closed is True
