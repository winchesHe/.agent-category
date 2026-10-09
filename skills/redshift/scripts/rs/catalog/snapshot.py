"""Load the single JSONL catalog artifact as one validated snapshot."""
from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Mapping

from ..errors import SkillError
from .identifiers import render_object_name
from .model import CatalogMeta, Coverage, Relation, parse_utc


_META_FIELDS = {
    "recordType",
    "schemaVersion",
    "generatedAt",
    "maxAgeDays",
    "databaseCount",
    "relationCount",
    "columnCount",
    "sourceTypes",
    "evidenceSources",
    "coverage",
}
_REQUIRED_META_FIELDS = {"completeEmptyDatabases"}
_EMPTY_DATABASE_FIELDS = {"name", "databaseType", "sourceType"}
_COVERAGE_FIELDS = {
    "status",
    "visibleDatabaseCount",
    "completeDatabaseCount",
    "failedDatabases",
}
_RELATION_FIELDS = {
    "recordType",
    "schemaVersion",
    "object",
    "database",
    "databaseType",
    "sourceType",
    "schema",
    "name",
    "relationType",
    "layer",
    "moego",
    "hiddenByDefault",
    "columns",
    "description",
    "tags",
    "dependsOn",
}
_MOEGO_FIELDS = {"domain", "subdomain", "service"}
_COLUMN_REQUIRED_FIELDS = {"name", "dataType", "nullable"}
_COLUMN_OPTIONAL_FIELDS = {"ordinal"}
_SOURCE_TYPES = {"warehouse", "mysql", "postgres", "saas", "unknown"}
_LAYERS = {"raw", "ods", "dwd", "dws", "ads", "dim", "audit", "tmp", "unknown"}
_DATABASE_TYPES = {"local", "datashare", "external", "catalog", "unknown"}
_RELATION_TYPES = {"table", "view"}
# Catalog generation and consumption may observe slightly different clocks.
# Larger future offsets indicate a corrupt artifact rather than fresh metadata.
CATALOG_FUTURE_SKEW_ALLOWANCE = timedelta(minutes=5)


@dataclass(frozen=True)
class Catalog:
    meta: CatalogMeta
    relations: tuple[Relation, ...]

    def freshness(self, now: datetime) -> str:
        if now.tzinfo is None or now.utcoffset() is None:
            raise _invalid()
        age = now - self.meta.generated_at
        if age < -CATALOG_FUTURE_SKEW_ALLOWANCE:
            raise _invalid()
        return "fresh" if age <= timedelta(days=self.meta.max_age_days) else "stale"


def _invalid() -> SkillError:
    return SkillError(category="catalog", code="invalid", retry_class="after_change")


def _is_int(value: Any) -> bool:
    return type(value) is int


def _non_empty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value)


def _has_canonical_object_name(relation: Relation) -> bool:
    try:
        expected = render_object_name(
            relation.database,
            relation.schema,
            relation.name,
        )
    except SkillError:
        return False
    return relation.object == expected


def _validate_raw_shape(records: list[Mapping[str, Any]]) -> None:
    if not records or any(not isinstance(record, Mapping) for record in records):
        raise _invalid()
    meta = records[0]
    if (
        not (_META_FIELDS | _REQUIRED_META_FIELDS).issubset(meta)
        or not set(meta).issubset(_META_FIELDS | _REQUIRED_META_FIELDS)
        or meta.get("recordType") != "meta"
    ):
        raise _invalid()
    if any(
        set(record) != _RELATION_FIELDS or record.get("recordType") != "relation"
        for record in records[1:]
    ):
        raise _invalid()
    coverage = meta.get("coverage")
    if not isinstance(coverage, Mapping) or set(coverage) != _COVERAGE_FIELDS:
        raise _invalid()
    if (
        not isinstance(meta.get("generatedAt"), str)
        or not isinstance(meta.get("sourceTypes"), Mapping)
        or not isinstance(meta.get("evidenceSources"), list)
        or not isinstance(coverage.get("failedDatabases"), list)
        or (
            not isinstance(meta["completeEmptyDatabases"], list)
        )
    ):
        raise _invalid()
    for record in records[1:]:
        if (
            not isinstance(record.get("moego"), Mapping)
            or not isinstance(record.get("columns"), list)
            or not isinstance(record.get("tags"), list)
            or not isinstance(record.get("dependsOn"), list)
        ):
            raise _invalid()


