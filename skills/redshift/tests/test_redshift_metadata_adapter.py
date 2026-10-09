from __future__ import annotations

from contextlib import contextmanager

import pytest

from scripts.rs.catalog.live import describe_object
from scripts.rs.catalog.redshift import (
    RedshiftCatalogSource,
    RedshiftDescribeSource,
    RedshiftLiveMetadataSource,
    parse_object_name,
    render_object_name,
)
from scripts.rs.catalog.identifiers import (
    parse_database_name,
    parse_database_schema_name,
    render_database_name,
    render_database_schema_name,
)
from scripts.rs.errors import SkillError


class DriverFailure(Exception):
    def __init__(self, sqlstate: str) -> None:
        super().__init__("private driver detail")
        self.pgcode = sqlstate


class FakeCursor:
    def __init__(self, connection) -> None:
        self.connection = connection
        self.description = ()
        self._rows = []

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def execute(self, sql, params=None):
        self.connection.calls.append((sql, params))
        if self.connection.failure is not None:
            failure = self.connection.failure
            self.connection.failure = None
            raise failure
        columns, rows = self.connection.responses.pop(0)
        self.description = tuple((name, None) for name in columns)
        self._rows = list(rows)
        if self.connection.add_warning:
            self.connection.notices.append("private warning text")

    def fetchall(self):
        return list(self._rows)

    def fetchmany(self, size):
        batch, self._rows = self._rows[:size], self._rows[size:]
        return batch


class FakeConnection:
    def __init__(self, responses, *, failure=None, add_warning=False) -> None:
        self.responses = list(responses)
        self.failure = failure
        self.add_warning = add_warning
        self.calls = []
        self.notices = []

    def cursor(self):
        return FakeCursor(self)


def factory_for(*connections):
    pending = list(connections)
    factory_calls = []

    @contextmanager
    def factory(**kwargs):
        factory_calls.append(kwargs)
        yield pending.pop(0)

    factory.calls = factory_calls
    return factory


def test_parse_object_name_requires_three_safe_identifier_parts() -> None:
    assert parse_object_name('db."mixed.schema"."a""b"') == (
        "db",
        "mixed.schema",
        'a"b',
    )

    for value in ("table", "schema.table", "a.b.c.d", "a..c", 'a."broken.c'):
        with pytest.raises(SkillError) as caught:
            parse_object_name(value)
        assert caught.value.full_code == "usage.invalid_value"


def test_live_identifier_parsers_support_one_and_two_quoted_parts_only() -> None:
    assert parse_database_name('"Mixed Database"') == "Mixed Database"
    assert parse_database_schema_name('"Mixed Database"."Sales Schema"') == (
        "Mixed Database",
        "Sales Schema",
    )
    assert render_database_name("Mixed Database") == '"Mixed Database"'
    assert render_database_schema_name("Mixed Database", "Sales Schema") == (
        '"Mixed Database"."Sales Schema"'
    )
    for value in ("db.schema", "db.schema.table", "db..schema", '"broken'):
        with pytest.raises(SkillError) as caught:
            parse_database_name(value)
        assert caught.value.full_code == "usage.invalid_value"

    for value in ('"line\nbreak"', '"' + ("界" * 43) + '"'):
        with pytest.raises(SkillError) as caught:
            parse_database_name(value)
        assert caught.value.full_code == "usage.invalid_value"


def test_object_name_renderer_round_trips_quoted_identifier_parts() -> None:
    parts = parse_object_name('db."mixed.schema"."a""b"')

    rendered = render_object_name(*parts)

    assert rendered == 'db."mixed.schema"."a""b"'
    assert parse_object_name(rendered) == parts


def test_live_inventory_uses_show_and_normalizes_database_types() -> None:
    conn = FakeConnection(
        [
            (
                ("database_name", "database_type"),
                (
                    ("dev", "local"),
                    ("shared", "shared"),
                    ("lake", "external"),
                    ("awsdatacatalog", "auto mounted catalog"),
                    ("future", "new-kind"),
                ),
            )
        ]
    )
    factory = factory_for(conn)
    source = RedshiftCatalogSource(
        control_database="dev",
        statement_timeout_ms=5000,
        connection_factory=factory,
    )

    assert source.show_databases() == (
        {"name": "dev", "databaseType": "local"},
        {"name": "shared", "databaseType": "datashare"},
        {"name": "lake", "databaseType": "external"},
        {"name": "awsdatacatalog", "databaseType": "catalog"},
        {"name": "future", "databaseType": "unknown"},
    )
    assert conn.calls == [("SHOW DATABASES", None)]
    assert factory.calls == [
        {"database": "dev", "statement_timeout_ms": 5000}
    ]


