"""Unit tests for billing plan classification helpers."""

from __future__ import annotations

import pytest

from egp_shared_types.billing_plans import is_recurring_membership_plan


@pytest.mark.parametrize(
    ("plan_code", "expected"),
    [
        ("monthly_membership", True),
        ("one_time_search_pack", False),
        ("free_trial", False),
        ("unknown_plan", False),
        ("", False),
    ],
)
def test_is_recurring_membership_plan_classifies_plans(
    plan_code: str, expected: bool
) -> None:
    assert is_recurring_membership_plan(plan_code) is expected
