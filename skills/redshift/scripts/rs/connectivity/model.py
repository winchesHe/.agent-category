"""Typed connection profiles shared by connectivity Adapters."""
from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping


@dataclass(frozen=True)
class TargetConfig:
    region: str | None = None
    cluster_identifier: str | None = None
    workgroup_name: str | None = None
    host: str | None = None
    port: int = 5439


@dataclass(frozen=True)
class AuthenticationConfig:
    mode: str
    username_env: str | None = None
    password_env: str | None = None
    db_user: str | None = None
    secret_arn_env: str | None = None


@dataclass(frozen=True)
class AwsCredentialsConfig:
    source: str
    expected_account_id: str
    profile: str | None = None
    expected_principal_arn: str | None = None


@dataclass(frozen=True)
class TlsTrustConfig:
    source: str
    path_env: str


@dataclass(frozen=True)
class TlsConfig:
    mode: str
    trust: TlsTrustConfig


@dataclass(frozen=True)
class ConnectionProfile:
    name: str
    deployment: str
    transport: str
    database: str
    target: TargetConfig
    authentication: AuthenticationConfig
    aws_credentials: AwsCredentialsConfig | None
    tls: TlsConfig | None
    connect_timeout_seconds: int = 10
    statement_timeout_ms: int = 30_000
    session_keepalive_seconds: int = 300
    aws_api_timeout_seconds: int = 10


@dataclass(frozen=True)
class ConnectionRegistry:
    default_connection: str
    catalog_connection: str | None
    connections: Mapping[str, ConnectionProfile]

    @classmethod
    def create(
        cls,
        *,
        default_connection: str,
        catalog_connection: str | None,
        connections: Mapping[str, ConnectionProfile],
    ) -> "ConnectionRegistry":
        return cls(
            default_connection=default_connection,
            catalog_connection=catalog_connection,
            connections=MappingProxyType(dict(connections)),
        )

    def resolve(self, name: str | None) -> ConnectionProfile:
        from ..errors import SkillError

        selected = self.default_connection if name is None else name
        profile = self.connections.get(selected)
        if profile is None:
            raise SkillError(
                category="config",
                code="connection_not_found",
                retry_class="after_change",
                details={"connection": selected},
            )
        return profile
