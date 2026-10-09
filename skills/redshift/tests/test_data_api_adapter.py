from __future__ import annotations

from datetime import datetime
from decimal import Decimal
import signal

import pytest

from scripts.rs.errors import Interrupted, SkillError
from scripts.rs.connectivity.data_api import DataApiAdapter
from scripts.rs.connectivity.model import (
    AuthenticationConfig,
    AwsCredentialsConfig,
    ConnectionProfile,
    TargetConfig,
)


def data_api_profile() -> ConnectionProfile:
    return ConnectionProfile(
        name="analytics-api",
        deployment="serverless",
        transport="data_api",
        database="analytics",
        target=TargetConfig(region="us-west-2", workgroup_name="analytics"),
        authentication=AuthenticationConfig(mode="iam"),
        aws_credentials=AwsCredentialsConfig(
            source="default",
            expected_account_id="123456789012",
        ),
        tls=None,
        statement_timeout_ms=2500,
    )


class DataApiClient:
    def __init__(self) -> None:
        self.events = []

    def statement_id(self, sql):
        if sql == "BEGIN READ ONLY":
            return "begin"
        if sql.startswith("SET statement_timeout"):
            return "timeout"
        if sql == "SHOW transaction_read_only":
            return "probe"
        if sql == "ROLLBACK":
            return "rollback"
        return "user"

    def execute_statement(self, **kwargs):
        statement_id = self.statement_id(kwargs["Sql"])
        self.events.append(("execute", statement_id, kwargs))
        return {"Id": statement_id}

    def describe_statement(self, **kwargs):
        statement_id = kwargs["Id"]
        self.events.append(("describe", statement_id))
        return {
            "Id": statement_id,
            "Status": "FINISHED",
            "SessionId": "session-1",
            "HasResultSet": statement_id in {"probe", "user"},
        }

    def get_statement_result(self, **kwargs):
        statement_id = kwargs["Id"]
        self.events.append(("result", statement_id))
        if statement_id == "probe":
            return {
                "ColumnMetadata": [{"name": "transaction_read_only", "typeName": "varchar"}],
                "Records": [[{"stringValue": "on"}]],
            }
        return {
            "ColumnMetadata": [{"name": "value", "typeName": "int8"}],
            "Records": [[{"longValue": 1}], [{"longValue": 2}]],
        }


class Resolver:
    def __init__(self, client) -> None:
        self.client = client

    def data_api_client(self):
        return self.client

    def data_api_request(self, database):
        return {"Database": database, "WorkgroupName": "analytics"}


def test_data_api_query_enforces_readonly_session_rolls_back_then_reads_result() -> None:
    client = DataApiClient()
    adapter = DataApiAdapter(
        data_api_profile(),
        {},
        aws_resolver_factory=lambda *_args: Resolver(client),
        invocation_id_factory=lambda: "invocation",
        monotonic=lambda: 0.0,
        sleep=lambda _seconds: None,
    )

    result = adapter.query(
        database="analytics",
        sql="SELECT %(value)s AS value",
        params={"value": 1},
        limit=10,
        statement_timeout_ms=2500,
    )

    assert result.records == ({"value": 1}, {"value": 2})
    assert result.columns[0].data_type == "bigint"
    execute = [event for event in client.events if event[0] == "execute"]
    assert [event[1] for event in execute] == [
        "begin",
        "timeout",
        "probe",
        "user",
        "rollback",
    ]
    assert execute[0][2]["Sql"] == "BEGIN READ ONLY"
    assert execute[2][2]["Sql"] == "SHOW transaction_read_only"
    assert ":p_value" in execute[3][2]["Sql"]
    assert execute[3][2]["Parameters"] == [{"name": "p_value", "value": "1"}]
    assert execute[4][2]["SessionKeepAliveSeconds"] == 0
    assert len({event[2]["ClientToken"] for event in execute}) == 5
    assert client.events.index(("result", "user")) > client.events.index(
        ("describe", "rollback")
    )


def test_data_api_uses_bounded_long_polling_for_every_provider_wait() -> None:
    class LongPollClient(DataApiClient):
        def __init__(self) -> None:
            super().__init__()
            self.describe_requests = []
            self.result_requests = []

        def describe_statement(self, **kwargs):
            self.describe_requests.append(kwargs)
            return super().describe_statement(**kwargs)

        def get_statement_result(self, **kwargs):
            self.result_requests.append(kwargs)
            return super().get_statement_result(**kwargs)

    client = LongPollClient()
    adapter = DataApiAdapter(
        data_api_profile(),
        {},
        aws_resolver_factory=lambda *_args: Resolver(client),
        invocation_id_factory=lambda: "invocation",
        monotonic=lambda: 0.0,
        sleep=lambda _seconds: None,
    )

    adapter.query(
        database="analytics",
        sql="SELECT 1",
        params={},
        limit=10,
        statement_timeout_ms=2500,
    )

    execute_requests = [
        event[2] for event in client.events if event[0] == "execute"
    ]
    assert execute_requests
    assert client.describe_requests
    assert client.result_requests
    wait_seconds = {
        request["WaitTimeSeconds"]
        for request in [
            *execute_requests,
            *client.describe_requests,
            *client.result_requests,
        ]
    }
    assert wait_seconds == {3, 5}
    assert all(1 <= value <= 30 for value in wait_seconds)


def test_data_api_does_not_sleep_after_a_successful_nonterminal_long_poll() -> None:
    class StartedThenFinishedClient(DataApiClient):
        def __init__(self) -> None:
            super().__init__()
            self.user_polls = 0

        def describe_statement(self, **kwargs):
            if kwargs["Id"] == "user":
                self.user_polls += 1
                if self.user_polls == 1:
                    return {
                        "Id": "user",
                        "Status": "STARTED",
                        "SessionId": "session-1",
                    }
            return super().describe_statement(**kwargs)

    client = StartedThenFinishedClient()
    sleeps = []
    result = DataApiAdapter(
        data_api_profile(),
        {},
        aws_resolver_factory=lambda *_args: Resolver(client),
        invocation_id_factory=lambda: "invocation",
        monotonic=lambda: 0.0,
        sleep=sleeps.append,
    ).query(
        database="analytics",
        sql="SELECT 1",
        params={},
        limit=10,
        statement_timeout_ms=2500,
    )

    assert result.records == ({"value": 1}, {"value": 2})
    assert client.user_polls == 2
    assert sleeps == []


def test_data_api_execute_long_poll_never_exceeds_remaining_operation_budget() -> None:
    client = DataApiClient()
    adapter = DataApiAdapter(
        data_api_profile(),
        {},
        aws_resolver_factory=lambda *_args: Resolver(client),
        invocation_id_factory=lambda: "invocation",
        monotonic=lambda: 0.0,
        sleep=lambda _seconds: None,
    )

    adapter.query(
        database="analytics",
        sql="SELECT 1",
        params={},
        limit=10,
        statement_timeout_ms=1,
    )

    user_request = next(
        event[2]
        for event in client.events
        if event[0] == "execute" and event[1] == "user"
    )
    assert user_request["WaitTimeSeconds"] == 1


