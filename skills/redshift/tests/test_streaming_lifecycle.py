from __future__ import annotations

import os
import signal
from dataclasses import dataclass

import pytest

from scripts.rs.connection import ConnectionConfig
from scripts.rs.connection import connect_streaming_config
from scripts.rs.errors import Interrupted, SkillError, output_error
from scripts.rs.models import InvocationState
from scripts.rs.output import publish_records
from scripts.rs.query.execute import open_query_stream


@dataclass(frozen=True)
class Description:
    name: str
    type_code: int


class SetupCursor:
    def __init__(self, events: list[str]) -> None:
        self.events = events

    def execute(self, *_: object) -> None:
        self.events.append("setup.execute")

    def close(self) -> None:
        self.events.append("setup.close")


class NamedCursor:
    description = (Description("id", 20),)

    def __init__(self, events: list[str], failure: BaseException | None) -> None:
        self.events = events
        self.failure = failure
        self.close_failure: BaseException | None = None
        self.returned_row = False
        self.fetch_sizes: list[int] = []

    def execute(self, *_: object) -> None:
        self.events.append("named.execute")

    def fetchmany(self, size: int) -> list[tuple[int]]:
        self.fetch_sizes.append(size)
        self.events.append("named.fetch")
        if self.failure is not None:
            raise self.failure
        if self.returned_row:
            return []
        self.returned_row = True
        return [(1,)]

    def close(self) -> None:
        self.events.append("named.close")
        if self.close_failure is not None:
            raise self.close_failure


class SqlstateError(Exception):
    def __init__(self, sqlstate: str) -> None:
        super().__init__("private driver detail")
        self.sqlstate = sqlstate


class LaterBatchFailingCursor(NamedCursor):
    def __init__(self, events: list[str], failure: BaseException) -> None:
        super().__init__(events, None)
        self.later_failure = failure
        self.fetch_count = 0

    def fetchmany(self, size: int) -> list[tuple[int]]:
        self.fetch_sizes.append(size)
        self.events.append("named.fetch")
        self.fetch_count += 1
        if self.fetch_count == 1:
            return [(index,) for index in range(size)]
        raise self.later_failure


class Connection:
    def __init__(self, events: list[str], failure: BaseException | None) -> None:
        self.events = events
        self.named_cursor = NamedCursor(events, failure)
        self.session: dict[str, bool] | None = None

    def set_session(self, **kwargs: bool) -> None:
        self.session = kwargs
        self.events.append("connection.set_session")

    def cursor(self, *, name: str | None = None):
        if name is None:
            return SetupCursor(self.events)
        assert name.startswith("moego_artifact_")
        return self.named_cursor

    def rollback(self) -> None:
        self.events.append("connection.rollback")

    def close(self) -> None:
        self.events.append("connection.close")


class LaterBatchFailingConnection(Connection):
    def __init__(self, events: list[str], failure: BaseException) -> None:
        super().__init__(events, None)
        self.named_cursor = LaterBatchFailingCursor(events, failure)


class Driver:
    def __init__(self, connection: Connection) -> None:
        self.connection = connection

    def connect(self, **_: object) -> Connection:
        return self.connection


@pytest.mark.parametrize("outcome", ["normal", "error", "signal"])
def test_streaming_lifecycle_closes_cursor_then_rolls_back_and_closes_connection(
    monkeypatch, outcome: str
) -> None:
    failure: BaseException | None
    if outcome == "error":
        failure = RuntimeError("private fetch detail")
    elif outcome == "signal":
        failure = Interrupted(signal.SIGTERM)
    else:
        failure = None
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
    events: list[str] = []
    connection = Connection(events, failure)
    monkeypatch.setattr("scripts.rs.connection._psycopg2", lambda: Driver(connection))
    factory = lambda **_kwargs: connect_streaming_config(config)

    if outcome == "normal":
        with open_query_stream(
            database="control",
            sql="SELECT 1 AS id",
            limit=1,
            statement_timeout_ms=2500,
            connection_factory=factory,
        ) as stream:
            assert tuple(stream) == ({"id": 1},)
    elif outcome == "signal":
        with pytest.raises(Interrupted):
            with open_query_stream(
                database="control",
                sql="SELECT 1 AS id",
                limit=1,
                statement_timeout_ms=2500,
                connection_factory=factory,
            ) as stream:
                tuple(stream)
    else:
        with pytest.raises(SkillError) as caught:
            with open_query_stream(
                database="control",
                sql="SELECT 1 AS id",
                limit=1,
                statement_timeout_ms=2500,
                connection_factory=factory,
            ) as stream:
                tuple(stream)
        assert caught.value.full_code == "internal.unexpected"

    assert connection.session == {"readonly": True, "autocommit": False}
    assert connection.named_cursor.fetch_sizes
    assert max(connection.named_cursor.fetch_sizes) <= 64
    assert events[-3:] == [
        "named.close",
        "connection.rollback",
        "connection.close",
    ]


