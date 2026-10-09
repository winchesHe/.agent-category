from __future__ import annotations

import pytest

from scripts.rs.catalog.live import MetadataRead, describe_object, list_relations, list_schemas
from scripts.rs.errors import SkillError


class ShowSuccessSource:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def show_columns(self, object_name: str) -> MetadataRead:
        self.calls.append("show")
        return MetadataRead(
            rows=(
                {"name": "payment_id", "dataType": "bigint", "nullable": False, "ordinal": 1},
                {"name": "amount", "dataType": "numeric", "nullable": True, "ordinal": 2},
            )
        )

    def svv_all_columns(self, object_name: str) -> MetadataRead:
        self.calls.append("svv")
        raise AssertionError("fallback must not run after SHOW success")


def test_describe_uses_show_as_the_authoritative_first_path() -> None:
    source = ShowSuccessSource()

    result = describe_object("dbt_dw.ads.payment_summary", source)

    assert source.calls == ["show"]
    assert result == {
        "object": "dbt_dw.ads.payment_summary",
        "metadataSource": "show_columns",
        "complete": True,
        "columns": [
            {"name": "payment_id", "dataType": "bigint", "nullable": False, "ordinal": 1},
            {"name": "amount", "dataType": "numeric", "nullable": True, "ordinal": 2},
        ],
    }


class UnsupportedShowSource:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def show_columns(self, object_name: str) -> MetadataRead:
        self.calls.append("show")
        raise SkillError(
            category="capability",
            code="show_metadata_unavailable",
            retry_class="after_change",
        )

    def svv_all_columns(self, object_name: str) -> MetadataRead:
        self.calls.append("svv")
        return MetadataRead(
            rows=({"name": "id", "dataType": "bigint", "nullable": False, "ordinal": 1},)
        )


def test_describe_falls_back_only_when_show_is_unsupported() -> None:
    source = UnsupportedShowSource()

    result = describe_object("mysql_prod.moe_customer.customer", source)

    assert source.calls == ["show", "svv"]
    assert result["metadataSource"] == "svv_all_columns"
    assert result["columns"] == [
        {"name": "id", "dataType": "bigint", "nullable": False, "ordinal": 1}
    ]


class NegativeMetadataSource:
    def __init__(self, outcome: str) -> None:
        self.outcome = outcome
        self.calls: list[str] = []

    def show_columns(self, object_name: str) -> MetadataRead:
        self.calls.append("show")
        if self.outcome == "permission":
            raise SkillError(
                category="metadata",
                code="permission_denied",
                retry_class="never",
            )
        if self.outcome == "warning":
            return MetadataRead(rows=(), warnings=("metadata warning",))
        if self.outcome == "incomplete":
            return MetadataRead(rows=(), complete=False)
        return MetadataRead(rows=())

    def svv_all_columns(self, object_name: str) -> MetadataRead:
        self.calls.append("svv")
        raise AssertionError("negative SHOW outcomes must not fall back")


@pytest.mark.parametrize(
    ("outcome", "full_code", "retry_class"),
    [
        ("permission", "metadata.permission_denied", "never"),
        ("warning", "metadata.incomplete", "transient"),
        ("incomplete", "metadata.incomplete", "transient"),
        ("not_found", "metadata.not_found", "after_change"),
    ],
)
def test_describe_keeps_permission_incomplete_and_not_found_distinct(
    outcome: str,
    full_code: str,
    retry_class: str,
) -> None:
    source = NegativeMetadataSource(outcome)

    with pytest.raises(SkillError) as caught:
        describe_object("dbt_dw.ads.missing", source)

    assert source.calls == ["show"]
    assert caught.value.full_code == full_code
    assert caught.value.retry_class == retry_class


class DiscoverySource:
    def __init__(
        self, schemas=(), relations=(), *, warning=False, complete=True, truncated=False
    ):
        self.schemas = tuple(schemas)
        self.relations = tuple(relations)
        self.warning = warning
        self.complete = complete
        self.truncated = truncated
        self.calls: list[tuple[str, ...]] = []

    def show_schemas(self, database: str) -> MetadataRead:
        self.calls.append(("schemas", database))
        return MetadataRead(
            rows=tuple({"name": name} for name in self.schemas),
            warnings=("warning",) if self.warning else (),
            complete=self.complete,
            truncated=self.truncated,
        )

    def show_relations(self, database: str, schema: str) -> MetadataRead:
        self.calls.append(("relations", database, schema))
        return MetadataRead(
            rows=self.relations,
            warnings=("warning",) if self.warning else (),
            complete=self.complete,
            truncated=self.truncated,
        )