def test_interactive_live_metadata_uses_show_for_schemas_and_relations() -> None:
    schema_connection = FakeConnection(
        [
            (
                ("database_name", "schema_name"),
                (("target", "public"), ("target", "pg_catalog")),
            ),
        ]
    )
    relation_connection = FakeConnection(
        [
            (
                (
                    "database_name",
                    "schema_name",
                    "table_name",
                    "table_type",
                    "remarks",
                ),
                (
                    ("target", "public", "orders", "TABLE", None),
                    (
                        "target",
                        "public",
                        "orders_view",
                        "MATERIALIZED VIEW",
                        "summary",
                    ),
                ),
            )
        ]
    )
    factory = factory_for(schema_connection, relation_connection)
    source = RedshiftLiveMetadataSource(
        control_database="control",
        statement_timeout_ms=5000,
        connection_factory=factory,
    )

    schemas = source.show_schemas("target")
    relations = source.show_relations("target", "public")

    assert schemas.rows == ({"name": "public"}, {"name": "pg_catalog"})
    assert relations.rows == (
        {"name": "orders", "relationType": "table", "description": None},
        {"name": "orders_view", "relationType": "view", "description": "summary"},
    )
    assert factory.calls == [
        {"database": "control", "statement_timeout_ms": 5000},
        {"database": "control", "statement_timeout_ms": 5000},
    ]
    assert schema_connection.calls == [
        ('SHOW SCHEMAS FROM DATABASE "target" LIMIT 10000', None),
    ]
    assert relation_connection.calls == [
        ('SHOW TABLES FROM SCHEMA "target"."public" LIMIT 10000', None),
    ]


def test_wire_catalog_metadata_reads_only_n_plus_one_rows_and_reports_overflow() -> None:
    class OverflowCursor(FakeCursor):
        def __init__(self, connection) -> None:
            super().__init__(connection)
            self.fetch_sizes = []

        def fetchall(self):
            raise AssertionError("catalog metadata must not use unbounded fetchall")

        def fetchmany(self, size):
            self.fetch_sizes.append(size)
            return super().fetchmany(size)

    class OverflowConnection(FakeConnection):
        def __init__(self, responses):
            super().__init__(responses)
            self.cursor_instance = None

        def cursor(self):
            self.cursor_instance = OverflowCursor(self)
            return self.cursor_instance

    connection = OverflowConnection(
        [
            (
                ("database_name", "schema_name"),
                tuple(("db", f"schema_{index}") for index in range(10_001)),
            )
        ]
    )
    source = RedshiftCatalogSource(
        control_database="control",
        statement_timeout_ms=5000,
        connection_factory=factory_for(connection),
    )

    with pytest.raises(SkillError) as caught:
        source.show_schemas("db")

    assert caught.value.full_code == "metadata.limit_exceeded"
    assert sum(connection.cursor_instance.fetch_sizes) == 10_001


def test_catalog_show_ceiling_cannot_be_reported_as_complete() -> None:
    connection = FakeConnection(
        [
            (
                ("database_name", "database_type"),
                tuple((f"database_{index}", "local") for index in range(10_000)),
            )
        ]
    )
    source = RedshiftCatalogSource(
        control_database="control",
        statement_timeout_ms=5000,
        connection_factory=factory_for(connection),
    )

    with pytest.raises(SkillError) as caught:
        source.show_databases()

    assert caught.value.full_code == "metadata.limit_exceeded"


def test_interactive_live_metadata_rejects_non_string_remarks() -> None:
    source = RedshiftLiveMetadataSource(
        control_database="control",
        statement_timeout_ms=5000,
        connection_factory=factory_for(
            FakeConnection(
                    [
                        (
                            (
                                "database_name",
                                "schema_name",
                                "table_name",
                                "table_type",
                                "remarks",
                            ),
                            (("target", "public", "orders", "TABLE", 7),),
                        )
                    ]
            )
        ),
    )

    with pytest.raises(SkillError) as caught:
        source.show_relations("target", "public")

    assert caught.value.full_code == "metadata.incomplete"


def test_interactive_live_metadata_requires_exact_scope_fields() -> None:
    schemas = RedshiftLiveMetadataSource(
        control_database="control",
        statement_timeout_ms=5000,
        connection_factory=factory_for(
            FakeConnection([(("schema_name",), (("public",),))])
        ),
    )
    relations = RedshiftLiveMetadataSource(
        control_database="control",
        statement_timeout_ms=5000,
        connection_factory=factory_for(
            FakeConnection(
                [
                    (
                        ("schema_name", "table_name", "table_type", "remarks"),
                        (("public", "orders", "TABLE", None),),
                    )
                ]
            )
        ),
    )

    for operation in (
        lambda: schemas.show_schemas("target"),
        lambda: relations.show_relations("target", "public"),
    ):
        with pytest.raises(SkillError) as caught:
            operation()
        assert caught.value.full_code == "metadata.incomplete"


