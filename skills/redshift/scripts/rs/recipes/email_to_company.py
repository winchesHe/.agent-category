"""Canonical bounded two-stage email-to-company lookup."""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

from ..errors import SkillError
from ..models import CommandResult, QueryResult


ACCOUNT_DATABASE = "pg_moego_account_prod"
BUSINESS_DATABASE = "mysql_prod"
ACCOUNT_LIMIT = 20
MEMBERSHIP_LIMIT = 200

ACCOUNT_SQL = """
SELECT id AS account_id
FROM pg_moego_account_prod.public.account
WHERE lower(email) = lower(%(email)s)
  AND status <> 2
  AND namespace_type = 'MOEGO'
  AND namespace_id = 0
ORDER BY id
""".strip()

MEMBERSHIP_SQL = """
SELECT DISTINCT
       s.account_id,
       s.company_id,
       c.name AS company_name,
       b.id AS business_id,
       b.business_name
FROM mysql_prod.moe_business.moe_staff AS s
LEFT JOIN mysql_prod.moe_business.moe_company AS c
  ON c.id = s.company_id
LEFT JOIN mysql_prod.moe_business.moe_business AS b
  ON b.company_id = s.company_id
 AND (s.working_in_all_locations = 1 OR b.id = s.business_id)
WHERE s.account_id IN %(account_ids)s
ORDER BY s.company_id, b.id
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


def _stage_meta(stage: int, result: QueryResult) -> dict[str, Any]:
    return {
        "stage": stage,
        "connectionDatabase": result.connection_database,
        "rowCount": result.row_count,
        "elapsedMs": result.elapsed_ms,
    }


def run_email_to_company(
    execute: QueryExecutor,
    *,
    email: str,
    account_database: str = ACCOUNT_DATABASE,
    business_database: str = BUSINESS_DATABASE,
    timeout_ms: int | None = None,
) -> CommandResult:
    """Resolve active MOEGO accounts, then their company/business memberships."""

    accounts_result = execute(
        sql=ACCOUNT_SQL,
        params={"email": email},
        database=account_database,
        limit=ACCOUNT_LIMIT,
        timeout_ms=timeout_ms,
    )
    _require_complete(accounts_result, 1)
    accounts = [dict(record) for record in accounts_result.records]
    stages = [_stage_meta(1, accounts_result)]

    if not accounts:
        return CommandResult(
            data={
                "accounts": [],
                "memberships": [],
                "accountCount": 0,
                "membershipCount": 0,
            },
            meta={"stages": stages},
        )

    try:
        account_ids = tuple(int(record["account_id"]) for record in accounts)
    except (KeyError, TypeError, ValueError) as exc:
        raise SkillError("internal", "unexpected", "never") from exc

    memberships_result = execute(
        sql=MEMBERSHIP_SQL,
        params={"account_ids": account_ids},
        database=business_database,
        limit=MEMBERSHIP_LIMIT,
        timeout_ms=timeout_ms,
    )
    _require_complete(memberships_result, 2)
    memberships = [dict(record) for record in memberships_result.records]
    stages.append(_stage_meta(2, memberships_result))
    return CommandResult(
        data={
            "accounts": accounts,
            "memberships": memberships,
            "accountCount": len(accounts),
            "membershipCount": len(memberships),
        },
        meta={"stages": stages},
    )
