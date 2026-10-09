"""Live-first inventory and metadata operations with injected I/O seams."""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable, Mapping, Protocol, Sequence

from ..errors import SkillError
from .identifiers import (
    parse_database_name,
    parse_database_schema_name,
    render_database_name,
    render_database_schema_name,
    render_identifier,
    render_object_name,
)
from .snapshot import Catalog


LiveDatabaseFetcher = Callable[[], Sequence[Mapping[str, Any]]]


@dataclass(frozen=True)
class MetadataRead:
    rows: Sequence[Mapping[str, Any]]
    warnings: tuple[str, ...] = ()
    complete: bool = True
    truncated: bool = False


class MetadataSource(Protocol):
    def show_columns(self, object_name: str) -> MetadataRead: ...

    def svv_all_columns(self, object_name: str) -> MetadataRead: ...


class LiveMetadataSource(Protocol):
    """SHOW-first source used only by interactive live discovery."""

    def show_schemas(self, database: str) -> MetadataRead: ...

    def show_relations(self, database: str, schema: str) -> MetadataRead: ...


_SYSTEM_SCHEMAS = {"information_schema", "pg_catalog", "pg_internal"}
LIVE_METADATA_MAX_LIMIT = 10_000


def _complete_read(read: MetadataRead) -> tuple[Mapping[str, Any], ...]:
    if read.warnings or not read.complete:
        raise SkillError("metadata", "incomplete", "transient")
    rows = tuple(read.rows)
    if any(not isinstance(row, Mapping) for row in rows):
        raise SkillError("metadata", "incomplete", "transient")
    return rows


def _sorted_limited(rows: Sequence[Mapping[str, Any]], limit: int) -> tuple[tuple[Mapping[str, Any], ...], bool]:
    if limit <= 0 or limit > LIVE_METADATA_MAX_LIMIT:
        raise SkillError(
            "usage",
            "invalid_value",
            "after_change",
            details={"argument": "--limit", "maximum": LIVE_METADATA_MAX_LIMIT},
        )
    ordered = tuple(
        sorted(
            rows,
            key=lambda row: (
                str(row["name"]).casefold(),
                str(row["name"]),
            ),
        )
    )
    return ordered[:limit], len(ordered) > limit


def list_schemas(
    database: str,
    source: LiveMetadataSource,
    *,
    include_system: bool,
    limit: int,
) -> dict[str, Any]:
    database_value = parse_database_name(database)
    read = source.show_schemas(database_value)
    rows = _complete_read(read)
    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in rows:
        name = row.get("name")
        if not isinstance(name, str) or not name or name in seen:
            raise SkillError("metadata", "incomplete", "transient")
        seen.add(name)
        if not include_system and name in _SYSTEM_SCHEMAS:
            continue
        try:
            object_name = render_database_schema_name(database_value, name)
        except SkillError as exc:
            raise SkillError("metadata", "incomplete", "transient") from exc
        normalized.append(
            {
                "database": render_database_name(database_value),
                "name": name,
                "object": object_name,
            }
        )
    selected, truncated = _sorted_limited(normalized, limit)
    truncated = truncated or read.truncated or len(rows) >= LIVE_METADATA_MAX_LIMIT
    return {
        "data": [dict(row) for row in selected],
        "meta": {
            "authoritative": True,
            "rowCount": len(selected),
            "truncated": truncated,
        },
    }


def list_relations(
    target: str,
    source: LiveMetadataSource,
    *,
    kind: str,
    limit: int,
) -> dict[str, Any]:
    if limit <= 0 or limit > LIVE_METADATA_MAX_LIMIT:
        raise SkillError(
            "usage",
            "invalid_value",
            "after_change",
            details={"argument": "--limit", "maximum": LIVE_METADATA_MAX_LIMIT},
        )
    if kind not in {"table", "view", "all"}:
        raise SkillError(
            "usage",
            "invalid_value",
            "after_change",
            details={"argument": "--kind"},
        )
    database, schema = parse_database_schema_name(target)
    read = source.show_relations(database, schema)
    rows = _complete_read(read)
    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in rows:
        name = row.get("name")
        relation_type = row.get("relationType")
        description = row.get("description")
        if (
            not isinstance(name, str)
            or not name
            or relation_type not in {"table", "view"}
            or (description is not None and not isinstance(description, str))
        ):
            raise SkillError("metadata", "incomplete", "transient")
        try:
            object_name = render_object_name(database, schema, name)
        except SkillError as exc:
            raise SkillError("metadata", "incomplete", "transient") from exc
        if object_name in seen:
            raise SkillError("metadata", "incomplete", "transient")
        seen.add(object_name)
        if kind != "all" and relation_type != kind:
            continue
        normalized.append(
            {
                "object": object_name,
                "database": render_database_name(database),
                "schema": render_identifier(schema),
                "name": name,
                "relationType": relation_type,
                "description": description,
            }
        )
    normalized.sort(key=lambda row: (str(row["name"]).casefold(), str(row["name"])))
    selected = normalized[:limit]
    return {
        "data": selected,
        "meta": {
            "authoritative": True,
            "rowCount": len(selected),
            "truncated": (
                len(normalized) > limit
                or read.truncated
                or len(rows) >= LIVE_METADATA_MAX_LIMIT
            ),
        },
    }