def test_interactive_live_metadata_rejects_oversized_remarks() -> None:
    source = RedshiftLiveMetadataSource(
        control_database="control",
        statement_timeout_ms=5000,
        connection_factory=factory_for(
            FakeConnection(
                [
                    (
                        (
                            "database_name",
                            "schema_name",
                            "table_name",
                            "table_type",
                            "remarks",
                        ),
                        (("target", "public", "orders", "TABLE", "x" * 4097),),
                    )
                ]
            )
        ),
    )

    with pytest.raises(SkillError) as caught:
        source.show_relations("target", "public")

    assert caught.value.full_code == "metadata.incomplete"


def test_interactive_live_metadata_does_not_fallback_when_show_is_unavailable() -> None:
    source = RedshiftLiveMetadataSource(
        control_database="control",
        statement_timeout_ms=5000,
        connection_factory=factory_for(FakeConnection([], failure=DriverFailure("0A000"))),
    )

    with pytest.raises(SkillError) as caught:
        source.show_schemas("target")

    assert caught.value.full_code == "capability.show_metadata_unavailable"


def test_relation_metadata_rejects_unknown_table_type() -> None:
    connection = FakeConnection(
        [
            (
                ("database_name", "schema_name", "table_name", "table_type", "remarks"),
                (("db", "public", "items", "CORRUPTED", None),),
            )
        ]
    )
    source = RedshiftCatalogSource(
        control_database="control",
        statement_timeout_ms=5000,
        connection_factory=factory_for(connection),
    )

    with pytest.raises(SkillError) as caught:
        source.show_relations("db")

    assert caught.value.full_code == "metadata.incomplete"


def test_builder_metadata_fanout_is_qualified_and_database_bounded() -> None:
    schema_conn = FakeConnection(
        [(('database_name', 'schema_name'), (("db", "public"),))]
    )
    relation_conn = FakeConnection(
        [
            (
                ("database_name", "schema_name", "table_name", "table_type", "remarks"),
                (("db", "public", "items", "VIEW", "description"),),
            )
        ]
    )
    column_conn = FakeConnection(
        [
            (
                (
                    "database_name",
                    "schema_name",
                    "table_name",
                    "column_name",
                    "ordinal_position",
                    "is_nullable",
                    "data_type",
                ),
                (("db", "public", "items", "id", 1, "NO", "bigint"),),
            )
        ]
    )
    factory = factory_for(schema_conn, relation_conn, column_conn)
    source = RedshiftCatalogSource(
        control_database="control",
        statement_timeout_ms=5000,
        connection_factory=factory,
    )

    assert source.show_schemas("db") == ("public",)
    assert source.show_relations("db") == {
        "public": (
            {
                "name": "items",
                "relationType": "view",
                "description": "description",
            },
        )
    }
    assert source.show_columns("db") == {
        "db.public.items": (
            {"name": "id", "dataType": "bigint", "nullable": False, "ordinal": 1},
        )
    }
    assert schema_conn.calls[0] == ('SHOW SCHEMAS FROM DATABASE "db"', None)
    relation_sql, relation_params = relation_conn.calls[0]
    assert "FROM SVV_ALL_TABLES" in relation_sql
    assert "WHERE database_name = %(database)s" in relation_sql
    assert relation_params == {"database": "db"}
    column_sql, column_params = column_conn.calls[0]
    assert "FROM SVV_ALL_COLUMNS" in column_sql
    assert "WHERE database_name = %(database)s" in column_sql
    assert column_params == {"database": "db"}


def test_live_columns_use_canonical_quoted_object_keys() -> None:
    connection = FakeConnection(
        [
            (
                (
                    "database_name",
                    "schema_name",
                    "table_name",
                    "column_name",
                    "ordinal_position",
                    "is_nullable",
                    "data_type",
                ),
                (("db", "mixed.schema", 'a"b', "id", 1, "NO", "bigint"),),
            )
        ]
    )
    source = RedshiftCatalogSource(
        control_database="control",
        statement_timeout_ms=5000,
        connection_factory=factory_for(connection),
    )

    assert source.show_columns("db") == {
        'db."mixed.schema"."a""b"': (
            {"name": "id", "dataType": "bigint", "nullable": False, "ordinal": 1},
        )
    }