def test_data_api_dispatches_with_positive_subsecond_budget() -> None:
    class IncrementingClock:
        value = 0.0

        def __call__(self) -> float:
            current = self.value
            self.value += 0.001
            return current

    client = DataApiClient()
    adapter = DataApiAdapter(
        data_api_profile(),
        {},
        aws_resolver_factory=lambda *_args: Resolver(client),
        invocation_id_factory=lambda: "invocation",
        monotonic=IncrementingClock(),
        sleep=lambda _seconds: None,
    )

    result = adapter.query(
        database="analytics",
        sql="SELECT 1",
        params={},
        limit=10,
        statement_timeout_ms=1,
    )

    assert result.records == ({"value": 1}, {"value": 2})
    assert any(event[:2] == ("execute", "user") for event in client.events)


def test_data_api_does_not_dispatch_when_budget_is_exhausted() -> None:
    client = DataApiClient()
    adapter = DataApiAdapter(
        data_api_profile(),
        {},
        aws_resolver_factory=lambda *_args: Resolver(client),
        invocation_id_factory=lambda: "invocation",
        monotonic=lambda: 1.0,
        sleep=lambda _seconds: None,
    )

    with pytest.raises(SkillError) as caught:
        adapter._execute_statement(
            database="analytics",
            sql="SELECT 1",
            phase="user",
            session_id="session-1",
            keepalive=300,
            deadline=1.0,
        )

    assert caught.value.full_code == "query.timeout"
    assert client.events == []


def test_data_api_streaming_reads_bounded_pages_after_rollback() -> None:
    class PagedClient(DataApiClient):
        def get_statement_result(self, **kwargs):
            statement_id = kwargs["Id"]
            token = kwargs.get("NextToken")
            self.events.append(("result", statement_id, token))
            if statement_id == "probe":
                return {
                    "ColumnMetadata": [
                        {"name": "transaction_read_only", "typeName": "varchar"}
                    ],
                    "Records": [[{"stringValue": "on"}]],
                }
            if token is None:
                return {
                    "ColumnMetadata": [{"name": "value", "typeName": "int8"}],
                    "Records": [[{"longValue": 1}]],
                    "NextToken": "page-2",
                }
            return {
                "ColumnMetadata": [{"name": "value", "typeName": "int8"}],
                "Records": [[{"longValue": 2}], [{"longValue": 3}]],
            }

    client = PagedClient()
    adapter = DataApiAdapter(
        data_api_profile(),
        {},
        aws_resolver_factory=lambda *_args: Resolver(client),
        invocation_id_factory=lambda: "invocation",
        monotonic=lambda: 0.0,
        sleep=lambda _seconds: None,
    )

    with adapter.stream_query(
        database="analytics",
        sql="SELECT value FROM items",
        params={},
        limit=2,
        statement_timeout_ms=2500,
    ) as stream:
        assert list(stream) == [{"value": 1}, {"value": 2}]

    assert stream.row_count == 2
    assert stream.truncated is True
    rollback_index = client.events.index(("describe", "rollback"))
    first_user_page = client.events.index(("result", "user", None))
    assert first_user_page > rollback_index


def test_data_api_repeated_next_token_fails_instead_of_looping() -> None:
    class LoopingClient(DataApiClient):
        def get_statement_result(self, **kwargs):
            statement_id = kwargs["Id"]
            token = kwargs.get("NextToken")
            if statement_id == "probe":
                return {
                    "ColumnMetadata": [
                        {"name": "transaction_read_only", "typeName": "varchar"}
                    ],
                    "Records": [[{"stringValue": "on"}]],
                }
            return {
                "ColumnMetadata": [{"name": "value", "typeName": "int8"}],
                "Records": [[{"longValue": 1}]],
                "NextToken": token or "loop",
            }

    client = LoopingClient()
    adapter = DataApiAdapter(
        data_api_profile(),
        {},
        aws_resolver_factory=lambda *_args: Resolver(client),
        invocation_id_factory=lambda: "invocation",
        monotonic=lambda: 0.0,
        sleep=lambda _seconds: None,
    )

    with pytest.raises(SkillError) as caught:
        with adapter.stream_query(
            database="analytics",
            sql="SELECT value FROM items",
            params={},
            limit=10,
            statement_timeout_ms=2500,
        ) as stream:
            list(stream)

    assert caught.value.full_code == "query.failed"
    assert caught.value.details == {"stage": "result_fetch"}


def test_data_api_explain_preserves_plan_and_local_advisories() -> None:
    class ExplainClient(DataApiClient):
        def get_statement_result(self, **kwargs):
            statement_id = kwargs["Id"]
            if statement_id == "probe":
                return {
                    "ColumnMetadata": [
                        {"name": "transaction_read_only", "typeName": "varchar"}
                    ],
                    "Records": [[{"stringValue": "on"}]],
                }
            return {
                "ColumnMetadata": [{"name": "QUERY PLAN", "typeName": "varchar"}],
                "Records": [
                    [{"stringValue": "XN Seq Scan"}],
                    [{"stringValue": "  -> items"}],
                ],
            }

    client = ExplainClient()
    adapter = DataApiAdapter(
        data_api_profile(),
        {},
        aws_resolver_factory=lambda *_args: Resolver(client),
        invocation_id_factory=lambda: "invocation",
        monotonic=lambda: 0.0,
        sleep=lambda _seconds: None,
    )

    result = adapter.explain(
        database="analytics",
        sql="SELECT * FROM items",
        params={},
        statement_timeout_ms=2500,
    )

    assert result.plan == ("XN Seq Scan", "  -> items")
    assert result.advisories == (
        {"code": "query.select_star", "severity": "info", "message": "查询使用 SELECT *"},
    )
    user = next(
        event for event in client.events if event[:2] == ("execute", "user")
    )
    assert user[2]["Sql"] == "EXPLAIN\nSELECT * FROM items"


def test_data_api_describe_reuses_existing_show_first_metadata_contract() -> None:
    class MetadataClient(DataApiClient):
        def get_statement_result(self, **kwargs):
            statement_id = kwargs["Id"]
            if statement_id == "probe":
                return {
                    "ColumnMetadata": [
                        {"name": "transaction_read_only", "typeName": "varchar"}
                    ],
                    "Records": [[{"stringValue": "on"}]],
                }
            return {
                "ColumnMetadata": [
                    {"name": "column_name", "typeName": "varchar"},
                    {"name": "ordinal_position", "typeName": "int4"},
                    {"name": "is_nullable", "typeName": "varchar"},
                    {"name": "data_type", "typeName": "varchar"},
                ],
                "Records": [
                    [
                        {"stringValue": "id"},
                        {"longValue": 1},
                        {"stringValue": "NO"},
                        {"stringValue": "bigint"},
                    ]
                ],
            }

    client = MetadataClient()
    adapter = DataApiAdapter(
        data_api_profile(),
        {},
        aws_resolver_factory=lambda *_args: Resolver(client),
        invocation_id_factory=lambda: "invocation",
        monotonic=lambda: 0.0,
        sleep=lambda _seconds: None,
    )

    result = adapter.describe_source("analytics", 2500).show_columns(
        "analytics.public.items"
    )

    assert result.rows == (
        {"name": "id", "dataType": "bigint", "nullable": False, "ordinal": 1},
    )
    user = next(
        event for event in client.events if event[:2] == ("execute", "user")
    )
    assert user[2]["Sql"] == (
        'SHOW COLUMNS FROM TABLE "analytics"."public"."items"'
    )


