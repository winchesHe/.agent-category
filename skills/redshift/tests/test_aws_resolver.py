from __future__ import annotations

import json

import pytest

from scripts.rs.connectivity.aws import (
    AwsResolver,
    _default_client_config,
    map_aws_error,
)
from scripts.rs.connectivity.model import (
    AuthenticationConfig,
    AwsCredentialsConfig,
    ConnectionProfile,
    TargetConfig,
    TlsConfig,
    TlsTrustConfig,
)
from scripts.rs.errors import SkillError


def test_default_aws_client_config_ignores_ambient_endpoint_overrides() -> None:
    config = _default_client_config(10)

    assert config.ignore_configured_endpoint_urls is True


def serverless_profile(mode: str = "iam") -> ConnectionProfile:
    return ConnectionProfile(
        name="serverless-wire",
        deployment="serverless",
        transport="wire",
        database="analytics",
        target=TargetConfig(region="us-west-2", workgroup_name="analytics"),
        authentication=AuthenticationConfig(
            mode=mode,
            secret_arn_env="WAREHOUSE_SECRET_ARN" if mode == "secret" else None,
        ),
        aws_credentials=AwsCredentialsConfig(
            source="profile",
            profile="readonly",
            expected_account_id="123456789012",
        ),
        tls=TlsConfig(
            mode="verify-full",
            trust=TlsTrustConfig(source="file", path_env="WAREHOUSE_CA"),
        ),
    )


class Sts:
    def get_caller_identity(self):
        return {
            "Account": "123456789012",
            "Arn": "arn:aws:sts::123456789012:assumed-role/readonly/session",
        }


class Serverless:
    def __init__(self) -> None:
        self.calls = []

    def get_workgroup(self, **kwargs):
        self.calls.append(("get_workgroup", kwargs))
        return {
            "workgroup": {
                "endpoint": {"address": "resolved.example.invalid", "port": 5439}
            }
        }

    def get_credentials(self, **kwargs):
        self.calls.append(("get_credentials", kwargs))
        return {"dbUser": "IAMR:readonly", "dbPassword": "temporary-secret"}


class Secrets:
    def get_secret_value(self, **kwargs):
        return {
            "SecretString": json.dumps(
                {"username": "readonly", "password": "temporary-secret"}
            )
        }


class Session:
    def __init__(self, clients):
        self.clients = clients

    def client(self, name, **_kwargs):
        return self.clients[name]


def test_data_api_http_400_throttling_remains_a_transient_connection_error() -> None:
    class ThrottlingException(Exception):
        response = {
            "Error": {"Code": "ThrottlingException"},
            "ResponseMetadata": {"HTTPStatusCode": 400},
        }

    error = map_aws_error(ThrottlingException(), stage="user")

    assert error.full_code == "connection.unavailable"
    assert error.retry_class == "transient"
    assert error.suggestion == "retry_connection"
    assert error.details == {"stage": "user"}


def test_serverless_iam_resolves_identity_endpoint_and_temporary_credentials() -> None:
    profile = serverless_profile()
    serverless = Serverless()
    session = Session({"sts": Sts(), "redshift-serverless": serverless})
    calls = []

    def session_factory(**kwargs):
        calls.append(kwargs)
        return session

    resolved = AwsResolver(
        profile,
        {},
        session_factory=session_factory,
    ).resolve_wire(profile, "analytics")

    assert calls == [{"profile_name": "readonly", "region_name": "us-west-2"}]
    assert resolved.host == "resolved.example.invalid"
    assert resolved.username == "IAMR:readonly"
    assert "temporary-secret" not in repr(resolved)
    assert serverless.calls == [
        ("get_workgroup", {"workgroupName": "analytics"}),
        (
            "get_credentials",
            {
                "workgroupName": "analytics",
                "dbName": "analytics",
                "durationSeconds": 900,
            },
        ),
    ]


