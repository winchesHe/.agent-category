"""Build and atomically publish the single-file local catalog."""
from __future__ import annotations

import json
import os
import re
import tempfile
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping, Protocol, Sequence

from ..errors import SkillError
from .enrichment import DomainMap, load_domain_map
from .identifiers import render_object_name
from .snapshot import Catalog, _catalog_from_records, load_catalog


class CatalogMetadataSource(Protocol):
    """Bounded metadata seam used by the offline builder and live adapter."""

    def show_databases(self) -> Sequence[Mapping[str, Any]]: ...

    def show_schemas(self, database: str) -> Sequence[str]: ...

    def show_relations(self, database: str) -> Mapping[str, Sequence[Mapping[str, Any]]]: ...

    def show_columns(self, database: str) -> Mapping[str, Sequence[Mapping[str, Any]]]: ...


_TECHNICAL_SCHEMA_NAMES = {
    "audit",
    "audits",
    "dbt_test__audit",
    "temp",
    "test",
    "tests",
    "tmp",
}


def _valid_columns_payload(
    columns: Any,
    expected_objects: set[str],
) -> bool:
    if not isinstance(columns, Mapping):
        return False
    if any(not isinstance(name, str) for name in columns):
        return False
    if not expected_objects.issubset(columns):
        return False
    for payload in columns.values():
        if not isinstance(payload, Sequence) or isinstance(
            payload, (str, bytes, bytearray)
        ):
            return False
        if any(not isinstance(column, Mapping) for column in payload):
            return False
    return True


def _technical_hidden(schema: str, name: str) -> bool:
    """Apply only explicit, build-time technical-noise rules."""

    normalized_schema = schema.casefold()
    normalized_name = name.casefold()
    schema_tokens = {token for token in re.split(r"[^a-z0-9]+", normalized_schema) if token}
    return (
        normalized_schema in _TECHNICAL_SCHEMA_NAMES
        or normalized_schema.startswith("dbt_test__audit")
        or bool(schema_tokens & {"audit", "temp", "test", "tests", "tmp"})
        or normalized_name.startswith(("dbt_test__", "temp_", "tmp_"))
        or normalized_name.endswith(("_temp", "_tmp"))
    )


def _warehouse_layer(schema: str) -> str:
    normalized = schema.casefold()
    for layer in ("ads", "dws", "dim", "dwd", "ods", "raw", "audit", "tmp"):
        if normalized == layer or normalized.startswith(f"{layer}_"):
            return layer
    return "unknown"


