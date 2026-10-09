"""Secure, strict named-connection registry for V2."""
from __future__ import annotations

import json
import ipaddress
import os
import re
import stat
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from ..errors import SkillError, config_error
from .model import (
    AuthenticationConfig,
    AwsCredentialsConfig,
    ConnectionProfile,
    ConnectionRegistry,
    TargetConfig,
    TlsConfig,
    TlsTrustConfig,
)


CONNECTIONS_FILE_MAX_BYTES = 262_144
CONNECTION_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
ENV_NAME = re.compile(r"^[A-Z][A-Z0-9_]*$")
ACCOUNT_ID = re.compile(r"^[0-9]{12}$")
_HOST_LABEL = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?$")
_MAX_HOST_BYTES = 253


class _DuplicateKey(ValueError):
    pass


def _invalid(*, key: str = "REDSHIFT_CONNECTIONS_FILE") -> SkillError:
    return config_error("invalid", key=key)


def _invalid_combination(connection_name: str) -> SkillError:
    return SkillError(
        category="config",
        code="invalid_combination",
        retry_class="after_change",
        details={"connection": connection_name},
    )


def _object_without_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateKey(key)
        result[key] = value
    return result


def _reject_constant(_: str) -> None:
    raise ValueError("non-standard JSON constant")


