"""Bounded current-v2 membership, subscription, benefit, and event trace."""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

from ..errors import SkillError, usage_error
from ..models import CommandResult, QueryResult


MEMBERSHIP_DATABASE = "pg_moego_membership_prod_v2"
MEMBERSHIP_LIMIT = 2
SUBSCRIPTION_LIMIT = 200
RELATED_LIMIT = 200

MEMBERSHIP_SQL = """
SELECT id,
       organization_id,
       organization_type,
       name,
       state,
       source,
       version,
       create_time,
       update_time,
       delete_time
FROM pg_moego_membership_prod_v2.public.memberships
WHERE id = %(membership_id)s
""".strip()

SUBSCRIPTION_SQL = """
SELECT id,
       organization_id,
       organization_type,
       membership_id,
       price_id,
       buyer_id,
       buyer_type,
       owner_id,
       owner_type,
       seller_id,
       seller_type,
       name,
       state,
       schedule_start_time,
       schedule_cancel_time,
       schedule_resume_time,
       pause_time,
       billing_agreement_id,
       current_billing_cycle_id,
       touch_point,
       last_event_time,
       maintain_benefits_after_cancel,
       create_time,
       update_time,
       delete_time
FROM pg_moego_membership_prod_v2.public.subscriptions
WHERE id = %(subscription_id)s
""".strip()

SUBSCRIPTIONS_SQL = """
SELECT id,
       organization_id,
       organization_type,
       membership_id,
       price_id,
       buyer_id,
       buyer_type,
       owner_id,
       owner_type,
       seller_id,
       seller_type,
       name,
       state,
       schedule_start_time,
       schedule_cancel_time,
       schedule_resume_time,
       pause_time,
       billing_agreement_id,
       current_billing_cycle_id,
       touch_point,
       last_event_time,
       maintain_benefits_after_cancel,
       create_time,
       update_time,
       delete_time
FROM pg_moego_membership_prod_v2.public.subscriptions
WHERE membership_id = %(membership_id)s
ORDER BY create_time, id
""".strip()

PRICE_SQL = """
SELECT id,
       organization_id,
       organization_type,
       membership_id,
       name,
       unit_amount,
       currency,
       tax_id,
       recurring_interval_unit,
       recurring_interval_value,
       billing_schedule,
       version,
       create_time,
       update_time,
       delete_time
FROM pg_moego_membership_prod_v2.public.prices
WHERE membership_id = %(membership_id)s
ORDER BY create_time, id
""".strip()

BENEFIT_CONFIG_SQL = """
SELECT id,
       organization_id,
       organization_type,
       type,
       membership_id,
       price_id,
       expiration_policy,
       promotion_id,
       version,
       create_time,
       update_time,
       delete_time
FROM pg_moego_membership_prod_v2.public.benefit_configs
WHERE membership_id = %(membership_id)s
ORDER BY create_time, id
""".strip()

BENEFIT_SQL = """
SELECT id,
       organization_id,
       organization_type,
       owner_id,
       owner_type,
       subscription_id,
       billing_cycle_id,
       config_id,
       type,
       state,
       coupon_id,
       create_time,
       update_time,
       delete_time,
       source
FROM pg_moego_membership_prod_v2.public.benefits
WHERE subscription_id IN %(subscription_ids)s
ORDER BY create_time, id
""".strip()

EVENT_SQL = """
SELECT id,
       uid,
       organization_id,
       organization_type,
       membership_id,
       subscription_id,
       type,
       state,
       create_time,
       update_time
FROM pg_moego_membership_prod_v2.public.events
WHERE membership_id = %(membership_id)s
ORDER BY create_time, id
""".strip()

SUBSCRIPTION_EVENT_SQL = """
SELECT id,
       uid,
       organization_id,
       organization_type,
       membership_id,
       subscription_id,
       type,
       state,
       create_time,
       update_time
FROM pg_moego_membership_prod_v2.public.events
WHERE membership_id = %(membership_id)s
  AND (subscription_id = %(subscription_id)s OR subscription_id IS NULL)
ORDER BY create_time, id
""".strip()


QueryExecutor = Callable[..., QueryResult]


def _require_complete(result: QueryResult, stage: int) -> None:
    if result.truncated:
        raise SkillError(
            category="query",
            code="limit_out_of_range",
            retry_class="after_change",
            details={"stage": stage},
        )


def _single_record(result: QueryResult) -> dict[str, Any] | None:
    if result.row_count > 1:
        raise SkillError("internal", "unexpected", "never")
    return dict(result.records[0]) if result.records else None


def _records(result: QueryResult) -> list[dict[str, Any]]:
    return [dict(record) for record in result.records]


def _stage_meta(stage: int, name: str, result: QueryResult) -> dict[str, Any]:
    return {
        "stage": stage,
        "name": name,
        "connectionDatabase": result.connection_database,
        "rowCount": result.row_count,
        "elapsedMs": result.elapsed_ms,
    }


def _empty_result(input_type: str, stages: list[dict[str, Any]]) -> CommandResult:
    return CommandResult(
        data={
            "inputType": input_type,
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
        },
        meta={"stages": stages},
    )


