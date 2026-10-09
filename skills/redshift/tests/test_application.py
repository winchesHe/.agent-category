from __future__ import annotations

import os
import signal
from contextlib import nullcontext
from datetime import datetime, timezone

import pytest

from scripts.rs.application import dispatch
from scripts.rs.catalog.builder import build_catalog
from scripts.rs.catalog.live import MetadataRead
from scripts.rs.cli import build_parser
from scripts.rs.errors import Interrupted, SkillError
from scripts.rs.models import Column, CommandResult, InvocationState, QueryResult
from scripts.rs.query.explain import ExplainResult


BASE_ENV: dict[str, str] = {}


class MetadataCatalogSource:
    def __init__(self, *, incomplete: bool = False) -> None:
        self.incomplete = incomplete

    def show_databases(self):
        return (
            {"name": "dbt_dw", "databaseType": "local"},
            {"name": "pg_new", "databaseType": "datashare"},
        )

    def show_schemas(self, database: str):
        if database == "pg_new" and self.incomplete:
            raise SkillError("metadata", "timeout", "transient")
        return ("ads",)

    def show_relations(self, database: str):
        return {"ads": ({"name": "payment_summary", "relationType": "table"},)}

    def show_columns(self, database: str):
        return {
            f"{database}.ads.payment_summary": (
                {"name": "id", "dataType": "bigint", "nullable": False},
            )
        }


class RecipeCatalogSource:
    def __init__(self, *databases: str) -> None:
        self.databases = databases
        self.calls = 0

    def show_databases(self):
        self.calls += 1
        return tuple(
            {"name": database, "databaseType": "local"}
            for database in self.databases
        )


DOMAIN_MAP = {
    "schemaVersion": 1,
    "databases": {"dbt_dw": {"sourceType": "warehouse"}},
    "relations": {
        "dbt_dw.ads.payment_summary": {
            "domain": "payment",
            "subdomain": None,
            "service": "data-warehouse",
            "layer": "ads",
            "hiddenByDefault": False,
        }
    },
}


def catalog_file(tmp_path, *, incomplete: bool = False):
    path = tmp_path / "catalog.jsonl"
    build_catalog(
        path,
        MetadataCatalogSource(incomplete=incomplete),
        generated_at=datetime(2026, 7, 15, tzinfo=timezone.utc),
        domain_map=DOMAIN_MAP,
    )
    return path


def parsed(*argv: str):
    return build_parser().parse_args(list(argv))


def query_result(database: str, records=({"id": 1},), *, truncated=False):
    return QueryResult(
        columns=(Column("id", "bigint"),),
        records=tuple(records),
        row_count=len(records),
        truncated=truncated,
        elapsed_ms=12,
        connection_database=database,
        statement_timeout_ms=4100,
    )


class BoundConnectivityStub:
    def __init__(
        self,
        *,
        query=None,
        stream_query=None,
        explain=None,
        catalog_source=None,
        describe_source=None,
        preflight=None,
        default_database: str = "default_db",
        default_statement_timeout_ms: int = 4100,
        owns_catalog: bool = True,
        public_meta=None,
    ) -> None:
        self._query = query
        self._stream_query = stream_query
        self._explain = explain
        self._catalog_source = catalog_source
        self._describe_source = describe_source
        self._preflight = preflight
        self.default_database = default_database
        self.default_statement_timeout_ms = default_statement_timeout_ms
        self.owns_catalog = owns_catalog
        self._public_meta = public_meta or (lambda _database: {})

    def query(self, **kwargs):
        if self._query is None:
            pytest.fail("query must not be called")
        return self._query(**kwargs)

    def stream_query(self, **kwargs):
        if self._stream_query is None:
            pytest.fail("stream_query must not be called")
        return self._stream_query(**kwargs)

    def explain(self, **kwargs):
        if self._explain is None:
            pytest.fail("explain must not be called")
        return self._explain(**kwargs)

    def catalog_source(self, database, timeout):
        if self._catalog_source is None:
            pytest.fail("catalog_source must not be called")
        return self._catalog_source(database, timeout)

    def describe_source(self, database, timeout):
        if self._describe_source is None:
            pytest.fail("describe_source must not be called")
        return self._describe_source(database, timeout)

    def preflight(self, *, connect_live):
        if self._preflight is None:
            pytest.fail("preflight must not be called")
        return self._preflight(connect_live=connect_live)

    def public_meta(self, database):
        return self._public_meta(database)


