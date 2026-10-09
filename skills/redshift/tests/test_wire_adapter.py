from __future__ import annotations

import json
import os
import sys

import pytest

from scripts.rs.connectivity.aws import ResolvedWireAuth
from scripts.rs.connectivity.model import (
    AuthenticationConfig,
    AwsCredentialsConfig,
    ConnectionProfile,
    TargetConfig,
    TlsConfig,
    TlsTrustConfig,
)
from scripts.rs.connectivity.registry import load_connection_registry
from scripts.rs.connectivity.wire import WireAdapter, _validate_ca_path


class Cursor:
    description = (("value", 20),)

    def __init__(self) -> None:
        self.executed = []

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def execute(self, sql, params=None):
        self.executed.append((sql, params))

    def fetchall(self):
        return [(1,)]


class Connection:
    def __init__(self) -> None:
        self.session = None
        self.closed = False
        self.cursors = []

    def set_session(self, **kwargs):
        self.session = kwargs

    def cursor(self):
        cursor = Cursor()
        self.cursors.append(cursor)
        return cursor

    def close(self):
        self.closed = True


@pytest.mark.parametrize(
    "message,password,signal,sqlstate",
    [
        ('connection to server at "warehouse.example.invalid" failed: timeout expired', 'opaque-secret', 'connectTimedOut', None),
        ('FATAL: password authentication failed for user "readonly"', 'opaque-secret', 'passwordRejected', None),
        ('FATAL: password authentication failed for user "readonly"', 'opaque-secret', 'passwordRejected', '28P01'),
        ('invalid supplied value: password authentication failed', 'password authentication failed', None, None),
    ],
)
def test_wire_doctor_preserves_only_safe_private_connect_diagnostics(
    tmp_path, monkeypatch, message, password, signal, sqlstate
):
    ca = tmp_path / "ca.pem"
    ca.write_text("test-ca", encoding="utf-8")
    ca.chmod(0o600)
    profile = ConnectionProfile(
        name="warehouse-wire", deployment="provisioned", transport="wire",
        database="analytics", target=TargetConfig(host="warehouse.example.invalid"),
        authentication=AuthenticationConfig(mode="password", username_env="WAREHOUSE_USER", password_env="WAREHOUSE_PASSWORD"),
        aws_credentials=None,
        tls=TlsConfig(mode="verify-full", trust=TlsTrustConfig(source="file", path_env="WAREHOUSE_CA")),
    )

    class OperationalError(Exception):
        pgcode = sqlstate

    class Driver:
        @staticmethod
        def connect(**_kwargs):
            raise OperationalError(message)

    monkeypatch.setattr("scripts.rs.connection._psycopg2", lambda: Driver)
    result = WireAdapter(profile, {
        "WAREHOUSE_USER": "readonly", "WAREHOUSE_PASSWORD": password,
        "WAREHOUSE_CA": str(ca),
    }, psycopg2_available=lambda: True).preflight(connect_live=True)
    assert result.data["capabilities"]["code"] == (
        "connection.auth_failed" if sqlstate else "connection.unavailable"
    )
    if sqlstate:
        assert result.data["capabilities"]["suggestion"] == "verify_database_credentials"
        assert result.data["capabilities"]["retryClass"] == "after_change"
    assert "diagnostics" not in result.data["capabilities"]
    assert result.diagnostics["connectionStage"] == "connect"
    for key in ("connectTimedOut", "passwordRejected", "tlsVerificationFailed"):
        assert result.diagnostics[key] is (key == signal)
    encoded = json.dumps({"data": result.data, "diagnostics": result.diagnostics})
    assert "warehouse.example.invalid" not in encoded
    assert password not in encoded
    if sqlstate:
        assert result.diagnostics["sqlState"] == sqlstate
        assert sqlstate not in json.dumps(result.data)
    else:
        assert "sqlState" not in result.diagnostics


@pytest.mark.skipif(sys.platform != "darwin", reason="macOS system CA alias")
def test_macos_system_ca_alias_resolves_to_the_canonical_system_file() -> None:
    assert _validate_ca_path("/etc/ssl/cert.pem") == "/private/etc/ssl/cert.pem"


