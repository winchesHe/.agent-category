from __future__ import annotations

import json
from copy import deepcopy
from datetime import datetime, timedelta, timezone

import pytest

from scripts.rs.errors import SkillError
from scripts.rs.catalog import load_catalog
from scripts.rs.catalog.snapshot import CATALOG_FUTURE_SKEW_ALLOWANCE


def _write_jsonl(path, records: list[dict[str, object]]) -> None:
    path.write_text(
        "".join(json.dumps(record, separators=(",", ":")) + "\n" for record in records),
        encoding="utf-8",
    )


def _valid_records() -> list[dict[str, object]]:
    return [
        {
            "recordType": "meta",
            "schemaVersion": 1,
            "generatedAt": "2026-07-14T00:00:00Z",
            "maxAgeDays": 7,
            "databaseCount": 1,
            "relationCount": 1,
            "columnCount": 2,
            "sourceTypes": {"warehouse": 1},
            "evidenceSources": ["redshift_live_metadata"],
            "completeEmptyDatabases": [],
            "coverage": {
                "status": "complete",
                "visibleDatabaseCount": 1,
                "completeDatabaseCount": 1,
                "failedDatabases": [],
            },
        },
        {
            "recordType": "relation",
            "schemaVersion": 1,
            "object": "dbt_dw.ads.payment_summary",
            "database": "dbt_dw",
            "databaseType": "local",
            "sourceType": "warehouse",
            "schema": "ads",
            "name": "payment_summary",
            "relationType": "table",
            "layer": "ads",
            "moego": {"domain": "payment", "subdomain": None, "service": "data-warehouse"},
            "hiddenByDefault": False,
            "columns": [
                {"name": "company_id", "dataType": "bigint", "nullable": True},
                {"name": "amount", "dataType": "numeric", "nullable": True},
            ],
            "description": None,
            "tags": [],
            "dependsOn": [],
        },
    ]


def test_load_catalog_validates_one_jsonl_and_recomputes_freshness(tmp_path) -> None:
    path = tmp_path / "catalog.jsonl"
    _write_jsonl(path, _valid_records())

    catalog = load_catalog(path)

    assert catalog.meta.relation_count == 1
    assert catalog.relations[0].object == "dbt_dw.ads.payment_summary"
    assert catalog.freshness(datetime(2026, 7, 20, tzinfo=timezone.utc)) == "fresh"
    assert catalog.freshness(datetime(2026, 7, 22, tzinfo=timezone.utc)) == "stale"


def test_catalog_freshness_rejects_a_naive_clock(tmp_path) -> None:
    path = tmp_path / "catalog.jsonl"
    _write_jsonl(path, _valid_records())
    catalog = load_catalog(path)

    with pytest.raises(SkillError) as caught:
        catalog.freshness(datetime(2026, 7, 20))

    assert caught.value.full_code == "catalog.invalid"


def test_catalog_freshness_allows_documented_clock_skew(tmp_path) -> None:
    path = tmp_path / "catalog.jsonl"
    _write_jsonl(path, _valid_records())
    catalog = load_catalog(path)

    now = catalog.meta.generated_at - CATALOG_FUTURE_SKEW_ALLOWANCE

    assert catalog.freshness(now) == "fresh"


def test_catalog_freshness_rejects_generated_at_beyond_clock_skew(tmp_path) -> None:
    path = tmp_path / "catalog.jsonl"
    _write_jsonl(path, _valid_records())
    catalog = load_catalog(path)

    now = (
        catalog.meta.generated_at
        - CATALOG_FUTURE_SKEW_ALLOWANCE
        - timedelta(microseconds=1)
    )

    with pytest.raises(SkillError) as caught:
        catalog.freshness(now)

    assert caught.value.full_code == "catalog.invalid"


def test_catalog_rejects_non_positive_freshness_window(tmp_path) -> None:
    records = _valid_records()
    records[0]["maxAgeDays"] = 0
    path = tmp_path / "catalog.jsonl"
    _write_jsonl(path, records)

    with pytest.raises(SkillError) as caught:
        load_catalog(path)

    assert caught.value.full_code == "catalog.invalid"


def test_load_catalog_accepts_the_single_optional_column_ordinal(tmp_path) -> None:
    records = _valid_records()
    records[1]["columns"][0]["ordinal"] = 1
    path = tmp_path / "catalog.jsonl"
    _write_jsonl(path, records)

    catalog = load_catalog(path)

    assert catalog.relations[0].columns[0]["ordinal"] == 1


def test_load_catalog_rejects_duplicate_relation_objects_as_one_invalid_artifact(tmp_path) -> None:
    records = _valid_records()
    records[0]["relationCount"] = 2
    records[0]["columnCount"] = 4
    records[0]["sourceTypes"] = {"warehouse": 2}
    records.append(dict(records[1]))
    path = tmp_path / "catalog.jsonl"
    _write_jsonl(path, records)

    with pytest.raises(SkillError) as caught:
        load_catalog(path)

    assert caught.value.full_code == "catalog.invalid"