def test_data_api_metadata_failure_stays_in_metadata_error_category() -> None:
    class FailedMetadataClient(DataApiClient):
        def describe_statement(self, **kwargs):
            statement_id = kwargs["Id"]
            return {
                "Id": statement_id,
                "Status": "FAILED" if statement_id == "user" else "FINISHED",
                "SessionId": "session-1",
                "HasResultSet": statement_id == "probe",
            }

    client = FailedMetadataClient()
    adapter = DataApiAdapter(
        data_api_profile(),
        {},
        aws_resolver_factory=lambda *_args: Resolver(client),
        invocation_id_factory=lambda: "invocation",
        monotonic=lambda: 0.0,
        sleep=lambda _seconds: None,
    )

    with pytest.raises(SkillError) as caught:
        adapter.describe_source("analytics", 2500).show_columns(
            "analytics.public.items"
        )

    assert caught.value.full_code == "metadata.failed"
    assert caught.value.retry_class == "never"


def test_data_api_live_metadata_stops_pagination_at_the_show_ceiling() -> None:
    class MetadataPagesClient(DataApiClient):
        def __init__(self) -> None:
            super().__init__()
            self.metadata_page_calls = 0

        def get_statement_result(self, **kwargs):
            if kwargs["Id"] == "probe":
                return super().get_statement_result(**kwargs)
            self.metadata_page_calls += 1
            result = {
                "ColumnMetadata": [
                    {"name": "database_name", "typeName": "varchar"},
                    {"name": "schema_name", "typeName": "varchar"},
                ],
                "Records": [
                    [
                        {"stringValue": "analytics"},
                        {"stringValue": f"schema_{self.metadata_page_calls}_{index}"},
                    ]
                    for index in range(6_000)
                ],
                "NextToken": f"page-{self.metadata_page_calls + 1}",
            }
            return result

    client = MetadataPagesClient()
    adapter = DataApiAdapter(
        data_api_profile(),
        {},
        aws_resolver_factory=lambda *_args: Resolver(client),
        invocation_id_factory=lambda: "invocation",
        monotonic=lambda: 0.0,
        sleep=lambda _seconds: None,
    )

    result = adapter.live_metadata_source("analytics", 2500).show_schemas(
        "analytics"
    )

    assert len(result.rows) == 10_000
    assert client.metadata_page_calls == 2
    assert result.truncated is True


def test_data_api_catalog_metadata_raises_after_proving_more_than_100k_rows() -> None:
    class CatalogPagesClient(DataApiClient):
        def __init__(self) -> None:
            super().__init__()
            self.metadata_page_calls = 0

        def get_statement_result(self, **kwargs):
            if kwargs["Id"] == "probe":
                return super().get_statement_result(**kwargs)
            self.metadata_page_calls += 1
            rows = [
                [
                    {"stringValue": "analytics"},
                    {"stringValue": f"schema_{self.metadata_page_calls}_{index}"},
                    {"stringValue": f"table_{self.metadata_page_calls}_{index}"},
                    {"stringValue": "TABLE"},
                    {"isNull": True},
                ]
                for index in range(50_000)
            ]
            result = {
                "ColumnMetadata": [
                    {"name": "database_name", "typeName": "varchar"},
                    {"name": "schema_name", "typeName": "varchar"},
                    {"name": "table_name", "typeName": "varchar"},
                    {"name": "table_type", "typeName": "varchar"},
                    {"name": "remarks", "typeName": "varchar"},
                ],
                "Records": rows,
            }
            if self.metadata_page_calls < 3:
                result["NextToken"] = f"page-{self.metadata_page_calls + 1}"
            return result

    client = CatalogPagesClient()
    adapter = DataApiAdapter(
        data_api_profile(),
        {},
        aws_resolver_factory=lambda *_args: Resolver(client),
        invocation_id_factory=lambda: "invocation",
        monotonic=lambda: 0.0,
        sleep=lambda _seconds: None,
    )

    with pytest.raises(SkillError) as caught:
        adapter.catalog_source("analytics", 2500).show_relations("analytics")

    assert caught.value.full_code == "metadata.limit_exceeded"
    assert client.metadata_page_calls == 3


def test_data_api_confirmed_user_failure_rolls_back_before_returning_error() -> None:
    class FailedClient(DataApiClient):
        def describe_statement(self, **kwargs):
            statement_id = kwargs["Id"]
            self.events.append(("describe", statement_id))
            return {
                "Id": statement_id,
                "Status": "FAILED" if statement_id == "user" else "FINISHED",
                "SessionId": "session-1",
                "HasResultSet": statement_id == "probe",
            }

    client = FailedClient()
    adapter = DataApiAdapter(
        data_api_profile(),
        {},
        aws_resolver_factory=lambda *_args: Resolver(client),
        invocation_id_factory=lambda: "invocation",
        monotonic=lambda: 0.0,
        sleep=lambda _seconds: None,
    )

    with pytest.raises(SkillError) as caught:
        adapter.query(
            database="analytics",
            sql="SELECT 1",
            params={},
            limit=10,
            statement_timeout_ms=2500,
        )

    assert caught.value.full_code == "query.failed"
    assert any(event[:2] == ("execute", "rollback") for event in client.events)


def test_data_api_cleanup_failure_never_replaces_user_failure() -> None:
    class FailedCleanupClient(DataApiClient):
        def describe_statement(self, **kwargs):
            statement_id = kwargs["Id"]
            self.events.append(("describe", statement_id))
            return {
                "Id": statement_id,
                "Status": "FAILED" if statement_id in {"user", "rollback"} else "FINISHED",
                "SessionId": "session-1",
                "HasResultSet": statement_id == "probe",
            }

    client = FailedCleanupClient()
    adapter = DataApiAdapter(
        data_api_profile(),
        {},
        aws_resolver_factory=lambda *_args: Resolver(client),
        invocation_id_factory=lambda: "invocation",
        monotonic=lambda: 0.0,
        sleep=lambda _seconds: None,
    )

    with pytest.raises(SkillError) as caught:
        adapter.query(
            database="analytics",
            sql="SELECT 1",
            params={},
            limit=10,
            statement_timeout_ms=2500,
        )

    assert caught.value.full_code == "query.failed"
    assert caught.value.details == {"stage": "user"}


