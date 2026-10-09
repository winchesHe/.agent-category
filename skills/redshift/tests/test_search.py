from __future__ import annotations

from datetime import datetime, timezone

import pytest

from scripts.rs.catalog.builder import build_catalog
from scripts.rs.catalog.live import list_databases
from scripts.rs.catalog.search import search_catalog
from scripts.rs.errors import SkillError


class SearchMetadataSource:
    def show_databases(self):
        return (
            {"name": "dbt_dw", "databaseType": "local"},
            {"name": "mysql_prod", "databaseType": "local"},
            {"name": "unknown_db", "databaseType": "local"},
        )

    def show_schemas(self, database: str):
        if database == "mysql_prod":
            raise SkillError(category="metadata", code="timeout", retry_class="transient")
        if database == "unknown_db":
            return ("public",)
        return ("ads", "dwd", "tmp")

    def show_relations(self, database: str):
        if database == "unknown_db":
            return {"public": ({"name": "mystery", "relationType": "table"},)}
        return {
            "ads": ({"name": "payment_summary", "relationType": "table"},),
            "dwd": ({"name": "fact_payment", "relationType": "table"},),
            "tmp": ({"name": "payment_scratch", "relationType": "table"},),
        }

    def show_columns(self, database: str):
        if database == "unknown_db":
            return {
                "unknown_db.public.mystery": (
                    {"name": "id", "dataType": "bigint", "nullable": False},
                )
            }
        return {
            "dbt_dw.ads.payment_summary": (
                {"name": "company_id", "dataType": "bigint", "nullable": True},
                {"name": "payment_amount", "dataType": "numeric", "nullable": True},
            ),
            "dbt_dw.dwd.fact_payment": (
                {"name": "payment_id", "dataType": "bigint", "nullable": False},
            ),
            "dbt_dw.tmp.payment_scratch": (
                {"name": "payment_id", "dataType": "bigint", "nullable": False},
            ),
        }


class EmptyMetadataSource:
    def show_databases(self):
        return ({"name": "empty_db", "databaseType": "local"},)

    def show_schemas(self, database: str):
        return ()

    def show_relations(self, database: str):
        return {}

    def show_columns(self, database: str):
        return {}


DOMAIN_MAP = {
    "schemaVersion": 1,
    "databases": {
        "dbt_dw": {"sourceType": "warehouse"},
        "unknown_db": {"sourceType": "unknown"},
    },
    "relations": {
        "dbt_dw.ads.payment_summary": {
            "domain": "payment",
            "subdomain": "analytics",
            "service": "data-warehouse",
            "layer": "ads",
            "hiddenByDefault": False,
        },
        "dbt_dw.dwd.fact_payment": {
            "domain": "payment",
            "subdomain": "transaction",
            "service": "data-warehouse",
            "layer": "dwd",
            "hiddenByDefault": False,
        },
        "dbt_dw.tmp.payment_scratch": {
            "domain": "payment",
            "subdomain": "temporary",
            "service": "data-warehouse",
            "layer": "tmp",
            "hiddenByDefault": True,
        },
        "unknown_db.public.mystery": {
            "domain": None,
            "subdomain": None,
            "service": None,
            "layer": "unknown",
            "hiddenByDefault": False,
        },
    },
}


def _catalog(tmp_path):
    return build_catalog(
        tmp_path / "catalog.jsonl",
        SearchMetadataSource(),
        generated_at=datetime(2026, 7, 15, tzinfo=timezone.utc),
        domain_map=DOMAIN_MAP,
    )


def test_search_uses_validated_enrichment_hides_noise_and_warns_on_incomplete_coverage(tmp_path) -> None:
    catalog = _catalog(tmp_path)

    result = search_catalog(
        catalog,
        text="payment",
        now=datetime(2026, 7, 20, tzinfo=timezone.utc),
    )

    assert result["catalogFreshness"] == "fresh"
    assert result["authoritative"] is False
    assert result["coverage"]["status"] == "incomplete"
    assert result["warnings"] == [{"code": "catalog.coverage_incomplete"}]
    assert [match["object"] for match in result["matches"]] == [
        "dbt_dw.ads.payment_summary",
        "dbt_dw.dwd.fact_payment",
    ]
    assert result["matches"][0]["domain"] == "payment"

    stale = search_catalog(
        catalog,
        text="payment",
        now=datetime(2026, 7, 23, tzinfo=timezone.utc),
    )
    assert stale["catalogFreshness"] == "stale"


def test_search_applies_all_filters_and_token_matching_without_runtime_guessing(tmp_path) -> None:
    catalog = _catalog(tmp_path)

    result = search_catalog(
        catalog,
        text="payment amount",
        database="dbt_dw",
        source_type="warehouse",
        schema="ads",
        layer="ads",
        domain="payment",
        kind="all",
        now=datetime(2026, 7, 20, tzinfo=timezone.utc),
    )

    assert [match["object"] for match in result["matches"]] == [
        "dbt_dw.ads.payment_summary"
    ]
    assert result["matches"][0]["matchedOn"] == ["table", "column"]

    hidden = search_catalog(
        catalog,
        layer="tmp",
        include_hidden=True,
        now=datetime(2026, 7, 20, tzinfo=timezone.utc),
    )
    assert [match["object"] for match in hidden["matches"]] == [
        "dbt_dw.tmp.payment_scratch"
    ]