@pytest.mark.parametrize("variant", ["empty", "relation_first", "second_meta", "bad_json"])
def test_load_catalog_fails_closed_for_structurally_invalid_jsonl(tmp_path, variant: str) -> None:
    records = _valid_records()
    path = tmp_path / "catalog.jsonl"
    if variant == "empty":
        path.write_text("", encoding="utf-8")
    elif variant == "relation_first":
        _write_jsonl(path, records[1:])
    elif variant == "second_meta":
        _write_jsonl(path, [records[0], records[0], records[1]])
    else:
        path.write_text('{"recordType":"meta"}\nnot-json\n', encoding="utf-8")

    with pytest.raises(SkillError) as caught:
        load_catalog(path)

    assert caught.value.full_code == "catalog.invalid"


@pytest.mark.parametrize(
    "variant",
    [
        "schema_version",
        "generated_at",
        "relation_count",
        "column_count",
        "database_count",
        "source_type_count",
        "coverage_total",
        "coverage_state",
        "duplicate_failed_database",
        "failed_stage",
        "coverage_relation_universe",
        "failed_before_columns_has_relations",
        "object_name",
        "invalid_identifier",
        "sort_order",
    ],
)
def test_load_catalog_rejects_any_integrity_invariant_failure(tmp_path, variant: str) -> None:
    records = _valid_records()
    meta = records[0]
    relation = records[1]
    coverage = meta["coverage"]

    if variant == "schema_version":
        relation["schemaVersion"] = 2
    elif variant == "generated_at":
        meta["generatedAt"] = "2026-07-14T01:00:00+01:00"
    elif variant == "relation_count":
        meta["relationCount"] = 0
    elif variant == "column_count":
        meta["columnCount"] = 1
    elif variant == "database_count":
        meta["databaseCount"] = 2
    elif variant == "source_type_count":
        meta["sourceTypes"] = {"warehouse": 2}
    elif variant == "coverage_total":
        coverage["visibleDatabaseCount"] = 2
    elif variant == "coverage_state":
        coverage.update(
            status="complete",
            completeDatabaseCount=0,
            failedDatabases=[{"database": "dbt_dw", "stage": "columns", "code": "metadata.timeout"}],
        )
    elif variant == "duplicate_failed_database":
        coverage.update(
            status="incomplete",
            visibleDatabaseCount=2,
            completeDatabaseCount=0,
            failedDatabases=[
                {"database": "dbt_dw", "stage": "relations", "code": "metadata.timeout"},
                {"database": "dbt_dw", "stage": "columns", "code": "metadata.permission_denied"},
            ],
        )
    elif variant == "failed_stage":
        coverage.update(
            status="incomplete",
            completeDatabaseCount=0,
            failedDatabases=[{"database": "dbt_dw", "stage": "connect", "code": "connection.timeout"}],
        )
    elif variant == "coverage_relation_universe":
        coverage.update(
            status="incomplete",
            completeDatabaseCount=0,
            failedDatabases=[
                {"database": "other_db", "stage": "schemas", "code": "metadata.timeout"}
            ],
        )
    elif variant == "failed_before_columns_has_relations":
        coverage.update(
            status="incomplete",
            completeDatabaseCount=0,
            failedDatabases=[
                {"database": "dbt_dw", "stage": "relations", "code": "metadata.timeout"}
            ],
        )
    elif variant == "object_name":
        relation["object"] = "dbt_dw.ads.not_the_record_name"
    elif variant == "invalid_identifier":
        relation["object"] = "dbt_dw.ads.bad\x00name"
        relation["name"] = "bad\x00name"
    else:
        earlier = deepcopy(relation)
        earlier.update(object="aaa.public.first", database="aaa", schema="public", name="first")
        records.append(earlier)
        meta.update(databaseCount=2, relationCount=2, columnCount=4, sourceTypes={"warehouse": 2})

    path = tmp_path / "catalog.jsonl"
    _write_jsonl(path, records)

    with pytest.raises(SkillError) as caught:
        load_catalog(path)

    assert caught.value.full_code == "catalog.invalid"