def test_data_api_readonly_probe_failure_cleans_up_session() -> None:
    class WritableProbeClient(DataApiClient):
        def get_statement_result(self, **kwargs):
            statement_id = kwargs["Id"]
            if statement_id == "probe":
                return {
                    "ColumnMetadata": [
                        {"name": "transaction_read_only", "typeName": "varchar"}
                    ],
                    "Records": [[{"stringValue": "off"}]],
                }
            return super().get_statement_result(**kwargs)

    client = WritableProbeClient()
    adapter = DataApiAdapter(
        data_api_profile(),
        {},
        aws_resolver_factory=lambda *_args: Resolver(client),
        invocation_id_factory=lambda: "invocation",
        monotonic=lambda: 0.0,
        sleep=lambda _seconds: None,
    )

    with pytest.raises(SkillError) as caught:
        adapter.query(
            database="analytics",
            sql="SELECT 1",
            params={},
            limit=10,
            statement_timeout_ms=2500,
        )

    assert caught.value.full_code == "capability.readonly_unavailable"
    assert any(event[:2] == ("execute", "rollback") for event in client.events)
    assert not any(event[:2] == ("execute", "user") for event in client.events)


def test_data_api_timeout_cancels_waits_for_abort_then_rolls_back() -> None:
    class Clock:
        value = 0.0

        def __call__(self):
            return self.value

    clock = Clock()

    class TimeoutClient(DataApiClient):
        def __init__(self) -> None:
            super().__init__()
            self.cancelled = False
            self.user_describe_requests = []

        def describe_statement(self, **kwargs):
            statement_id = kwargs["Id"]
            self.events.append(("describe", statement_id))
            if statement_id == "user":
                self.user_describe_requests.append(kwargs)
                if not self.cancelled:
                    clock.value = 4.0
                return {
                    "Id": statement_id,
                    "Status": "ABORTED" if self.cancelled else "STARTED",
                    "SessionId": "session-1",
                }
            return {
                "Id": statement_id,
                "Status": "FINISHED",
                "SessionId": "session-1",
                "HasResultSet": statement_id == "probe",
            }

        def cancel_statement(self, **kwargs):
            self.events.append(("cancel", kwargs["Id"]))
            self.cancelled = True
            return {"Status": True}

    client = TimeoutClient()
    adapter = DataApiAdapter(
        data_api_profile(),
        {},
        aws_resolver_factory=lambda *_args: Resolver(client),
        invocation_id_factory=lambda: "invocation",
        monotonic=clock,
        sleep=lambda _seconds: None,
    )

    with pytest.raises(SkillError) as caught:
        adapter.query(
            database="analytics",
            sql="SELECT 1",
            params={},
            limit=10,
            statement_timeout_ms=2500,
        )

    assert caught.value.full_code == "query.timeout"
    assert caught.value.details == {
        "stage": "user",
        "executionState": "stopped",
    }
    assert ("cancel", "user") in client.events
    assert any(event[:2] == ("execute", "rollback") for event in client.events)
    assert client.user_describe_requests
    assert all(
        1 <= request["WaitTimeSeconds"] <= 30
        for request in client.user_describe_requests
    )


def test_data_api_setup_timeout_cancels_and_settles_before_rollback() -> None:
    class Clock:
        value = 0.0

        def __call__(self):
            return self.value

    clock = Clock()

    class SetupTimeoutClient(DataApiClient):
        def __init__(self) -> None:
            super().__init__()
            self.cancelled = False

        def describe_statement(self, **kwargs):
            statement_id = kwargs["Id"]
            self.events.append(("describe", statement_id))
            if statement_id == "timeout":
                return {
                    "Id": statement_id,
                    "Status": "ABORTED" if self.cancelled else "STARTED",
                    "SessionId": "session-1",
                }
            return {
                "Id": statement_id,
                "Status": "FINISHED",
                "SessionId": "session-1",
                "HasResultSet": statement_id == "probe",
            }

        def execute_statement(self, **kwargs):
            response = super().execute_statement(**kwargs)
            if self.statement_id(kwargs["Sql"]) == "timeout":
                clock.value = 121.0
            return response

        def cancel_statement(self, **kwargs):
            self.events.append(("cancel", kwargs["Id"]))
            self.cancelled = True
            return {"Status": True}

    client = SetupTimeoutClient()
    adapter = DataApiAdapter(
        data_api_profile(),
        {},
        aws_resolver_factory=lambda *_args: Resolver(client),
        invocation_id_factory=lambda: "invocation",
        monotonic=clock,
        sleep=lambda _seconds: None,
    )

    with pytest.raises(SkillError) as caught:
        adapter.query(
            database="analytics",
            sql="SELECT 1",
            params={},
            limit=10,
            statement_timeout_ms=2500,
        )

    assert caught.value.full_code == "query.timeout"
    cancel_index = client.events.index(("cancel", "timeout"))
    rollback_index = next(
        index
        for index, event in enumerate(client.events)
        if event[:2] == ("execute", "rollback")
    )
    assert cancel_index < rollback_index


def test_data_api_cancel_and_settlement_share_one_cleanup_deadline() -> None:
    class Clock:
        value = 0.0

        def __call__(self) -> float:
            return self.value

    clock = Clock()

    class SlowCancelClient(DataApiClient):
        def __init__(self) -> None:
            super().__init__()
            self.cancelled = False

        def describe_statement(self, **kwargs):
            if kwargs["Id"] == "user":
                self.events.append(("describe", "user"))
                if self.cancelled:
                    return {
                        "Id": "user",
                        "Status": "ABORTED",
                        "SessionId": "session-1",
                    }
                clock.value = 4.0
                return {
                    "Id": "user",
                    "Status": "STARTED",
                    "SessionId": "session-1",
                }
            return super().describe_statement(**kwargs)

        def cancel_statement(self, **kwargs):
            self.events.append(("cancel", kwargs["Id"]))
            self.cancelled = True
            clock.value = 65.0
            return {"Status": True}

    client = SlowCancelClient()
    adapter = DataApiAdapter(
        data_api_profile(),
        {},
        aws_resolver_factory=lambda *_args: Resolver(client),
        invocation_id_factory=lambda: "invocation",
        monotonic=clock,
        sleep=lambda _seconds: None,
    )

    with pytest.raises(SkillError) as caught:
        adapter.query(
            database="analytics",
            sql="SELECT 1",
            params={},
            limit=10,
            statement_timeout_ms=2500,
        )

    assert caught.value.full_code == "query.timeout"
    assert caught.value.details["executionState"] == "may_be_running"
    cancel_index = client.events.index(("cancel", "user"))
    assert not any(
        event == ("describe", "user")
        for event in client.events[cancel_index + 1 :]
    )
    assert not any(event[:2] == ("execute", "rollback") for event in client.events)


def test_data_api_setup_phases_share_one_absolute_deadline() -> None:
    client = DataApiClient()

    adapter = DataApiAdapter(
        data_api_profile(),
        {},
        aws_resolver_factory=lambda *_args: Resolver(client),
        invocation_id_factory=lambda: "invocation",
        monotonic=lambda: 0.0,
        sleep=lambda _seconds: None,
    )
    budgets = []

    def wait(statement_id, *, deadline, stage):
        budgets.append((stage, deadline))
        return {
            "Id": statement_id,
            "Status": "FINISHED",
            "SessionId": "session-1",
            "HasResultSet": statement_id in {"probe", "user"},
        }

    adapter._wait = wait
    adapter.query(
        database="analytics",
        sql="SELECT 1",
        params={},
        limit=10,
        statement_timeout_ms=2500,
    )

    setup = dict(budgets)
    assert setup["begin"] == setup["timeout"] == setup["probe"]


