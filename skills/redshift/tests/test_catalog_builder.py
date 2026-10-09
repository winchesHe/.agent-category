from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from scripts.rs.catalog.builder import build_catalog
from scripts.rs.catalog import load_catalog
from scripts.rs.catalog import builder as catalog_builder
from scripts.rs.errors import SkillError


class CompleteMetadataSource:
    def show_databases(self):
        return (
            {"name": "mysql_prod", "databaseType": "local", "sourceType": "mysql"},
            {"name": "dbt_dw", "databaseType": "local", "sourceType": "warehouse"},
        )

    def show_schemas(self, database: str):
        return {"dbt_dw": ("ads",), "mysql_prod": ("moe_customer",)}[database]

    def show_relations(self, database: str):
        if database == "dbt_dw":
            return {
                "ads": (
                    {
                        "name": "payment_summary",
                        "relationType": "table",
                        "layer": "ads",
                        "moego": {
                            "domain": "payment",
                            "subdomain": None,
                            "service": "data-warehouse",
                        },
                    },
                )
            }
        return {
            "moe_customer": (
                {
                    "name": "customer",
                    "relationType": "table",
                    "layer": "unknown",
                    "moego": {
                        "domain": "customer",
                        "subdomain": None,
                        "service": "customer",
                    },
                },
            )
        }

    def show_columns(self, database: str):
        return {
            "dbt_dw": {
                "dbt_dw.ads.payment_summary": (
                    {"name": "company_id", "dataType": "bigint", "nullable": True},
                )
            },
            "mysql_prod": {
                "mysql_prod.moe_customer.customer": (
                    {"name": "id", "dataType": "bigint", "nullable": False},
                )
            },
        }[database]


class BareMetadataSource:
    def show_databases(self):
        return ({"name": "dbt_dw", "databaseType": "local"},)

    def show_schemas(self, database: str):
        return ("public",)

    def show_relations(self, database: str):
        return {"public": ({"name": "events", "relationType": "table"},)}

    def show_columns(self, database: str):
        return {
            "dbt_dw.public.events": (
                {"name": "id", "dataType": "bigint", "nullable": False},
            )
        }


class QuotedMetadataSource:
    def show_databases(self):
        return ({"name": "db", "databaseType": "local"},)

    def show_schemas(self, database: str):
        return ("mixed.schema",)

    def show_relations(self, database: str):
        return {"mixed.schema": ({"name": 'a"b', "relationType": "table"},)}

    def show_columns(self, database: str):
        return {
            'db."mixed.schema"."a""b"': (
                {"name": "id", "dataType": "bigint", "nullable": False},
            )
        }


@pytest.mark.parametrize(
    "column_payload",
    (
        None,
        7,
        "not-a-column-sequence",
        ({"name": "id", "dataType": "bigint", "nullable": False}, 7),
    ),
)
def test_builder_maps_malformed_column_payload_to_incomplete_coverage(
    tmp_path,
    column_payload,
) -> None:
    class MalformedColumnsSource(BareMetadataSource):
        def show_columns(self, database: str):
            if column_payload is None:
                return None
            return {"dbt_dw.public.events": column_payload}

    destination = tmp_path / "catalog.jsonl"

    build_catalog(
        destination,
        MalformedColumnsSource(),
        generated_at=datetime(2026, 7, 15, tzinfo=timezone.utc),
    )

    catalog = load_catalog(destination)
    assert catalog.meta.coverage.status == "incomplete"
    assert catalog.meta.coverage.failed_databases == (
        {
            "database": "dbt_dw",
            "stage": "columns",
            "code": "metadata.incomplete",
        },
    )
    assert catalog.relations[0].columns == ()


