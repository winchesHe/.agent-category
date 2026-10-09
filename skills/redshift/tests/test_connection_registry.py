from __future__ import annotations

import json
import os

import pytest

from scripts.rs.connectivity.registry import load_connection_registry
from scripts.rs.errors import SkillError


def write_config(tmp_path, payload):
    path = tmp_path / "connections.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    os.chmod(path, 0o600)
    return path


def minimal_registry_payload():
    return {
        "schemaVersion": 1,
        "defaultConnection": "analytics-api",
        "connections": {
            "analytics-api": {
                "deployment": "serverless",
                "transport": "data_api",
                "database": "analytics",
                "target": {
                    "region": "us-west-2",
                    "workgroupName": "analytics",
                },
                "authentication": {"mode": "iam"},
                "awsCredentials": {
                    "source": "default",
                    "expectedAccountId": "123456789012",
                },
            }
        },
    }


def wire_registry_payload(host: str) -> dict:
    return {
        "schemaVersion": 1,
        "defaultConnection": "warehouse-wire",
        "connections": {
            "warehouse-wire": {
                "deployment": "provisioned",
                "transport": "wire",
                "database": "warehouse",
                "target": {"host": host, "port": 5439},
                "authentication": {
                    "mode": "password",
                    "usernameEnv": "WAREHOUSE_USER",
                    "passwordEnv": "WAREHOUSE_PASSWORD",
                },
                "tls": {
                    "mode": "verify-full",
                    "trust": {"source": "file", "pathEnv": "WAREHOUSE_CA"},
                },
            }
        },
    }


@pytest.mark.parametrize(
    "host",
    [
        "/var/run/redshift.sock",
        "@abstract-redshift",
        "redshift-a,redshift-b",
        "redshift host",
        "redshift.example.invalid:5439",
        "999.1.1.1",
        "a." + ("b" * 64) + ".example.invalid",
    ],
)
def test_explicit_wire_host_rejects_non_single_network_hosts(tmp_path, host: str) -> None:
    with pytest.raises(SkillError) as caught:
        load_connection_registry(
            {"REDSHIFT_CONNECTIONS_FILE": str(write_config(tmp_path, wire_registry_payload(host)))}
        )

    assert caught.value.full_code == "config.invalid"
    assert host not in repr(caught.value.to_payload())


@pytest.mark.parametrize(
    "host",
    [
        "redshift.example.invalid",
        "123",
        "192.0.2.10",
        "2001:db8::10",
    ],
)
def test_explicit_wire_host_accepts_single_dns_or_ip_host(tmp_path, host: str) -> None:
    registry = load_connection_registry(
        {"REDSHIFT_CONNECTIONS_FILE": str(write_config(tmp_path, wire_registry_payload(host)))}
    )

    assert registry.resolve(None).target.host == host


def test_named_registry_resolves_one_typed_data_api_profile_without_mutating_env(
    tmp_path,
) -> None:
    path = write_config(
        tmp_path,
        {
            "schemaVersion": 1,
            "defaultConnection": "analytics-api",
            "catalogConnection": "analytics-api",
            "connections": {
                "analytics-api": {
                    "deployment": "serverless",
                    "transport": "data_api",
                    "database": "analytics",
                    "target": {
                        "region": "us-west-2",
                        "workgroupName": "analytics",
                    },
                    "authentication": {"mode": "iam"},
                    "awsCredentials": {
                        "source": "profile",
                        "profile": "analytics-readonly",
                        "expectedAccountId": "123456789012",
                    },
                }
            },
        },
    )
    env = {"REDSHIFT_CONNECTIONS_FILE": str(path)}
    before = dict(env)

    registry = load_connection_registry(env)
    profile = registry.resolve(None)

    assert registry.default_connection == "analytics-api"
    assert registry.catalog_connection == "analytics-api"
    assert profile.name == "analytics-api"
    assert profile.deployment == "serverless"
    assert profile.transport == "data_api"
    assert profile.database == "analytics"
    assert profile.target.workgroup_name == "analytics"
    assert profile.authentication.mode == "iam"
    assert profile.aws_credentials.profile == "analytics-readonly"
    assert env == before


def test_missing_skill_local_registry_returns_a_named_config_error(
    tmp_path, monkeypatch
) -> None:
    module_path = tmp_path / "skill" / "scripts" / "rs" / "connectivity" / "registry.py"
    monkeypatch.setattr("scripts.rs.connectivity.registry.__file__", str(module_path))

    with pytest.raises(SkillError) as caught:
        load_connection_registry({})

    assert caught.value.full_code == "config.missing"
    assert caught.value.details == {"key": "connections.json"}