def test_data_api_setup_dispatch_time_counts_against_absolute_deadline() -> None:
    class Clock:
        value = 0.0

        def __call__(self):
            return self.value

    clock = Clock()

    class SlowDispatchClient(DataApiClient):
        def execute_statement(self, **kwargs):
            statement_id = self.statement_id(kwargs["Sql"])
            self.events.append(("execute", statement_id, kwargs))
            if statement_id == "timeout":
                clock.value = 121.0
            return {"Id": statement_id}

        def cancel_statement(self, **kwargs):
            self.events.append(("cancel", kwargs["Id"]))
            return {"Status": True}

    client = SlowDispatchClient()
    adapter = DataApiAdapter(
        data_api_profile(),
        {},
        aws_resolver_factory=lambda *_args: Resolver(client),
        invocation_id_factory=lambda: "invocation",
        monotonic=clock,
        sleep=lambda _seconds: None,
    )

    with pytest.raises(SkillError) as caught:
        adapter.query(
            database="analytics",
            sql="SELECT 1",
            params={},
            limit=10,
            statement_timeout_ms=2500,
        )

    assert caught.value.full_code == "query.timeout"
    assert ("cancel", "timeout") in client.events
    assert any(event[:2] == ("execute", "rollback") for event in client.events)
    assert not any(event[:2] == ("execute", "user") for event in client.events)


def test_data_api_user_execute_interruption_never_rolls_back_unknown_submission() -> None:
    class SubmitInterruptedClient(DataApiClient):
        def execute_statement(self, **kwargs):
            statement_id = self.statement_id(kwargs["Sql"])
            self.events.append(("execute", statement_id, kwargs))
            if statement_id == "user":
                raise Interrupted(signal.SIGTERM)
            return {"Id": statement_id}

    client = SubmitInterruptedClient()
    adapter = DataApiAdapter(
        data_api_profile(),
        {},
        aws_resolver_factory=lambda *_args: Resolver(client),
        invocation_id_factory=lambda: "invocation",
        monotonic=lambda: 0.0,
        sleep=lambda _seconds: None,
    )

    with pytest.raises(Interrupted) as caught:
        adapter.query(
            database="analytics",
            sql="SELECT 1",
            params={},
            limit=10,
            statement_timeout_ms=2500,
        )

    assert caught.value.details == {
        "stage": "user",
        "executionState": "may_be_running",
    }
    assert not any(event[:2] == ("execute", "rollback") for event in client.events)


def test_data_api_missing_user_statement_id_is_unknown_submission() -> None:
    class MissingIdClient(DataApiClient):
        def execute_statement(self, **kwargs):
            statement_id = self.statement_id(kwargs["Sql"])
            self.events.append(("execute", statement_id, kwargs))
            return {} if statement_id == "user" else {"Id": statement_id}

    client = MissingIdClient()
    adapter = DataApiAdapter(
        data_api_profile(),
        {},
        aws_resolver_factory=lambda *_args: Resolver(client),
        invocation_id_factory=lambda: "invocation",
        monotonic=lambda: 0.0,
        sleep=lambda _seconds: None,
    )

    with pytest.raises(SkillError) as caught:
        adapter.query(
            database="analytics",
            sql="SELECT 1",
            params={},
            limit=10,
            statement_timeout_ms=2500,
        )

    assert caught.value.full_code == "query.submission_unknown"
    assert caught.value.details == {
        "stage": "user",
        "executionState": "may_be_running",
    }
    assert not any(event[:2] == ("execute", "rollback") for event in client.events)


def test_data_api_missing_setup_statement_id_never_races_rollback() -> None:
    class MissingSetupIdClient(DataApiClient):
        def execute_statement(self, **kwargs):
            statement_id = self.statement_id(kwargs["Sql"])
            self.events.append(("execute", statement_id, kwargs))
            return {} if statement_id == "timeout" else {"Id": statement_id}

    client = MissingSetupIdClient()
    adapter = DataApiAdapter(
        data_api_profile(),
        {},
        aws_resolver_factory=lambda *_args: Resolver(client),
        invocation_id_factory=lambda: "invocation",
        monotonic=lambda: 0.0,
        sleep=lambda _seconds: None,
    )

    with pytest.raises(SkillError) as caught:
        adapter.query(
            database="analytics",
            sql="SELECT 1",
            params={},
            limit=10,
            statement_timeout_ms=2500,
        )

    assert caught.value.full_code == "query.failed"
    assert caught.value.details == {
        "stage": "timeout",
        "executionState": "may_be_running",
    }
    assert not any(event[:2] == ("execute", "rollback") for event in client.events)


def test_data_api_finished_begin_after_interruption_is_rolled_back() -> None:
    class FinishedBeginClient(DataApiClient):
        def __init__(self) -> None:
            super().__init__()
            self.begin_polls = 0

        def describe_statement(self, **kwargs):
            statement_id = kwargs["Id"]
            self.events.append(("describe", statement_id))
            if statement_id == "begin":
                self.begin_polls += 1
                if self.begin_polls == 1:
                    raise Interrupted(signal.SIGTERM)
            return {
                "Id": statement_id,
                "Status": "FINISHED",
                "SessionId": "session-1",
                "HasResultSet": False,
            }

        def cancel_statement(self, **kwargs):
            self.events.append(("cancel", kwargs["Id"]))
            return {"Status": True}

    client = FinishedBeginClient()
    adapter = DataApiAdapter(
        data_api_profile(),
        {},
        aws_resolver_factory=lambda *_args: Resolver(client),
        invocation_id_factory=lambda: "invocation",
        monotonic=lambda: 0.0,
        sleep=lambda _seconds: None,
    )

    with pytest.raises(Interrupted):
        adapter.query(
            database="analytics",
            sql="SELECT 1",
            params={},
            limit=10,
            statement_timeout_ms=2500,
        )

    assert ("cancel", "begin") in client.events
    assert any(event[:2] == ("execute", "rollback") for event in client.events)


def test_data_api_nonterminal_poll_failure_never_races_rollback() -> None:
    class AccessDenied(Exception):
        response = {
            "Error": {"Code": "AccessDeniedException"},
            "ResponseMetadata": {"HTTPStatusCode": 403},
        }

    class PollFailureClient(DataApiClient):
        def describe_statement(self, **kwargs):
            statement_id = kwargs["Id"]
            self.events.append(("describe", statement_id))
            if statement_id == "user":
                raise AccessDenied()
            return {
                "Id": statement_id,
                "Status": "FINISHED",
                "SessionId": "session-1",
                "HasResultSet": statement_id == "probe",
            }

        def cancel_statement(self, **kwargs):
            self.events.append(("cancel", kwargs["Id"]))
            return {"Status": True}

    client = PollFailureClient()
    adapter = DataApiAdapter(
        data_api_profile(),
        {},
        aws_resolver_factory=lambda *_args: Resolver(client),
        invocation_id_factory=lambda: "invocation",
        monotonic=lambda: 0.0,
        sleep=lambda _seconds: None,
    )

    with pytest.raises(SkillError) as caught:
        adapter.query(
            database="analytics",
            sql="SELECT 1",
            params={},
            limit=10,
            statement_timeout_ms=2500,
        )

    assert caught.value.full_code == "query.failed"
    assert ("cancel", "user") in client.events
    assert not any(event[:2] == ("execute", "rollback") for event in client.events)


