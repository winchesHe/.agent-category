from __future__ import annotations

import io
import json
from contextlib import nullcontext

import pytest

from scripts.rs.application import dispatch as application_dispatch
from scripts.rs.cli import main
from scripts.rs.connection import ConnectionConfig
from scripts.rs.connection import connect_config
from scripts.rs.errors import SkillError
from scripts.rs.models import CommandResult
from scripts.rs.query.execute import execute_query


SENTINEL = "SECRET_VALUE endpoint.internal.invalid user@example.invalid"


def test_unexpected_exception_text_never_reaches_public_streams() -> None:
    stdout = io.StringIO()
    stderr = io.StringIO()

    def explode(args, state):
        raise RuntimeError(SENTINEL)

    code = main(
        ["doctor"],
        dispatcher=explode,
        stdout=stdout,
        stderr=stderr,
        environ={},
        install_signal_handlers=False,
    )
    assert code == 8
    assert json.loads(stdout.getvalue())["error"] == {
        "category": "internal",
        "code": "unexpected",
        "retryClass": "never",
    }
    assert SENTINEL not in stdout.getvalue()
    assert SENTINEL not in stderr.getvalue()


def test_raw_connection_exception_is_replaced_by_stable_error(monkeypatch) -> None:
    config = ConnectionConfig(
        host="redacted",
        port=5439,
        username="redacted",
        password="redacted",
        database="control",
        sslmode="require",
        connect_timeout=1,
        statement_timeout_ms=1000,
    )

    class DriverError(Exception):
        pgcode = "08006"

    class Driver:
        def connect(self, **kwargs):
            raise DriverError(SENTINEL)

    monkeypatch.setattr("scripts.rs.connection._psycopg2", lambda: Driver())
    with pytest.raises(SkillError) as caught:
        with connect_config(config):
            pass
    assert caught.value.full_code == "connection.unavailable"
    assert SENTINEL not in repr(caught.value.to_payload())


def test_debug_diagnostics_use_an_allowlist_and_never_emit_values() -> None:
    stdout = io.StringIO()
    stderr = io.StringIO()

    def dispatch(args, state):
        state.diagnostics.update(
            {
                "command": "query",
                "connectionDatabase": "selected_db",
                "sqlSha256": "a" * 64,
                "parameterNames": ["email"],
                "parameterTypes": {"email": "string"},
                "elapsedMs": 1,
                "rawSql": f"SELECT {SENTINEL}",
                "parameterValues": {"email": SENTINEL},
            }
        )
        return CommandResult(data={"ok": True})

    code = main(
        ["query", "--sql", "SELECT 1", "--debug"],
        dispatcher=dispatch,
        stdout=stdout,
        stderr=stderr,
        environ={},
        install_signal_handlers=False,
    )
    assert code == 0
    diagnostic = json.loads(stderr.getvalue())
    assert diagnostic["sqlSha256"] == "a" * 64
    assert "rawSql" not in diagnostic
    assert "parameterValues" not in diagnostic
    assert SENTINEL not in stderr.getvalue()


def test_sqlstate_is_emitted_only_to_debug_diagnostics() -> None:
    stdout = io.StringIO()
    stderr = io.StringIO()

    def dispatch(args, state):
        raise SkillError(
            category="internal",
            code="unexpected",
            retry_class="never",
            diagnostics={"sqlState": "XX123", "rawException": SENTINEL},
        )

    code = main(
        ["query", "--sql", "SELECT 1", "--debug"],
        dispatcher=dispatch,
        stdout=stdout,
        stderr=stderr,
        environ={},
        install_signal_handlers=False,
    )

    assert code == 8
    assert json.loads(stdout.getvalue())["error"] == {
        "category": "internal",
        "code": "unexpected",
        "retryClass": "never",
    }
    diagnostic = json.loads(stderr.getvalue())
    assert diagnostic["sqlState"] == "XX123"
    assert "rawException" not in diagnostic
    assert SENTINEL not in stdout.getvalue()
    assert SENTINEL not in stderr.getvalue()


def test_live_query_sqlstate_survives_all_error_wrappers_to_debug_only() -> None:
    stdout = io.StringIO()
    stderr = io.StringIO()

    class DriverError(Exception):
        pgcode = "XX123"

    class Cursor:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            return None

        def execute(self, *_):
            raise DriverError(SENTINEL)

    class Connection:
        def cursor(self):
            return Cursor()

    def query_executor(**kwargs):
        return execute_query(
            **kwargs,
            connection_factory=lambda **_connection: nullcontext(Connection()),
        )

    class BoundConnectivity:
        default_database = "control_db"
        default_statement_timeout_ms = 30_000

        def query(self, **kwargs):
            return query_executor(**kwargs)

        def public_meta(self, _database):
            return {}

    class Connectivity:
        def bind(self, _connection_name):
            return BoundConnectivity()

    def dispatch(args, state):
        return application_dispatch(
            args,
            state,
            environ={},
            connectivity=Connectivity(),
        )

    code = main(
        ["query", "--sql", "SELECT 1", "--debug"],
        dispatcher=dispatch,
        stdout=stdout,
        stderr=stderr,
        environ={},
        install_signal_handlers=False,
    )

    assert code == 8
    assert json.loads(stdout.getvalue())["error"] == {
        "category": "internal",
        "code": "unexpected",
        "retryClass": "never",
    }
    assert json.loads(stderr.getvalue())["sqlState"] == "XX123"
    assert SENTINEL not in stdout.getvalue()
    assert SENTINEL not in stderr.getvalue()
