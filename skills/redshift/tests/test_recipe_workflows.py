from __future__ import annotations

from dataclasses import replace

import pytest

from scripts.rs.errors import SkillError
from scripts.rs.models import Column, QueryResult
from scripts.rs.query.guard import validate_read_only_sql
from scripts.rs.query.execute import JSON_MAX_LIMIT
from scripts.rs.recipes.appointment_timeline import (
    APPOINTMENT_DATABASE,
    APPOINTMENT_LIMIT,
    APPOINTMENT_SQL,
    STATUS_HISTORY_LIMIT,
    STATUS_HISTORY_SQL,
    run_appointment_timeline,
)
from scripts.rs.recipes.membership_entitlement import (
    BENEFIT_CONFIG_SQL,
    BENEFIT_SQL,
    EVENT_SQL,
    MEMBERSHIP_DATABASE,
    MEMBERSHIP_LIMIT,
    MEMBERSHIP_SQL,
    PRICE_SQL,
    RELATED_LIMIT,
    SUBSCRIPTION_LIMIT,
    SUBSCRIPTION_EVENT_SQL,
    SUBSCRIPTION_SQL,
    SUBSCRIPTIONS_SQL,
    run_membership_entitlement,
)
from scripts.rs.recipes.refund_origin import (
    ORDER_DATABASE,
    ORDER_PAYMENT_LIMIT,
    ORDER_PAYMENT_SQL,
    PAYMENT_DATABASE,
    PAYMENT_LIMIT,
    PAYMENT_SQL,
    REFUND_LIMIT,
    REFUND_SQL,
    run_refund_origin,
)


def result(records=(), *, truncated=False, database="db") -> QueryResult:
    names = tuple(records[0].keys()) if records else ()
    return QueryResult(
        columns=tuple(Column(name, "text") for name in names),
        records=tuple(records),
        row_count=len(records),
        truncated=truncated,
        elapsed_ms=1,
        connection_database=database,
        statement_timeout_ms=1000,
    )


def test_all_recipe_sql_is_single_statement_readonly_and_uses_live_verified_objects() -> None:
    expected_objects = {
        APPOINTMENT_SQL: "pg_moego_fulfillment_prod.public.appointment",
        STATUS_HISTORY_SQL: "pg_moego_fulfillment_prod.public.appointment_status_record",
        REFUND_SQL: "pg_moego_payment_prod.public.refund",
        PAYMENT_SQL: "pg_moego_payment_prod.public.payment",
        ORDER_PAYMENT_SQL: "pg_moego_order_prod.public.order_payment",
        MEMBERSHIP_SQL: "pg_moego_membership_prod_v2.public.memberships",
        SUBSCRIPTION_SQL: "pg_moego_membership_prod_v2.public.subscriptions",
        SUBSCRIPTIONS_SQL: "pg_moego_membership_prod_v2.public.subscriptions",
        PRICE_SQL: "pg_moego_membership_prod_v2.public.prices",
        BENEFIT_CONFIG_SQL: "pg_moego_membership_prod_v2.public.benefit_configs",
        BENEFIT_SQL: "pg_moego_membership_prod_v2.public.benefits",
        EVENT_SQL: "pg_moego_membership_prod_v2.public.events",
        SUBSCRIPTION_EVENT_SQL: "pg_moego_membership_prod_v2.public.events",
    }
    for sql, object_name in expected_objects.items():
        assert validate_read_only_sql(sql) == sql
        assert object_name in sql
    assert max(
        APPOINTMENT_LIMIT,
        STATUS_HISTORY_LIMIT,
        REFUND_LIMIT,
        PAYMENT_LIMIT,
        ORDER_PAYMENT_LIMIT,
        MEMBERSHIP_LIMIT,
        SUBSCRIPTION_LIMIT,
        RELATED_LIMIT,
    ) <= JSON_MAX_LIMIT


