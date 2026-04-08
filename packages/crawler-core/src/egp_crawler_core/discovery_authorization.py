"""Shared discovery entitlement checks for API and worker flows."""

from __future__ import annotations

from dataclasses import dataclass


class DiscoveryAuthorizationError(PermissionError):
    """Raised when discovery execution is not currently entitled."""


@dataclass(frozen=True, slots=True)
class DiscoveryAuthorizationSnapshot:
    has_active_subscription: bool
    over_keyword_limit: bool
    active_keywords: list[str]


@dataclass(frozen=True, slots=True)
class SubscriptionLike:
    subscription_status: object
    keyword_limit: int | None


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
        raise DiscoveryAuthorizationError("active keyword configuration exceeds plan limit")
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
    has_active_subscription = any(
        str(getattr(subscription.subscription_status, "value", subscription.subscription_status))
        == "active"
        for subscription in subscriptions
    )
    current_subscription = next(
        (
            subscription
            for subscription in subscriptions
            if str(getattr(subscription.subscription_status, "value", subscription.subscription_status))
            == "active"
        ),
        subscriptions[0] if subscriptions else None,
    )
    keyword_limit = current_subscription.keyword_limit if current_subscription is not None else None
    over_keyword_limit = keyword_limit is not None and len(active_keywords) > int(keyword_limit)
    return DiscoveryAuthorizationSnapshot(
        has_active_subscription=has_active_subscription,
        over_keyword_limit=over_keyword_limit,
        active_keywords=active_keywords,
    )