def test_builder_publishes_one_valid_deterministically_sorted_jsonl(tmp_path) -> None:
    destination = tmp_path / "catalog.jsonl"

    build_catalog(
        destination,
        CompleteMetadataSource(),
        generated_at=datetime(2026, 7, 15, tzinfo=timezone.utc),
    )

    catalog = load_catalog(destination)
    assert [relation.object for relation in catalog.relations] == [
        "dbt_dw.ads.payment_summary",
        "mysql_prod.moe_customer.customer",
    ]
    assert catalog.meta.database_count == 2
    assert catalog.meta.relation_count == 2
    assert catalog.meta.column_count == 2
    assert catalog.meta.source_types == {"warehouse": 1, "mysql": 1}
    assert catalog.meta.coverage.status == "complete"
    assert catalog.meta.coverage.complete_database_count == 2
    assert catalog.meta.coverage.failed_databases == ()
    assert catalog.meta.complete_empty_databases == ()
    assert not list(tmp_path.glob(".*.tmp"))


def test_builder_persists_complete_empty_database_identity(tmp_path) -> None:
    class EmptySource:
        def show_databases(self):
            return (
                {
                    "name": "empty_db",
                    "databaseType": "local",
                    "sourceType": "postgres",
                },
            )

        def show_schemas(self, database: str):
            return ()

        def show_relations(self, database: str):
            return {}

        def show_columns(self, database: str):
            return {}

    catalog = build_catalog(
        tmp_path / "catalog.jsonl",
        EmptySource(),
        generated_at=datetime(2026, 7, 15, tzinfo=timezone.utc),
    )

    assert catalog.meta.complete_empty_databases == (
        {"name": "empty_db", "databaseType": "local", "sourceType": "postgres"},
    )


def test_builder_defaults_absent_optional_enrichment_without_guessing(tmp_path) -> None:
    catalog = build_catalog(
        tmp_path / "catalog.jsonl",
        BareMetadataSource(),
        generated_at=datetime(2026, 7, 15, tzinfo=timezone.utc),
    )

    relation = catalog.relations[0]
    assert relation.source_type is None
    assert relation.moego == {"domain": None, "subdomain": None, "service": None}
    assert relation.layer == "unknown"
    assert relation.hidden_by_default is False
    assert catalog.meta.source_types == {}


def test_builder_uses_canonical_quoted_object_keys_for_columns(tmp_path) -> None:
    catalog = build_catalog(
        tmp_path / "catalog.jsonl",
        QuotedMetadataSource(),
        generated_at=datetime(2026, 7, 15, tzinfo=timezone.utc),
    )

    relation = catalog.relations[0]
    assert relation.object == 'db."mixed.schema"."a""b"'
    assert relation.columns == (
        {"name": "id", "dataType": "bigint", "nullable": False},
    )
    assert catalog.meta.coverage.status == "complete"


@pytest.mark.parametrize(
    ("schema", "name"),
    [
        ("dbt_test__audit", "accepted_values_orders"),
        ("audit", "daily_checks"),
        ("tests", "relationships_customer"),
        ("tmp", "payment_stage"),
        ("public", "tmp_payment_stage"),
        ("public", "payment_stage_temp"),
        ("public", "dbt_test__not_null_customer"),
    ],
)
def test_builder_marks_explicit_technical_noise_hidden_by_default(
    tmp_path,
    schema: str,
    name: str,
) -> None:
    class NoiseSource(BareMetadataSource):
        def show_schemas(self, database: str):
            return (schema,)

        def show_relations(self, database: str):
            return {schema: ({"name": name, "relationType": "table"},)}

        def show_columns(self, database: str):
            return {
                f"dbt_dw.{schema}.{name}": (
                    {"name": "id", "dataType": "bigint", "nullable": False},
                )
            }

    catalog = build_catalog(
        tmp_path / "catalog.jsonl",
        NoiseSource(),
        generated_at=datetime(2026, 7, 15, tzinfo=timezone.utc),
    )

    assert catalog.relations[0].hidden_by_default is True


class IncompleteMetadataSource(CompleteMetadataSource):
    def show_columns(self, database: str):
        if database == "mysql_prod":
            raise SkillError(
                category="metadata",
                code="timeout",
                retry_class="transient",
                message="raw driver detail must not be persisted",
            )
        return super().show_columns(database)


