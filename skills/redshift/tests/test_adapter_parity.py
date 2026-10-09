from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime
from decimal import Decimal

import pytest

from scripts.rs.connectivity.data_api import DataApiAdapter
from scripts.rs.connectivity.model import (
    AuthenticationConfig,
    AwsCredentialsConfig,
    ConnectionProfile,
    TargetConfig,
    TlsConfig,
    TlsTrustConfig,
)
from scripts.rs.connectivity.wire import WireAdapter
from scripts.rs.errors import SkillError


class _Description:
    def __init__(self, name: str, type_code: int) -> None:
        self.name = name
        self.type_code = type_code


class _WireCursor:
    def __init__(self, columns, rows) -> None:
        self.description = tuple(_Description(*item) for item in columns)
        self._rows = list(rows)

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def execute(self, _sql, _params=None):
        return None

    def fetchall(self):
        return list(self._rows)

    def fetchmany(self, size):
        batch, self._rows = self._rows[:size], self._rows[size:]
        return batch


class _WireConnection:
    def __init__(self, columns, rows) -> None:
        self._columns = columns
        self._rows = rows

    def cursor(self):
        return _WireCursor(self._columns, self._rows)


class _LiveWireCursor:
    def __init__(self, connection) -> None:
        self.connection = connection
        self.description = ()
        self._rows = []

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def execute(self, sql, _params=None):
        self.connection.sql.append(sql)
        if sql.startswith("SHOW SCHEMAS"):
            self.description = (("database_name", None), ("schema_name", None))
            self._rows = [("analytics", "public"), ("analytics", "analytics")]
        else:
            self.description = (
                ("database_name", None),
                ("schema_name", None),
                ("table_name", None),
                ("table_type", None),
                ("remarks", None),
            )
            self._rows = [
                ("analytics", "public", "orders", "TABLE", None),
                ("analytics", "public", "orders_view", "VIEW", "summary"),
            ]

    def fetchall(self):
        return list(self._rows)

    def fetchmany(self, size):
        batch, self._rows = self._rows[:size], self._rows[size:]
        return batch


class _LiveWireConnection:
    def __init__(self) -> None:
        self.sql = []
        self.notices = []

    def cursor(self):
        return _LiveWireCursor(self)


class _DataApiClient:
    def __init__(self, columns, records) -> None:
        self._columns = columns
        self._records = records

    @staticmethod
    def _statement_id(sql):
        if sql == "BEGIN READ ONLY":
            return "begin"
        if sql.startswith("SET statement_timeout"):
            return "timeout"
        if sql == "SHOW transaction_read_only":
            return "probe"
        if sql == "ROLLBACK":
            return "rollback"
        return "user"

    def execute_statement(self, **kwargs):
        return {"Id": self._statement_id(kwargs["Sql"])}

    def describe_statement(self, **kwargs):
        statement_id = kwargs["Id"]
        return {
            "Id": statement_id,
            "Status": "FINISHED",
            "SessionId": "session-1",
            "HasResultSet": statement_id in {"probe", "user"},
        }

    def get_statement_result(self, **kwargs):
        if kwargs["Id"] == "probe":
            return {
                "ColumnMetadata": [
                    {"name": "transaction_read_only", "typeName": "varchar"}
                ],
                "Records": [[{"stringValue": "on"}]],
            }
        return {
            "ColumnMetadata": self._columns,
            "Records": self._records,
        }


