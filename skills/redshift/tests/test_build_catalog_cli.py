from __future__ import annotations

import io
import json
from datetime import datetime, timezone

from scripts.build_catalog import main
from scripts.rs.errors import SkillError


ENV: dict[str, str] = {}


class CompleteSource:
    def show_databases(self):
        return ({"name": "db", "databaseType": "local"},)

    def show_schemas(self, database: str):
        return ("public",)

    def show_relations(self, database: str):
        return {"public": ({"name": "items", "relationType": "table"},)}

    def show_columns(self, database: str):
        return {
            "db.public.items": (
                {"name": "id", "dataType": "bigint", "nullable": False},
            )
        }


class BoundConnectivity:
    def __init__(self, source_factory=lambda _database, _timeout: CompleteSource()):
        self.default_database = "control"
        self.default_statement_timeout_ms = 5000
        self._source_factory = source_factory

    def catalog_source(self, database, timeout):
        return self._source_factory(database, timeout)


class Connectivity:
    def __init__(self, source_factory=lambda _database, _timeout: CompleteSource()):
        self.bound = BoundConnectivity(source_factory)

    def bind_catalog(self):
        return self.bound


def invoke(argv, *, source_factory=lambda _database, _timeout: CompleteSource()):
    stdout = io.StringIO()
    code = main(
        argv,
        environ=ENV,
        stdout=stdout,
        connectivity=Connectivity(source_factory),
        clock=lambda: datetime(2026, 7, 15, tzinfo=timezone.utc),
    )
    return code, json.loads(stdout.getvalue())


def test_builder_cli_publishes_and_prints_only_a_typed_summary(tmp_path) -> None:
    destination = tmp_path / "private-name.jsonl"

    code, payload = invoke(["--output", str(destination)])

    assert code == 0
    assert payload["ok"] is True
    assert payload["data"] == {
        "generatedAt": "2026-07-15T00:00:00Z",
        "databaseCount": 1,
        "relationCount": 1,
        "columnCount": 1,
        "coverage": {
            "status": "complete",
            "visibleDatabaseCount": 1,
            "completeDatabaseCount": 1,
            "failedDatabases": [],
        },
    }
    assert str(destination) not in repr(payload)
    assert destination.is_file()


def test_builder_cli_never_exposes_raw_metadata_exception(tmp_path) -> None:
    class FailedSource(CompleteSource):
        def show_databases(self):
            raise SkillError(
                "metadata",
                "timeout",
                "transient",
                message="private endpoint and driver detail",
            )

    code, payload = invoke(
        ["--output", str(tmp_path / "catalog.jsonl")],
        source_factory=lambda _database, _timeout: FailedSource(),
    )

    assert code == 6
    assert payload == {
        "schemaVersion": 1,
        "ok": False,
        "error": {
            "category": "metadata",
            "code": "timeout",
            "retryClass": "transient",
        },
    }
    assert "private endpoint" not in repr(payload)


def test_builder_cli_parser_and_window_errors_are_json(tmp_path) -> None:
    code, payload = invoke([])
    assert code == 2
    assert payload["error"]["code"] == "missing_argument"

    code, payload = invoke(
        ["--output", str(tmp_path / "catalog.jsonl"), "--max-age-days", "0"]
    )
    assert code == 2
    assert payload["error"]["code"] == "invalid_value"

    code, payload = invoke(
        ["--output", str(tmp_path / "catalog-timeout.jsonl"), "--timeout-ms", "-1"]
    )
    assert code == 2
    assert payload["error"] == {
        "category": "usage",
        "code": "invalid_value",
        "retryClass": "after_change",
    }


def test_builder_cli_keyboard_interrupt_is_a_typed_control_error(tmp_path) -> None:
    def interrupted_source(_database, _timeout):
        raise KeyboardInterrupt

    code, payload = invoke(
        ["--output", str(tmp_path / "catalog.jsonl")],
        source_factory=interrupted_source,
    )

    assert code == 130
    assert payload == {
        "schemaVersion": 1,
        "ok": False,
        "error": {
            "category": "control",
            "code": "interrupted",
            "retryClass": "never",
        },
    }


def test_builder_cli_runtime_error_is_typed_without_raw_detail(tmp_path) -> None:
    def failed_source(_database, _timeout):
        raise RuntimeError("private endpoint and driver detail")

    code, payload = invoke(
        ["--output", str(tmp_path / "catalog.jsonl")],
        source_factory=failed_source,
    )

    assert code == 8
    assert payload == {
        "schemaVersion": 1,
        "ok": False,
        "error": {
            "category": "internal",
            "code": "unexpected",
            "retryClass": "never",
        },
    }
    assert "private endpoint" not in repr(payload)


def test_builder_cli_broken_stdout_returns_internal_exit_without_raw_detail(
    tmp_path,
) -> None:
    class BrokenStdout:
        def write(self, _value):
            raise RuntimeError("private output detail")

        def flush(self):
            raise AssertionError("flush must not run after failed write")

    code = main(
        ["--output", str(tmp_path / "catalog.jsonl")],
        environ=ENV,
        stdout=BrokenStdout(),
        connectivity=Connectivity(lambda _database, _timeout: CompleteSource()),
        clock=lambda: datetime(2026, 7, 15, tzinfo=timezone.utc),
    )

    assert code == 8
