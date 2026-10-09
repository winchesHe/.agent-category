"""Bounded current-model appointment snapshot and status timeline."""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

from ..errors import SkillError
from ..models import CommandResult, QueryResult


APPOINTMENT_DATABASE = "pg_moego_fulfillment_prod"
APPOINTMENT_LIMIT = 2
STATUS_HISTORY_LIMIT = 200

APPOINTMENT_SQL = """
SELECT id,
       business_id,
       customer_id,
       company_id,
       status,
       service_item_type,
       created_at,
       updated_at,
       delete_at,
       time_range,
       start_time,
       end_time,
       payment_status,
       no_show,
       source,
       no_show_by,
       created_by,
       repeat_id
FROM pg_moego_fulfillment_prod.public.appointment
WHERE id = %(appointment_id)s
""".strip()

STATUS_HISTORY_SQL = """
SELECT id,
       appointment_id,
       from_status,
       to_status,
       change_type,
       update_by,
       changed_at,
       is_revert,
       reverted_at,
       created_at,
       updated_at
FROM pg_moego_fulfillment_prod.public.appointment_status_record
WHERE appointment_id = %(appointment_id)s
ORDER BY COALESCE(changed_at, created_at), id
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


def run_appointment_timeline(
    execute: QueryExecutor,
    *,
    appointment_id: int,
    database: str = APPOINTMENT_DATABASE,
    timeout_ms: int | None = None,
) -> CommandResult:
    """Return one current appointment and its ordered status transitions."""

    appointment_result = execute(
        sql=APPOINTMENT_SQL,
        params={"appointment_id": appointment_id},
        database=database,
        limit=APPOINTMENT_LIMIT,
        timeout_ms=timeout_ms,
    )
    _require_complete(appointment_result, 1)
    appointment = _single_record(appointment_result)
    stages = [_stage_meta(1, "appointment", appointment_result)]
    if appointment is None:
        return CommandResult(
            data={
                "appointment": None,
                "statusHistory": [],
                "statusHistoryCount": 0,
            },
            meta={"stages": stages},
        )

    history_result = execute(
        sql=STATUS_HISTORY_SQL,
        params={"appointment_id": appointment_id},
        database=database,
        limit=STATUS_HISTORY_LIMIT,
        timeout_ms=timeout_ms,
    )
    _require_complete(history_result, 2)
    history = [dict(record) for record in history_result.records]
    stages.append(_stage_meta(2, "status_history", history_result))
    return CommandResult(
        data={
            "appointment": appointment,
            "statusHistory": history,
            "statusHistoryCount": len(history),
        },
        meta={"stages": stages},
    )