class ConnectivityStub:
    def __init__(self, bound: BoundConnectivityStub) -> None:
        self.bound = bound
        self.bind_calls: list[str | None] = []

    def bind(self, connection_name):
        self.bind_calls.append(connection_name)
        return self.bound


def test_doctor_list_connections_does_not_run_preflight() -> None:
    events: list[str] = []

    class Connectivity:
        def list_connections(self):
            events.append("list")
            return CommandResult(data={"connections": []})

        def preflight(self, *_args, **_kwargs):
            raise AssertionError("static inventory must not run preflight")

    result = dispatch(
        parsed("doctor", "--list-connections"),
        InvocationState(),
        connectivity=Connectivity(),
    )

    assert events == ["list"]
    assert result.data == {"connections": []}


def test_query_dispatch_uses_one_bound_connectivity_dependency() -> None:
    events: list[object] = []

    class BoundConnectivity:
        default_database = "default_db"
        default_statement_timeout_ms = 4100

        def query(self, **kwargs):
            events.append(("query", kwargs))
            return query_result(kwargs["database"])

        def public_meta(self, _database):
            return {}

    class Connectivity:
        def bind(self, connection_name):
            events.append(("bind", connection_name))
            return BoundConnectivity()

    outcome = dispatch(
        parsed("query", "--database", "selected_db", "--sql", "SELECT 1"),
        InvocationState(),
        environ=BASE_ENV,
        connectivity=Connectivity(),
    )

    assert events[0] == ("bind", None)
    assert events[1][0] == "query"
    assert outcome.meta["connectionDatabase"] == "selected_db"


def test_schemas_dispatches_live_metadata_without_loading_catalog(tmp_path) -> None:
    events: list[object] = []

    class LiveSource:
        def show_schemas(self, database):
            events.append(("show_schemas", database))
            return MetadataRead(
                rows=(
                    {"name": "pg_catalog"},
                    {"name": "public"},
                    {"name": "analytics"},
                )
            )

    class Bound:
        default_database = "control_db"
        default_statement_timeout_ms = 4100

        def live_metadata_source(self, database, timeout):
            events.append(("source", database, timeout))
            return LiveSource()

        def public_meta(self, database):
            return {
                "connectionName": "selected",
                "deployment": "serverless",
                "transport": "data_api",
                "authMode": "iam",
                "connectionDatabase": database,
            }

    class Connectivity:
        def bind(self, connection_name):
            events.append(("bind", connection_name))
            return Bound()

    outcome = dispatch(
        parsed("schemas", "target_db", "--connection", "selected", "--limit", "10"),
        InvocationState(),
        catalog_path=tmp_path / "must-not-be-read.jsonl",
        connectivity=Connectivity(),
    )

    assert [row["name"] for row in outcome.data] == ["analytics", "public"]
    assert outcome.meta["authoritative"] is True
    assert outcome.meta["rowCount"] == 2
    assert outcome.meta["truncated"] is False
    assert events == [
        ("bind", "selected"),
        ("source", "control_db", 4100),
        ("show_schemas", "target_db"),
    ]