def test_registry_defaults_to_the_skill_root_connections_file(
    tmp_path, monkeypatch
) -> None:
    skill_root = tmp_path / "skill"
    module_path = skill_root / "scripts" / "rs" / "connectivity" / "registry.py"
    module_path.parent.mkdir(parents=True)
    path = write_config(skill_root, minimal_registry_payload())
    monkeypatch.setattr("scripts.rs.connectivity.registry.__file__", str(module_path))

    registry = load_connection_registry({})

    assert registry.default_connection == "analytics-api"
    assert registry.resolve(None).transport == "data_api"
    assert path.name == "connections.json"


def test_invalid_registry_fails_without_an_alternate_connection_source(tmp_path) -> None:
    path = write_config(
        tmp_path,
        {
            "schemaVersion": 1,
            "defaultConnection": "broken",
            "connections": {
                "broken": {
                    "deployment": "serverless",
                    "transport": "data_api",
                    "database": "analytics",
                    "target": {"region": "us-west-2"},
                    "authentication": {"mode": "iam"},
                    "awsCredentials": {
                        "source": "default",
                        "expectedAccountId": "123456789012",
                    },
                }
            },
        },
    )
    env = {"REDSHIFT_CONNECTIONS_FILE": str(path)}

    with pytest.raises(SkillError) as caught:
        load_connection_registry(env)

    assert caught.value.full_code == "config.invalid_combination"


def test_named_registry_rejects_duplicate_keys_and_unsafe_file_mode(tmp_path) -> None:
    duplicate = tmp_path / "duplicate.json"
    duplicate.write_text(
        '{"schemaVersion":1,"schemaVersion":1,"defaultConnection":"x","connections":{}}',
        encoding="utf-8",
    )
    os.chmod(duplicate, 0o600)
    with pytest.raises(SkillError) as caught:
        load_connection_registry({"REDSHIFT_CONNECTIONS_FILE": str(duplicate)})
    assert caught.value.full_code == "config.invalid"


def test_named_registry_rejects_symlinked_parent_directory(tmp_path) -> None:
    real_directory = tmp_path / "real"
    real_directory.mkdir(mode=0o700)
    path = write_config(real_directory, minimal_registry_payload())
    linked_directory = tmp_path / "linked"
    linked_directory.symlink_to(real_directory, target_is_directory=True)

    with pytest.raises(SkillError) as caught:
        load_connection_registry(
            {"REDSHIFT_CONNECTIONS_FILE": str(linked_directory / path.name)}
        )

    assert caught.value.full_code == "config.invalid"


def test_named_registry_rejects_group_or_other_writable_parent(tmp_path) -> None:
    unsafe_directory = tmp_path / "unsafe"
    unsafe_directory.mkdir(mode=0o700)
    path = write_config(unsafe_directory, minimal_registry_payload())
    os.chmod(unsafe_directory, 0o770)

    with pytest.raises(SkillError) as caught:
        load_connection_registry({"REDSHIFT_CONNECTIONS_FILE": str(path)})

    assert caught.value.full_code == "config.invalid"


def test_named_registry_accepts_owner_controlled_parent_directories(tmp_path) -> None:
    safe_directory = tmp_path / "safe" / "nested"
    safe_directory.mkdir(parents=True, mode=0o700)
    path = write_config(safe_directory, minimal_registry_payload())

    registry = load_connection_registry({"REDSHIFT_CONNECTIONS_FILE": str(path)})

    assert registry.default_connection == "analytics-api"

    unsafe = write_config(tmp_path, {"schemaVersion": 1})
    os.chmod(unsafe, 0o644)
    with pytest.raises(SkillError) as caught:
        load_connection_registry({"REDSHIFT_CONNECTIONS_FILE": str(unsafe)})
    assert caught.value.full_code == "config.invalid"

    target = write_config(tmp_path, {"schemaVersion": 1})
    link = tmp_path / "connections-link.json"
    link.symlink_to(target)
    with pytest.raises(SkillError) as caught:
        load_connection_registry({"REDSHIFT_CONNECTIONS_FILE": str(link)})
    assert caught.value.full_code == "config.invalid"


