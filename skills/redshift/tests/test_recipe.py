from __future__ import annotations

from dataclasses import replace

import pytest

from scripts.rs.errors import SkillError
from scripts.rs.models import Column, QueryResult
from scripts.rs.recipes.email_to_company import (
    ACCOUNT_DATABASE,
    ACCOUNT_SQL,
    BUSINESS_DATABASE,
    MEMBERSHIP_SQL,
    run_email_to_company,
)
from scripts.rs.recipes.registry import list_recipes


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


def test_registry_exposes_stable_recipe_metadata() -> None:
    recipes = list_recipes()
    assert [item["name"] for item in recipes] == [
        "email-to-company",
        "appointment-timeline",
        "refund-origin",
        "membership-entitlement",
    ]
    assert recipes[0]["parameters"] == ["email"]
    assert all(item["verifiedAt"] for item in recipes)
    assert recipes[0]["sources"] == [ACCOUNT_DATABASE, BUSINESS_DATABASE]


def test_canonical_identity_filter_exists_only_in_account_stage() -> None:
    for clause in (
        "status <> 2",
        "namespace_type = 'MOEGO'",
        "namespace_id = 0",
    ):
        assert ACCOUNT_SQL.count(clause) == 1
        assert clause not in MEMBERSHIP_SQL
    assert "legacy_moe_account" not in ACCOUNT_SQL + MEMBERSHIP_SQL
    assert "profile_email" not in ACCOUNT_SQL + MEMBERSHIP_SQL
    assert "b.id = s.business_id" in MEMBERSHIP_SQL
    assert "s.working_in_all_locations = 1" in MEMBERSHIP_SQL


def test_recipe_runs_two_bounded_stages_and_does_not_echo_email() -> None:
    calls = []

    def execute(**kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            return result(({"account_id": 7},), database=kwargs["database"])
        return result(
            (
                {
                    "account_id": 7,
                    "company_id": 8,
                    "company_name": "Example",
                    "business_id": 9,
                    "business_name": "Example East",
                },
            ),
            database=kwargs["database"],
        )

    outcome = run_email_to_company(execute, email="person@example.invalid", timeout_ms=1200)
    assert [call["database"] for call in calls] == [ACCOUNT_DATABASE, BUSINESS_DATABASE]
    assert [call["limit"] for call in calls] == [20, 200]
    assert calls[0]["params"] == {"email": "person@example.invalid"}
    assert calls[1]["params"] == {"account_ids": (7,)}
    assert outcome.data["accountCount"] == 1
    assert outcome.data["membershipCount"] == 1
    assert "person@example.invalid" not in repr(outcome.data)


def test_empty_account_result_does_not_run_membership_stage() -> None:
    calls = []

    def execute(**kwargs):
        calls.append(kwargs)
        return result(database=kwargs["database"])

    outcome = run_email_to_company(execute, email="none@example.invalid")
    assert len(calls) == 1
    assert outcome.data == {
        "accounts": [],
        "memberships": [],
        "accountCount": 0,
        "membershipCount": 0,
    }


@pytest.mark.parametrize("failing_stage", [1, 2])
def test_stage_failure_is_not_converted_to_empty_result(failing_stage: int) -> None:
    calls = 0

    def execute(**kwargs):
        nonlocal calls
        calls += 1
        if calls == failing_stage:
            raise SkillError("query", "timeout", "transient")
        return result(({"account_id": 7},), database=kwargs["database"])

    with pytest.raises(SkillError) as caught:
        run_email_to_company(execute, email="person@example.invalid")
    assert caught.value.full_code == "query.timeout"


@pytest.mark.parametrize("truncated_stage", [1, 2])
def test_truncated_stage_is_rejected_as_incomplete(truncated_stage: int) -> None:
    calls = 0

    def execute(**kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            base = result(({"account_id": 7},), database=kwargs["database"])
        else:
            base = result(({"account_id": 7, "company_id": 8},), database=kwargs["database"])
        return replace(base, truncated=calls == truncated_stage)

    with pytest.raises(SkillError) as caught:
        run_email_to_company(execute, email="person@example.invalid")
    assert caught.value.full_code == "query.limit_out_of_range"
    assert caught.value.details["stage"] == truncated_stage