def test_relations_dispatches_live_metadata_and_filters_kind() -> None:
    events: list[object] = []

    class LiveSource:
        def show_relations(self, database, schema):
            events.append(("show_relations", database, schema))
            return MetadataRead(
                rows=(
                    {"name": "orders_view", "relationType": "view", "description": "summary"},
                    {"name": "orders", "relationType": "table", "description": None},
                )
            )

    class Bound:
        default_database = "control_db"
        default_statement_timeout_ms = 4100

        def live_metadata_source(self, database, timeout):
            events.append(("source", database, timeout))
            return LiveSource()

        def public_meta(self, database):
            return {
                "connectionName": "selected",
                "deployment": "provisioned",
                "transport": "wire",
                "authMode": "password",
                "connectionDatabase": database,
            }

    class Connectivity:
        def bind(self, connection_name):
            events.append(("bind", connection_name))
            return Bound()

    outcome = dispatch(
        parsed("relations", "target_db.sales", "--connection", "selected", "--kind", "view"),
        InvocationState(),
        connectivity=Connectivity(),
    )

    assert outcome.data == [
        {
            "object": "target_db.sales.orders_view",
            "database": "target_db",
            "schema": "sales",
            "name": "orders_view",
            "relationType": "view",
            "description": "summary",
        }
    ]
    assert outcome.meta["authoritative"] is True
    assert events == [
        ("bind", "selected"),
        ("source", "control_db", 4100),
        ("show_relations", "target_db", "sales"),
    ]


def test_explain_dispatch_uses_the_same_bound_connectivity_seam() -> None:
    events: list[object] = []

    class BoundConnectivity:
        default_database = "default_db"
        default_statement_timeout_ms = 4100

        def explain(self, **kwargs):
            events.append(("explain", kwargs))
            return ExplainResult(
                plan=("scan",),
                advisories=(),
                elapsed_ms=1,
                connection_database=kwargs["database"],
                statement_timeout_ms=kwargs["statement_timeout_ms"],
            )

        def public_meta(self, _database):
            return {}

    class Connectivity:
        def bind(self, connection_name):
            events.append(("bind", connection_name))
            return BoundConnectivity()

    outcome = dispatch(
        parsed("explain", "--database", "selected_db", "--sql", "SELECT 1"),
        InvocationState(),
        environ=BASE_ENV,
        connectivity=Connectivity(),
    )

    assert events[0] == ("bind", None)
    assert events[1][0] == "explain"
    assert outcome.data["plan"] == ("scan",)


def test_query_dispatch_uses_leaf_database_and_env_timeout_without_mutation() -> None:
    calls = []

    def execute(**kwargs):
        calls.append(kwargs)
        return query_result(kwargs["database"])

    env = dict(BASE_ENV)
    before = dict(env)
    state = InvocationState()
    outcome = dispatch(
        parsed(
            "query",
            "--database",
            "selected_db",
            "--sql",
            "SELECT id FROM selected_db.public.items",
        ),
        state,
        environ=env,
        connectivity=ConnectivityStub(BoundConnectivityStub(query=execute)),
    )
    assert calls[0]["database"] == "selected_db"
    assert calls[0]["statement_timeout_ms"] == 4100
    assert outcome.data["records"] == ({"id": 1},)
    assert outcome.meta["connectionDatabase"] == "selected_db"
    assert env == before
    assert state.diagnostics["sqlSha256"]
    assert "SELECT id" not in repr(state.diagnostics)


def test_named_query_reports_only_stable_connection_metadata() -> None:
    bound = BoundConnectivityStub(
        query=lambda **kwargs: query_result(kwargs["database"]),
        public_meta=lambda database: {
            "connectionName": "analytics-api",
            "deployment": "serverless",
            "transport": "data_api",
            "authMode": "iam",
            "connectionDatabase": database,
        },
    )

    outcome = dispatch(
        parsed(
            "query",
            "--connection",
            "analytics-api",
            "--database",
            "analytics",
            "--sql",
            "SELECT 1",
        ),
        InvocationState(),
        environ=BASE_ENV,
        connectivity=ConnectivityStub(bound),
    )

    assert outcome.meta == {
        "elapsedMs": 12,
        "statementTimeoutMs": 4100,
        "connectionDatabase": "analytics",
        "connectionName": "analytics-api",
        "deployment": "serverless",
        "transport": "data_api",
        "authMode": "iam",
    }


