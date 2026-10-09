"""Stable registry for the small set of maintained MoeGo recipes."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .appointment_timeline import APPOINTMENT_DATABASE
from .email_to_company import ACCOUNT_DATABASE, BUSINESS_DATABASE
from .membership_entitlement import MEMBERSHIP_DATABASE
from .refund_origin import ORDER_DATABASE, PAYMENT_DATABASE


@dataclass(frozen=True)
class RecipeSpec:
    name: str
    purpose: str
    parameters: tuple[str, ...]
    sources: tuple[str, ...]
    verified_at: str

    def to_payload(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "purpose": self.purpose,
            "parameters": list(self.parameters),
            "sources": list(self.sources),
            "verifiedAt": self.verified_at,
        }


RECIPE_SPECS: tuple[RecipeSpec, ...] = (
    RecipeSpec(
        name="email-to-company",
        purpose="Resolve active MOEGO accounts to company and business memberships",
        parameters=("email",),
        sources=(ACCOUNT_DATABASE, BUSINESS_DATABASE),
        verified_at="2026-07-14",
    ),
    RecipeSpec(
        name="appointment-timeline",
        purpose="Return a current appointment snapshot and ordered status transitions",
        parameters=("appointment_id",),
        sources=(APPOINTMENT_DATABASE,),
        verified_at="2026-07-15",
    ),
    RecipeSpec(
        name="refund-origin",
        purpose="Trace a current refund to its payment and matching order-payment records",
        parameters=("refund_id",),
        sources=(PAYMENT_DATABASE, ORDER_DATABASE),
        verified_at="2026-07-15",
    ),
    RecipeSpec(
        name="membership-entitlement",
        purpose="Trace one current membership or subscription through prices, benefits, and events",
        parameters=("membership_id", "subscription_id"),
        sources=(MEMBERSHIP_DATABASE,),
        verified_at="2026-07-15",
    ),
)


def list_recipes() -> list[dict[str, Any]]:
    return [spec.to_payload() for spec in RECIPE_SPECS]