class _LiveDataApiClient(_DataApiClient):
    @staticmethod
    def _statement_id(sql):
        if sql.startswith("SHOW SCHEMAS"):
            return "schemas"
        if sql.startswith("SHOW TABLES"):
            return "relations"
        return _DataApiClient._statement_id(sql)

    def get_statement_result(self, **kwargs):
        statement_id = kwargs["Id"]
        if statement_id == "schemas":
            return {
                "ColumnMetadata": [
                    {"name": "database_name", "typeName": "varchar"},
                    {"name": "schema_name", "typeName": "varchar"},
                ],
                "Records": [
                    [{"stringValue": "analytics"}, {"stringValue": "public"}],
                    [{"stringValue": "analytics"}, {"stringValue": "analytics"}],
                ],
            }
        if statement_id == "relations":
            return {
                "ColumnMetadata": [
                    {"name": "database_name", "typeName": "varchar"},
                    {"name": "schema_name", "typeName": "varchar"},
                    {"name": "table_name", "typeName": "varchar"},
                    {"name": "table_type", "typeName": "varchar"},
                    {"name": "remarks", "typeName": "varchar"},
                ],
                "Records": [
                    [
                        {"stringValue": "analytics"},
                        {"stringValue": "public"},
                        {"stringValue": "orders"},
                        {"stringValue": "TABLE"},
                        {"isNull": True},
                    ],
                    [
                        {"stringValue": "analytics"},
                        {"stringValue": "public"},
                        {"stringValue": "orders_view"},
                        {"stringValue": "VIEW"},
                        {"stringValue": "summary"},
                    ],
                ],
            }
        return super().get_statement_result(**kwargs)

    def describe_statement(self, **kwargs):
        result = super().describe_statement(**kwargs)
        if kwargs["Id"] in {"schemas", "relations"}:
            result["HasResultSet"] = True
        return result


class _Resolver:
    def __init__(self, client) -> None:
        self._client = client

    def data_api_client(self):
        return self._client

    @staticmethod
    def data_api_request(database):
        return {"Database": database, "WorkgroupName": "analytics"}


def _wire_profile() -> ConnectionProfile:
    return ConnectionProfile(
        name="analytics-wire",
        deployment="provisioned",
        transport="wire",
        database="analytics",
        target=TargetConfig(host="example.invalid", port=5439),
        authentication=AuthenticationConfig(
            mode="password",
            username_env="WAREHOUSE_USER",
            password_env="WAREHOUSE_PASSWORD",
        ),
        aws_credentials=None,
        tls=TlsConfig(
            mode="verify-full",
            trust=TlsTrustConfig(source="file", path_env="WAREHOUSE_CA"),
        ),
    )


def _data_api_profile() -> ConnectionProfile:
    return ConnectionProfile(
        name="analytics-api",
        deployment="serverless",
        transport="data_api",
        database="analytics",
        target=TargetConfig(region="us-west-2", workgroup_name="analytics"),
        authentication=AuthenticationConfig(mode="iam"),
        aws_credentials=AwsCredentialsConfig(
            source="default",
            expected_account_id="123456789012",
        ),
        tls=None,
    )


def _query(transport, monkeypatch, *, wire_columns, wire_rows, api_columns, api_rows):
    if transport == "wire":
        @contextmanager
        def connect(_config):
            yield _WireConnection(wire_columns, wire_rows)

        monkeypatch.setattr("scripts.rs.connection.connect_config", connect)
        monkeypatch.setattr(
            "scripts.rs.connectivity.wire._validate_ca_path", lambda value: value
        )
        adapter = WireAdapter(
            _wire_profile(),
            {
                "WAREHOUSE_USER": "readonly",
                "WAREHOUSE_PASSWORD": "test-only",
                "WAREHOUSE_CA": "/test/ca.pem",
            },
        )
    else:
        client = _DataApiClient(api_columns, api_rows)
        adapter = DataApiAdapter(
            _data_api_profile(),
            {},
            aws_resolver_factory=lambda *_args: _Resolver(client),
            invocation_id_factory=lambda: "invocation",
            monotonic=lambda: 0.0,
            sleep=lambda _seconds: None,
            jitter=lambda interval: interval,
        )
    return adapter.query(
        database="analytics",
        sql="SELECT value FROM analytics.public.items",
        params={},
        limit=10,
        statement_timeout_ms=2500,
    )