def test_named_query_failure_carries_stable_connection_metadata_only() -> None:
    def fail(**_kwargs):
        raise SkillError("query", "failed", "never", details={"stage": "user"})

    bound = BoundConnectivityStub(
        query=fail,
        public_meta=lambda database: {
            "connectionName": "analytics-api",
            "deployment": "serverless",
            "transport": "data_api",
            "authMode": "iam",
            "connectionDatabase": database,
        },
    )

    with pytest.raises(SkillError) as caught:
        dispatch(
            parsed(
                "query",
                "--connection",
                "analytics-api",
                "--sql",
                "SELECT 1",
            ),
            InvocationState(),
            environ=BASE_ENV,
            connectivity=ConnectivityStub(bound),
        )

    assert caught.value.meta == {
        "connectionDatabase": "default_db",
        "connectionName": "analytics-api",
        "deployment": "serverless",
        "transport": "data_api",
        "authMode": "iam",
    }


def test_json_query_never_reads_output_directory() -> None:
    outcome = dispatch(
        parsed("query", "--sql", "SELECT 1"),
        InvocationState(),
        environ=BASE_ENV,
        connectivity=ConnectivityStub(
            BoundConnectivityStub(
                query=lambda **kwargs: query_result(kwargs["database"])
            )
        ),
    )
    assert outcome.data["rowCount"] == 1


def test_artifact_dispatch_publishes_and_returns_only_relative_ref(tmp_path) -> None:
    os.chmod(tmp_path, 0o700)
    env = {**BASE_ENV, "REDSHIFT_OUTPUT_DIR": str(tmp_path)}

    class Stream:
        columns = (Column("id", "bigint"),)
        row_count = 0
        truncated = False
        elapsed_ms = 12
        connection_database = "default_db"
        statement_timeout_ms = 4100

        def __iter__(self):
            self.row_count = 1
            yield {"id": 1}

    outcome = dispatch(
        parsed(
            "query",
            "--sql",
            "SELECT id FROM items",
            "--format",
            "ndjson",
            "--output",
            "items.ndjson",
        ),
        InvocationState(),
        environ=env,
        connectivity=ConnectivityStub(
            BoundConnectivityStub(
                stream_query=lambda **kwargs: nullcontext(Stream())
            )
        ),
    )
    assert outcome.data == {
        "outputRef": "items.ndjson",
        "format": "ndjson",
        "rowCount": 1,
        "truncated": False,
    }
    assert str(tmp_path) not in repr(outcome)
    assert (tmp_path / "items.ndjson").read_text() == '{"id":1}\n'


def test_artifact_dispatch_uses_streaming_query_without_eager_records(tmp_path) -> None:
    os.chmod(tmp_path, 0o700)
    env = {**BASE_ENV, "REDSHIFT_OUTPUT_DIR": str(tmp_path)}
    calls: list[dict[str, object]] = []

    class Stream:
        columns = (Column("id", "bigint"),)
        row_count = 0
        truncated = False
        elapsed_ms = 12
        connection_database = "default_db"
        statement_timeout_ms = 4100

        def __iter__(self):
            self.row_count = 1
            yield {"id": 1}

    def open_stream(**kwargs):
        calls.append(kwargs)
        return nullcontext(Stream())

    outcome = dispatch(
        parsed(
            "query",
            "--sql",
            "SELECT id FROM items",
            "--format",
            "ndjson",
            "--output",
            "items.ndjson",
        ),
        InvocationState(),
        environ=env,
        connectivity=ConnectivityStub(
            BoundConnectivityStub(
                query=lambda **kwargs: pytest.fail("artifact must not use eager query"),
                stream_query=open_stream,
            )
        ),
    )

    assert calls[0]["limit"] == 200
    assert "fmt" not in calls[0]
    assert outcome.data == {
        "outputRef": "items.ndjson",
        "format": "ndjson",
        "rowCount": 1,
        "truncated": False,
    }
    assert (tmp_path / "items.ndjson").read_text(encoding="utf-8") == '{"id":1}\n'


def test_artifact_dispatch_preserves_signal_and_cleans_unpublished_temp(tmp_path) -> None:
    os.chmod(tmp_path, 0o700)
    env = {**BASE_ENV, "REDSHIFT_OUTPUT_DIR": str(tmp_path)}
    interrupted = Interrupted(signal.SIGTERM)

    class Stream:
        columns = (Column("id", "bigint"),)

        def __iter__(self):
            raise interrupted
            yield

    with pytest.raises(Interrupted) as caught:
        dispatch(
            parsed(
                "query",
                "--sql",
                "SELECT id FROM items",
                "--format",
                "ndjson",
                "--output",
                "items.ndjson",
            ),
            InvocationState(),
            environ=env,
            connectivity=ConnectivityStub(
                BoundConnectivityStub(
                    stream_query=lambda **kwargs: nullcontext(Stream())
                )
            ),
        )

    assert caught.value is interrupted
    assert not (tmp_path / "items.ndjson").exists()
    assert not list(tmp_path.glob(".redshift-tmp-*"))