def test_column_metadata_rejects_unknown_nullable_value() -> None:
    connection = FakeConnection(
        [
            (
                (
                    "database_name",
                    "schema_name",
                    "table_name",
                    "column_name",
                    "ordinal_position",
                    "is_nullable",
                    "data_type",
                ),
                (("db", "public", "items", "id", 1, None, "bigint"),),
            )
        ]
    )
    source = RedshiftCatalogSource(
        control_database="control",
        statement_timeout_ms=5000,
        connection_factory=factory_for(connection),
    )

    with pytest.raises(SkillError) as caught:
        source.show_columns("db")

    assert caught.value.full_code == "metadata.incomplete"


@pytest.mark.parametrize("ordinal", [1.9, True, 0, -1, "1"])
def test_column_metadata_requires_positive_integer_ordinal(ordinal) -> None:
    connection = FakeConnection(
        [
            (
                (
                    "database_name",
                    "schema_name",
                    "table_name",
                    "column_name",
                    "ordinal_position",
                    "is_nullable",
                    "data_type",
                ),
                (("db", "public", "items", "id", ordinal, "NO", "bigint"),),
            )
        ]
    )
    source = RedshiftCatalogSource(
        control_database="control",
        statement_timeout_ms=5000,
        connection_factory=factory_for(connection),
    )

    with pytest.raises(SkillError) as caught:
        source.show_columns("db")

    assert caught.value.full_code == "metadata.incomplete"


def test_catalog_source_reuses_one_control_connection_inside_context() -> None:
    control = FakeConnection(
        [
            (("database_name", "database_type"), (("db", "local"),)),
            (("database_name", "schema_name"), (("db", "public"),)),
            (
                ("database_name", "schema_name", "table_name", "table_type", "remarks"),
                (("db", "public", "items", "TABLE", None),),
            ),
            (
                (
                    "database_name",
                    "schema_name",
                    "table_name",
                    "column_name",
                    "ordinal_position",
                    "is_nullable",
                    "data_type",
                ),
                (("db", "public", "items", "id", 1, "NO", "bigint"),),
            ),
        ]
    )
    factory = factory_for(control)

    with RedshiftCatalogSource(
        control_database="control",
        statement_timeout_ms=5000,
        connection_factory=factory,
    ) as source:
        source.show_databases()
        source.show_schemas("db")
        source.show_relations("db")
        source.show_columns("db")

    assert factory.calls == [
        {"database": "control", "statement_timeout_ms": 5000}
    ]
    assert len(control.calls) == 4


def test_describe_show_first_and_exact_svv_fallback() -> None:
    show_conn = FakeConnection([], failure=DriverFailure("0A000"))
    fallback_conn = FakeConnection(
        [
            (
                ("column_name", "ordinal_position", "is_nullable", "data_type"),
                (("id", 1, "NO", "bigint"),),
            )
        ]
    )
    factory = factory_for(show_conn, fallback_conn)
    source = RedshiftDescribeSource(
        control_database="control",
        statement_timeout_ms=5000,
        connection_factory=factory,
    )

    result = describe_object("db.public.items", source)

    assert result["metadataSource"] == "svv_all_columns"
    assert result["columns"][0] == {
        "name": "id",
        "dataType": "bigint",
        "nullable": False,
        "ordinal": 1,
    }
    assert show_conn.calls[0] == (
        'SHOW COLUMNS FROM TABLE "db"."public"."items"',
        None,
    )
    fallback_sql, fallback_params = fallback_conn.calls[0]
    assert "WHERE database_name = %(database)s" in fallback_sql
    assert "AND schema_name = %(schema)s" in fallback_sql
    assert "AND table_name = %(table)s" in fallback_sql
    assert fallback_params == {
        "database": "db",
        "schema": "public",
        "table": "items",
    }


def test_describe_permission_and_warning_never_become_not_found() -> None:
    permission = RedshiftDescribeSource(
        control_database="control",
        statement_timeout_ms=5000,
        connection_factory=factory_for(
            FakeConnection([], failure=DriverFailure("42501"))
        ),
    )
    with pytest.raises(SkillError) as caught:
        describe_object("db.public.items", permission)
    assert caught.value.full_code == "metadata.permission_denied"

    warning = RedshiftDescribeSource(
        control_database="control",
        statement_timeout_ms=5000,
        connection_factory=factory_for(
            FakeConnection(
                [(('column_name', 'ordinal_position', 'is_nullable', 'data_type'), ())],
                add_warning=True,
            )
        ),
    )
    with pytest.raises(SkillError) as caught:
        describe_object("db.public.items", warning)
    assert caught.value.full_code == "metadata.incomplete"
    assert "private warning text" not in repr(caught.value.to_payload())
