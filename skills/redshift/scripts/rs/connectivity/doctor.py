"""Transport-neutral capability checks for one bound connection Adapter."""
from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..catalog.snapshot import load_catalog
from ..errors import SkillError
from ..models import CommandResult
from ..output import validate_output_target


def _catalog_path() -> Path:
    return Path(__file__).resolve().parents[3] / "references" / "catalog.jsonl"


def _catalog_check(
    path: str | Path | None = None,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    selected = Path(path) if path is not None else _catalog_path()
    try:
        catalog = load_catalog(selected)
        current = now if now is not None else datetime.now(timezone.utc)
        freshness = catalog.freshness(current)
    except SkillError as exc:
        return {"status": "unavailable", "code": exc.full_code}
    return {
        "status": "available",
        "schemaVersion": catalog.meta.schema_version,
        "generatedAt": catalog.meta.generated_at.isoformat().replace("+00:00", "Z"),
        "freshness": freshness,
        "coverageStatus": catalog.meta.coverage.status,
    }


def _quote_identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def _cross_database_fixture(
    source: Any,
    databases: tuple[Mapping[str, Any], ...],
    control_database: str,
) -> tuple[str, str, str] | None:
    first_error: SkillError | None = None
    inspected_candidate = False
    candidates = (
        item
        for item in databases
        if item["name"] != control_database
        and item["databaseType"] in {"local", "datashare"}
    )
    for item in list(candidates)[:5]:
        database = str(item["name"])
        try:
            schemas = tuple(source.show_schemas(database))[:5]
            relations_by_schema = source.show_relations(database)
        except SkillError as exc:
            if first_error is None:
                first_error = exc
            continue
        inspected_candidate = True
        for schema in schemas:
            relations = tuple(relations_by_schema.get(schema, ()))
            if relations:
                return database, schema, str(relations[0]["name"])
    if not inspected_candidate and first_error is not None:
        raise first_error
    return None


def probe_metadata_capabilities(
    capabilities: Mapping[str, Any],
    *,
    database: str,
    source: Any,
    execute_query: Callable[..., Any],
    statement_timeout_ms: int,
) -> dict[str, Any]:
    """Add bounded metadata and cross-database evidence to a live probe."""

    result = dict(capabilities)
    try:
        databases = tuple(source.show_databases())
        result["showDatabases"] = "available"
    except SkillError as exc:
        result["showDatabases"] = "unavailable"
        result["showDatabasesCode"] = exc.full_code
        return result
    try:
        fixture = _cross_database_fixture(source, databases, database)
    except SkillError as exc:
        result["crossDatabaseRead"] = "unavailable"
        result["crossDatabaseReadCode"] = exc.full_code
        return result
    if fixture is None:
        result["crossDatabaseRead"] = "not_checked"
        result["crossDatabaseReadCode"] = "capability.no_cross_database_fixture"
        return result
    sql = "SELECT 1 FROM " + ".".join(_quote_identifier(part) for part in fixture) + " LIMIT 1"
    try:
        execute_query(
            database=database,
            sql=sql,
            params={},
            limit=1,
            statement_timeout_ms=statement_timeout_ms,
        )
    except SkillError as exc:
        result["crossDatabaseRead"] = "unavailable"
        result["crossDatabaseReadCode"] = exc.full_code
    else:
        result["crossDatabaseRead"] = "available"
    return result


def _artifact_check(environ: Mapping[str, str]) -> dict[str, Any]:
    configured = environ.get("REDSHIFT_OUTPUT_DIR")
    if not configured:
        return {
            "name": "artifact_export",
            "status": "unavailable",
            "code": "config.missing",
            "optional": True,
        }
    try:
        validate_output_target(configured, "doctor-check")
    except SkillError as exc:
        return {
            "name": "artifact_export",
            "status": "unavailable",
            "code": exc.full_code,
            "optional": True,
        }
    return {"name": "artifact_export", "status": "available", "optional": True}


def run_adapter_doctor(
    *,
    environ: Mapping[str, str],
    dependency_name: str,
    dependency_available: Callable[[], bool],
    additional_dependencies: tuple[tuple[str, Callable[[], bool]], ...] = (),
    static_config_check: Callable[[], None],
    connect_live: bool,
    live_probe: Callable[[], Mapping[str, Any]],
) -> CommandResult:
    dependencies = ((dependency_name, dependency_available), *additional_dependencies)
    dependency_results = tuple((name, check()) for name, check in dependencies)
    dependencies_ok = all(available for _name, available in dependency_results)
    checks: list[dict[str, Any]] = [
        {
            "name": name,
            "status": "available" if available else "unavailable",
            **({} if available else {"code": "config.dependency_missing"}),
        }
        for name, available in dependency_results
    ]
    config_ok = False
    config_check: dict[str, Any] = {"name": "connection_config", "status": "unavailable"}
    try:
        static_config_check()
    except SkillError as exc:
        config_check["code"] = exc.full_code
        key = exc.details.get("key")
        if isinstance(key, str):
            config_check["invalidKey"] = key
    else:
        config_ok = True
        config_check["status"] = "available"
    checks.append(config_check)
    catalog = dict(_catalog_check())
    catalog["name"] = "catalog"
    checks.append(catalog)
    artifact = _artifact_check(environ)
    checks.append(artifact)
    capabilities: dict[str, Any] = {}
    diagnostics: dict[str, Any] = {}
    live_available = False
    if connect_live and dependencies_ok and config_ok:
        capabilities = dict(live_probe())
        diagnostics = dict(capabilities.pop("diagnostics", {}))
        live_available = capabilities.get("connectivity") == "available" and (
            capabilities.get("readonly") is True
        )
        live_check: dict[str, Any] = {
            "name": "live_capabilities",
            "status": "available" if live_available else "unavailable",
        }
        if capabilities.get("connectivity") == "available" and not live_available:
            live_check["code"] = "capability.readonly_unavailable"
        elif not live_available and isinstance(capabilities.get("code"), str):
            live_check["code"] = capabilities["code"]
        checks.append(live_check)
    query_available = dependencies_ok and config_ok and connect_live and live_available
    return CommandResult(
        diagnostics=diagnostics,
        data={
            "skillAvailable": query_available,
            "jsonQueryAvailable": query_available,
            "catalogSearchAvailable": catalog.get("status") == "available",
            "artifactExportAvailable": artifact["status"] == "available",
            "checks": checks,
            "capabilities": capabilities,
        }
    )