def test_appointment_timeline_returns_snapshot_then_ordered_status_history() -> None:
    calls = []

    def execute(**kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            return result(
                ({"id": 11, "status": 2, "created_at": "2026-01-01"},),
                database=kwargs["database"],
            )
        return result(
            (
                {"id": 21, "appointment_id": 11, "from_status": 1, "to_status": 2},
            ),
            database=kwargs["database"],
        )

    outcome = run_appointment_timeline(execute, appointment_id=11, timeout_ms=1200)
    assert [call["database"] for call in calls] == [
        APPOINTMENT_DATABASE,
        APPOINTMENT_DATABASE,
    ]
    assert [call["limit"] for call in calls] == [APPOINTMENT_LIMIT, STATUS_HISTORY_LIMIT]
    assert all(call["params"] == {"appointment_id": 11} for call in calls)
    assert outcome.data == {
        "appointment": {"id": 11, "status": 2, "created_at": "2026-01-01"},
        "statusHistory": [
            {"id": 21, "appointment_id": 11, "from_status": 1, "to_status": 2}
        ],
        "statusHistoryCount": 1,
    }
    assert [stage["name"] for stage in outcome.meta["stages"]] == [
        "appointment",
        "status_history",
    ]


def test_appointment_no_match_stops_before_history() -> None:
    calls = []

    def execute(**kwargs):
        calls.append(kwargs)
        return result(database=kwargs["database"])

    outcome = run_appointment_timeline(execute, appointment_id=11)
    assert len(calls) == 1
    assert outcome.data == {
        "appointment": None,
        "statusHistory": [],
        "statusHistoryCount": 0,
    }


def test_refund_origin_follows_refund_to_payment_and_order_payment() -> None:
    calls = []

    def execute(**kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            return result(
                ({"id": 31, "payment_id": 41, "external_type": "ORDER"},),
                database=kwargs["database"],
            )
        if len(calls) == 2:
            return result(
                ({"id": 41, "external_type": "ORDER", "external_id": "51"},),
                database=kwargs["database"],
            )
        return result(
            ({"id": 61, "payment_id": 41, "order_id": 51},),
            database=kwargs["database"],
        )

    outcome = run_refund_origin(execute, refund_id=31, timeout_ms=1300)
    assert [call["database"] for call in calls] == [
        PAYMENT_DATABASE,
        PAYMENT_DATABASE,
        ORDER_DATABASE,
    ]
    assert [call["limit"] for call in calls] == [
        REFUND_LIMIT,
        PAYMENT_LIMIT,
        ORDER_PAYMENT_LIMIT,
    ]
    assert calls[0]["params"] == {"refund_id": 31}
    assert calls[1]["params"] == {"payment_id": 41}
    assert calls[2]["params"] == {"payment_id": 41}
    assert outcome.data["refund"]["id"] == 31
    assert outcome.data["payment"]["id"] == 41
    assert outcome.data["orderPayments"][0]["order_id"] == 51
    assert outcome.data["orderPaymentCount"] == 1


def test_refund_no_match_stops_before_related_stages() -> None:
    calls = []

    def execute(**kwargs):
        calls.append(kwargs)
        return result(database=kwargs["database"])

    outcome = run_refund_origin(execute, refund_id=31)
    assert len(calls) == 1
    assert outcome.data == {
        "refund": None,
        "payment": None,
        "orderPayments": [],
        "orderPaymentCount": 0,
    }


def _membership_result_for_call(call_number: int, database: str) -> QueryResult:
    records = {
        1: ({"id": 71, "state": "ACTIVE"},),
        2: ({"id": 81, "membership_id": 71, "price_id": 91},),
        3: ({"id": 91, "membership_id": 71},),
        4: ({"id": 101, "membership_id": 71},),
        5: ({"id": 111, "subscription_id": 81},),
        6: ({"id": 121, "membership_id": 71, "subscription_id": 81},),
    }[call_number]
    return result(records, database=database)


def test_membership_entitlement_from_membership_id_runs_fixed_chain() -> None:
    calls = []

    def execute(**kwargs):
        calls.append(kwargs)
        return _membership_result_for_call(len(calls), kwargs["database"])

    outcome = run_membership_entitlement(execute, membership_id=71, timeout_ms=1400)
    assert len(calls) == 6
    assert all(call["database"] == MEMBERSHIP_DATABASE for call in calls)
    assert [call["limit"] for call in calls] == [
        MEMBERSHIP_LIMIT,
        SUBSCRIPTION_LIMIT,
        RELATED_LIMIT,
        RELATED_LIMIT,
        RELATED_LIMIT,
        RELATED_LIMIT,
    ]
    assert calls[0]["params"] == {"membership_id": 71}
    assert calls[1]["params"] == {"membership_id": 71}
    assert calls[4]["params"] == {"subscription_ids": (81,)}
    assert calls[5]["params"] == {"membership_id": 71}
    assert calls[5]["sql"] == EVENT_SQL
    assert outcome.data["inputType"] == "membership_id"
    assert outcome.data["membershipCount"] == 1
    assert outcome.data["subscriptionCount"] == 1
    assert outcome.data["benefitCount"] == 1
    assert outcome.data["eventCount"] == 1


def test_membership_entitlement_from_subscription_id_resolves_membership_first() -> None:
    calls = []

    def execute(**kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            return result(
                ({"id": 81, "membership_id": 71, "price_id": 91},),
                database=kwargs["database"],
            )
        if len(calls) == 2:
            return result(({"id": 71, "state": "ACTIVE"},), database=kwargs["database"])
        return _membership_result_for_call(len(calls), kwargs["database"])

    outcome = run_membership_entitlement(execute, subscription_id=81)
    assert len(calls) == 6
    assert calls[0]["params"] == {"subscription_id": 81}
    assert calls[1]["params"] == {"membership_id": 71}
    assert calls[4]["params"] == {"subscription_ids": (81,)}
    assert calls[5]["params"] == {"membership_id": 71, "subscription_id": 81}
    assert calls[5]["sql"] == SUBSCRIPTION_EVENT_SQL
    assert outcome.data["inputType"] == "subscription_id"
    assert outcome.data["memberships"][0]["id"] == 71
    assert outcome.data["subscriptions"][0]["id"] == 81


def test_membership_no_match_stops_after_lookup() -> None:
    calls = []

    def execute(**kwargs):
        calls.append(kwargs)
        return result(database=kwargs["database"])

    outcome = run_membership_entitlement(execute, subscription_id=81)
    assert len(calls) == 1
    assert outcome.data == {
        "inputType": "subscription_id",
        "memberships": [],
        "subscriptions": [],
        "prices": [],
        "benefitConfigs": [],
        "benefits": [],
        "events": [],
        "membershipCount": 0,
        "subscriptionCount": 0,
        "priceCount": 0,
        "benefitConfigCount": 0,
        "benefitCount": 0,
        "eventCount": 0,
    }


def test_membership_requires_exactly_one_lookup_identifier() -> None:
    execute = lambda **kwargs: pytest.fail("invalid input must not execute")
    with pytest.raises(SkillError) as missing:
        run_membership_entitlement(execute)
    assert missing.value.full_code == "usage.missing_argument"

    with pytest.raises(SkillError) as conflicting:
        run_membership_entitlement(execute, membership_id=1, subscription_id=2)
    assert conflicting.value.full_code == "usage.invalid_combination"


@pytest.mark.parametrize(
    ("runner", "kwargs", "truncated_call"),
    [
        (run_appointment_timeline, {"appointment_id": 11}, 2),
        (run_refund_origin, {"refund_id": 31}, 1),
        (run_membership_entitlement, {"membership_id": 71}, 4),
    ],
)
def test_recipe_truncation_is_never_returned_as_complete(runner, kwargs, truncated_call) -> None:
    calls = 0

    def execute(**stage):
        nonlocal calls
        calls += 1
        if runner is run_appointment_timeline:
            records = ({"id": 11},) if calls == 1 else ({"appointment_id": 11},)
        elif runner is run_refund_origin:
            records = ({"id": 31, "payment_id": 41},)
        else:
            records = _membership_result_for_call(calls, stage["database"]).records
        base = result(records, database=stage["database"])
        return replace(base, truncated=calls == truncated_call)

    with pytest.raises(SkillError) as caught:
        runner(execute, **kwargs)
    assert caught.value.full_code == "query.limit_out_of_range"
    assert caught.value.details["stage"] == truncated_call