def run_membership_entitlement(
    execute: QueryExecutor,
    *,
    membership_id: int | None = None,
    subscription_id: int | None = None,
    database: str = MEMBERSHIP_DATABASE,
    timeout_ms: int | None = None,
) -> CommandResult:
    """Trace one current-v2 membership or subscription through its entitlements."""

    if membership_id is None and subscription_id is None:
        raise usage_error("missing_argument")
    if membership_id is not None and subscription_id is not None:
        raise usage_error("invalid_combination")

    stages: list[dict[str, Any]] = []
    if membership_id is not None:
        input_type = "membership_id"
        membership_result = execute(
            sql=MEMBERSHIP_SQL,
            params={"membership_id": membership_id},
            database=database,
            limit=MEMBERSHIP_LIMIT,
            timeout_ms=timeout_ms,
        )
        _require_complete(membership_result, 1)
        membership = _single_record(membership_result)
        stages.append(_stage_meta(1, "membership", membership_result))
        if membership is None:
            return _empty_result(input_type, stages)
        memberships = [membership]

        subscriptions_result = execute(
            sql=SUBSCRIPTIONS_SQL,
            params={"membership_id": membership_id},
            database=database,
            limit=SUBSCRIPTION_LIMIT,
            timeout_ms=timeout_ms,
        )
        _require_complete(subscriptions_result, 2)
        subscriptions = _records(subscriptions_result)
        stages.append(_stage_meta(2, "subscriptions", subscriptions_result))
    else:
        input_type = "subscription_id"
        subscription_result = execute(
            sql=SUBSCRIPTION_SQL,
            params={"subscription_id": subscription_id},
            database=database,
            limit=MEMBERSHIP_LIMIT,
            timeout_ms=timeout_ms,
        )
        _require_complete(subscription_result, 1)
        subscription = _single_record(subscription_result)
        stages.append(_stage_meta(1, "subscription", subscription_result))
        if subscription is None:
            return _empty_result(input_type, stages)
        subscriptions = [subscription]
        try:
            membership_id = int(subscription["membership_id"])
        except (KeyError, TypeError, ValueError) as exc:
            raise SkillError("internal", "unexpected", "never") from exc

        membership_result = execute(
            sql=MEMBERSHIP_SQL,
            params={"membership_id": membership_id},
            database=database,
            limit=MEMBERSHIP_LIMIT,
            timeout_ms=timeout_ms,
        )
        _require_complete(membership_result, 2)
        membership = _single_record(membership_result)
        memberships = [membership] if membership is not None else []
        stages.append(_stage_meta(2, "membership", membership_result))

    prices_result = execute(
        sql=PRICE_SQL,
        params={"membership_id": membership_id},
        database=database,
        limit=RELATED_LIMIT,
        timeout_ms=timeout_ms,
    )
    _require_complete(prices_result, 3)
    prices = _records(prices_result)
    stages.append(_stage_meta(3, "prices", prices_result))

    configs_result = execute(
        sql=BENEFIT_CONFIG_SQL,
        params={"membership_id": membership_id},
        database=database,
        limit=RELATED_LIMIT,
        timeout_ms=timeout_ms,
    )
    _require_complete(configs_result, 4)
    configs = _records(configs_result)
    stages.append(_stage_meta(4, "benefit_configs", configs_result))

    try:
        subscription_ids = tuple(int(record["id"]) for record in subscriptions)
    except (KeyError, TypeError, ValueError) as exc:
        raise SkillError("internal", "unexpected", "never") from exc
    benefits: list[dict[str, Any]] = []
    if subscription_ids:
        benefits_result = execute(
            sql=BENEFIT_SQL,
            params={"subscription_ids": subscription_ids},
            database=database,
            limit=RELATED_LIMIT,
            timeout_ms=timeout_ms,
        )
        _require_complete(benefits_result, 5)
        benefits = _records(benefits_result)
        stages.append(_stage_meta(5, "benefits", benefits_result))

    event_sql = EVENT_SQL if input_type == "membership_id" else SUBSCRIPTION_EVENT_SQL
    event_params = {"membership_id": membership_id}
    if input_type == "subscription_id":
        event_params["subscription_id"] = subscription_id
    events_result = execute(
        sql=event_sql,
        params=event_params,
        database=database,
        limit=RELATED_LIMIT,
        timeout_ms=timeout_ms,
    )
    _require_complete(events_result, 6)
    events = _records(events_result)
    stages.append(_stage_meta(6, "events", events_result))

    return CommandResult(
        data={
            "inputType": input_type,
            "memberships": memberships,
            "subscriptions": subscriptions,
            "prices": prices,
            "benefitConfigs": configs,
            "benefits": benefits,
            "events": events,
            "membershipCount": len(memberships),
            "subscriptionCount": len(subscriptions),
            "priceCount": len(prices),
            "benefitConfigCount": len(configs),
            "benefitCount": len(benefits),
            "eventCount": len(events),
        },
        meta={"stages": stages},
    )