def test_schemas_hides_system_names_sorts_and_reports_truncation() -> None:
    source = DiscoverySource(
        schemas=("public", "pg_catalog", "analytics", "information_schema")
    )

    result = list_schemas(
        '"Mixed Database"', source, include_system=False, limit=1
    )

    assert result == {
        "data": [
            {
                "database": '"Mixed Database"',
                "name": "analytics",
                "object": '"Mixed Database".analytics',
            }
        ],
        "meta": {"authoritative": True, "rowCount": 1, "truncated": True},
    }
    assert source.calls == [("schemas", "Mixed Database")]


def test_schemas_include_system_and_empty_result_is_success() -> None:
    source = DiscoverySource(schemas=("pg_catalog",))

    result = list_schemas("db", source, include_system=True, limit=200)

    assert result["data"] == [
        {"database": "db", "name": "pg_catalog", "object": "db.pg_catalog"}
    ]
    assert result["meta"] == {
        "authoritative": True,
        "rowCount": 1,
        "truncated": False,
    }


def test_schemas_only_hide_exact_system_identifiers() -> None:
    source = DiscoverySource(schemas=("pg_catalog", "PG_CATALOG"))

    result = list_schemas("db", source, include_system=False, limit=200)

    assert result["data"] == [
        {"database": "db", "name": "PG_CATALOG", "object": 'db."PG_CATALOG"'}
    ]


def test_live_discovery_marks_the_redshift_show_ceiling_as_truncated() -> None:
    schemas = DiscoverySource(
        schemas=tuple(f"schema_{index}" for index in range(10_000)), truncated=True
    )
    relations = DiscoverySource(
        relations=tuple(
            {
                "name": f"relation_{index}",
                "relationType": "table",
                "description": None,
            }
            for index in range(10_000)
        ),
        truncated=True,
    )

    assert list_schemas("db", schemas, include_system=False, limit=10_000)["meta"][
        "truncated"
    ] is True
    assert list_relations("db.public", relations, kind="all", limit=10_000)["meta"][
        "truncated"
    ] is True


def test_relations_normalize_types_filter_and_preserve_canonical_names() -> None:
    source = DiscoverySource(
        relations=(
            {"name": 'a"b', "relationType": "view", "description": None},
            {"name": "orders", "relationType": "table", "description": "orders"},
        )
    )

    result = list_relations(
        '"Mixed Database"."Sales Schema"', source, kind="all", limit=200
    )

    assert result["data"] == [
        {
            "object": '"Mixed Database"."Sales Schema"."a""b"',
            "database": '"Mixed Database"',
            "schema": '"Sales Schema"',
            "name": 'a"b',
            "relationType": "view",
            "description": None,
        },
        {
            "object": '"Mixed Database"."Sales Schema".orders',
            "database": '"Mixed Database"',
            "schema": '"Sales Schema"',
            "name": "orders",
            "relationType": "table",
            "description": "orders",
        },
    ]
    assert source.calls == [("relations", "Mixed Database", "Sales Schema")]


def test_live_discovery_keeps_empty_complete_result_and_typed_incomplete() -> None:
    empty = DiscoverySource()
    assert list_relations("db.public", empty, kind="table", limit=200) == {
        "data": [],
        "meta": {"authoritative": True, "rowCount": 0, "truncated": False},
    }

    for source in (DiscoverySource(warning=True), DiscoverySource(complete=False)):
        with pytest.raises(SkillError) as caught:
            list_schemas("db", source, include_system=False, limit=200)
        assert caught.value.full_code == "metadata.incomplete"


@pytest.mark.parametrize(
    "rows",
    [
        ({"name": "orders", "relationType": "procedure", "description": None},),
        ({"name": "界" * 43, "relationType": "table", "description": None},),
        ({"name": "orders", "relationType": "table", "description": 3},),
        ({"name": "orders", "relationType": "table", "description": None},
         {"name": "orders", "relationType": "table", "description": None}),
    ],
)
def test_relations_reject_malformed_or_duplicate_rows(rows) -> None:
    source = DiscoverySource(relations=rows)

    with pytest.raises(SkillError) as caught:
        list_relations("db.public", source, kind="all", limit=200)

    assert caught.value.full_code == "metadata.incomplete"