def test_builder_publishes_only_precisely_bounded_incomplete_coverage(tmp_path) -> None:
    destination = tmp_path / "catalog.jsonl"

    build_catalog(
        destination,
        IncompleteMetadataSource(),
        generated_at=datetime(2026, 7, 15, tzinfo=timezone.utc),
    )

    catalog = load_catalog(destination)
    assert catalog.meta.coverage.status == "incomplete"
    assert catalog.meta.coverage.visible_database_count == 2
    assert catalog.meta.coverage.complete_database_count == 1
    assert catalog.meta.coverage.failed_databases == (
        {"database": "mysql_prod", "stage": "columns", "code": "metadata.timeout"},
    )
    mysql_relation = next(item for item in catalog.relations if item.database == "mysql_prod")
    assert mysql_relation.columns == ()
    assert "raw driver detail" not in destination.read_text(encoding="utf-8")


@pytest.mark.parametrize("stage", ["relations", "columns"])
def test_builder_records_metadata_limit_overflow_as_incomplete_database(
    tmp_path, stage: str
) -> None:
    class OverflowSource(CompleteMetadataSource):
        def show_relations(self, database: str):
            if database == "mysql_prod" and stage == "relations":
                raise SkillError("metadata", "limit_exceeded", "after_change")
            return super().show_relations(database)

        def show_columns(self, database: str):
            if database == "mysql_prod" and stage == "columns":
                raise SkillError("metadata", "limit_exceeded", "after_change")
            return super().show_columns(database)

    catalog = build_catalog(
        tmp_path / "catalog.jsonl",
        OverflowSource(),
        generated_at=datetime(2026, 7, 15, tzinfo=timezone.utc),
    )

    assert catalog.meta.coverage.status == "incomplete"
    assert catalog.meta.coverage.failed_databases == (
        {
            "database": "mysql_prod",
            "stage": stage,
            "code": "metadata.limit_exceeded",
        },
    )


class FailedCollectionStageSource(CompleteMetadataSource):
    def __init__(self, stage: str) -> None:
        self.stage = stage

    def show_schemas(self, database: str):
        if database == "mysql_prod" and self.stage == "schemas":
            raise SkillError(category="metadata", code="timeout", retry_class="transient")
        return super().show_schemas(database)

    def show_relations(self, database: str):
        if database == "mysql_prod" and self.stage == "relations":
            raise SkillError(
                category="metadata",
                code="permission_denied",
                retry_class="never",
            )
        return super().show_relations(database)


@pytest.mark.parametrize(
    ("stage", "code"),
    [
        ("schemas", "metadata.timeout"),
        ("relations", "metadata.permission_denied"),
    ],
)
def test_builder_publishes_each_precisely_bounded_failed_stage(
    tmp_path,
    stage: str,
    code: str,
) -> None:
    destination = tmp_path / "catalog.jsonl"

    catalog = build_catalog(
        destination,
        FailedCollectionStageSource(stage),
        generated_at=datetime(2026, 7, 15, tzinfo=timezone.utc),
    )

    assert catalog.meta.database_count == 1
    assert catalog.meta.relation_count == 1
    assert catalog.meta.column_count == 1
    assert catalog.meta.coverage.visible_database_count == 2
    assert catalog.meta.coverage.complete_database_count == 1
    assert catalog.meta.coverage.failed_databases == (
        {"database": "mysql_prod", "stage": stage, "code": code},
    )