def test_data_api_terminal_session_mismatch_still_rolls_back() -> None:
    class MismatchedSessionClient(DataApiClient):
        def describe_statement(self, **kwargs):
            result = super().describe_statement(**kwargs)
            if kwargs["Id"] == "user":
                result["SessionId"] = "other-session"
            return result

    client = MismatchedSessionClient()
    adapter = DataApiAdapter(
        data_api_profile(),
        {},
        aws_resolver_factory=lambda *_args: Resolver(client),
        invocation_id_factory=lambda: "invocation",
        monotonic=lambda: 0.0,
        sleep=lambda _seconds: None,
    )

    with pytest.raises(SkillError):
        adapter.query(
            database="analytics",
            sql="SELECT 1",
            params={},
            limit=10,
            statement_timeout_ms=2500,
        )

    assert any(event[:2] == ("execute", "rollback") for event in client.events)


def test_data_api_transient_poll_error_uses_injected_bounded_jitter() -> None:
    class EndpointConnectionError(Exception):
        pass

    class PollOnceClient(DataApiClient):
        def __init__(self) -> None:
            super().__init__()
            self.user_polls = 0

        def describe_statement(self, **kwargs):
            statement_id = kwargs["Id"]
            self.events.append(("describe", statement_id))
            if statement_id == "user":
                self.user_polls += 1
                if self.user_polls == 1:
                    raise EndpointConnectionError()
            return {
                "Id": statement_id,
                "Status": "FINISHED",
                "SessionId": "session-1",
                "HasResultSet": statement_id in {"probe", "user"},
            }

    sleeps = []
    client = PollOnceClient()
    result = DataApiAdapter(
        data_api_profile(),
        {},
        aws_resolver_factory=lambda *_args: Resolver(client),
        invocation_id_factory=lambda: "invocation",
        monotonic=lambda: 0.0,
        sleep=sleeps.append,
        jitter=lambda interval: interval / 2,
    ).query(
        database="analytics",
        sql="SELECT 1",
        params={},
        limit=10,
        statement_timeout_ms=2500,
    )

    assert result.row_count == 2
    assert 0.125 in sleeps


def test_data_api_unknown_remote_state_never_races_rollback() -> None:
    class StuckClient(DataApiClient):
        def describe_statement(self, **kwargs):
            statement_id = kwargs["Id"]
            self.events.append(("describe", statement_id))
            if statement_id == "user":
                return {
                    "Id": statement_id,
                    "Status": "STARTED",
                    "SessionId": "session-1",
                }
            return {
                "Id": statement_id,
                "Status": "FINISHED",
                "SessionId": "session-1",
                "HasResultSet": statement_id == "probe",
            }

        def cancel_statement(self, **kwargs):
            self.events.append(("cancel", kwargs["Id"]))
            raise RuntimeError("injected cancel failure")

    client = StuckClient()
    ticks = iter(range(0, 1000, 10))
    adapter = DataApiAdapter(
        data_api_profile(),
        {},
        aws_resolver_factory=lambda *_args: Resolver(client),
        invocation_id_factory=lambda: "invocation",
        monotonic=lambda: next(ticks),
        sleep=lambda _seconds: None,
    )

    with pytest.raises(SkillError) as caught:
        adapter.query(
            database="analytics",
            sql="SELECT 1",
            params={},
            limit=10,
            statement_timeout_ms=2500,
        )

    assert caught.value.details["executionState"] == "may_be_running"
    assert not any(event[:2] == ("execute", "rollback") for event in client.events)


def test_data_api_static_doctor_reports_missing_dependency_without_network() -> None:
    events = []

    class LazyResolver:
        def data_api_client(self):
            events.append("client")
            raise AssertionError("static doctor must not create an AWS client")

    adapter = DataApiAdapter(
        data_api_profile(),
        {},
        aws_resolver_factory=lambda *_args: LazyResolver(),
        dependency_available=lambda: False,
    )

    result = adapter.preflight(connect_live=False)

    assert result.data["skillAvailable"] is False
    assert result.data["checks"][0] == {
        "name": "boto3",
        "status": "unavailable",
        "code": "config.dependency_missing",
    }
    assert events == []


def test_data_api_static_doctor_does_not_claim_query_without_live_proof() -> None:
    events = []

    class LazyResolver:
        def data_api_client(self):
            events.append("client")
            raise AssertionError("static doctor must not create an AWS client")

    adapter = DataApiAdapter(
        data_api_profile(),
        {},
        aws_resolver_factory=lambda *_args: LazyResolver(),
        dependency_available=lambda: True,
    )

    result = adapter.preflight(connect_live=False)

    assert result.data["skillAvailable"] is False
    assert result.data["jsonQueryAvailable"] is False
    assert events == []


def test_data_api_known_permission_rejection_is_not_submission_unknown() -> None:
    class AccessDenied(Exception):
        response = {
            "Error": {"Code": "AccessDeniedException"},
            "ResponseMetadata": {"HTTPStatusCode": 403},
        }

    class RejectedClient(DataApiClient):
        def execute_statement(self, **kwargs):
            statement_id = self.statement_id(kwargs["Sql"])
            self.events.append(("execute", statement_id, kwargs))
            if statement_id == "user":
                raise AccessDenied()
            return {"Id": statement_id}

    client = RejectedClient()
    adapter = DataApiAdapter(
        data_api_profile(),
        {},
        aws_resolver_factory=lambda *_args: Resolver(client),
        invocation_id_factory=lambda: "invocation",
        monotonic=lambda: 0.0,
        sleep=lambda _seconds: None,
    )

    with pytest.raises(SkillError) as caught:
        adapter.query(
            database="analytics",
            sql="SELECT 1",
            params={},
            limit=10,
            statement_timeout_ms=2500,
        )

    assert caught.value.full_code == "connection.permission_denied"
    assert any(event[:2] == ("execute", "rollback") for event in client.events)


def test_data_api_uncertain_user_submission_never_retries_or_rolls_back() -> None:
    class EndpointConnectionError(Exception):
        pass

    class UnknownClient(DataApiClient):
        def execute_statement(self, **kwargs):
            statement_id = self.statement_id(kwargs["Sql"])
            self.events.append(("execute", statement_id, kwargs))
            if statement_id == "user":
                raise EndpointConnectionError()
            return {"Id": statement_id}

    client = UnknownClient()
    adapter = DataApiAdapter(
        data_api_profile(),
        {},
        aws_resolver_factory=lambda *_args: Resolver(client),
        invocation_id_factory=lambda: "invocation",
        monotonic=lambda: 0.0,
        sleep=lambda _seconds: None,
    )

    with pytest.raises(SkillError) as caught:
        adapter.query(
            database="analytics",
            sql="SELECT 1",
            params={},
            limit=10,
            statement_timeout_ms=2500,
        )

    assert caught.value.full_code == "query.submission_unknown"
    assert sum(1 for event in client.events if event[:2] == ("execute", "user")) == 1
    assert not any(event[:2] == ("execute", "rollback") for event in client.events)