@pytest.mark.parametrize("variant", ["overlap", "count", "duplicate", "shape"])
def test_load_catalog_validates_complete_empty_database_identities(tmp_path, variant: str) -> None:
    records = _valid_records()
    meta = records[0]
    empty = {"name": "empty_db", "databaseType": "local", "sourceType": None}
    if variant == "overlap":
        meta["completeEmptyDatabases"] = [
            {"name": "dbt_dw", "databaseType": "local", "sourceType": "warehouse"}
        ]
    elif variant == "count":
        meta["completeEmptyDatabases"] = [empty]
    elif variant == "duplicate":
        meta.update(databaseCount=0, relationCount=0, columnCount=0, sourceTypes={})
        records = [meta]
        meta["coverage"]["visibleDatabaseCount"] = 2
        meta["coverage"]["completeDatabaseCount"] = 2
        meta["completeEmptyDatabases"] = [empty, dict(empty)]
    else:
        meta["completeEmptyDatabases"] = [{"name": "empty_db"}]

    path = tmp_path / "catalog.jsonl"
    _write_jsonl(path, records)

    with pytest.raises(SkillError) as caught:
        load_catalog(path)

    assert caught.value.full_code == "catalog.invalid"


def test_load_catalog_reports_missing_artifact_as_unavailable(tmp_path) -> None:
    with pytest.raises(SkillError) as caught:
        load_catalog(tmp_path / "missing.jsonl")

    assert caught.value.full_code == "catalog.unavailable"


def test_load_catalog_reports_filesystem_read_failure_as_unavailable(tmp_path) -> None:
    with pytest.raises(SkillError) as caught:
        load_catalog(tmp_path)

    assert caught.value.full_code == "catalog.unavailable"


def test_load_catalog_reports_permission_failure_as_unavailable(tmp_path, monkeypatch) -> None:
    path = tmp_path / "catalog.jsonl"
    path.write_text("unreadable", encoding="utf-8")

    def deny_read(*_args, **_kwargs):
        raise PermissionError("denied")

    monkeypatch.setattr("scripts.rs.catalog.snapshot.Path.read_text", deny_read)

    with pytest.raises(SkillError) as caught:
        load_catalog(path)

    assert caught.value.full_code == "catalog.unavailable"


@pytest.mark.parametrize(
    "variant",
    [
        "database_type",
        "source_type",
        "relation_type",
        "layer",
        "moego_shape",
        "hidden_flag",
        "column_shape",
        "column_nullable",
        "description",
        "tags",
        "depends_on",
    ],
)
def test_load_catalog_rejects_malformed_typed_relation_fields(tmp_path, variant: str) -> None:
    records = _valid_records()
    relation = records[1]

    if variant == "database_type":
        relation["databaseType"] = "mystery"
    elif variant == "source_type":
        relation["sourceType"] = "oracle"
    elif variant == "relation_type":
        relation["relationType"] = "procedure"
    elif variant == "layer":
        relation["layer"] = "silver"
    elif variant == "moego_shape":
        relation["moego"] = {"domain": "payment"}
    elif variant == "hidden_flag":
        relation["hiddenByDefault"] = 0
    elif variant == "column_shape":
        relation["columns"] = [{"name": "company_id", "dataType": "bigint"}]
        records[0]["columnCount"] = 1
    elif variant == "column_nullable":
        relation["columns"][0]["nullable"] = "yes"
    elif variant == "description":
        relation["description"] = 1
    elif variant == "tags":
        relation["tags"] = ["finance", 2]
    else:
        relation["dependsOn"] = ["dbt_dw.raw.payment", 2]

    path = tmp_path / "catalog.jsonl"
    _write_jsonl(path, records)

    with pytest.raises(SkillError) as caught:
        load_catalog(path)

    assert caught.value.full_code == "catalog.invalid"


def test_load_catalog_rejects_conflicting_source_types_within_one_database(tmp_path) -> None:
    records = _valid_records()
    second = deepcopy(records[1])
    second.update(
        object="dbt_dw.ads.second",
        name="second",
        sourceType="mysql",
    )
    records.append(second)
    records[0].update(
        relationCount=2,
        columnCount=4,
        sourceTypes={"warehouse": 1, "mysql": 1},
    )
    path = tmp_path / "catalog.jsonl"
    _write_jsonl(path, records)

    with pytest.raises(SkillError) as caught:
        load_catalog(path)

    assert caught.value.full_code == "catalog.invalid"


@pytest.mark.parametrize("duplicate", ["name", "ordinal", "order"])
def test_load_catalog_rejects_duplicate_columns_within_relation(
    tmp_path, duplicate: str
) -> None:
    records = _valid_records()
    second = deepcopy(records[1]["columns"][0])
    if duplicate == "name":
        second["ordinal"] = 2
    elif duplicate == "ordinal":
        records[1]["columns"][0]["ordinal"] = 1
        second["name"] = "second_id"
        second["ordinal"] = 1
    else:
        records[1]["columns"][0]["ordinal"] = 2
        second["name"] = "second_id"
        second["ordinal"] = 1
    records[1]["columns"].append(second)
    records[0]["columnCount"] = 3
    path = tmp_path / "catalog.jsonl"
    _write_jsonl(path, records)

    with pytest.raises(SkillError) as caught:
        load_catalog(path)

    assert caught.value.full_code == "catalog.invalid"