def test_builder_applies_explicit_domain_map_without_guessing_missing_entries(tmp_path) -> None:
    destination = tmp_path / "catalog.jsonl"
    domain_map = {
        "schemaVersion": 1,
        "databases": {"dbt_dw": {"sourceType": "warehouse"}},
        "relations": {
            "dbt_dw.ads.payment_summary": {
                "domain": "payment",
                "subdomain": "transaction",
                "service": "data-warehouse",
                "layer": "ads",
                "hiddenByDefault": True,
            }
        },
    }

    build_catalog(
        destination,
        CompleteMetadataSource(),
        generated_at=datetime(2026, 7, 15, tzinfo=timezone.utc),
        domain_map=domain_map,
    )

    catalog = load_catalog(destination)
    warehouse = next(item for item in catalog.relations if item.database == "dbt_dw")
    unmapped = next(item for item in catalog.relations if item.database == "mysql_prod")
    assert warehouse.source_type == "warehouse"
    assert warehouse.moego == {
        "domain": "payment",
        "subdomain": "transaction",
        "service": "data-warehouse",
    }
    assert warehouse.layer == "ads"
    assert warehouse.hidden_by_default is True
    assert unmapped.source_type is None
    assert unmapped.moego == {"domain": None, "subdomain": None, "service": None}
    assert unmapped.layer == "unknown"
    assert catalog.meta.source_types == {"warehouse": 1}
    assert catalog.meta.evidence_sources == (
        "redshift_live_metadata",
        "maintained_domain_map",
    )


@pytest.mark.parametrize(
    ("schema", "expected"),
    [
        ("ads", "ads"),
        ("dws_daily", "dws"),
        ("dim", "dim"),
        ("dwd_10mins", "dwd"),
        ("ods_source", "ods"),
        ("raw", "raw"),
        ("business_named_schema", "unknown"),
    ],
)
def test_builder_derives_only_explicit_warehouse_schema_layers(
    tmp_path,
    schema: str,
    expected: str,
) -> None:
    class WarehouseSource(BareMetadataSource):
        def show_schemas(self, database: str):
            return (schema,)

        def show_relations(self, database: str):
            return {schema: ({"name": "events", "relationType": "table"},)}

        def show_columns(self, database: str):
            return {
                f"dbt_dw.{schema}.events": (
                    {"name": "id", "dataType": "bigint", "nullable": False},
                )
            }

    domain_map = {
        "schemaVersion": 1,
        "databases": {"dbt_dw": {"sourceType": "warehouse"}},
        "relations": {},
    }
    catalog = build_catalog(
        tmp_path / "catalog.jsonl",
        WarehouseSource(),
        generated_at=datetime(2026, 7, 15, tzinfo=timezone.utc),
        domain_map=domain_map,
    )

    assert catalog.relations[0].layer == expected


def test_builder_fetches_relations_once_per_database_and_filters_to_visible_schemas(
    tmp_path,
) -> None:
    class BatchedSource(BareMetadataSource):
        def __init__(self) -> None:
            self.relation_calls: list[str] = []

        def show_schemas(self, database: str):
            return ("public", "analytics")

        def show_relations(self, database: str):
            self.relation_calls.append(database)
            return {
                "public": ({"name": "events", "relationType": "table"},),
                "analytics": ({"name": "daily", "relationType": "view"},),
                "not_visible": ({"name": "secret", "relationType": "table"},),
            }

        def show_columns(self, database: str):
            return {
                "dbt_dw.public.events": (),
                "dbt_dw.analytics.daily": (),
            }

    source = BatchedSource()

    catalog = build_catalog(
        tmp_path / "catalog.jsonl",
        source,
        generated_at=datetime(2026, 7, 15, tzinfo=timezone.utc),
    )

    assert source.relation_calls == ["dbt_dw"]
    assert [relation.object for relation in catalog.relations] == [
        "dbt_dw.analytics.daily",
        "dbt_dw.public.events",
    ]


def test_builder_marks_missing_relation_columns_as_bounded_incomplete(tmp_path) -> None:
    class MissingColumnsSource(CompleteMetadataSource):
        def show_columns(self, database: str):
            if database == "mysql_prod":
                return {}
            return super().show_columns(database)

    catalog = build_catalog(
        tmp_path / "catalog.jsonl",
        MissingColumnsSource(),
        generated_at=datetime(2026, 7, 15, tzinfo=timezone.utc),
    )

    assert catalog.meta.coverage.failed_databases == (
        {
            "database": "mysql_prod",
            "stage": "columns",
            "code": "metadata.incomplete",
        },
    )