def _read_secure_file(path_value: str, *, missing_key: str) -> str:
    path = Path(path_value)
    if (
        not path.is_absolute()
        or not path.parts
        or any(component in {"", ".", ".."} for component in path.parts[1:])
    ):
        raise _invalid()
    allowed_directory_owners = {0, os.geteuid()}
    directory_fd: int | None = None
    descriptor: int | None = None
    try:
        directory_fd = os.open("/", os.O_RDONLY | os.O_DIRECTORY)
        root_info = os.fstat(directory_fd)
        if (
            root_info.st_uid not in allowed_directory_owners
            or stat.S_IMODE(root_info.st_mode) & 0o022
        ):
            raise _invalid()
        for component in path.parts[1:-1]:
            flags = os.O_RDONLY | os.O_DIRECTORY
            if hasattr(os, "O_NOFOLLOW"):
                flags |= os.O_NOFOLLOW
            next_fd = os.open(component, flags, dir_fd=directory_fd)
            info = os.fstat(next_fd)
            if (
                info.st_uid not in allowed_directory_owners
                or stat.S_IMODE(info.st_mode) & 0o022
            ):
                os.close(next_fd)
                raise _invalid()
            os.close(directory_fd)
            directory_fd = next_fd
        flags = os.O_RDONLY
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        descriptor = os.open(path.name, flags, dir_fd=directory_fd)
        info = os.fstat(descriptor)
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_uid != os.geteuid()
            or stat.S_IMODE(info.st_mode) != 0o600
            or info.st_size > CONNECTIONS_FILE_MAX_BYTES
        ):
            raise _invalid()
        chunks: list[bytes] = []
        remaining = CONNECTIONS_FILE_MAX_BYTES + 1
        while remaining > 0:
            chunk = os.read(descriptor, min(65_536, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        raw = b"".join(chunks)
        if len(raw) > CONNECTIONS_FILE_MAX_BYTES:
            raise _invalid()
        try:
            return raw.decode("utf-8")
        except UnicodeError as exc:
            raise _invalid() from exc
    except FileNotFoundError as exc:
        raise config_error("missing", key=missing_key) from exc
    except (OSError, SkillError) as exc:
        if isinstance(exc, SkillError):
            raise
        raise _invalid() from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)
        if directory_fd is not None:
            os.close(directory_fd)


def _strict_object(value: Any, allowed: set[str]) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or set(value) - allowed:
        raise _invalid()
    return value


def _string(value: Any, *, key: str | None = None) -> str:
    if not isinstance(value, str) or not value or any(ord(char) < 32 for char in value):
        raise _invalid(key=key or "REDSHIFT_CONNECTIONS_FILE")
    return value


def _optional_string(value: Any) -> str | None:
    if value is None:
        return None
    return _string(value)


def _validate_explicit_host(value: str) -> str:
    if len(value.encode("ascii", errors="ignore")) != len(value) or len(
        value.encode("utf-8")
    ) > _MAX_HOST_BYTES:
        raise _invalid()
    if any(char.isspace() for char in value) or any(char in value for char in "/,@"):
        raise _invalid()
    try:
        ipaddress.ip_address(value)
    except ValueError:
        if ":" in value:
            raise _invalid()
        labels = value.split(".")
        if not labels or any(not _HOST_LABEL.fullmatch(label) for label in labels):
            raise _invalid()
        if len(labels) == 4 and all(label.isdigit() for label in labels):
            raise _invalid()
    return value


def _bounded_int(value: Any, *, default: int, minimum: int, maximum: int) -> int:
    selected = default if value is None else value
    if isinstance(selected, bool) or not isinstance(selected, int):
        raise _invalid()
    if selected < minimum or selected > maximum:
        raise _invalid()
    return selected


def _env_name(value: Any) -> str:
    selected = _string(value)
    if not ENV_NAME.fullmatch(selected):
        raise _invalid()
    return selected


def _parse_target(raw: Any, deployment: str) -> TargetConfig:
    value = _strict_object(
        raw,
        {"region", "clusterIdentifier", "workgroupName", "host", "port"},
    )
    region = _optional_string(value.get("region"))
    cluster = _optional_string(value.get("clusterIdentifier"))
    workgroup = _optional_string(value.get("workgroupName"))
    host = _optional_string(value.get("host"))
    if host is not None:
        host = _validate_explicit_host(host)
    port = _bounded_int(value.get("port"), default=5439, minimum=1, maximum=65_535)
    if deployment == "provisioned" and workgroup is not None:
        raise _invalid()
    if deployment == "serverless" and cluster is not None:
        raise _invalid()
    return TargetConfig(
        region=region,
        cluster_identifier=cluster,
        workgroup_name=workgroup,
        host=host,
        port=port,
    )


def _parse_authentication(raw: Any) -> AuthenticationConfig:
    value = _strict_object(
        raw,
        {"mode", "usernameEnv", "passwordEnv", "dbUser", "secretArnEnv"},
    )
    mode = _string(value.get("mode"))
    if mode not in {"password", "iam", "iam_db_user", "secret"}:
        raise _invalid()
    return AuthenticationConfig(
        mode=mode,
        username_env=_env_name(value["usernameEnv"])
        if "usernameEnv" in value
        else None,
        password_env=_env_name(value["passwordEnv"])
        if "passwordEnv" in value
        else None,
        db_user=_optional_string(value.get("dbUser")),
        secret_arn_env=_env_name(value["secretArnEnv"])
        if "secretArnEnv" in value
        else None,
    )


def _parse_aws_credentials(raw: Any) -> AwsCredentialsConfig:
    value = _strict_object(
        raw,
        {"source", "profile", "expectedAccountId", "expectedPrincipalArn"},
    )
    source = _string(value.get("source"))
    profile = _optional_string(value.get("profile"))
    account = _string(value.get("expectedAccountId"))
    principal = _optional_string(value.get("expectedPrincipalArn"))
    if source not in {"default", "profile"}:
        raise _invalid()
    if (source == "profile") != (profile is not None):
        raise _invalid()
    if not ACCOUNT_ID.fullmatch(account):
        raise _invalid()
    return AwsCredentialsConfig(
        source=source,
        profile=profile,
        expected_account_id=account,
        expected_principal_arn=principal,
    )


def _parse_tls(raw: Any) -> TlsConfig:
    value = _strict_object(raw, {"mode", "trust"})
    mode = _string(value.get("mode"))
    trust = _strict_object(value.get("trust"), {"source", "pathEnv"})
    source = _string(trust.get("source"))
    if mode != "verify-full" or source != "file":
        raise _invalid()
    return TlsConfig(
        mode=mode,
        trust=TlsTrustConfig(source=source, path_env=_env_name(trust.get("pathEnv"))),
    )


def _validate_combination(profile: ConnectionProfile) -> None:
    auth = profile.authentication
    target = profile.target
    aws = profile.aws_credentials
    if profile.transport == "data_api":
        if target.host is not None or profile.tls is not None:
            raise _invalid_combination(profile.name)
        if target.region is None:
            raise _invalid_combination(profile.name)
        if profile.deployment == "provisioned" and target.cluster_identifier is None:
            raise _invalid_combination(profile.name)
        if profile.deployment == "serverless" and target.workgroup_name is None:
            raise _invalid_combination(profile.name)
        if auth.mode not in {"iam", "iam_db_user", "secret"} or aws is None:
            raise _invalid_combination(profile.name)
        if auth.mode == "iam_db_user" and (
            profile.deployment != "provisioned" or auth.db_user is None
        ):
            raise _invalid_combination(profile.name)
    else:
        if profile.tls is None:
            raise _invalid_combination(profile.name)
        if auth.mode == "iam_db_user":
            raise _invalid_combination(profile.name)
        if auth.mode == "password":
            if (
                auth.username_env is None
                or auth.password_env is None
                or target.host is None
                or aws is not None
            ):
                raise _invalid_combination(profile.name)
        elif auth.mode in {"iam", "secret"}:
            if aws is None or target.region is None:
                raise _invalid_combination(profile.name)
            requires_discovery_target = auth.mode == "iam" or target.host is None
            if requires_discovery_target:
                if (
                    profile.deployment == "provisioned"
                    and target.cluster_identifier is None
                ):
                    raise _invalid_combination(profile.name)
                if (
                    profile.deployment == "serverless"
                    and target.workgroup_name is None
                ):
                    raise _invalid_combination(profile.name)
        else:
            raise _invalid_combination(profile.name)
    if auth.mode == "secret" and auth.secret_arn_env is None:
        raise _invalid_combination(profile.name)
    if auth.mode != "secret" and auth.secret_arn_env is not None:
        raise _invalid_combination(profile.name)
    if auth.mode != "iam_db_user" and auth.db_user is not None:
        raise _invalid_combination(profile.name)
    if auth.mode != "password" and (
        auth.username_env is not None or auth.password_env is not None
    ):
        raise _invalid_combination(profile.name)


def _parse_profile(name: str, raw: Any) -> ConnectionProfile:
    if not CONNECTION_NAME.fullmatch(name):
        raise _invalid()
    value = _strict_object(
        raw,
        {
            "deployment",
            "transport",
            "database",
            "target",
            "authentication",
            "awsCredentials",
            "tls",
            "connectTimeoutSeconds",
            "statementTimeoutMs",
            "sessionKeepAliveSeconds",
            "awsApiTimeoutSeconds",
        },
    )
    deployment = _string(value.get("deployment"))
    transport = _string(value.get("transport"))
    if deployment not in {"provisioned", "serverless"} or transport not in {
        "wire",
        "data_api",
    }:
        raise _invalid_combination(name)
    raw_target = value.get("target")
    if (
        transport == "data_api"
        and isinstance(raw_target, Mapping)
        and ({"host", "port"} & set(raw_target))
    ):
        raise _invalid_combination(name)
    profile = ConnectionProfile(
        name=name,
        deployment=deployment,
        transport=transport,
        database=_string(value.get("database")),
        target=_parse_target(raw_target, deployment),
        authentication=_parse_authentication(value.get("authentication")),
        aws_credentials=_parse_aws_credentials(value["awsCredentials"])
        if "awsCredentials" in value
        else None,
        tls=_parse_tls(value["tls"]) if "tls" in value else None,
        connect_timeout_seconds=_bounded_int(
            value.get("connectTimeoutSeconds"), default=10, minimum=1, maximum=60
        ),
        statement_timeout_ms=_bounded_int(
            value.get("statementTimeoutMs"),
            default=30_000,
            minimum=1,
            maximum=86_000_000,
        ),
        session_keepalive_seconds=_bounded_int(
            value.get("sessionKeepAliveSeconds"),
            default=300,
            minimum=1,
            maximum=86_400,
        ),
        aws_api_timeout_seconds=_bounded_int(
            value.get("awsApiTimeoutSeconds"), default=10, minimum=1, maximum=60
        ),
    )
    _validate_combination(profile)
    return profile


def _parse_named_registry(raw: str) -> ConnectionRegistry:
    try:
        payload = json.loads(
            raw,
            object_pairs_hook=_object_without_duplicates,
            parse_constant=_reject_constant,
        )
    except (_DuplicateKey, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise _invalid() from exc
    value = _strict_object(
        payload,
        {"schemaVersion", "defaultConnection", "catalogConnection", "connections"},
    )
    if value.get("schemaVersion") != 1:
        raise _invalid()
    default = _string(value.get("defaultConnection"))
    catalog = _optional_string(value.get("catalogConnection"))
    raw_connections = value.get("connections")
    if not isinstance(raw_connections, Mapping) or not raw_connections:
        raise _invalid()
    connections = {
        _string(name): _parse_profile(_string(name), profile)
        for name, profile in raw_connections.items()
    }
    if default not in connections or (catalog is not None and catalog not in connections):
        raise _invalid()
    return ConnectionRegistry.create(
        default_connection=default,
        catalog_connection=catalog,
        connections=connections,
    )


def load_connection_registry(environ: Mapping[str, str]) -> ConnectionRegistry:
    override = environ.get("REDSHIFT_CONNECTIONS_FILE")
    if override:
        path = override
        missing_key = "REDSHIFT_CONNECTIONS_FILE"
    else:
        path = str(Path(__file__).resolve().parents[3] / "connections.json")
        missing_key = "connections.json"
    return _parse_named_registry(_read_secure_file(path, missing_key=missing_key))
