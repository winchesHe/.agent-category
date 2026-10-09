"""Typed values for the local Redshift catalog artifact."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping


@dataclass(frozen=True)
class Coverage:
    status: str
    visible_database_count: int
    complete_database_count: int
    failed_databases: tuple[Mapping[str, str], ...]


@dataclass(frozen=True)
class CatalogMeta:
    schema_version: int
    generated_at: datetime
    max_age_days: int
    database_count: int
    relation_count: int
    column_count: int
    source_types: Mapping[str, int]
    evidence_sources: tuple[str, ...]
    coverage: Coverage
    complete_empty_databases: tuple[Mapping[str, Any], ...]


@dataclass(frozen=True)
class Relation:
    object: str
    database: str
    database_type: str
    source_type: str | None
    schema: str
    name: str
    relation_type: str
    layer: str
    moego: Mapping[str, Any]
    hidden_by_default: bool
    columns: tuple[Mapping[str, Any], ...]
    description: str | None
    tags: tuple[str, ...]
    depends_on: tuple[str, ...]


def parse_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        raise ValueError("generatedAt must be UTC")
    return parsed
