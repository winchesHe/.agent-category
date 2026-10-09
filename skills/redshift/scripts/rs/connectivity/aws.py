"""AWS identity, target and credential resolution without public topology leakage."""
from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

from ..errors import SkillError, config_error
from .model import ConnectionProfile


@dataclass(frozen=True)
class ResolvedWireAuth:
    host: str
    port: int
    username: str
    password: str = field(repr=False)


SessionFactory = Callable[..., Any]
ClientConfigFactory = Callable[[int], Any]


def _default_session_factory(*, profile_name: str | None, region_name: str) -> Any:
    try:
        import boto3
    except ImportError as exc:
        raise config_error("dependency_missing", key="boto3") from exc
    return boto3.Session(profile_name=profile_name, region_name=region_name)


def _default_client_config(timeout: int) -> Any:
    try:
        from botocore.config import Config
    except ImportError as exc:
        raise config_error("dependency_missing", key="boto3") from exc
    return Config(
        connect_timeout=timeout,
        read_timeout=timeout,
        retries={"total_max_attempts": 3, "mode": "standard"},
        ignore_configured_endpoint_urls=True,
    )


def map_aws_error(exc: BaseException, *, stage: str) -> SkillError:
    name = type(exc).__name__
    response = getattr(exc, "response", None)
    error = response.get("Error", {}) if isinstance(response, Mapping) else {}
    code = error.get("Code") if isinstance(error, Mapping) else None
    http = (
        response.get("ResponseMetadata", {}).get("HTTPStatusCode")
        if isinstance(response, Mapping)
        and isinstance(response.get("ResponseMetadata"), Mapping)
        else None
    )
    if name in {
        "NoCredentialsError",
        "PartialCredentialsError",
        "CredentialRetrievalError",
    } or code in {"ExpiredToken", "InvalidClientTokenId", "UnrecognizedClientException"}:
        return SkillError(
            "connection", "aws_credentials_unavailable", "after_change", details={"stage": stage}
        )
    if name in {"SSOTokenLoadError", "UnauthorizedSSOTokenError"}:
        return SkillError(
            "connection", "auth_interaction_required", "after_change", details={"stage": stage}
        )
    if code in {
        "AccessDenied",
        "AccessDeniedException",
        "UnauthorizedException",
        "UnauthorizedOperation",
    } or http in {401, 403}:
        return SkillError(
            "connection", "permission_denied", "after_change", details={"stage": stage}
        )
    if code in {
        "ResourceNotFoundException",
        "ClusterNotFound",
        "ClusterNotFoundFault",
        "WorkgroupNotFoundException",
    }:
        stable = "secret_unavailable" if stage == "secret" else "target_not_found"
        return SkillError("connection", stable, "after_change", details={"stage": stage})
    if name in {
        "EndpointConnectionError",
        "ConnectTimeoutError",
        "ReadTimeoutError",
    } or (isinstance(http, int) and http >= 500):
        return SkillError(
            "connection", "endpoint_unreachable", "transient", details={"stage": stage}
        )
    return SkillError("connection", "unavailable", "transient", details={"stage": stage})


def aws_error_code(exc: BaseException) -> str | None:
    response = getattr(exc, "response", None)
    error = response.get("Error", {}) if isinstance(response, Mapping) else {}
    code = error.get("Code") if isinstance(error, Mapping) else None
    return code if isinstance(code, str) else None


def _required_string(value: Any, *, stage: str) -> str:
    if not isinstance(value, str) or not value:
        code = "secret_unavailable" if stage == "secret" else "target_not_found"
        raise SkillError("connection", code, "after_change", details={"stage": stage})
    return value


