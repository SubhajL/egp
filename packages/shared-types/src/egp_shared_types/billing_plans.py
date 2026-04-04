"""Shared billing plan definitions used by billing APIs and activation logic."""

from __future__ import annotations

from calendar import monthrange
from dataclasses import dataclass
from datetime import date, timedelta


@dataclass(frozen=True, slots=True)
class BillingPlanDefinition:
    code: str
    label: str
    description: str
    currency: str
    amount_due: str
    billing_interval: str
    keyword_limit: int
    duration_days: int | None = None
    duration_months: int | None = None


_BILLING_PLANS = (
    BillingPlanDefinition(
        code="one_time_search_pack",
        label="One-Time Search Pack",
        description="1 keyword for 3 days",
        currency="THB",
        amount_due="300.00",
        billing_interval="one_time",
        keyword_limit=1,
        duration_days=3,
    ),
    BillingPlanDefinition(
        code="monthly_membership",
        label="Monthly Membership",
        description="Up to 5 active keywords during the prepaid billing period",
        currency="THB",
        amount_due="1500.00",
        billing_interval="monthly",
        keyword_limit=5,
        duration_months=1,
    ),
)


def list_billing_plan_definitions() -> list[BillingPlanDefinition]:
    return list(_BILLING_PLANS)


def get_billing_plan_definition(plan_code: str) -> BillingPlanDefinition | None:
    normalized_code = str(plan_code).strip()
    for plan in _BILLING_PLANS:
        if plan.code == normalized_code:
            return plan
    return None


def derive_plan_period_end(
    plan: BillingPlanDefinition, *, billing_period_start: date
) -> date:
    if plan.duration_days is not None:
        return billing_period_start + timedelta(days=plan.duration_days - 1)

    if plan.duration_months is None:
        raise ValueError(f"billing plan {plan.code} has no duration")

    month_index = billing_period_start.month - 1 + plan.duration_months
    year = billing_period_start.year + month_index // 12
    month = month_index % 12 + 1
    last_day = monthrange(year, month)[1]
    candidate_day = min(billing_period_start.day, last_day)
    next_period_start = date(year, month, candidate_day)
    return next_period_start - timedelta(days=1)
