"""Deterministic in-memory discovery over a validated catalog."""
from __future__ import annotations

from datetime import datetime
from collections.abc import Sequence
from typing import Any

from .model import Relation
from .snapshot import Catalog


_LAYER_PRIORITY = {
    "ads": 60,
    "dws": 50,
    "dim": 40,
    "dwd": 30,
    "ods": 20,
    "raw": 10,
    "audit": 2,
    "tmp": 1,
    "unknown": 0,
}


def _coverage_payload(catalog: Catalog) -> dict[str, Any]:
    coverage = catalog.meta.coverage
    return {
        "status": coverage.status,
        "visibleDatabaseCount": coverage.visible_database_count,
        "completeDatabaseCount": coverage.complete_database_count,
        "failedDatabases": [dict(item) for item in coverage.failed_databases],
    }


def _generated_at(catalog: Catalog) -> str:
    return catalog.meta.generated_at.isoformat().replace("+00:00", "Z")


def _match(relation: Relation, text: str | None) -> tuple[int, list[str]] | None:
    if not text:
        return 0, []
    query = text.casefold().strip()
    name = relation.name.casefold()
    object_name = relation.object.casefold()
    column_names = [str(column["name"]).casefold() for column in relation.columns]
    tokens = query.split()
    matched_on: list[str] = []
    if any(token in name or token in object_name for token in tokens):
        matched_on.append("table")
    if any(any(token in column for column in column_names) for token in tokens):
        matched_on.append("column")
    candidates = [name, object_name, *column_names]
    if not matched_on or not all(any(token in candidate for candidate in candidates) for token in tokens):
        return None
    if any(query == candidate for candidate in candidates):
        score = 1000
    elif any(candidate.startswith(query) for candidate in candidates):
        score = 900
    elif len(tokens) > 1:
        score = 800
    else:
        score = 700
    return score, matched_on


def search_catalog(
    catalog: Catalog,
    *,
    text: str | None = None,
    now: datetime,
    database: str | None = None,
    source_type: str | None = None,
    schema: str | None = None,
    layer: str | Sequence[str] | None = None,
    domain: str | None = None,
    kind: str = "all",
    include_hidden: bool = False,
    limit: int = 20,
) -> dict[str, Any]:
    selected_layers = (
        None
        if layer is None
        else {layer}
        if isinstance(layer, str)
        else set(layer)
    )
    matches: list[dict[str, Any]] = []
    for relation in catalog.relations:
        if database is not None and relation.database != database:
            continue
        if source_type is not None and relation.source_type != source_type:
            continue
        if schema is not None and relation.schema != schema:
            continue
        if selected_layers is not None and relation.layer not in selected_layers:
            continue
        if domain is not None and relation.moego.get("domain") != domain:
            continue
        if kind in {"table", "view"} and relation.relation_type != kind:
            continue
        if relation.hidden_by_default and not include_hidden:
            continue
        match = _match(relation, text)
        if match is None:
            continue
        base_score, matched_on = match
        if kind == "column" and text and "column" not in matched_on:
            continue
        matches.append(
            {
                "object": relation.object,
                "sourceType": relation.source_type,
                "layer": relation.layer,
                "domain": relation.moego.get("domain"),
                "relationType": relation.relation_type,
                "matchedOn": matched_on,
                "score": base_score + _LAYER_PRIORITY.get(relation.layer, 0),
                "columns": [str(column["name"]) for column in relation.columns],
            }
        )
    matches.sort(key=lambda item: (-item["score"], item["object"]))
    coverage = _coverage_payload(catalog)
    warnings = (
        [{"code": "catalog.coverage_incomplete"}]
        if coverage["status"] == "incomplete"
        else []
    )
    return {
        "catalogGeneratedAt": _generated_at(catalog),
        "catalogFreshness": catalog.freshness(now),
        "coverage": coverage,
        "warnings": warnings,
        "authoritative": False,
        "matches": matches[:limit],
    }
