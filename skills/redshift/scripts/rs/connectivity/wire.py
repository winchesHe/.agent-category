"""Wire Adapter preserving V2 query and artifact behavior."""
from __future__ import annotations

import os
import stat
import importlib.util
import sys
from collections.abc import Mapping
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from .. import connection
from ..catalog.redshift import (
    RedshiftCatalogSource,
    RedshiftDescribeSource,
    RedshiftLiveMetadataSource,
)
from ..connection import ConnectionConfig
from ..errors import SkillError, config_error
from ..query.execute import execute_query, open_query_stream
from ..query.explain import execute_explain
from .aws import AwsResolver
from .doctor import probe_metadata_capabilities, run_adapter_doctor
from .model import ConnectionProfile


CA_FILE_MAX_BYTES = 1_048_576


def _required(environ: Mapping[str, str], key: str) -> str:
    value = environ.get(key)
    if not value:
        raise config_error("missing", key=key)
    return value


def _validate_ca_path(value: str) -> str:
    path = Path(value)
    if sys.platform == "darwin" and path == Path("/etc/ssl/cert.pem"):
        # macOS exposes the Apple-managed bundle through /etc, which is a system
        # symlink. Validate and pass the canonical file without allowing any
        # other symlink path through this trust boundary.
        path = Path("/private/etc/ssl/cert.pem")
    if (
        not path.is_absolute()
        or not path.parts
        or any(component in {"", ".", ".."} for component in path.parts[1:])
    ):
        raise config_error("invalid", key="tls.trust.pathEnv")
    allowed_owners = {0, os.geteuid()}
    directory_fd: int | None = None
    try:
        directory_fd = os.open("/", os.O_RDONLY | os.O_DIRECTORY)
        root_info = os.fstat(directory_fd)
        if root_info.st_uid not in allowed_owners or stat.S_IMODE(root_info.st_mode) & 0o022:
            raise config_error("invalid", key="tls.trust.pathEnv")
        for component in path.parts[1:-1]:
            flags = os.O_RDONLY | os.O_DIRECTORY
            if hasattr(os, "O_NOFOLLOW"):
                flags |= os.O_NOFOLLOW
            next_fd = os.open(component, flags, dir_fd=directory_fd)
            info = os.fstat(next_fd)
            if info.st_uid not in allowed_owners or stat.S_IMODE(info.st_mode) & 0o022:
                os.close(next_fd)
                raise config_error("invalid", key="tls.trust.pathEnv")
            os.close(directory_fd)
            directory_fd = next_fd
        flags = os.O_RDONLY
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        file_fd = os.open(path.name, flags, dir_fd=directory_fd)
        try:
            info = os.fstat(file_fd)
            if (
                not stat.S_ISREG(info.st_mode)
                or info.st_uid not in allowed_owners
                or stat.S_IMODE(info.st_mode) & 0o022
                or info.st_size > CA_FILE_MAX_BYTES
            ):
                raise config_error("invalid", key="tls.trust.pathEnv")
        finally:
            os.close(file_fd)
    except (OSError, SkillError) as exc:
        if isinstance(exc, SkillError):
            raise
        raise config_error("invalid", key="tls.trust.pathEnv") from exc
    finally:
        if directory_fd is not None:
            os.close(directory_fd)
    return str(path)