class AwsResolver:
    def __init__(
        self,
        profile: ConnectionProfile,
        environ: Mapping[str, str],
        *,
        session_factory: SessionFactory = _default_session_factory,
        client_config_factory: ClientConfigFactory | None = None,
    ) -> None:
        if profile.aws_credentials is None or profile.target.region is None:
            raise SkillError(
                "config",
                "invalid_combination",
                "after_change",
                details={"connection": profile.name},
            )
        self.profile = profile
        self._environ = dict(environ)
        self._session_factory = session_factory
        self._client_config_factory = (
            client_config_factory
            if client_config_factory is not None
            else (
                _default_client_config
                if session_factory is _default_session_factory
                else lambda _timeout: None
            )
        )
        self._session: Any | None = None
        self._clients: dict[str, Any] = {}
        self._identity_verified = False

    def _session_value(self) -> Any:
        if self._session is None:
            credentials = self.profile.aws_credentials
            try:
                self._session = self._session_factory(
                    profile_name=credentials.profile,
                    region_name=self.profile.target.region,
                )
            except SkillError:
                raise
            except Exception as exc:
                raise map_aws_error(exc, stage="credentials") from exc
        return self._session

    def client(self, service: str) -> Any:
        if service not in self._clients:
            try:
                config = self._client_config_factory(
                    self.profile.aws_api_timeout_seconds
                )
                if config is None:
                    self._clients[service] = self._session_value().client(service)
                else:
                    self._clients[service] = self._session_value().client(
                        service,
                        config=config,
                    )
            except SkillError:
                raise
            except Exception as exc:
                raise map_aws_error(exc, stage="credentials") from exc
        return self._clients[service]

    def verify_identity(self) -> None:
        if self._identity_verified:
            return
        try:
            identity = self.client("sts").get_caller_identity()
        except SkillError:
            raise
        except Exception as exc:
            raise map_aws_error(exc, stage="identity") from exc
        credentials = self.profile.aws_credentials
        account = identity.get("Account") if isinstance(identity, Mapping) else None
        arn = identity.get("Arn") if isinstance(identity, Mapping) else None
        if account != credentials.expected_account_id or (
            credentials.expected_principal_arn is not None
            and arn != credentials.expected_principal_arn
        ):
            raise SkillError(
                "connection", "auth_failed", "after_change", details={"stage": "identity"}
            )
        self._identity_verified = True

    def _endpoint(self) -> tuple[str, int]:
        target = self.profile.target
        if target.host is not None:
            return target.host, target.port
        self.verify_identity()
        try:
            if self.profile.deployment == "provisioned":
                response = self.client("redshift").describe_clusters(
                    ClusterIdentifier=target.cluster_identifier
                )
                clusters = response.get("Clusters", [])
                endpoint = clusters[0].get("Endpoint", {}) if len(clusters) == 1 else {}
            else:
                response = self.client("redshift-serverless").get_workgroup(
                    workgroupName=target.workgroup_name
                )
                workgroup = response.get("workgroup", {})
                endpoint = workgroup.get("endpoint", {}) if isinstance(workgroup, Mapping) else {}
        except SkillError:
            raise
        except Exception as exc:
            raise map_aws_error(exc, stage="target") from exc
        host = _required_string(endpoint.get("Address") or endpoint.get("address"), stage="target")
        port = endpoint.get("Port") or endpoint.get("port")
        if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65_535:
            raise SkillError(
                "connection", "target_not_found", "after_change", details={"stage": "target"}
            )
        return host, port

    def _iam_credentials(self, database: str) -> tuple[str, str]:
        target = self.profile.target
        self.verify_identity()
        try:
            if self.profile.deployment == "provisioned":
                response = self.client("redshift").get_cluster_credentials_with_iam(
                    DbName=database,
                    ClusterIdentifier=target.cluster_identifier,
                    DurationSeconds=900,
                )
            else:
                response = self.client("redshift-serverless").get_credentials(
                    workgroupName=target.workgroup_name,
                    dbName=database,
                    durationSeconds=900,
                )
        except SkillError:
            raise
        except Exception as exc:
            raise map_aws_error(exc, stage="credentials") from exc
        return (
            _required_string(response.get("DbUser") or response.get("dbUser"), stage="credentials"),
            _required_string(
                response.get("DbPassword") or response.get("dbPassword"),
                stage="credentials",
            ),
        )

    def secret_arn(self) -> str:
        key = self.profile.authentication.secret_arn_env
        value = self._environ.get(key or "")
        if not value:
            raise config_error("missing", key=key or "secretArnEnv")
        return value

    def _secret_credentials(self) -> tuple[str, str]:
        self.verify_identity()
        try:
            response = self.client("secretsmanager").get_secret_value(
                SecretId=self.secret_arn()
            )
        except SkillError:
            raise
        except Exception as exc:
            raise map_aws_error(exc, stage="secret") from exc
        raw = response.get("SecretString") if isinstance(response, Mapping) else None
        try:
            def unique_object(items: list[tuple[str, Any]]) -> dict[str, Any]:
                result: dict[str, Any] = {}
                for key, value in items:
                    if key in result:
                        raise ValueError("duplicate secret field")
                    result[key] = value
                return result

            payload = (
                json.loads(raw, object_pairs_hook=unique_object)
                if isinstance(raw, str)
                else None
            )
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise SkillError(
                "connection",
                "secret_unavailable",
                "after_change",
                details={"stage": "secret"},
            ) from exc
        if not isinstance(payload, Mapping):
            raise SkillError(
                "connection", "secret_unavailable", "after_change", details={"stage": "secret"}
            )
        return (
            _required_string(payload.get("username"), stage="secret"),
            _required_string(payload.get("password"), stage="secret"),
        )

    def resolve_wire(self, profile: ConnectionProfile, database: str) -> ResolvedWireAuth:
        if profile is not self.profile:
            raise SkillError("internal", "unexpected", "never")
        host, port = self._endpoint()
        if profile.authentication.mode == "iam":
            username, password = self._iam_credentials(database)
        elif profile.authentication.mode == "secret":
            username, password = self._secret_credentials()
        else:
            raise SkillError(
                "capability", "auth_mode_unavailable", "after_change"
            )
        return ResolvedWireAuth(
            host=host,
            port=port,
            username=username,
            password=password,
        )

    def data_api_client(self) -> Any:
        self.verify_identity()
        return self.client("redshift-data")

    def data_api_request(self, database: str) -> dict[str, Any]:
        self.verify_identity()
        target = self.profile.target
        request: dict[str, Any] = {"Database": database}
        if self.profile.deployment == "provisioned":
            request["ClusterIdentifier"] = target.cluster_identifier
        else:
            request["WorkgroupName"] = target.workgroup_name
        auth = self.profile.authentication
        if auth.mode == "iam_db_user":
            request["DbUser"] = auth.db_user
        elif auth.mode == "secret":
            request["SecretArn"] = self.secret_arn()
        return request