@pytest.mark.parametrize("transport", ["wire", "data_api"])
def test_adapter_query_canonical_value_parity(transport, monkeypatch) -> None:
    expected = {
        "flag": True,
        "amount": Decimal("12.30"),
        "created_at": datetime(2026, 8, 19, 0, 0),
        "payload": b"\x0a\x0b",
        "missing": None,
    }
    result = _query(
        transport,
        monkeypatch,
        wire_columns=(
            ("flag", 16),
            ("amount", 1700),
            ("created_at", 1114),
            ("payload", 17),
            ("missing", 1043),
        ),
        wire_rows=((True, Decimal("12.30"), expected["created_at"], b"\x0a\x0b", None),),
        api_columns=[
            {"name": "flag", "typeName": "bool"},
            {"name": "amount", "typeName": "numeric"},
            {"name": "created_at", "typeName": "timestamp"},
            {"name": "payload", "typeName": "varbyte"},
            {"name": "missing", "typeName": "varchar"},
        ],
        api_rows=[[
            {"booleanValue": True},
            {"stringValue": "12.30"},
            {"stringValue": "2026-08-19 00:00:00"},
            {"blobValue": b"\x0a\x0b"},
            {"isNull": True},
        ]],
    )

    assert result.records == (expected,)
    assert result.row_count == 1
    assert result.truncated is False


@pytest.mark.parametrize("transport", ["wire", "data_api"])
def test_adapter_query_empty_result_parity(transport, monkeypatch) -> None:
    result = _query(
        transport,
        monkeypatch,
        wire_columns=(("value", 20),),
        wire_rows=(),
        api_columns=[{"name": "value", "typeName": "int8"}],
        api_rows=[],
    )

    assert result.records == ()
    assert result.row_count == 0
    assert result.truncated is False


@pytest.mark.parametrize("transport", ["wire", "data_api"])
def test_adapter_query_duplicate_column_error_parity(transport, monkeypatch) -> None:
    with pytest.raises(SkillError) as caught:
        _query(
            transport,
            monkeypatch,
            wire_columns=(("value", 20), ("value", 20)),
            wire_rows=((1, 2),),
            api_columns=[
                {"name": "value", "typeName": "int8"},
                {"name": "value", "typeName": "int8"},
            ],
            api_rows=[[{"longValue": 1}, {"longValue": 2}]],
        )

    assert caught.value.full_code == "query.duplicate_output_column"


@pytest.mark.parametrize("transport", ["wire", "data_api"])
def test_live_metadata_source_has_common_show_semantics(transport, monkeypatch) -> None:
    if transport == "wire":
        connection = _LiveWireConnection()

        @contextmanager
        def connect(_config):
            yield connection

        monkeypatch.setattr("scripts.rs.connection.connect_config", connect)
        monkeypatch.setattr(
            "scripts.rs.connectivity.wire._validate_ca_path", lambda value: value
        )
        adapter = WireAdapter(
            _wire_profile(),
            {
                "WAREHOUSE_USER": "readonly",
                "WAREHOUSE_PASSWORD": "test-only",
                "WAREHOUSE_CA": "/test/ca.pem",
            },
        )
    else:
        client = _LiveDataApiClient([], [])
        adapter = DataApiAdapter(
            _data_api_profile(),
            {},
            aws_resolver_factory=lambda *_args: _Resolver(client),
            invocation_id_factory=lambda: "invocation",
            monotonic=lambda: 0.0,
            sleep=lambda _seconds: None,
            jitter=lambda interval: interval,
        )

    source = adapter.live_metadata_source("analytics", 2500)
    schemas = source.show_schemas("analytics")
    relations = source.show_relations("analytics", "public")

    assert schemas.rows == ({"name": "public"}, {"name": "analytics"})
    assert relations.rows == (
        {"name": "orders", "relationType": "table", "description": None},
        {"name": "orders_view", "relationType": "view", "description": "summary"},
    )