def _coverage_payload(catalog: Catalog) -> dict[str, Any]:
    coverage = catalog.meta.coverage
    return {
        "status": coverage.status,
        "visibleDatabaseCount": coverage.visible_database_count,
        "completeDatabaseCount": coverage.complete_database_count,
        "failedDatabases": [dict(item) for item in coverage.failed_databases],
    }


def list_databases(
    fetch_live_databases: LiveDatabaseFetcher,
    *,
    catalog: Catalog | None,
    now: datetime,
    source_type: str | None = None,
) -> dict[str, Any]:
    if source_type is not None and catalog is None:
        raise SkillError(
            category="catalog",
            code="unavailable",
            retry_class="after_change",
        )
    live_databases = fetch_live_databases()
    if catalog is None:
        rows = [
            {
                "name": item["name"],
                "databaseType": item["databaseType"],
                "sourceType": None,
                "objectCount": None,
                "enrichmentStatus": "missing",
                "catalogFreshness": None,
            }
            for item in live_databases
        ]
        return {
            "data": rows,
            "meta": {"catalogGeneratedAt": None, "coverage": None},
        }

    relations_by_database: dict[str, list[Any]] = defaultdict(list)
    for relation in catalog.relations:
        relations_by_database[relation.database].append(relation)
    failed_names = {
        item["database"] for item in catalog.meta.coverage.failed_databases
    }
    complete_empty_databases = {
        str(item["name"]): item
        for item in catalog.meta.complete_empty_databases
    }
    freshness = catalog.freshness(now)
    rows: list[dict[str, Any]] = []
    for item in live_databases:
        name = str(item["name"])
        relations = relations_by_database.get(name, [])
        classified = {relation.source_type for relation in relations if relation.source_type is not None}
        resolved_source_type = next(iter(classified)) if len(classified) == 1 else None
        empty_database = complete_empty_databases.get(name)
        complete_empty = (
            empty_database is not None
            and empty_database["databaseType"] == item["databaseType"]
        )
        if complete_empty:
            resolved_source_type = empty_database["sourceType"]
        if name in failed_names:
            status = "incomplete"
        elif relations or complete_empty:
            status = "complete"
        else:
            status = "missing"
        row = {
            "name": name,
            "databaseType": item["databaseType"],
            "sourceType": resolved_source_type,
            "objectCount": len(relations) if status == "complete" and freshness == "fresh" else None,
            "enrichmentStatus": status,
            "catalogFreshness": freshness,
        }
        if source_type is None or resolved_source_type == source_type:
            rows.append(row)
    return {
        "data": rows,
        "meta": {
            "catalogGeneratedAt": catalog.meta.generated_at.isoformat().replace("+00:00", "Z"),
            "coverage": _coverage_payload(catalog),
        },
    }


def describe_object(
    object_name: str,
    source: MetadataSource,
    *,
    known_incomplete: bool = False,
) -> dict[str, Any]:
    metadata_source = "show_columns"
    try:
        result = source.show_columns(object_name)
    except SkillError as exc:
        if exc.full_code != "capability.show_metadata_unavailable":
            raise
        result = source.svv_all_columns(object_name)
        metadata_source = "svv_all_columns"
    if result.warnings or not result.complete:
        raise SkillError(category="metadata", code="incomplete", retry_class="transient")
    if not result.rows and known_incomplete:
        raise SkillError(category="metadata", code="incomplete", retry_class="transient")
    if not result.rows:
        raise SkillError(category="metadata", code="not_found", retry_class="after_change")
    return {
        "object": object_name,
        "metadataSource": metadata_source,
        "complete": True,
        "columns": [dict(column) for column in result.rows],
    }