def test_builder_does_not_replace_catalog_with_an_impossible_empty_universe(tmp_path) -> None:
    class EmptyUniverseSource(CompleteMetadataSource):
        def show_databases(self):
            return ()

    destination = tmp_path / "catalog.jsonl"
    destination.write_bytes(b"old-catalog\n")

    with pytest.raises(SkillError) as caught:
        build_catalog(
            destination,
            EmptyUniverseSource(),
            generated_at=datetime(2026, 7, 15, tzinfo=timezone.utc),
        )

    assert caught.value.full_code == "metadata.incomplete"
    assert destination.read_bytes() == b"old-catalog\n"


class UnknownDatabaseUniverseSource(CompleteMetadataSource):
    def show_databases(self):
        raise SkillError(
            category="metadata",
            code="timeout",
            retry_class="transient",
            message="raw driver detail must not be persisted",
        )


def test_builder_does_not_publish_when_database_universe_is_unknown(tmp_path) -> None:
    destination = tmp_path / "catalog.jsonl"
    original = b"old-catalog-must-survive\n"
    destination.write_bytes(original)

    with pytest.raises(SkillError) as caught:
        build_catalog(
            destination,
            UnknownDatabaseUniverseSource(),
            generated_at=datetime(2026, 7, 15, tzinfo=timezone.utc),
        )

    assert caught.value.full_code == "metadata.timeout"
    assert destination.read_bytes() == original
    assert not list(tmp_path.glob(".*.tmp"))


def test_builder_does_not_publish_when_database_universe_exceeds_limit(tmp_path) -> None:
    destination = tmp_path / "catalog.jsonl"
    original = b"old-catalog-must-survive\n"
    destination.write_bytes(original)

    class OverflowUniverseSource(CompleteMetadataSource):
        def show_databases(self):
            raise SkillError("metadata", "limit_exceeded", "after_change")

    with pytest.raises(SkillError) as caught:
        build_catalog(
            destination,
            OverflowUniverseSource(),
            generated_at=datetime(2026, 7, 15, tzinfo=timezone.utc),
        )

    assert caught.value.full_code == "metadata.limit_exceeded"
    assert destination.read_bytes() == original


@pytest.mark.parametrize("failure_point", ["temp_fsync", "replace"])
def test_builder_preserves_existing_catalog_on_every_prepublish_failure(
    tmp_path,
    monkeypatch,
    failure_point: str,
) -> None:
    destination = tmp_path / "catalog.jsonl"
    original = b"old-catalog-must-survive\n"
    destination.write_bytes(original)

    if failure_point == "temp_fsync":
        monkeypatch.setattr(
            catalog_builder.os,
            "fsync",
            lambda _fd: (_ for _ in ()).throw(OSError("injected temp fsync failure")),
        )
    else:
        monkeypatch.setattr(
            catalog_builder.os,
            "replace",
            lambda _source, _destination: (_ for _ in ()).throw(
                OSError("injected replace failure")
            ),
        )

    with pytest.raises(SkillError) as caught:
        build_catalog(
            destination,
            CompleteMetadataSource(),
            generated_at=datetime(2026, 7, 15, tzinfo=timezone.utc),
        )

    assert caught.value.full_code == "catalog.publish_failed"
    assert destination.read_bytes() == original
    assert not list(tmp_path.glob(".*.tmp"))


@pytest.mark.parametrize("failure_point", ["mkdir", "mkstemp"])
def test_builder_maps_destination_setup_failures_to_publish_failed(
    tmp_path,
    monkeypatch,
    failure_point: str,
) -> None:
    destination = tmp_path / "nested" / "catalog.jsonl"

    if failure_point == "mkdir":
        monkeypatch.setattr(
            Path,
            "mkdir",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("injected mkdir failure")),
        )
    else:
        monkeypatch.setattr(
            catalog_builder.tempfile,
            "mkstemp",
            lambda **_kwargs: (_ for _ in ()).throw(OSError("injected mkstemp failure")),
        )

    with pytest.raises(SkillError) as caught:
        build_catalog(
            destination,
            CompleteMetadataSource(),
            generated_at=datetime(2026, 7, 15, tzinfo=timezone.utc),
        )

    assert caught.value.full_code == "catalog.publish_failed"
    assert not destination.exists()
    assert not list(tmp_path.rglob(".*.tmp"))