def test_data_api_page_retry_reuses_token_without_duplicate_rows() -> None:
    class EndpointConnectionError(Exception):
        pass

    class RetryPageClient(DataApiClient):
        def __init__(self) -> None:
            super().__init__()
            self.page_attempts = 0

        def get_statement_result(self, **kwargs):
            statement_id = kwargs["Id"]
            token = kwargs.get("NextToken")
            if statement_id == "probe":
                return {
                    "ColumnMetadata": [
                        {"name": "transaction_read_only", "typeName": "varchar"}
                    ],
                    "Records": [[{"stringValue": "on"}]],
                }
            if token is None:
                return {
                    "ColumnMetadata": [{"name": "value", "typeName": "int8"}],
                    "Records": [[{"longValue": 1}]],
                    "NextToken": "page-2",
                }
            self.page_attempts += 1
            if self.page_attempts == 1:
                raise EndpointConnectionError()
            return {
                "ColumnMetadata": [{"name": "value", "typeName": "int8"}],
                "Records": [[{"longValue": 2}]],
            }

    client = RetryPageClient()
    adapter = DataApiAdapter(
        data_api_profile(),
        {},
        aws_resolver_factory=lambda *_args: Resolver(client),
        invocation_id_factory=lambda: "invocation",
        monotonic=lambda: 0.0,
        sleep=lambda _seconds: None,
    )

    with adapter.stream_query(
        database="analytics",
        sql="SELECT value FROM items",
        params={},
        limit=10,
        statement_timeout_ms=2500,
    ) as stream:
        rows = list(stream)

    assert rows == [{"value": 1}, {"value": 2}]
    assert client.page_attempts == 2


def test_data_api_poll_retries_transient_transport_failure_with_same_statement_id() -> None:
    class EndpointConnectionError(Exception):
        pass

    class RetryPollClient(DataApiClient):
        def __init__(self) -> None:
            super().__init__()
            self.user_poll_attempts = 0

        def describe_statement(self, **kwargs):
            statement_id = kwargs["Id"]
            self.events.append(("describe", statement_id))
            if statement_id == "user":
                self.user_poll_attempts += 1
                if self.user_poll_attempts == 1:
                    raise EndpointConnectionError()
            return {
                "Id": statement_id,
                "Status": "FINISHED",
                "SessionId": "session-1",
                "HasResultSet": statement_id in {"probe", "user"},
            }

    client = RetryPollClient()
    result = DataApiAdapter(
        data_api_profile(),
        {},
        aws_resolver_factory=lambda *_args: Resolver(client),
        invocation_id_factory=lambda: "invocation",
        monotonic=lambda: 0.0,
        sleep=lambda _seconds: None,
    ).query(
        database="analytics",
        sql="SELECT 1",
        params={},
        limit=10,
        statement_timeout_ms=2500,
    )

    assert result.records == ({"value": 1}, {"value": 2})
    assert client.user_poll_attempts == 2
    assert not any(event[0] == "cancel" for event in client.events)


def test_data_api_decodes_common_redshift_types_into_canonical_result_values() -> None:
    class TypesClient(DataApiClient):
        def get_statement_result(self, **kwargs):
            statement_id = kwargs["Id"]
            if statement_id == "probe":
                return {
                    "ColumnMetadata": [
                        {"name": "transaction_read_only", "typeName": "varchar"}
                    ],
                    "Records": [[{"stringValue": "on"}]],
                }
            return {
                "ColumnMetadata": [
                    {"name": "flag", "typeName": "bool"},
                    {"name": "amount", "typeName": "numeric"},
                    {"name": "created_at", "typeName": "timestamp"},
                    {"name": "payload", "typeName": "varbyte"},
                    {"name": "missing", "typeName": "varchar"},
                ],
                "Records": [
                    [
                        {"booleanValue": True},
                        {"stringValue": "12.30"},
                        {"stringValue": "2026-08-19 00:00:00"},
                        {"blobValue": b"\x0a\x0b"},
                        {"isNull": True},
                    ]
                ],
            }

    client = TypesClient()
    result = DataApiAdapter(
        data_api_profile(),
        {},
        aws_resolver_factory=lambda *_args: Resolver(client),
        invocation_id_factory=lambda: "invocation",
        monotonic=lambda: 0.0,
        sleep=lambda _seconds: None,
    ).query(
        database="analytics",
        sql="SELECT 1",
        params={},
        limit=10,
        statement_timeout_ms=2500,
    )

    assert [column.data_type for column in result.columns] == [
        "boolean",
        "numeric",
        "timestamp without time zone",
        "bytea",
        "character varying",
    ]
    assert result.records == (
        {
            "flag": True,
            "amount": Decimal("12.30"),
            "created_at": datetime(2026, 8, 19, 0, 0),
            "payload": b"\x0a\x0b",
            "missing": None,
        },
    )


def test_data_api_result_not_ready_is_retried_without_resubmitting_sql() -> None:
    class ResourceNotFoundException(Exception):
        response = {
            "Error": {"Code": "ResourceNotFoundException"},
            "ResponseMetadata": {"HTTPStatusCode": 400},
        }

    class EventuallyReadyClient(DataApiClient):
        def __init__(self) -> None:
            super().__init__()
            self.user_result_attempts = 0

        def get_statement_result(self, **kwargs):
            statement_id = kwargs["Id"]
            if statement_id == "probe":
                return {
                    "ColumnMetadata": [
                        {"name": "transaction_read_only", "typeName": "varchar"}
                    ],
                    "Records": [[{"stringValue": "on"}]],
                }
            self.user_result_attempts += 1
            if self.user_result_attempts < 3:
                raise ResourceNotFoundException()
            return {
                "ColumnMetadata": [{"name": "value", "typeName": "int8"}],
                "Records": [[{"longValue": 1}]],
            }

    client = EventuallyReadyClient()
    result = DataApiAdapter(
        data_api_profile(),
        {},
        aws_resolver_factory=lambda *_args: Resolver(client),
        invocation_id_factory=lambda: "invocation",
        monotonic=lambda: 0.0,
        sleep=lambda _seconds: None,
    ).query(
        database="analytics",
        sql="SELECT 1",
        params={},
        limit=10,
        statement_timeout_ms=2500,
    )

    assert result.records == ({"value": 1},)
    assert client.user_result_attempts == 3
    assert sum(1 for event in client.events if event[0] == "execute") == 5