def test_databases_is_live_first_and_distinguishes_missing_from_explicit_unknown(tmp_path) -> None:
    catalog = _catalog(tmp_path)
    calls = 0

    def fetch_live_databases():
        nonlocal calls
        calls += 1
        return (
            {"name": "dbt_dw", "databaseType": "local"},
            {"name": "mysql_prod", "databaseType": "local"},
            {"name": "unknown_db", "databaseType": "local"},
            {"name": "pg_new", "databaseType": "datashare"},
        )

    result = list_databases(
        fetch_live_databases,
        catalog=catalog,
        now=datetime(2026, 7, 20, tzinfo=timezone.utc),
    )

    assert calls == 1
    assert result["data"] == [
        {
            "name": "dbt_dw",
            "databaseType": "local",
            "sourceType": "warehouse",
            "objectCount": 3,
            "enrichmentStatus": "complete",
            "catalogFreshness": "fresh",
        },
        {
            "name": "mysql_prod",
            "databaseType": "local",
            "sourceType": None,
            "objectCount": None,
            "enrichmentStatus": "incomplete",
            "catalogFreshness": "fresh",
        },
        {
            "name": "unknown_db",
            "databaseType": "local",
            "sourceType": "unknown",
            "objectCount": 1,
            "enrichmentStatus": "complete",
            "catalogFreshness": "fresh",
        },
        {
            "name": "pg_new",
            "databaseType": "datashare",
            "sourceType": None,
            "objectCount": None,
            "enrichmentStatus": "missing",
            "catalogFreshness": "fresh",
        },
    ]

    stale = list_databases(
        fetch_live_databases,
        catalog=catalog,
        now=datetime(2026, 7, 23, tzinfo=timezone.utc),
    )
    assert stale["data"][0]["objectCount"] is None


def test_databases_can_be_technically_complete_without_source_classification(tmp_path) -> None:
    catalog = build_catalog(
        tmp_path / "catalog.jsonl",
        SearchMetadataSource(),
        generated_at=datetime(2026, 7, 15, tzinfo=timezone.utc),
    )

    result = list_databases(
        lambda: ({"name": "dbt_dw", "databaseType": "local"},),
        catalog=catalog,
        now=datetime(2026, 7, 20, tzinfo=timezone.utc),
    )

    assert result["data"] == [
        {
            "name": "dbt_dw",
            "databaseType": "local",
            "sourceType": None,
            "objectCount": 3,
            "enrichmentStatus": "complete",
            "catalogFreshness": "fresh",
        }
    ]


def test_databases_uses_persisted_identity_for_complete_empty_database(
    tmp_path,
) -> None:
    catalog = build_catalog(
        tmp_path / "catalog.jsonl",
        EmptyMetadataSource(),
        generated_at=datetime(2026, 7, 15, tzinfo=timezone.utc),
    )

    fresh = list_databases(
        lambda: ({"name": "empty_db", "databaseType": "local"},),
        catalog=catalog,
        now=datetime(2026, 7, 20, tzinfo=timezone.utc),
    )
    assert fresh["data"] == [
        {
            "name": "empty_db",
            "databaseType": "local",
            "sourceType": None,
            "objectCount": 0,
            "enrichmentStatus": "complete",
            "catalogFreshness": "fresh",
        }
    ]

    stale = list_databases(
        lambda: ({"name": "empty_db", "databaseType": "local"},),
        catalog=catalog,
        now=datetime(2026, 7, 23, tzinfo=timezone.utc),
    )
    assert stale["data"][0]["enrichmentStatus"] == "complete"
    assert stale["data"][0]["objectCount"] is None

    filtered = list_databases(
        lambda: ({"name": "empty_db", "databaseType": "local"},),
        catalog=catalog,
        now=datetime(2026, 7, 20, tzinfo=timezone.utc),
        source_type="warehouse",
    )
    assert filtered["data"] == []


def test_databases_does_not_transfer_empty_identity_to_new_database(tmp_path) -> None:
    catalog = build_catalog(
        tmp_path / "catalog.jsonl",
        EmptyMetadataSource(),
        generated_at=datetime(2026, 7, 15, tzinfo=timezone.utc),
    )

    result = list_databases(
        lambda: ({"name": "new_db", "databaseType": "local"},),
        catalog=catalog,
        now=datetime(2026, 7, 20, tzinfo=timezone.utc),
    )

    assert result["data"][0]["enrichmentStatus"] == "missing"


def test_databases_source_filter_requires_catalog_before_live_inventory() -> None:
    calls = 0

    def fetch_live_databases():
        nonlocal calls
        calls += 1
        return ({"name": "dbt_dw", "databaseType": "local"},)

    with pytest.raises(SkillError) as caught:
        list_databases(
            fetch_live_databases,
            catalog=None,
            now=datetime(2026, 7, 20, tzinfo=timezone.utc),
            source_type="warehouse",
        )

    assert caught.value.full_code == "catalog.unavailable"
    assert calls == 0


def test_databases_source_filter_returns_only_classified_matches(tmp_path) -> None:
    result = list_databases(
        lambda: SearchMetadataSource().show_databases(),
        catalog=_catalog(tmp_path),
        now=datetime(2026, 7, 20, tzinfo=timezone.utc),
        source_type="warehouse",
    )

    assert [row["name"] for row in result["data"]] == ["dbt_dw"]
    assert all(row["sourceType"] == "warehouse" for row in result["data"])