def test_named_password_wire_query_is_readonly_and_autocommit(
    tmp_path, monkeypatch
) -> None:
    ca = tmp_path / "redshift-ca.pem"
    ca.write_text("test-ca", encoding="utf-8")
    os.chmod(ca, 0o600)
    profile = ConnectionProfile(
        name="warehouse-wire",
        deployment="provisioned",
        transport="wire",
        database="control",
        target=TargetConfig(host="redacted.example.invalid", port=5439),
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
    environ = {
        "WAREHOUSE_USER": "readonly",
        "WAREHOUSE_PASSWORD": "operator-secret",
        "WAREHOUSE_CA": str(ca),
    }
    connection = Connection()
    monkeypatch.setattr(
        "scripts.rs.connection._open_connection", lambda _config: connection
    )

    result = WireAdapter(profile, environ).query(
        database="control",
        sql="SELECT 1 AS value",
        params={},
        limit=10,
        statement_timeout_ms=2500,
    )

    assert connection.session == {"readonly": True, "autocommit": True}
    assert connection.closed is True
    assert result.records == ({"value": 1},)
    assert "operator-secret" not in repr(result)


def test_named_password_wire_requires_verify_full_and_explicit_ca(
    tmp_path, monkeypatch
) -> None:
    ca = tmp_path / "redshift-ca.pem"
    ca.write_text("test-ca", encoding="utf-8")
    os.chmod(ca, 0o600)
    config = tmp_path / "connections.json"
    config.write_text(
        json.dumps(
            {
                "schemaVersion": 1,
                "defaultConnection": "warehouse-wire",
                "connections": {
                    "warehouse-wire": {
                        "deployment": "provisioned",
                        "transport": "wire",
                        "database": "warehouse",
                        "target": {
                            "host": "redacted.example.invalid",
                            "port": 5439,
                        },
                        "authentication": {
                            "mode": "password",
                            "usernameEnv": "WAREHOUSE_USER",
                            "passwordEnv": "WAREHOUSE_PASSWORD",
                        },
                        "tls": {
                            "mode": "verify-full",
                            "trust": {
                                "source": "file",
                                "pathEnv": "WAREHOUSE_CA",
                            },
                        },
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    os.chmod(config, 0o600)
    env = {
        "REDSHIFT_CONNECTIONS_FILE": str(config),
        "WAREHOUSE_USER": "readonly",
        "WAREHOUSE_PASSWORD": "operator-secret",
        "WAREHOUSE_CA": str(ca),
    }
    profile = load_connection_registry(env).resolve(None)
    connection = Connection()
    captured = []

    def open_connection(selected):
        captured.append(selected)
        return connection

    monkeypatch.setattr("scripts.rs.connection._open_connection", open_connection)

    WireAdapter(profile, env).query(
        database="warehouse",
        sql="SELECT 1 AS value",
        params={},
        limit=10,
        statement_timeout_ms=2500,
    )

    assert captured[0].sslmode == "verify-full"
    assert captured[0].sslrootcert == str(ca)
    assert "operator-secret" not in repr(captured[0])


def test_serverless_iam_wire_uses_aws_resolver_without_exposing_temporary_password(
    tmp_path, monkeypatch
) -> None:
    ca = tmp_path / "redshift-ca.pem"
    ca.write_text("test-ca", encoding="utf-8")
    os.chmod(ca, 0o600)
    profile = ConnectionProfile(
        name="serverless-wire",
        deployment="serverless",
        transport="wire",
        database="analytics",
        target=TargetConfig(region="us-west-2", workgroup_name="analytics"),
        authentication=AuthenticationConfig(mode="iam"),
        aws_credentials=AwsCredentialsConfig(
            source="default", expected_account_id="123456789012"
        ),
        tls=TlsConfig(
            mode="verify-full",
            trust=TlsTrustConfig(source="file", path_env="WAREHOUSE_CA"),
        ),
    )
    events = []

    class Resolver:
        def resolve_wire(self, selected_profile, database):
            events.append((selected_profile.name, database))
            return ResolvedWireAuth(
                host="resolved.example.invalid",
                port=5439,
                username="IAMR:readonly",
                password="test-only",
            )

    connection = Connection()
    captured = []

    def open_connection(selected):
        captured.append(selected)
        return connection

    monkeypatch.setattr("scripts.rs.connection._open_connection", open_connection)

    WireAdapter(
        profile,
        {"WAREHOUSE_CA": str(ca)},
        aws_resolver_factory=lambda *_args: Resolver(),
    ).query(
        database="analytics",
        sql="SELECT 1 AS value",
        params={},
        limit=10,
        statement_timeout_ms=2500,
    )

    assert events == [("serverless-wire", "analytics")]
    assert captured[0].host == "resolved.example.invalid"
    assert "test-only" not in repr(captured[0])


def test_named_wire_static_doctor_validates_ca_without_connecting(tmp_path) -> None:
    profile = ConnectionProfile(
        name="warehouse-wire",
        deployment="provisioned",
        transport="wire",
        database="warehouse",
        target=TargetConfig(host="redacted.example.invalid"),
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

    result = WireAdapter(
        profile,
        {
            "WAREHOUSE_USER": "readonly",
            "WAREHOUSE_PASSWORD": "operator-secret",
        },
    ).preflight(connect_live=False)

    assert result.data["skillAvailable"] is False
    config_check = next(
        item for item in result.data["checks"] if item["name"] == "connection_config"
    )
    assert config_check == {
        "name": "connection_config",
        "status": "unavailable",
        "code": "config.missing",
        "invalidKey": "WAREHOUSE_CA",
    }


def test_wire_static_doctor_does_not_claim_query_without_live_proof(tmp_path) -> None:
    ca = tmp_path / "redshift-ca.pem"
    ca.write_text("test-ca", encoding="utf-8")
    os.chmod(ca, 0o600)
    profile = ConnectionProfile(
        name="warehouse-wire",
        deployment="provisioned",
        transport="wire",
        database="warehouse",
        target=TargetConfig(host="redacted.example.invalid"),
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

    result = WireAdapter(
        profile,
        {
            "WAREHOUSE_USER": "readonly",
            "WAREHOUSE_PASSWORD": "operator-secret",
            "WAREHOUSE_CA": str(ca),
        },
        psycopg2_available=lambda: True,
    ).preflight(connect_live=False)

    assert result.data["skillAvailable"] is False
    assert result.data["jsonQueryAvailable"] is False
    assert not any(item["name"] == "live_capabilities" for item in result.data["checks"])


def test_wire_ca_root_open_failure_returns_typed_config_error(
    tmp_path, monkeypatch
) -> None:
    ca = tmp_path / "redshift-ca.pem"
    ca.write_text("test-ca", encoding="utf-8")
    os.chmod(ca, 0o600)
    profile = ConnectionProfile(
        name="warehouse-wire",
        deployment="provisioned",
        transport="wire",
        database="warehouse",
        target=TargetConfig(host="redacted.example.invalid"),
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

    monkeypatch.setattr(
        "scripts.rs.connectivity.wire.os.open",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("private detail")),
    )

    result = WireAdapter(
        profile,
        {
            "WAREHOUSE_USER": "readonly",
            "WAREHOUSE_PASSWORD": "operator-secret",
            "WAREHOUSE_CA": str(ca),
        },
        psycopg2_available=lambda: True,
    ).preflight(connect_live=False)

    config_check = next(
        item for item in result.data["checks"] if item["name"] == "connection_config"
    )
    assert config_check == {
        "name": "connection_config",
        "status": "unavailable",
        "code": "config.invalid",
        "invalidKey": "tls.trust.pathEnv",
    }
    assert "private detail" not in repr(result.data)


def test_aws_backed_wire_static_doctor_requires_boto3(tmp_path) -> None:
    ca = tmp_path / "redshift-ca.pem"
    ca.write_text("test-ca", encoding="utf-8")
    os.chmod(ca, 0o600)
    profile = ConnectionProfile(
        name="provisioned-wire",
        deployment="provisioned",
        transport="wire",
        database="analytics",
        target=TargetConfig(region="us-west-2", cluster_identifier="analytics"),
        authentication=AuthenticationConfig(mode="iam"),
        aws_credentials=AwsCredentialsConfig(
            source="default", expected_account_id="123456789012"
        ),
        tls=TlsConfig(
            mode="verify-full",
            trust=TlsTrustConfig(source="file", path_env="WAREHOUSE_CA"),
        ),
    )

    result = WireAdapter(
        profile,
        {"WAREHOUSE_CA": str(ca)},
        psycopg2_available=lambda: True,
        boto3_available=lambda: False,
    ).preflight(connect_live=False)

    checks = {item["name"]: item for item in result.data["checks"]}
    assert checks["psycopg2"]["status"] == "available"
    assert checks["boto3"] == {
        "name": "boto3",
        "status": "unavailable",
        "code": "config.dependency_missing",
    }
    assert result.data["skillAvailable"] is False