def test_data_api_result_not_ready_uses_deadline_instead_of_three_attempts() -> None:
    class ResourceNotFoundException(Exception):
        response = {
            "Error": {"Code": "ResourceNotFoundException"},
            "ResponseMetadata": {"HTTPStatusCode": 400},
        }

    class ReadyOnFifthAttempt(DataApiClient):
        def __init__(self) -> None:
            super().__init__()
            self.user_result_attempts = 0

        def get_statement_result(self, **kwargs):
            statement_id = kwargs["Id"]
            if statement_id == "probe":
                return super().get_statement_result(**kwargs)
            self.user_result_attempts += 1
            if self.user_result_attempts < 5:
                raise ResourceNotFoundException()
            return {
                "ColumnMetadata": [{"name": "value", "typeName": "int8"}],
                "Records": [[{"longValue": 1}]],
            }

    client = ReadyOnFifthAttempt()
    result = DataApiAdapter(
        data_api_profile(),
        {},
        aws_resolver_factory=lambda *_args: Resolver(client),
        invocation_id_factory=lambda: "invocation",
        monotonic=lambda: 0.0,
        sleep=lambda _seconds: None,
    ).query(
        database="analytics",
        sql="SELECT 1",
        params={},
        limit=10,
        statement_timeout_ms=2500,
    )

    assert result.records == ({"value": 1},)
    assert client.user_result_attempts == 5
    assert sum(1 for event in client.events if event[0] == "execute") == 5


def test_data_api_result_not_ready_stops_at_the_result_fetch_deadline() -> None:
    class ResourceNotFoundException(Exception):
        response = {
            "Error": {"Code": "ResourceNotFoundException"},
            "ResponseMetadata": {"HTTPStatusCode": 400},
        }

    class Clock:
        value = 0.0

        def __call__(self):
            return self.value

    class NeverReadyClient(DataApiClient):
        def __init__(self, clock) -> None:
            super().__init__()
            self.clock = clock
            self.user_result_attempts = 0

        def get_statement_result(self, **kwargs):
            if kwargs["Id"] == "probe":
                return super().get_statement_result(**kwargs)
            self.user_result_attempts += 1
            self.clock.value += 31.0
            raise ResourceNotFoundException()

    clock = Clock()
    client = NeverReadyClient(clock)
    adapter = DataApiAdapter(
        data_api_profile(),
        {},
        aws_resolver_factory=lambda *_args: Resolver(client),
        invocation_id_factory=lambda: "invocation",
        monotonic=clock,
        sleep=lambda _seconds: None,
    )

    with pytest.raises(SkillError) as caught:
        adapter.query(
            database="analytics",
            sql="SELECT 1",
            params={},
            limit=10,
            statement_timeout_ms=2500,
        )

    assert caught.value.full_code == "query.failed"
    assert caught.value.details == {"stage": "result_fetch"}
    assert client.user_result_attempts == 2
    assert sum(1 for event in client.events if event[0] == "execute") == 5


def test_data_api_result_pages_share_one_absolute_fetch_deadline() -> None:
    class Clock:
        value = 0.0

        def __call__(self) -> float:
            return self.value

    clock = Clock()

    class SlowPagesClient(DataApiClient):
        def __init__(self) -> None:
            super().__init__()
            self.user_result_calls = 0

        def get_statement_result(self, **kwargs):
            if kwargs["Id"] == "probe":
                return super().get_statement_result(**kwargs)
            self.user_result_calls += 1
            clock.value += 31.0
            if self.user_result_calls == 1:
                return {
                    "ColumnMetadata": [{"name": "value", "typeName": "int8"}],
                    "Records": [[{"longValue": 1}]],
                    "NextToken": "page-2",
                }
            return {
                "ColumnMetadata": [{"name": "value", "typeName": "int8"}],
                "Records": [[{"longValue": 2}]],
            }

    client = SlowPagesClient()
    adapter = DataApiAdapter(
        data_api_profile(),
        {},
        aws_resolver_factory=lambda *_args: Resolver(client),
        invocation_id_factory=lambda: "invocation",
        monotonic=clock,
        sleep=lambda _seconds: None,
    )

    with pytest.raises(SkillError) as caught:
        adapter.query(
            database="analytics",
            sql="SELECT 1",
            params={},
            limit=10,
            statement_timeout_ms=2500,
        )

    assert caught.value.full_code == "query.failed"
    assert caught.value.details == {"stage": "result_fetch"}
    assert client.user_result_calls == 2


@pytest.mark.parametrize("operation", ["stream", "explain", "metadata"])
def test_data_api_other_paginated_operations_share_one_fetch_deadline(
    operation: str,
) -> None:
    class Clock:
        value = 0.0

        def __call__(self) -> float:
            return self.value

    clock = Clock()

    class SlowPagesClient(DataApiClient):
        def __init__(self) -> None:
            super().__init__()
            self.user_result_calls = 0

        def get_statement_result(self, **kwargs):
            if kwargs["Id"] == "probe":
                return super().get_statement_result(**kwargs)
            self.user_result_calls += 1
            clock.value += 31.0
            if operation == "metadata":
                metadata = [
                    {"name": "database_name", "typeName": "varchar"},
                    {"name": "database_type", "typeName": "varchar"},
                ]
                record = [
                    {"stringValue": "analytics"},
                    {"stringValue": "local"},
                ]
            elif operation == "explain":
                metadata = [{"name": "plan", "typeName": "varchar"}]
                record = [{"stringValue": "XN Result"}]
            else:
                metadata = [{"name": "value", "typeName": "int8"}]
                record = [{"longValue": self.user_result_calls}]
            result = {"ColumnMetadata": metadata, "Records": [record]}
            if self.user_result_calls == 1:
                result["NextToken"] = "page-2"
            return result

    client = SlowPagesClient()
    adapter = DataApiAdapter(
        data_api_profile(),
        {},
        aws_resolver_factory=lambda *_args: Resolver(client),
        invocation_id_factory=lambda: "invocation",
        monotonic=clock,
        sleep=lambda _seconds: None,
    )

    with pytest.raises(SkillError) as caught:
        if operation == "stream":
            with adapter.stream_query(
                database="analytics",
                sql="SELECT 1",
                params={},
                limit=10,
                statement_timeout_ms=2500,
            ) as stream:
                list(stream)
        elif operation == "explain":
            adapter.explain(
                database="analytics",
                sql="SELECT 1",
                params={},
                statement_timeout_ms=2500,
            )
        else:
            adapter.catalog_source("analytics", 2500).show_databases()

    assert caught.value.full_code in {"query.failed", "metadata.failed"}
    assert client.user_result_calls == 2


def test_data_api_requires_has_result_set_before_fetching_user_results() -> None:
    class MissingResultSetClient(DataApiClient):
        def __init__(self) -> None:
            super().__init__()
            self.user_result_calls = 0

        def describe_statement(self, **kwargs):
            result = super().describe_statement(**kwargs)
            if kwargs["Id"] == "user":
                result["HasResultSet"] = False
            return result

        def get_statement_result(self, **kwargs):
            if kwargs["Id"] == "user":
                self.user_result_calls += 1
            return super().get_statement_result(**kwargs)

    client = MissingResultSetClient()
    adapter = DataApiAdapter(
        data_api_profile(),
        {},
        aws_resolver_factory=lambda *_args: Resolver(client),
        invocation_id_factory=lambda: "invocation",
        monotonic=lambda: 0.0,
        sleep=lambda _seconds: None,
    )

    with pytest.raises(SkillError) as caught:
        adapter.query(
            database="analytics",
            sql="SELECT 1",
            params={},
            limit=10,
            statement_timeout_ms=2500,
        )

    assert caught.value.full_code == "query.failed"
    assert caught.value.details == {"stage": "result_fetch"}
    assert client.user_result_calls == 0