def test_builder_cleanup_failure_does_not_replace_primary_publish_error(
    tmp_path, monkeypatch
) -> None:
    destination = tmp_path / "catalog.jsonl"
    monkeypatch.setattr(
        catalog_builder.os,
        "fsync",
        lambda _fd: (_ for _ in ()).throw(OSError("primary fsync failure")),
    )
    monkeypatch.setattr(
        Path,
        "unlink",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("cleanup failure")),
    )

    with pytest.raises(SkillError) as caught:
        build_catalog(
            destination,
            CompleteMetadataSource(),
            generated_at=datetime(2026, 7, 15, tzinfo=timezone.utc),
        )

    assert caught.value.full_code == "catalog.publish_failed"
    assert isinstance(caught.value.__cause__, OSError)
    assert str(caught.value.__cause__) == "primary fsync failure"


def test_builder_fdopen_failure_closes_raw_fd_and_removes_temp(
    tmp_path, monkeypatch
) -> None:
    destination = tmp_path / "catalog.jsonl"
    original = b"old-catalog-must-survive\n"
    destination.write_bytes(original)
    opened_fd: int | None = None
    real_mkstemp = catalog_builder.tempfile.mkstemp

    def capture_mkstemp(**kwargs):
        nonlocal opened_fd
        opened_fd, name = real_mkstemp(**kwargs)
        return opened_fd, name

    monkeypatch.setattr(catalog_builder.tempfile, "mkstemp", capture_mkstemp)
    monkeypatch.setattr(
        catalog_builder.os,
        "fdopen",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("fdopen failure")),
    )

    with pytest.raises(SkillError) as caught:
        build_catalog(
            destination,
            CompleteMetadataSource(),
            generated_at=datetime(2026, 7, 15, tzinfo=timezone.utc),
        )

    assert caught.value.full_code == "catalog.publish_failed"
    assert opened_fd is not None
    with pytest.raises(OSError):
        catalog_builder.os.fstat(opened_fd)
    assert destination.read_bytes() == original
    assert not list(tmp_path.glob(".*.tmp"))


def test_builder_reports_unknown_after_replace_if_directory_fsync_fails(
    tmp_path,
    monkeypatch,
) -> None:
    destination = tmp_path / "catalog.jsonl"
    destination.write_bytes(b"old-catalog\n")
    real_fsync = catalog_builder.os.fsync
    calls = 0

    def fail_directory_fsync(fd: int) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("injected directory fsync failure")
        real_fsync(fd)

    monkeypatch.setattr(catalog_builder.os, "fsync", fail_directory_fsync)

    with pytest.raises(SkillError) as caught:
        build_catalog(
            destination,
            CompleteMetadataSource(),
            generated_at=datetime(2026, 7, 15, tzinfo=timezone.utc),
        )

    assert caught.value.full_code == "catalog.publish_unknown"
    assert destination.read_text(encoding="utf-8").startswith('{"columnCount"')
    assert not list(tmp_path.glob(".*.tmp"))


class InvalidTypedMetadataSource(CompleteMetadataSource):
    def show_databases(self):
        return ({"name": "dbt_dw", "databaseType": "mystery", "sourceType": "warehouse"},)


def test_builder_validates_all_records_in_memory_before_creating_temp(
    tmp_path,
    monkeypatch,
) -> None:
    destination = tmp_path / "catalog.jsonl"
    original = b"old-catalog-must-survive\n"
    destination.write_bytes(original)
    monkeypatch.setattr(
        catalog_builder.tempfile,
        "mkstemp",
        lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError("temp must not exist before in-memory validation")
        ),
    )

    with pytest.raises(SkillError) as caught:
        build_catalog(
            destination,
            InvalidTypedMetadataSource(),
            generated_at=datetime(2026, 7, 15, tzinfo=timezone.utc),
        )

    assert caught.value.full_code == "catalog.invalid"
    assert destination.read_bytes() == original