def _generated_at(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None or value.utcoffset().total_seconds() != 0:
        raise ValueError("generated_at must be UTC")
    return value.isoformat().replace("+00:00", "Z")


def _relation_record(
    database: Mapping[str, Any],
    schema: str,
    relation: Mapping[str, Any],
    columns: Mapping[str, Sequence[Mapping[str, Any]]],
    domain_map: DomainMap | None,
) -> dict[str, Any]:
    name = str(relation["name"])
    object_name = render_object_name(str(database["name"]), schema, name)
    mapped = domain_map.relation(object_name) if domain_map else None
    if mapped is None:
        raw_moego = relation.get("moego")
        moego = (
            {"domain": None, "subdomain": None, "service": None}
            if raw_moego is None
            else dict(raw_moego)
        )
        layer = relation.get("layer", "unknown")
        hidden = bool(relation.get("hiddenByDefault", False))
        source_type = database.get("sourceType")
    else:
        moego = {key: mapped[key] for key in ("domain", "subdomain", "service")}
        layer = mapped["layer"]
        hidden = bool(mapped["hiddenByDefault"])
        source_type = domain_map.source_type(str(database["name"]))
    if source_type == "warehouse" and layer == "unknown":
        layer = _warehouse_layer(schema)
    hidden = hidden or _technical_hidden(schema, name)
    return {
        "recordType": "relation",
        "schemaVersion": 1,
        "object": object_name,
        "database": database["name"],
        "databaseType": database["databaseType"],
        "sourceType": source_type,
        "schema": schema,
        "name": name,
        "relationType": relation["relationType"],
        "layer": layer,
        "moego": moego,
        "hiddenByDefault": hidden,
        "columns": [dict(column) for column in columns.get(object_name, ())],
        "description": relation.get("description"),
        "tags": list(relation.get("tags") or ()),
        "dependsOn": list(relation.get("dependsOn") or ()),
    }


def _write_atomic(destination: Path, records: Sequence[Mapping[str, Any]]) -> Catalog:
    _catalog_from_records(list(records))
    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
        fd, temp_name = tempfile.mkstemp(
            prefix=f".{destination.name}.",
            suffix=".tmp",
            dir=destination.parent,
        )
    except OSError as exc:
        raise SkillError(
            category="catalog",
            code="publish_failed",
            retry_class="after_change",
        ) from exc
    temp_path = Path(temp_name)
    file_fd: int | None = fd
    replaced = False
    try:
        try:
            handle = os.fdopen(file_fd, "w", encoding="utf-8")
            file_fd = None
            with handle:
                for record in records:
                    handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
                    handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            catalog = load_catalog(temp_path)
            os.replace(temp_path, destination)
            replaced = True
            flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
            directory_fd = os.open(destination.parent, flags)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
            return catalog
        except SkillError:
            raise
        except OSError as exc:
            raise SkillError(
                category="catalog",
                code="publish_unknown" if replaced else "publish_failed",
                retry_class="never" if replaced else "after_change",
            ) from exc
    finally:
        if file_fd is not None:
            try:
                os.close(file_fd)
            except OSError:
                pass
        try:
            temp_path.unlink()
        except OSError:
            pass


def build_catalog(
    destination: str | Path,
    source: CatalogMetadataSource,
    *,
    generated_at: datetime,
    max_age_days: int = 7,
    evidence_sources: Sequence[str] = ("redshift_live_metadata",),
    domain_map: str | Path | Mapping[str, Any] | DomainMap | None = None,
) -> Catalog:
    enrichment = (
        domain_map
        if isinstance(domain_map, DomainMap)
        else load_domain_map(domain_map)
        if domain_map is not None
        else None
    )
    databases = sorted(source.show_databases(), key=lambda item: str(item["name"]))
    if not databases:
        raise SkillError("metadata", "incomplete", "transient")
    relations: list[dict[str, Any]] = []
    failed_databases: list[dict[str, str]] = []
    complete_empty_databases: list[dict[str, Any]] = []
    for database in databases:
        database_name = str(database["name"])
        try:
            schemas = sorted(source.show_schemas(database_name))
        except SkillError as exc:
            failed_databases.append(
                {"database": database_name, "stage": "schemas", "code": exc.full_code}
            )
            continue
        try:
            relations_by_schema = source.show_relations(database_name)
        except SkillError as exc:
            failed_databases.append(
                {"database": database_name, "stage": "relations", "code": exc.full_code}
            )
            continue
        if any(not isinstance(schema, str) for schema in relations_by_schema):
            failed_databases.append(
                {
                    "database": database_name,
                    "stage": "relations",
                    "code": "metadata.incomplete",
                }
            )
            continue
        relation_specs = [
            (schema, relation)
            for schema in schemas
            for relation in relations_by_schema.get(schema, ())
        ]
        try:
            columns = source.show_columns(database_name)
        except SkillError as exc:
            failed_databases.append(
                {"database": database_name, "stage": "columns", "code": exc.full_code}
            )
            columns = {}
        else:
            expected_objects = {
                render_object_name(database_name, schema, str(relation["name"]))
                for schema, relation in relation_specs
            }
            if not _valid_columns_payload(columns, expected_objects):
                failed_databases.append(
                    {
                        "database": database_name,
                        "stage": "columns",
                        "code": "metadata.incomplete",
                    }
                )
                columns = {}
        if not relation_specs and not any(
            item["database"] == database_name for item in failed_databases
        ):
            source_type = (
                enrichment.source_type(database_name)
                if enrichment is not None
                else database.get("sourceType")
            )
            complete_empty_databases.append(
                {
                    "name": database_name,
                    "databaseType": database["databaseType"],
                    "sourceType": source_type,
                }
            )
        relations.extend(
            _relation_record(database, schema, relation, columns, enrichment)
            for schema, relation in relation_specs
        )

    relations.sort(key=lambda item: (item["database"], item["schema"], item["name"]))
    source_types = Counter(
        str(relation["sourceType"])
        for relation in relations
        if relation["sourceType"] is not None
    )
    resolved_evidence_sources = list(evidence_sources)
    if enrichment is not None and "maintained_domain_map" not in resolved_evidence_sources:
        resolved_evidence_sources.append("maintained_domain_map")
    meta = {
        "recordType": "meta",
        "schemaVersion": 1,
        "generatedAt": _generated_at(generated_at),
        "maxAgeDays": max_age_days,
        "databaseCount": len({relation["database"] for relation in relations}),
        "relationCount": len(relations),
        "columnCount": sum(len(relation["columns"]) for relation in relations),
        "sourceTypes": dict(source_types),
        "evidenceSources": resolved_evidence_sources,
        "completeEmptyDatabases": complete_empty_databases,
        "coverage": {
            "status": "incomplete" if failed_databases else "complete",
            "visibleDatabaseCount": len(databases),
            "completeDatabaseCount": len(databases) - len(failed_databases),
            "failedDatabases": failed_databases,
        },
    }
    return _write_atomic(Path(destination), [meta, *relations])
