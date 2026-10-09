"""Validated MoeGo domain enrichment loaded from a mapping or JSON path."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from ..errors import SkillError
from .identifiers import parse_object_name, render_object_name


_DEFAULT_RELATION = {
    "domain": None,
    "subdomain": None,
    "service": None,
    "layer": "unknown",
    "hiddenByDefault": False,
}
_SOURCE_TYPES = {"warehouse", "mysql", "postgres", "saas", "unknown"}
_LAYERS = {"raw", "ods", "dwd", "dws", "ads", "dim", "audit", "tmp", "unknown"}
_RELATION_FIELDS = {"domain", "subdomain", "service", "layer", "hiddenByDefault"}


@dataclass(frozen=True)
class DomainMap:
    databases: Mapping[str, Mapping[str, str]]
    relations: Mapping[str, Mapping[str, Any]]

    def source_type(self, database: str) -> str | None:
        item = self.databases.get(database)
        return str(item["sourceType"]) if item else None

    def relation(self, object_name: str) -> dict[str, Any]:
        result = dict(_DEFAULT_RELATION)
        result.update(self.relations.get(object_name, {}))
        return result


def _invalid(exc: BaseException | None = None) -> SkillError:
    error = SkillError(category="catalog", code="invalid", retry_class="after_change")
    if exc is not None:
        error.__cause__ = exc
    return error


def _canonical_object_key(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    try:
        return render_object_name(*parse_object_name(value)) == value
    except SkillError:
        return False


def _validated_payload(payload: Mapping[str, Any]) -> tuple[dict[str, dict[str, str]], dict[str, dict[str, Any]]]:
    if set(payload) != {"schemaVersion", "databases", "relations"}:
        raise _invalid()
    if type(payload["schemaVersion"]) is not int or payload["schemaVersion"] != 1:
        raise _invalid()
    raw_databases = payload["databases"]
    raw_relations = payload["relations"]
    if not isinstance(raw_databases, Mapping) or not isinstance(raw_relations, Mapping):
        raise _invalid()

    databases: dict[str, dict[str, str]] = {}
    for name, item in raw_databases.items():
        if not isinstance(name, str) or not name or not isinstance(item, Mapping):
            raise _invalid()
        if set(item) != {"sourceType"} or item["sourceType"] not in _SOURCE_TYPES:
            raise _invalid()
        databases[name] = {"sourceType": str(item["sourceType"])}

    relations: dict[str, dict[str, Any]] = {}
    for object_name, item in raw_relations.items():
        if (
            not _canonical_object_key(object_name)
            or not isinstance(item, Mapping)
            or set(item) != _RELATION_FIELDS
        ):
            raise _invalid()
        if any(item[field] is not None and not isinstance(item[field], str) for field in ("domain", "subdomain", "service")):
            raise _invalid()
        if item["layer"] not in _LAYERS or not isinstance(item["hiddenByDefault"], bool):
            raise _invalid()
        relations[object_name] = dict(item)
    return databases, relations


def load_domain_map(source: str | Path | Mapping[str, Any]) -> DomainMap:
    try:
        if isinstance(source, Mapping):
            payload = dict(source)
        else:
            payload = json.loads(Path(source).read_text(encoding="utf-8"))
        databases, relations = _validated_payload(payload)
        return DomainMap(databases=databases, relations=relations)
    except SkillError:
        raise
    except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        raise _invalid(exc) from exc