@pytest.mark.parametrize(
    ("deployment", "transport", "auth_mode"),
    [
        ("provisioned", "wire", "password"),
        ("serverless", "wire", "password"),
        ("provisioned", "wire", "iam"),
        ("serverless", "wire", "iam"),
        ("provisioned", "wire", "secret"),
        ("serverless", "wire", "secret"),
        ("provisioned", "data_api", "iam"),
        ("provisioned", "data_api", "iam_db_user"),
        ("serverless", "data_api", "iam"),
        ("provisioned", "data_api", "secret"),
        ("serverless", "data_api", "secret"),
    ],
)
def test_registry_accepts_every_v2_core_combination(
    tmp_path, deployment, transport, auth_mode
) -> None:
    target = {"region": "us-west-2"}
    target[
        "clusterIdentifier" if deployment == "provisioned" else "workgroupName"
    ] = "target"
    if transport == "wire" and auth_mode == "password":
        target = {"host": "redacted.example.invalid", "port": 5439}
    authentication = {"mode": auth_mode}
    if auth_mode == "password":
        authentication.update(
            {"usernameEnv": "WAREHOUSE_USER", "passwordEnv": "WAREHOUSE_PASSWORD"}
        )
    elif auth_mode == "secret":
        authentication["secretArnEnv"] = "WAREHOUSE_SECRET_ARN"
    elif auth_mode == "iam_db_user":
        authentication["dbUser"] = "readonly"
    profile = {
        "deployment": deployment,
        "transport": transport,
        "database": "analytics",
        "target": target,
        "authentication": authentication,
    }
    if auth_mode != "password":
        profile["awsCredentials"] = {
            "source": "default",
            "expectedAccountId": "123456789012",
        }
    if transport == "wire":
        profile["tls"] = {
            "mode": "verify-full",
            "trust": {"source": "file", "pathEnv": "WAREHOUSE_CA"},
        }
    path = write_config(
        tmp_path,
        {
            "schemaVersion": 1,
            "defaultConnection": "selected",
            "connections": {"selected": profile},
        },
    )

    selected = load_connection_registry(
        {"REDSHIFT_CONNECTIONS_FILE": str(path)}
    ).resolve(None)

    assert (selected.deployment, selected.transport, selected.authentication.mode) == (
        deployment,
        transport,
        auth_mode,
    )


@pytest.mark.parametrize("deployment", ["provisioned", "serverless"])
def test_wire_secret_accepts_explicit_host_without_aws_target_identifier(
    tmp_path, deployment
) -> None:
    path = write_config(
        tmp_path,
        {
            "schemaVersion": 1,
            "defaultConnection": "gateway-secret",
            "connections": {
                "gateway-secret": {
                    "deployment": deployment,
                    "transport": "wire",
                    "database": "analytics",
                    "target": {
                        "region": "us-west-2",
                        "host": "gateway.example.invalid",
                        "port": 45439,
                    },
                    "authentication": {
                        "mode": "secret",
                        "secretArnEnv": "WAREHOUSE_SECRET_ARN",
                    },
                    "awsCredentials": {
                        "source": "default",
                        "expectedAccountId": "123456789012",
                    },
                    "tls": {
                        "mode": "verify-full",
                        "trust": {"source": "file", "pathEnv": "WAREHOUSE_CA"},
                    },
                }
            },
        },
    )

    profile = load_connection_registry(
        {"REDSHIFT_CONNECTIONS_FILE": str(path)}
    ).resolve(None)

    assert profile.authentication.mode == "secret"
    assert profile.target.host == "gateway.example.invalid"
    assert profile.target.cluster_identifier is None
    assert profile.target.workgroup_name is None


@pytest.mark.parametrize("deployment", ["provisioned", "serverless"])
def test_wire_iam_explicit_host_still_requires_aws_target_identifier(
    tmp_path, deployment
) -> None:
    path = write_config(
        tmp_path,
        {
            "schemaVersion": 1,
            "defaultConnection": "gateway-iam",
            "connections": {
                "gateway-iam": {
                    "deployment": deployment,
                    "transport": "wire",
                    "database": "analytics",
                    "target": {
                        "region": "us-west-2",
                        "host": "gateway.example.invalid",
                    },
                    "authentication": {"mode": "iam"},
                    "awsCredentials": {
                        "source": "default",
                        "expectedAccountId": "123456789012",
                    },
                    "tls": {
                        "mode": "verify-full",
                        "trust": {"source": "file", "pathEnv": "WAREHOUSE_CA"},
                    },
                }
            },
        },
    )

    with pytest.raises(SkillError) as caught:
        load_connection_registry({"REDSHIFT_CONNECTIONS_FILE": str(path)})

    assert caught.value.full_code == "config.invalid_combination"


@pytest.mark.parametrize(
    "mutation",
    [
        lambda profile: profile["authentication"].update({"dbUser": "unexpected"}),
        lambda profile: profile["target"].update({"port": 5439}),
    ],
)
def test_data_api_registry_rejects_fields_from_another_union_variant(
    tmp_path, mutation
) -> None:
    profile = {
        "deployment": "serverless",
        "transport": "data_api",
        "database": "analytics",
        "target": {"region": "us-west-2", "workgroupName": "analytics"},
        "authentication": {"mode": "iam"},
        "awsCredentials": {
            "source": "default",
            "expectedAccountId": "123456789012",
        },
    }
    mutation(profile)
    path = write_config(
        tmp_path,
        {
            "schemaVersion": 1,
            "defaultConnection": "selected",
            "connections": {"selected": profile},
        },
    )

    with pytest.raises(SkillError) as caught:
        load_connection_registry({"REDSHIFT_CONNECTIONS_FILE": str(path)})

    assert caught.value.full_code == "config.invalid_combination"