def test_explain_dispatch_keeps_plan_hard_and_advisories_separate() -> None:
    def explain(**kwargs):
        return ExplainResult(
            plan=("scan",),
            advisories=({"code": "query.select_star", "severity": "info", "message": "x"},),
            elapsed_ms=5,
            connection_database=kwargs["database"],
            statement_timeout_ms=kwargs["statement_timeout_ms"],
        )

    outcome = dispatch(
        parsed("explain", "--database", "dbt_dw", "--sql", "SELECT * FROM x"),
        InvocationState(),
        environ=BASE_ENV,
        connectivity=ConnectivityStub(BoundConnectivityStub(explain=explain)),
    )
    assert outcome.data == {
        "plan": ("scan",),
        "advisories": (
            {"code": "query.select_star", "severity": "info", "message": "x"},
        ),
    }
    assert outcome.meta["connectionDatabase"] == "dbt_dw"


def test_recipe_list_is_offline_and_email_recipe_uses_shared_executor() -> None:
    offline_connectivity = ConnectivityStub(BoundConnectivityStub())
    listed = dispatch(
        parsed("recipe", "list"),
        InvocationState(),
        environ={},
        connectivity=offline_connectivity,
    )
    assert listed.data[0]["name"] == "email-to-company"
    assert offline_connectivity.bind_calls == []

    calls = []

    def execute(**kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            return query_result(kwargs["database"], ({"account_id": 1},))
        return QueryResult(
            columns=(Column("account_id", "bigint"), Column("company_id", "bigint")),
            records=({"account_id": 1, "company_id": 2},),
            row_count=1,
            truncated=False,
            elapsed_ms=2,
            connection_database=kwargs["database"],
            statement_timeout_ms=kwargs["statement_timeout_ms"],
        )

    source = RecipeCatalogSource(
        "pg_moego_account_prod",
        "mysql_prod",
    )
    outcome = dispatch(
        parsed("recipe", "email-to-company", "--email", "person@example.invalid"),
        InvocationState(),
        environ=BASE_ENV,
        connectivity=ConnectivityStub(
            BoundConnectivityStub(
                query=execute,
                catalog_source=lambda _database, _timeout: source,
            )
        ),
    )
    assert source.calls == 1
    assert len(calls) == 2
    assert outcome.data["membershipCount"] == 1
    assert "person@example.invalid" not in repr(outcome)


@pytest.mark.parametrize(
    ("arguments", "expected_database"),
    [
        (
            ("recipe", "appointment-timeline", "--appointment-id", "1"),
            "pg_moego_fulfillment_prod",
        ),
        (
            ("recipe", "refund-origin", "--refund-id", "1"),
            "pg_moego_payment_prod",
        ),
        (
            ("recipe", "membership-entitlement", "--membership-id", "1"),
            "pg_moego_membership_prod_v2",
        ),
    ],
)
def test_new_recipe_no_match_dispatches_through_shared_executor(
    arguments, expected_database
) -> None:
    calls = []

    def execute(**kwargs):
        calls.append(kwargs)
        return query_result(kwargs["database"], ())

    source = RecipeCatalogSource(
        "pg_moego_fulfillment_prod",
        "pg_moego_payment_prod",
        "pg_moego_order_prod",
        "pg_moego_membership_prod_v2",
    )
    outcome = dispatch(
        parsed(*arguments),
        InvocationState(),
        environ=BASE_ENV,
        connectivity=ConnectivityStub(
            BoundConnectivityStub(
                query=execute,
                catalog_source=lambda _database, _timeout: source,
            )
        ),
    )
    assert source.calls == 1
    assert len(calls) == 1
    assert calls[0]["database"] == expected_database
    assert outcome.meta["stages"][0]["rowCount"] == 0


def test_recipe_source_preflight_stops_before_any_recipe_sql() -> None:
    source = RecipeCatalogSource("unrelated_database")
    query_calls: list[object] = []

    with pytest.raises(SkillError) as caught:
        dispatch(
            parsed("recipe", "appointment-timeline", "--appointment-id", "1"),
            InvocationState(),
            environ=BASE_ENV,
            connectivity=ConnectivityStub(
                BoundConnectivityStub(
                    query=lambda **kwargs: query_calls.append(kwargs),
                    catalog_source=lambda _database, _timeout: source,
                )
            ),
        )

    assert caught.value.full_code == "capability.recipe_source_unavailable"
    assert caught.value.retry_class == "after_change"
    assert caught.value.suggestion == "select_connection"
    assert caught.value.details == {
        "databases": ["pg_moego_fulfillment_prod"]
    }
    assert source.calls == 1
    assert query_calls == []


def test_recipe_source_preflight_rejects_malformed_inventory_as_incomplete() -> None:
    class MalformedSource:
        def show_databases(self):
            return ({"database": "wrong-field"},)

    with pytest.raises(SkillError) as caught:
        dispatch(
            parsed("recipe", "appointment-timeline", "--appointment-id", "1"),
            InvocationState(),
            environ=BASE_ENV,
            connectivity=ConnectivityStub(
                BoundConnectivityStub(
                    query=lambda **_kwargs: pytest.fail("query must not run"),
                    catalog_source=lambda _database, _timeout: MalformedSource(),
                )
            ),
        )

    assert caught.value.full_code == "metadata.incomplete"


def test_unreadable_sql_file_returns_typed_usage_without_path(tmp_path) -> None:
    missing = tmp_path / "contains-private-name.sql"
    with pytest.raises(SkillError) as caught:
        dispatch(
            parsed("query", "--file", str(missing)),
            InvocationState(),
            environ=BASE_ENV,
        )
    assert caught.value.full_code == "usage.invalid_value"
    assert str(missing) not in repr(caught.value.to_payload())


def test_databases_is_live_first_and_invalid_catalog_only_removes_enrichment(
    tmp_path,
) -> None:
    invalid = tmp_path / "catalog.jsonl"
    invalid.write_text("not-json\n", encoding="utf-8")
    source = MetadataCatalogSource()

    outcome = dispatch(
        parsed("databases"),
        InvocationState(),
        environ=BASE_ENV,
        catalog_path=invalid,
        connectivity=ConnectivityStub(
            BoundConnectivityStub(catalog_source=lambda database, timeout: source)
        ),
        clock=lambda: datetime(2026, 7, 20, tzinfo=timezone.utc),
    )

    assert [item["name"] for item in outcome.data] == ["dbt_dw", "pg_new"]
    assert all(item["enrichmentStatus"] == "missing" for item in outcome.data)
    assert all(item["catalogFreshness"] is None for item in outcome.data)
    assert outcome.meta == {"catalogGeneratedAt": None, "coverage": None}


def test_databases_without_filter_uses_live_inventory_when_catalog_is_missing(
    tmp_path,
) -> None:
    source = MetadataCatalogSource()

    outcome = dispatch(
        parsed("databases"),
        InvocationState(),
        environ=BASE_ENV,
        catalog_path=tmp_path / "missing.jsonl",
        connectivity=ConnectivityStub(
            BoundConnectivityStub(catalog_source=lambda database, timeout: source)
        ),
        clock=lambda: datetime(2026, 7, 20, tzinfo=timezone.utc),
    )

    assert [item["name"] for item in outcome.data] == ["dbt_dw", "pg_new"]
    assert all(item["enrichmentStatus"] == "missing" for item in outcome.data)


@pytest.mark.parametrize(
    ("catalog_contents", "expected_code"),
    [(None, "catalog.unavailable"), ("not-json\n", "catalog.invalid")],
)
def test_databases_source_filter_preserves_catalog_load_errors(
    tmp_path,
    catalog_contents,
    expected_code,
) -> None:
    path = tmp_path / "catalog.jsonl"
    if catalog_contents is not None:
        path.write_text(catalog_contents, encoding="utf-8")

    with pytest.raises(SkillError) as caught:
        dispatch(
            parsed("databases", "--source-type", "warehouse"),
            InvocationState(),
            environ=BASE_ENV,
            catalog_path=path,
            connectivity=ConnectivityStub(
                BoundConnectivityStub(
                    catalog_source=lambda database, timeout: MetadataCatalogSource()
                )
            ),
            clock=lambda: datetime(2026, 7, 20, tzinfo=timezone.utc),
        )

    assert caught.value.full_code == expected_code


def test_databases_source_filter_returns_only_catalog_classified_matches(
    tmp_path,
) -> None:
    outcome = dispatch(
        parsed("databases", "--source-type", "warehouse"),
        InvocationState(),
        environ=BASE_ENV,
        catalog_path=catalog_file(tmp_path),
        connectivity=ConnectivityStub(
            BoundConnectivityStub(
                catalog_source=lambda database, timeout: MetadataCatalogSource()
            )
        ),
        clock=lambda: datetime(2026, 7, 20, tzinfo=timezone.utc),
    )

    assert [item["name"] for item in outcome.data] == ["dbt_dw"]
    assert outcome.data[0]["sourceType"] == "warehouse"


def test_non_catalog_connection_never_joins_catalog_enrichment(tmp_path) -> None:
    path = catalog_file(tmp_path)
    outcome = dispatch(
        parsed("databases"),
        InvocationState(),
        environ=BASE_ENV,
        catalog_path=path,
        connectivity=ConnectivityStub(
            BoundConnectivityStub(
                owns_catalog=False,
                catalog_source=lambda database, timeout: MetadataCatalogSource(),
            )
        ),
        clock=lambda: datetime(2026, 7, 20, tzinfo=timezone.utc),
    )

    assert [item["name"] for item in outcome.data] == ["dbt_dw", "pg_new"]
    assert all(item["sourceType"] is None for item in outcome.data)
    assert all(item["enrichmentStatus"] == "missing" for item in outcome.data)
    assert outcome.meta == {"catalogGeneratedAt": None, "coverage": None}


def test_non_catalog_connection_rejects_catalog_source_filter(tmp_path) -> None:
    with pytest.raises(SkillError) as caught:
        dispatch(
            parsed("databases", "--source-type", "warehouse"),
            InvocationState(),
            environ=BASE_ENV,
            catalog_path=catalog_file(tmp_path),
            connectivity=ConnectivityStub(
                BoundConnectivityStub(
                    owns_catalog=False,
                    catalog_source=lambda database, timeout: MetadataCatalogSource(),
                )
            ),
            clock=lambda: datetime(2026, 7, 20, tzinfo=timezone.utc),
        )

    assert caught.value.full_code == "catalog.unavailable"


def test_search_is_offline_supports_layer_lists_and_carries_coverage(tmp_path) -> None:
    path = catalog_file(tmp_path, incomplete=True)
    offline_connectivity = ConnectivityStub(BoundConnectivityStub())

    outcome = dispatch(
        parsed("search", "payment", "--layer", "ads,dws"),
        InvocationState(),
        environ={},
        catalog_path=path,
        connectivity=offline_connectivity,
        clock=lambda: datetime(2026, 7, 20, tzinfo=timezone.utc),
    )

    assert [item["object"] for item in outcome.data["matches"]] == [
        "dbt_dw.ads.payment_summary"
    ]
    assert outcome.data["coverage"]["status"] == "incomplete"
    assert outcome.data["warnings"] == [{"code": "catalog.coverage_incomplete"}]
    assert offline_connectivity.bind_calls == []


class DescribeSuccess:
    def show_columns(self, object_name: str) -> MetadataRead:
        return MetadataRead(
            rows=(
                {"name": "id", "dataType": "bigint", "nullable": False, "ordinal": 1},
            )
        )

    def svv_all_columns(self, object_name: str) -> MetadataRead:
        raise AssertionError("SHOW succeeded")


class DescribeEmpty(DescribeSuccess):
    def show_columns(self, object_name: str) -> MetadataRead:
        return MetadataRead(rows=())


def test_describe_is_live_and_adds_only_available_catalog_enrichment(tmp_path) -> None:
    path = catalog_file(tmp_path)
    state = InvocationState()

    outcome = dispatch(
        parsed("describe", "dbt_dw.ads.payment_summary"),
        state,
        environ=BASE_ENV,
        catalog_path=path,
        connectivity=ConnectivityStub(
            BoundConnectivityStub(
                describe_source=lambda database, timeout: DescribeSuccess()
            )
        ),
    )

    assert outcome.data["sourceType"] == "warehouse"
    assert outcome.data["layer"] == "ads"
    assert outcome.data["relationType"] == "table"
    assert outcome.data["metadataSource"] == "show_columns"
    assert outcome.data["statistics"]["estimatedRows"] is None
    assert state.diagnostics["metadataFallbackSource"] == "show_columns"


def test_non_catalog_connection_describe_ignores_catalog_enrichment(tmp_path) -> None:
    outcome = dispatch(
        parsed("describe", "dbt_dw.ads.payment_summary"),
        InvocationState(),
        environ=BASE_ENV,
        catalog_path=catalog_file(tmp_path),
        connectivity=ConnectivityStub(
            BoundConnectivityStub(
                owns_catalog=False,
                describe_source=lambda database, timeout: DescribeSuccess(),
            )
        ),
    )

    assert outcome.data["metadataSource"] == "show_columns"
    assert "sourceType" not in outcome.data
    assert "layer" not in outcome.data
    assert "dbt" not in outcome.data


def test_describe_returns_a_round_trippable_canonical_object_name(tmp_path) -> None:
    outcome = dispatch(
        parsed("describe", 'db."mixed.schema"."a""b"'),
        InvocationState(),
        environ=BASE_ENV,
        catalog_path=tmp_path / "missing.jsonl",
        connectivity=ConnectivityStub(
            BoundConnectivityStub(
                describe_source=lambda database, timeout: DescribeSuccess()
            )
        ),
    )

    assert outcome.data["object"] == 'db."mixed.schema"."a""b"'


def test_describe_empty_is_incomplete_when_catalog_proves_database_gap(tmp_path) -> None:
    path = catalog_file(tmp_path, incomplete=True)

    with pytest.raises(SkillError) as caught:
        dispatch(
            parsed("describe", "pg_new.ads.payment_summary"),
            InvocationState(),
            environ=BASE_ENV,
            catalog_path=path,
            connectivity=ConnectivityStub(
                BoundConnectivityStub(
                    describe_source=lambda database, timeout: DescribeEmpty()
                )
            ),
        )

    assert caught.value.full_code == "metadata.incomplete"


def test_describe_not_found_returns_canonical_object_and_search_action(tmp_path) -> None:
    with pytest.raises(SkillError) as caught:
        dispatch(
            parsed("describe", 'db."mixed.schema"."a""b"'),
            InvocationState(),
            environ=BASE_ENV,
            catalog_path=tmp_path / "missing.jsonl",
            connectivity=ConnectivityStub(
                BoundConnectivityStub(
                    describe_source=lambda database, timeout: DescribeEmpty()
                )
            ),
        )

    assert caught.value.to_payload() == {
        "category": "metadata",
        "code": "not_found",
        "retryClass": "after_change",
        "details": {"object": 'db."mixed.schema"."a""b"'},
        "suggestion": "search_object",
    }
    assert caught.value.meta == {"connectionDatabase": "db"}


def test_live_doctor_requires_the_skill_local_connection_registry(
    tmp_path, monkeypatch
) -> None:
    module_path = tmp_path / "skill" / "scripts" / "rs" / "connectivity" / "registry.py"
    monkeypatch.setattr("scripts.rs.connectivity.registry.__file__", str(module_path))

    with pytest.raises(SkillError) as caught:
        dispatch(parsed("doctor"), InvocationState(), environ={})

    assert caught.value.full_code == "config.missing"
    assert caught.value.details == {"key": "connections.json"}