class WireAdapter:
    def __init__(
        self,
        profile: ConnectionProfile,
        environ: Mapping[str, str],
        *,
        aws_resolver_factory: Any = AwsResolver,
        psycopg2_available: Any = lambda: importlib.util.find_spec("psycopg2")
        is not None,
        boto3_available: Any = lambda: importlib.util.find_spec("boto3") is not None,
    ) -> None:
        self.profile = profile
        self._environ = dict(environ)
        self._aws_resolver_factory = aws_resolver_factory
        self._psycopg2_available = psycopg2_available
        self._boto3_available = boto3_available

    def _connection_config(self, database: str, timeout: int) -> ConnectionConfig:
        auth = self.profile.authentication
        target = self.profile.target
        if auth.mode == "password":
            username = _required(self._environ, auth.username_env or "")
            password = _required(self._environ, auth.password_env or "")
            host = target.host
            port = target.port
        else:
            resolved = self._aws_resolver_factory(
                self.profile, self._environ
            ).resolve_wire(self.profile, database)
            host = resolved.host
            port = resolved.port
            username = resolved.username
            password = resolved.password
        if host is None or self.profile.tls is None:
            raise SkillError(
                category="config",
                code="invalid_combination",
                retry_class="after_change",
                details={"connection": self.profile.name},
            )
        sslrootcert = None
        sslrootcert = _validate_ca_path(
            _required(self._environ, self.profile.tls.trust.path_env)
        )
        return ConnectionConfig(
            host=host,
            port=port,
            username=username,
            password=password,
            database=database,
            sslmode=self.profile.tls.mode,
            connect_timeout=self.profile.connect_timeout_seconds,
            statement_timeout_ms=timeout,
            sslrootcert=sslrootcert,
        )

    @contextmanager
    def _connect(self, *, database: str, statement_timeout_ms: int) -> Iterator[Any]:
        config = self._connection_config(database, statement_timeout_ms)
        with connection.connect_config(config) as conn:
            yield conn

    @contextmanager
    def _connect_streaming(
        self, *, database: str, statement_timeout_ms: int
    ) -> Iterator[Any]:
        config = self._connection_config(database, statement_timeout_ms)
        with connection.connect_streaming_config(config) as conn:
            yield conn

    def query(self, **kwargs: Any):
        return execute_query(**kwargs, connection_factory=self._connect)

    def stream_query(self, **kwargs: Any):
        return open_query_stream(**kwargs, connection_factory=self._connect_streaming)

    def explain(self, **kwargs: Any):
        return execute_explain(**kwargs, connection_factory=self._connect)

    def catalog_source(self, database: str, timeout: int) -> RedshiftCatalogSource:
        return RedshiftCatalogSource(
            control_database=database,
            statement_timeout_ms=timeout,
            connection_factory=self._connect,
        )

    def describe_source(self, database: str, timeout: int) -> RedshiftDescribeSource:
        return RedshiftDescribeSource(
            control_database=database,
            statement_timeout_ms=timeout,
            connection_factory=self._connect,
        )

    def live_metadata_source(
        self, database: str, timeout: int
    ) -> RedshiftLiveMetadataSource:
        return RedshiftLiveMetadataSource(
            control_database=database,
            statement_timeout_ms=timeout,
            connection_factory=self._connect,
        )

    def preflight(self, *, connect_live: bool):
        def static_config_check() -> None:
            if self.profile.tls is None:
                raise SkillError(
                    "config",
                    "invalid_combination",
                    "after_change",
                    details={"connection": self.profile.name},
                )
            _validate_ca_path(
                _required(self._environ, self.profile.tls.trust.path_env)
            )
            auth = self.profile.authentication
            if auth.mode == "password":
                _required(self._environ, auth.username_env or "")
                _required(self._environ, auth.password_env or "")
            elif auth.mode == "secret":
                _required(self._environ, auth.secret_arn_env or "")

        def live_probe() -> Mapping[str, Any]:
            database = self.profile.database
            timeout = self.profile.statement_timeout_ms
            try:
                with self._connect(
                    database=database,
                    statement_timeout_ms=timeout,
                ) as conn:
                    with conn.cursor() as cursor:
                        cursor.execute("SHOW transaction_read_only")
                        row = cursor.fetchone()
            except SkillError as exc:
                return {
                    "connectivity": "unavailable",
                    "readonly": False,
                    "code": exc.full_code,
                    "retryClass": exc.retry_class,
                    **({"suggestion": exc.suggestion} if exc.suggestion else {}),
                    "diagnostics": dict(exc.diagnostics),
                }
            capabilities = {
                "connectivity": "available",
                "readonly": bool(row)
                and str(row[0]).casefold() in {"on", "true", "t", "1"},
                "showDatabases": "not_checked",
                "crossDatabaseRead": "not_checked",
            }
            if not capabilities["readonly"]:
                return capabilities
            return probe_metadata_capabilities(
                capabilities,
                database=database,
                source=self.catalog_source(database, timeout),
                execute_query=self.query,
                statement_timeout_ms=timeout,
            )

        return run_adapter_doctor(
            environ=self._environ,
            dependency_name="psycopg2",
            dependency_available=self._psycopg2_available,
            additional_dependencies=(
                (("boto3", self._boto3_available),)
                if self.profile.authentication.mode in {"iam", "secret"}
                else ()
            ),
            static_config_check=static_config_check,
            connect_live=connect_live,
            live_probe=live_probe,
        )
