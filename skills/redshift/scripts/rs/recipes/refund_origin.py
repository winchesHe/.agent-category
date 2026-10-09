"""Bounded current-model refund to payment and order-payment trace."""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

from ..errors import SkillError
from ..models import CommandResult, QueryResult


PAYMENT_DATABASE = "pg_moego_payment_prod"
ORDER_DATABASE = "pg_moego_order_prod"
REFUND_LIMIT = 2
PAYMENT_LIMIT = 2
ORDER_PAYMENT_LIMIT = 200

REFUND_SQL = """
SELECT id,
       created_time,
       updated_time,
       external_type,
       external_id,
       payer_type,
       payer_id,
       payee_type,
       payee_id,
       channel_type,
       channel_reference_id,
       channel_refund_id,
       payment_id,
       currency,
       amount,
       status,
       reason,
       creator_type,
       creator_id,
       issue_time
FROM pg_moego_payment_prod.public.refund
WHERE id = %(refund_id)s
""".strip()

PAYMENT_SQL = """
SELECT id,
       created_time,
       updated_time,
       external_type,
       external_id,
       payer_type,
       payer_id,
       payee_type,
       payee_id,
       payment_type,
       channel_type,
       channel_payment_id,
       channel_reference_id,
       status,
       currency,
       amount,
       processing_fee,
       convenience_fee,
       tips,
       discount,
       refund_status,
       refund_count,
       refunding_amount,
       refunded_amount,
       paid_by,
       transaction_id,
       method_id,
       creator_type,
       creator_id
FROM pg_moego_payment_prod.public.payment
WHERE id = %(payment_id)s
""".strip()

ORDER_PAYMENT_SQL = """
SELECT id,
       order_id,
       company_id,
       business_id,
       customer_id,
       payment_id,
       payment_method,
       payment_method_vendor,
       is_online,
       is_deposit,
       currency,
       total_amount,
       amount,
       refunded_amount,
       payment_status,
       reason,
       pay_time,
       cancel_time,
       fail_time,
       create_time,
       update_time
FROM pg_moego_order_prod.public.order_payment
WHERE payment_id = %(payment_id)s
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


def _stage_meta(stage: int, name: str, result: QueryResult) -> dict[str, Any]:
    return {
        "stage": stage,
        "name": name,
        "connectionDatabase": result.connection_database,
        "rowCount": result.row_count,
        "elapsedMs": result.elapsed_ms,
    }


def run_refund_origin(
    execute: QueryExecutor,
    *,
    refund_id: int,
    payment_database: str = PAYMENT_DATABASE,
    order_database: str = ORDER_DATABASE,
    timeout_ms: int | None = None,
) -> CommandResult:
    """Return a refund, its payment, and matching order-payment records."""

    refund_result = execute(
        sql=REFUND_SQL,
        params={"refund_id": refund_id},
        database=payment_database,
        limit=REFUND_LIMIT,
        timeout_ms=timeout_ms,
    )
    _require_complete(refund_result, 1)
    refund = _single_record(refund_result)
    stages = [_stage_meta(1, "refund", refund_result)]
    if refund is None:
        return CommandResult(
            data={
                "refund": None,
                "payment": None,
                "orderPayments": [],
                "orderPaymentCount": 0,
            },
            meta={"stages": stages},
        )

    try:
        payment_id = int(refund["payment_id"])
    except (KeyError, TypeError, ValueError) as exc:
        raise SkillError("internal", "unexpected", "never") from exc

    payment_result = execute(
        sql=PAYMENT_SQL,
        params={"payment_id": payment_id},
        database=payment_database,
        limit=PAYMENT_LIMIT,
        timeout_ms=timeout_ms,
    )
    _require_complete(payment_result, 2)
    payment = _single_record(payment_result)
    stages.append(_stage_meta(2, "payment", payment_result))

    order_result = execute(
        sql=ORDER_PAYMENT_SQL,
        params={"payment_id": payment_id},
        database=order_database,
        limit=ORDER_PAYMENT_LIMIT,
        timeout_ms=timeout_ms,
    )
    _require_complete(order_result, 3)
    order_payments = [dict(record) for record in order_result.records]
    stages.append(_stage_meta(3, "order_payments", order_result))
    return CommandResult(
        data={
            "refund": refund,
            "payment": payment,
            "orderPayments": order_payments,
            "orderPaymentCount": len(order_payments),
        },
        meta={"stages": stages},
    )
