"""Shared discovery entitlement checks for API and worker flows."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta


class DiscoveryAuthorizationError(PermissionError):
    """Raised when discovery execution is not currently entitled."""


@dataclass(frozen=True, slots=True)
class DiscoveryAuthorizationSnapshot:
    has_active_subscription: bool
    over_keyword_limit: bool
    active_keywords: list[str]


@dataclass(frozen=True, slots=True)
class SubscriptionLike:
    plan_code: str
    subscription_status: object
    billing_period_start: str
    billing_period_end: str
    keyword_limit: int | None
    activated_at: str
    created_at: str


@dataclass(frozen=True, slots=True)
class EffectiveDiscoveryEntitlement:
    plan_code: str | None
    subscription_status: str | None
    has_active_subscription: bool
    keyword_limit: int | None
    profile_cycle_started_at: datetime | None


def normalize_keyword(value: str) -> str:
    return str(value).strip()


def require_discovery_authorization(
    *,
    snapshot: DiscoveryAuthorizationSnapshot,
    keyword: str,
) -> DiscoveryAuthorizationSnapshot:
    if not snapshot.has_active_subscription:
        raise DiscoveryAuthorizationError("active subscription required for runs")
    if snapshot.over_keyword_limit:
        raise DiscoveryAuthorizationError(
            "active keyword configuration exceeds plan limit"
        )
    normalized_keyword = normalize_keyword(keyword)
    entitled_keywords = {value.casefold() for value in snapshot.active_keywords}
    if not normalized_keyword or normalized_keyword.casefold() not in entitled_keywords:
        raise DiscoveryAuthorizationError("discover keyword is not entitled for tenant")
    return snapshot


def build_discovery_authorization_snapshot(
    *,
    subscriptions: list[SubscriptionLike],
    active_keywords: list[str],
) -> DiscoveryAuthorizationSnapshot:
    entitlement = resolve_effective_discovery_entitlement(subscriptions=subscriptions)
    keyword_limit = entitlement.keyword_limit
    over_keyword_limit = keyword_limit is not None and len(active_keywords) > int(
        keyword_limit
    )
    return DiscoveryAuthorizationSnapshot(
        has_active_subscription=entitlement.has_active_subscription,
        over_keyword_limit=over_keyword_limit,
        active_keywords=active_keywords,
    )


def resolve_effective_discovery_entitlement(
    *, subscriptions: list[SubscriptionLike]
) -> EffectiveDiscoveryEntitlement:
    current_subscription = _select_current_subscription(subscriptions)
    if current_subscription is None:
        return EffectiveDiscoveryEntitlement(
            plan_code=None,
            subscription_status=None,
            has_active_subscription=False,
            keyword_limit=None,
            profile_cycle_started_at=None,
        )

    current_status = _status_value(current_subscription)
    current_plan_code = str(getattr(current_subscription, "plan_code", "") or "")
    if current_status == "active":
        return EffectiveDiscoveryEntitlement(
            plan_code=current_plan_code or None,
            subscription_status=current_status,
            has_active_subscription=True,
            keyword_limit=getattr(current_subscription, "keyword_limit", None),
            profile_cycle_started_at=_profile_cycle_start_for_active_subscription(
                current_subscription=current_subscription,
                subscriptions=subscriptions,
            ),
        )

    if current_status == "expired" and current_plan_code == "monthly_membership":
        fallback_start = datetime.combine(
            date.fromisoformat(str(current_subscription.billing_period_end)) + timedelta(days=1),
            time.min,
            tzinfo=UTC,
        )
        return EffectiveDiscoveryEntitlement(
            plan_code="free_trial",
            subscription_status="active",
            has_active_subscription=True,
            keyword_limit=1,
            profile_cycle_started_at=fallback_start,
        )

    return EffectiveDiscoveryEntitlement(
        plan_code=current_plan_code or None,
        subscription_status=current_status,
        has_active_subscription=False,
        keyword_limit=getattr(current_subscription, "keyword_limit", None),
        profile_cycle_started_at=None,
    )


def _profile_cycle_start_for_active_subscription(
    *,
    current_subscription: SubscriptionLike,
    subscriptions: list[SubscriptionLike],
) -> datetime | None:
    if str(getattr(current_subscription, "plan_code", "") or "") != "one_time_search_pack":
        return None
    current_id = str(getattr(current_subscription, "id", "") or "")
    current_period_start = _subscription_date_ordinal(
        current_subscription,
        "billing_period_start",
    )
    has_previous_one_time_cycle = any(
        str(getattr(subscription, "plan_code", "") or "") == "one_time_search_pack"
        and str(getattr(subscription, "id", "") or "") != current_id
        and _subscription_date_ordinal(subscription, "billing_period_start")
        < current_period_start
        for subscription in subscriptions
    )
    if not has_previous_one_time_cycle:
        return None
    return _parse_datetime(str(current_subscription.activated_at))


def _select_current_subscription(
    subscriptions: list[SubscriptionLike],
) -> SubscriptionLike | None:
    if not subscriptions:
        return None
    priorities = {"active": 0, "pending_activation": 1, "expired": 2, "cancelled": 3}
    return min(
        subscriptions,
        key=lambda subscription: (
            priorities.get(_status_value(subscription), 99),
            -_subscription_date_ordinal(subscription, "billing_period_end"),
            -_subscription_date_ordinal(subscription, "billing_period_start"),
            str(getattr(subscription, "created_at", "") or ""),
        ),
    )


def _status_value(subscription: SubscriptionLike) -> str:
    return str(
        getattr(
            subscription.subscription_status,
            "value",
            subscription.subscription_status,
        )
    )


def _parse_datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed


def _subscription_date_ordinal(subscription: SubscriptionLike, field_name: str) -> int:
    raw_value = getattr(subscription, field_name, None)
    if raw_value in {None, ""}:
        return 0
    return date.fromisoformat(str(raw_value)).toordinal()
