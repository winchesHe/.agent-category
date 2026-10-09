"""One application dependency for all live Redshift operations."""
from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any, Protocol

from .model import ConnectionProfile, ConnectionRegistry
from .registry import load_connection_registry
from ..errors import SkillError, config_error
from ..models import CommandResult


AdapterFactory = Callable[[ConnectionProfile, Mapping[str, str]], Any]
RegistryLoader = Callable[[Mapping[str, str]], ConnectionRegistry]


class BoundConnectivityPort(Protocol):
    connection_name: str
    default_database: str
    default_statement_timeout_ms: int
    owns_catalog: bool

    def query(self, **kwargs: Any) -> Any: ...
    def stream_query(self, **kwargs: Any) -> Any: ...
    def explain(self, **kwargs: Any) -> Any: ...
    def catalog_source(self, database: str, timeout: int) -> Any: ...
    def describe_source(self, database: str, timeout: int) -> Any: ...
    def live_metadata_source(self, database: str, timeout: int) -> Any: ...
    def preflight(self, *, connect_live: bool) -> Any: ...
    def public_meta(self, database: str | None) -> dict[str, str]: ...


class ConnectivityPort(Protocol):
    def bind(self, connection_name: str | None) -> BoundConnectivityPort: ...
    def bind_catalog(self) -> BoundConnectivityPort: ...
    def list_connections(self) -> CommandResult: ...
    def preflight(
        self,
        connection_name: str | None,
        *,
        connect_live: bool,
    ) -> CommandResult: ...


def _wire_adapter(profile: ConnectionProfile, environ: Mapping[str, str]) -> Any:
    from .wire import WireAdapter

    return WireAdapter(profile, environ)


def _data_api_adapter(profile: ConnectionProfile, environ: Mapping[str, str]) -> Any:
    from .data_api import DataApiAdapter

    return DataApiAdapter(profile, environ)


class BoundConnectivity:
    """One resolved profile and its selected Adapter for one invocation."""

    def __init__(
        self,
        profile: ConnectionProfile,
        adapter: Any,
        environ: Mapping[str, str],
        *,
        owns_catalog: bool,
    ) -> None:
        self.profile = profile
        self._adapter = adapter
        self._environ = environ
        self.connection_name = profile.name
        self.owns_catalog = owns_catalog

    @property
    def default_database(self) -> str:
        return self.profile.database

    @property
    def default_statement_timeout_ms(self) -> int:
        return self.profile.statement_timeout_ms

    def query(self, **kwargs: Any):
        return self._adapter.query(**kwargs)

    def stream_query(self, **kwargs: Any):
        return self._adapter.stream_query(**kwargs)

    def explain(self, **kwargs: Any):
        return self._adapter.explain(**kwargs)

    def catalog_source(self, database: str, timeout: int):
        return self._adapter.catalog_source(database, timeout)

    def describe_source(self, database: str, timeout: int):
        return self._adapter.describe_source(database, timeout)

    def live_metadata_source(self, database: str, timeout: int):
        return self._adapter.live_metadata_source(database, timeout)

    def preflight(self, *, connect_live: bool):
        return self._adapter.preflight(connect_live=connect_live)

    def public_meta(self, database: str | None) -> dict[str, str]:
        result = {
            "connectionName": self.profile.name,
            "deployment": self.profile.deployment,
            "transport": self.profile.transport,
            "authMode": self.profile.authentication.mode,
        }
        if database is not None:
            result["connectionDatabase"] = database
        return result


class RedshiftConnectivity:
    """Resolve one connection profile and instantiate only its declared Adapter."""

    def __init__(
        self,
        environ: Mapping[str, str],
        *,
        registry_loader: RegistryLoader = load_connection_registry,
        wire_adapter_factory: AdapterFactory = _wire_adapter,
        data_api_adapter_factory: AdapterFactory = _data_api_adapter,
    ) -> None:
        self._environ = dict(environ)
        self._registry_loader = registry_loader
        self._wire_adapter_factory = wire_adapter_factory
        self._data_api_adapter_factory = data_api_adapter_factory
        self._registry: ConnectionRegistry | None = None

    def _load_registry(self) -> ConnectionRegistry:
        if self._registry is None:
            self._registry = self._registry_loader(self._environ)
        return self._registry

    def bind(self, connection_name: str | None) -> BoundConnectivity:
        registry = self._load_registry()
        profile = registry.resolve(connection_name)
        factory = (
            self._wire_adapter_factory
            if profile.transport == "wire"
            else self._data_api_adapter_factory
        )
        return BoundConnectivity(
            profile,
            factory(profile, self._environ),
            self._environ,
            owns_catalog=registry.catalog_connection == profile.name,
        )

    def bind_catalog(self) -> BoundConnectivity:
        catalog_connection = self._load_registry().catalog_connection
        if catalog_connection is None:
            raise config_error("missing", key="catalogConnection")
        return self.bind(catalog_connection)

    def list_connections(self) -> CommandResult:
        registry = self._load_registry()
        connections = [
            {
                "name": profile.name,
                "deployment": profile.deployment,
                "transport": profile.transport,
                "database": profile.database,
                "authMode": profile.authentication.mode,
                "default": profile.name == registry.default_connection,
                "catalog": profile.name == registry.catalog_connection,
            }
            for profile in sorted(
                registry.connections.values(), key=lambda item: item.name
            )
        ]
        return CommandResult(data={"connections": connections})

    def preflight(
        self,
        connection_name: str | None,
        *,
        connect_live: bool,
    ) -> CommandResult:
        bound = self.bind(connection_name)
        result = bound.preflight(connect_live=connect_live)
        return CommandResult(
            data=result.data,
            meta={**result.meta, **bound.public_meta(bound.default_database)},
            diagnostics=result.diagnostics,
        )