def test_named_cursor_cleanup_interruption_never_replaces_writer_error(
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
    events: list[str] = []
    connection = Connection(events, None)
    connection.named_cursor.close_failure = Interrupted(signal.SIGTERM)
    monkeypatch.setattr("scripts.rs.connection._psycopg2", lambda: Driver(connection))
    factory = lambda **_kwargs: connect_streaming_config(config)
    original = output_error("write_failed")

    with pytest.raises(SkillError) as caught:
        with open_query_stream(
            database="control",
            sql="SELECT 1 AS id",
            limit=1,
            statement_timeout_ms=2500,
            connection_factory=factory,
        ):
            raise original

    assert caught.value.full_code == "output.write_failed"
    assert caught.value.__cause__ is original
    assert events[-3:] == [
        "named.close",
        "connection.rollback",
        "connection.close",
    ]


@pytest.mark.parametrize(
    ("sqlstate", "expected_code"),
    [("57014", "query.timeout"), ("08006", "connection.unavailable")],
)
def test_later_batch_driver_failure_keeps_typed_contract_and_removes_temp(
    tmp_path, monkeypatch, sqlstate: str, expected_code: str
) -> None:
    os.chmod(tmp_path, 0o700)
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
    events: list[str] = []
    connection = LaterBatchFailingConnection(events, SqlstateError(sqlstate))
    monkeypatch.setattr("scripts.rs.connection._psycopg2", lambda: Driver(connection))
    factory = lambda **_kwargs: connect_streaming_config(config)
    state = InvocationState()

    with pytest.raises(SkillError) as caught:
        with open_query_stream(
            database="control",
            sql="SELECT id FROM control.public.items",
            limit=100,
            statement_timeout_ms=2500,
            connection_factory=factory,
        ) as stream:
            publish_records(
                output_dir=tmp_path,
                final_name="results.ndjson",
                fmt="ndjson",
                columns=("id",),
                records=stream,
                state=state,
            )

    assert caught.value.full_code == expected_code
    assert caught.value.meta == {"connectionDatabase": "control"}
    assert not (tmp_path / "results.ndjson").exists()
    assert not list(tmp_path.glob(".redshift-tmp-*"))
    assert events[-3:] == ["named.close", "connection.rollback", "connection.close"]


@pytest.mark.parametrize(
    "failure", [Interrupted(signal.SIGTERM), output_error("size_limit_exceeded")]
)
def test_later_batch_fetch_preserves_control_and_typed_errors(
    monkeypatch, failure: SkillError
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
    events: list[str] = []
    connection = LaterBatchFailingConnection(events, failure)
    monkeypatch.setattr("scripts.rs.connection._psycopg2", lambda: Driver(connection))
    factory = lambda **_kwargs: connect_streaming_config(config)

    with pytest.raises(type(failure)) as caught:
        with open_query_stream(
            database="control",
            sql="SELECT id FROM control.public.items",
            limit=100,
            statement_timeout_ms=2500,
            connection_factory=factory,
        ) as stream:
            tuple(stream)

    if isinstance(failure, Interrupted):
        assert caught.value is failure
    else:
        assert caught.value.full_code == failure.full_code
        assert caught.value.__cause__ is failure
    assert events[-3:] == ["named.close", "connection.rollback", "connection.close"]