def _parse_meta(record: Mapping[str, Any]) -> CatalogMeta:
    coverage = record["coverage"]
    return CatalogMeta(
        schema_version=record["schemaVersion"],
        generated_at=parse_utc(record["generatedAt"]),
        max_age_days=record["maxAgeDays"],
        database_count=record["databaseCount"],
        relation_count=record["relationCount"],
        column_count=record["columnCount"],
        source_types=dict(record["sourceTypes"]),
        evidence_sources=tuple(record["evidenceSources"]),
        coverage=Coverage(
            status=coverage["status"],
            visible_database_count=coverage["visibleDatabaseCount"],
            complete_database_count=coverage["completeDatabaseCount"],
            failed_databases=tuple(coverage["failedDatabases"]),
        ),
        complete_empty_databases=tuple(record["completeEmptyDatabases"]),
    )


def _parse_relation(record: Mapping[str, Any]) -> Relation:
    return Relation(
        object=record["object"],
        database=record["database"],
        database_type=record["databaseType"],
        source_type=record["sourceType"],
        schema=record["schema"],
        name=record["name"],
        relation_type=record["relationType"],
        layer=record["layer"],
        moego=dict(record.get("moego") or {}),
        hidden_by_default=record["hiddenByDefault"],
        columns=tuple(record["columns"]),
        description=record.get("description"),
        tags=tuple(record.get("tags") or ()),
        depends_on=tuple(record.get("dependsOn") or ()),
    )


