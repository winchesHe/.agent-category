from __future__ import annotations

import pytest

from scripts.rs.connectivity.doctor import run_adapter_doctor
from scripts.rs.connectivity.model import (
    AuthenticationConfig,
    AwsCredentialsConfig,
    ConnectionProfile,
    ConnectionRegistry,
    TargetConfig,
)
from scripts.rs.connectivity.service import RedshiftConnectivity
from scripts.rs.errors import SkillError


@pytest.mark.parametrize(
    ("connectivity", "readonly", "expected"),
    (
        ("unavailable", False, False),
        ("available", False, False),
        ("available", True, True),
    ),
)
def test_live_doctor_availability_requires_connectivity_and_readonly(
    connectivity: str,
    readonly: bool,
    expected: bool,
) -> None:
    result = run_adapter_doctor(
        environ={},
        dependency_name="driver",
        dependency_available=lambda: True,
        static_config_check=lambda: None,
        connect_live=True,
        live_probe=lambda: {
            "connectivity": connectivity,
            "readonly": readonly,
        },
    )

    assert result.data["skillAvailable"] is expected
    assert result.data["jsonQueryAvailable"] is expected
    assert result.data["capabilities"] == {
        "connectivity": connectivity,
        "readonly": readonly,
    }


def profile(transport: str) -> ConnectionProfile:
    return ConnectionProfile(
        name=f"selected-{transport}",
        deployment="serverless",
        transport=transport,
        database="analytics",
        target=TargetConfig(region="us-west-2", workgroup_name="analytics"),
        authentication=AuthenticationConfig(mode="iam"),
        aws_credentials=AwsCredentialsConfig(
            source="default",
            expected_account_id="123456789012",
        ),
        tls=None,
    )


def test_bind_resolves_once_and_selects_only_the_declared_adapter() -> None:
    selected = profile("data_api")
    registry = ConnectionRegistry.create(
        default_connection=selected.name,
        catalog_connection=None,
        connections={selected.name: selected},
    )
    events: list[object] = []

    def wire_factory(*_args, **_kwargs):
        raise AssertionError("wire adapter must not be created")

    def data_api_factory(resolved, environ):
        events.append((resolved, environ))
        return object()

    connectivity = RedshiftConnectivity(
        {},
        registry_loader=lambda _environ: registry,
        wire_adapter_factory=wire_factory,
        data_api_adapter_factory=data_api_factory,
    )

    bound = connectivity.bind(None)

    assert bound.connection_name == selected.name
    assert bound.default_database == "analytics"
    assert bound.owns_catalog is False
    assert events == [(selected, {})]


def test_catalog_binding_uses_only_frozen_catalog_connection() -> None:
    catalog = profile("data_api")
    other = ConnectionProfile(
        **{**catalog.__dict__, "name": "other-api"}
    )
    registry = ConnectionRegistry.create(
        default_connection=other.name,
        catalog_connection=catalog.name,
        connections={catalog.name: catalog, other.name: other},
    )
    selected = []
    connectivity = RedshiftConnectivity(
        {},
        registry_loader=lambda _environ: registry,
        data_api_adapter_factory=lambda resolved, _environ: selected.append(resolved.name)
        or object(),
    )

    bound = connectivity.bind_catalog()

    assert bound.connection_name == catalog.name
    assert bound.owns_catalog is True
    assert selected == [catalog.name]

    missing = RedshiftConnectivity(
        {},
        registry_loader=lambda _environ: ConnectionRegistry.create(
            default_connection=other.name,
            catalog_connection=None,
            connections={other.name: other},
        ),
        data_api_adapter_factory=lambda *_args: object(),
    )
    with pytest.raises(SkillError) as caught:
        missing.bind_catalog()
    assert caught.value.full_code == "config.missing"
    assert caught.value.details == {"key": "catalogConnection"}


def test_list_connections_is_static_sorted_and_redacted() -> None:
    serverless = profile("data_api")
    provisioned = ConnectionProfile(
        name="archive-wire",
        deployment="provisioned",
        transport="wire",
        database="archive",
        target=TargetConfig(host="private.example.invalid", port=5439),
        authentication=AuthenticationConfig(
            mode="password",
            username_env="ARCHIVE_USER",
            password_env="ARCHIVE_PASSWORD",
        ),
        aws_credentials=None,
        tls=None,
    )
    registry = ConnectionRegistry.create(
        default_connection=serverless.name,
        catalog_connection=provisioned.name,
        connections={serverless.name: serverless, provisioned.name: provisioned},
    )

    def adapter_must_not_be_created(*_args, **_kwargs):
        raise AssertionError("connection discovery must not create an adapter")

    connectivity = RedshiftConnectivity(
        {},
        registry_loader=lambda _environ: registry,
        wire_adapter_factory=adapter_must_not_be_created,
        data_api_adapter_factory=adapter_must_not_be_created,
    )

    result = connectivity.list_connections()

    assert result.data == {
        "connections": [
            {
                "name": "archive-wire",
                "deployment": "provisioned",
                "transport": "wire",
                "database": "archive",
                "authMode": "password",
                "default": False,
                "catalog": True,
            },
            {
                "name": "selected-data_api",
                "deployment": "serverless",
                "transport": "data_api",
                "database": "analytics",
                "authMode": "iam",
                "default": True,
                "catalog": False,
            },
        ]
    }
    rendered = repr(result.data)
    assert "private.example.invalid" not in rendered
    assert "ARCHIVE_USER" not in rendered
    assert "ARCHIVE_PASSWORD" not in rendered