def test_wire_secret_uses_secret_arn_env_and_never_exposes_secret_value() -> None:
    profile = serverless_profile("secret")
    serverless = Serverless()
    session = Session(
        {
            "sts": Sts(),
            "redshift-serverless": serverless,
            "secretsmanager": Secrets(),
        }
    )
    resolved = AwsResolver(
        profile,
        {"WAREHOUSE_SECRET_ARN": "arn:aws:secretsmanager:region:account:secret:test"},
        session_factory=lambda **_kwargs: session,
    ).resolve_wire(profile, "analytics")

    assert resolved.username == "readonly"
    assert "temporary-secret" not in repr(resolved)


def test_malformed_secret_is_stable_secret_unavailable_not_transient_connection() -> None:
    class MalformedSecrets:
        def get_secret_value(self, **_kwargs):
            return {"SecretString": "not-json"}

    profile = serverless_profile("secret")
    resolver = AwsResolver(
        profile,
        {"WAREHOUSE_SECRET_ARN": "arn:aws:secretsmanager:region:account:secret:test"},
        session_factory=lambda **_kwargs: Session(
            {
                "sts": Sts(),
                "redshift-serverless": Serverless(),
                "secretsmanager": MalformedSecrets(),
            }
        ),
    )

    with pytest.raises(SkillError) as caught:
        resolver.resolve_wire(profile, "analytics")

    assert caught.value.full_code == "connection.secret_unavailable"


def test_aws_identity_mismatch_fails_before_target_or_credentials() -> None:
    class WrongSts:
        def get_caller_identity(self):
            return {"Account": "000000000000", "Arn": "redacted"}

    profile = serverless_profile()
    resolver = AwsResolver(
        profile,
        {},
        session_factory=lambda **_kwargs: Session(
            {"sts": WrongSts(), "redshift-serverless": Serverless()}
        ),
    )

    with pytest.raises(SkillError) as caught:
        resolver.resolve_wire(profile, "analytics")

    assert caught.value.full_code == "connection.auth_failed"
    assert caught.value.details == {"stage": "identity"}


@pytest.mark.parametrize(
    ("mode", "expected"),
    [
        ("iam", {}),
        ("iam_db_user", {"DbUser": "readonly"}),
        (
            "secret",
            {"SecretArn": "arn:aws:secretsmanager:region:account:secret:test"},
        ),
    ],
)
def test_provisioned_data_api_auth_request_is_explicit_and_typed(mode, expected) -> None:
    authentication = AuthenticationConfig(
        mode=mode,
        db_user="readonly" if mode == "iam_db_user" else None,
        secret_arn_env="WAREHOUSE_SECRET_ARN" if mode == "secret" else None,
    )
    profile = ConnectionProfile(
        name="provisioned-api",
        deployment="provisioned",
        transport="data_api",
        database="analytics",
        target=TargetConfig(region="us-west-2", cluster_identifier="warehouse"),
        authentication=authentication,
        aws_credentials=AwsCredentialsConfig(
            source="default", expected_account_id="123456789012"
        ),
        tls=None,
    )
    resolver = AwsResolver(
        profile,
        {
            "WAREHOUSE_SECRET_ARN": "arn:aws:secretsmanager:region:account:secret:test"
        },
        session_factory=lambda **_kwargs: Session({"sts": Sts()}),
    )

    request = resolver.data_api_request("analytics")

    assert request == {
        "Database": "analytics",
        "ClusterIdentifier": "warehouse",
        **expected,
    }


def test_aws_clients_use_bounded_timeout_and_standard_retry_config() -> None:
    calls = []

    class ConfigSession:
        def client(self, name, **kwargs):
            calls.append((name, kwargs))
            return Sts() if name == "sts" else object()

    profile = serverless_profile()
    resolver = AwsResolver(
        profile,
        {},
        session_factory=lambda **_kwargs: ConfigSession(),
        client_config_factory=lambda timeout: {"timeout": timeout, "retries": 3},
    )

    resolver.data_api_client()

    assert calls == [
        ("sts", {"config": {"timeout": 10, "retries": 3}}),
        ("redshift-data", {"config": {"timeout": 10, "retries": 3}}),
    ]