def _validate(meta: CatalogMeta, relations: tuple[Relation, ...], records: list[Mapping[str, Any]]) -> None:
    if (
        not _is_int(meta.schema_version)
        or meta.schema_version != 1
        or any(
            not _is_int(record.get("schemaVersion"))
            or record.get("schemaVersion") != 1
            for record in records
        )
    ):
        raise _invalid()
    if not _is_int(meta.max_age_days) or meta.max_age_days <= 0:
        raise _invalid()
    if not all(
        _is_int(value) and value >= 0
        for value in (
            meta.database_count,
            meta.relation_count,
            meta.column_count,
            meta.coverage.visible_database_count,
            meta.coverage.complete_database_count,
        )
    ):
        raise _invalid()
    if (
        not isinstance(meta.source_types, Mapping)
        or any(
            source_type not in _SOURCE_TYPES or not _is_int(count) or count <= 0
            for source_type, count in meta.source_types.items()
        )
        or not meta.evidence_sources
        or any(not _non_empty_string(item) for item in meta.evidence_sources)
        or len(meta.evidence_sources) != len(set(meta.evidence_sources))
    ):
        raise _invalid()

    objects = [relation.object for relation in relations]
    if len(objects) != len(set(objects)):
        raise _invalid()
    if any(not _has_canonical_object_name(relation) for relation in relations):
        raise _invalid()
    keys = [(relation.database, relation.schema, relation.name) for relation in relations]
    if keys != sorted(keys):
        raise _invalid()

    source_types_by_database: dict[str, set[str | None]] = {}
    database_types: dict[str, str] = {}
    for relation in relations:
        if not all(
            _non_empty_string(value)
            for value in (
                relation.object,
                relation.database,
                relation.database_type,
                relation.schema,
                relation.name,
                relation.relation_type,
            )
        ):
            raise _invalid()
        if relation.database_type not in _DATABASE_TYPES:
            raise _invalid()
        if relation.relation_type not in _RELATION_TYPES:
            raise _invalid()
        if relation.source_type is not None and relation.source_type not in _SOURCE_TYPES:
            raise _invalid()
        if relation.layer not in _LAYERS or type(relation.hidden_by_default) is not bool:
            raise _invalid()
        if (
            set(relation.moego) != _MOEGO_FIELDS
            or any(
                value is not None and not _non_empty_string(value)
                for value in relation.moego.values()
            )
        ):
            raise _invalid()
        if relation.description is not None and not isinstance(relation.description, str):
            raise _invalid()
        if any(not _non_empty_string(item) for item in relation.tags):
            raise _invalid()
        if any(not _non_empty_string(item) for item in relation.depends_on):
            raise _invalid()
        for column in relation.columns:
            if not isinstance(column, Mapping):
                raise _invalid()
            column_fields = set(column)
            if (
                not _COLUMN_REQUIRED_FIELDS.issubset(column_fields)
                or not column_fields.issubset(_COLUMN_REQUIRED_FIELDS | _COLUMN_OPTIONAL_FIELDS)
                or not _non_empty_string(column.get("name"))
                or not _non_empty_string(column.get("dataType"))
                or type(column.get("nullable")) is not bool
            ):
                raise _invalid()
            if "ordinal" in column and (
                not _is_int(column["ordinal"]) or column["ordinal"] <= 0
            ):
                raise _invalid()
        column_names = [column["name"] for column in relation.columns]
        if len(column_names) != len(set(column_names)):
            raise _invalid()
        ordinals = [column["ordinal"] for column in relation.columns if "ordinal" in column]
        if len(ordinals) != len(set(ordinals)) or ordinals != sorted(ordinals):
            raise _invalid()
        source_types_by_database.setdefault(relation.database, set()).add(relation.source_type)
        previous_database_type = database_types.setdefault(
            relation.database, relation.database_type
        )
        if previous_database_type != relation.database_type:
            raise _invalid()
    if any(len(source_types) != 1 for source_types in source_types_by_database.values()):
        raise _invalid()

    if meta.relation_count != len(relations):
        raise _invalid()
    if meta.column_count != sum(len(relation.columns) for relation in relations):
        raise _invalid()
    if meta.database_count != len({relation.database for relation in relations}):
        raise _invalid()
    classified_source_types = Counter(
        relation.source_type for relation in relations if relation.source_type is not None
    )
    if dict(meta.source_types) != dict(classified_source_types):
        raise _invalid()

    coverage = meta.coverage
    failed = coverage.failed_databases
    if coverage.status not in {"complete", "incomplete"}:
        raise _invalid()
    if coverage.visible_database_count != coverage.complete_database_count + len(failed):
        raise _invalid()
    if coverage.status == "complete" and failed:
        raise _invalid()
    if coverage.status == "incomplete" and not failed:
        raise _invalid()
    failed_names: list[str] = []
    for item in failed:
        if set(item) != {"database", "stage", "code"}:
            raise _invalid()
        database = item["database"]
        stage = item["stage"]
        code = item["code"]
        if not _non_empty_string(database) or stage not in {"schemas", "relations", "columns"}:
            raise _invalid()
        if not isinstance(code, str) or not re.fullmatch(
            r"[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*", code
        ):
            raise _invalid()
        failed_names.append(database)
    if len(failed_names) != len(set(failed_names)):
        raise _invalid()
    failed_by_name = {
        item["database"]: item["stage"]
        for item in failed
    }
    relation_database_names = {relation.database for relation in relations}
    if any(
        database in relation_database_names and stage != "columns"
        for database, stage in failed_by_name.items()
    ):
        raise _invalid()
    complete_relation_names = relation_database_names - set(failed_by_name)
    if (
        meta.database_count > coverage.visible_database_count
        or len(complete_relation_names) > coverage.complete_database_count
    ):
        raise _invalid()

    empty_databases = meta.complete_empty_databases
    empty_names: list[str] = []
    for item in empty_databases:
        if not isinstance(item, Mapping) or set(item) != _EMPTY_DATABASE_FIELDS:
            raise _invalid()
        name = item["name"]
        database_type = item["databaseType"]
        source_type = item["sourceType"]
        if (
            not _non_empty_string(name)
            or database_type not in _DATABASE_TYPES
            or (source_type is not None and source_type not in _SOURCE_TYPES)
        ):
            raise _invalid()
        empty_names.append(name)
    if (
        empty_names != sorted(empty_names)
        or len(empty_names) != len(set(empty_names))
        or set(empty_names) & (relation_database_names | set(failed_by_name))
        or len(complete_relation_names) + len(empty_names)
        != coverage.complete_database_count
    ):
        raise _invalid()


def _catalog_from_records(records: list[Mapping[str, Any]]) -> Catalog:
    try:
        _validate_raw_shape(records)
        meta = _parse_meta(records[0])
        relations = tuple(_parse_relation(record) for record in records[1:])
        _validate(meta, relations, records)
        return Catalog(meta=meta, relations=relations)
    except SkillError:
        raise
    except (IndexError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise _invalid() from exc


def load_catalog(path: str | Path) -> Catalog:
    try:
        records = [
            json.loads(line)
            for line in Path(path).read_text(encoding="utf-8").splitlines()
        ]
        return _catalog_from_records(records)
    except FileNotFoundError as exc:
        raise SkillError(category="catalog", code="unavailable", retry_class="after_change") from exc
    except OSError as exc:
        raise SkillError(category="catalog", code="unavailable", retry_class="after_change") from exc
    except SkillError:
        raise
    except (AttributeError, TypeError, UnicodeError, ValueError, json.JSONDecodeError) as exc:
        raise _invalid() from exc
