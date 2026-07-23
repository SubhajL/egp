"""Shared discovery entitlement checks for API and worker flows."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta

from egp_shared_types.enums import (
    KeywordGroupEffectiveStatus,
    KeywordGroupStatusReason,
)

_EXPIRED_PLAN_CODES_THAT_FALL_BACK_TO_TRIAL = {
    "one_time_search_pack",
    "monthly_membership",
}


class DiscoveryAuthorizationError(PermissionError):
    """Raised when discovery execution is not currently entitled."""


@dataclass(frozen=True, slots=True)
class DiscoveryAuthorizationSnapshot:
    has_active_subscription: bool
    over_keyword_limit: bool
    active_keywords: list[str]
    runnable_profile_keywords: frozenset[tuple[str, str]] = frozenset()


@dataclass(frozen=True, slots=True)
class ProfileKeywordCandidate:
    profile_id: str
    profile_type: str
    enabled_by_user: bool
    created_at: str
    keywords: list[str]


@dataclass(frozen=True, slots=True)
class RunnableProfileKeyword:
    profile_id: str
    profile_type: str
    keyword: str


@dataclass(frozen=True, slots=True)
class ProfileEffectiveStatus:
    status: KeywordGroupEffectiveStatus
    reason: KeywordGroupStatusReason | None


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
    profile_id: str | None = None,
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
    if profile_id is not None and (
        str(profile_id), normalized_keyword.casefold()
    ) not in snapshot.runnable_profile_keywords:
        raise DiscoveryAuthorizationError(
            "discover profile keyword is not entitled for tenant"
        )
    return snapshot


def build_discovery_authorization_snapshot(
    *,
    subscriptions: list[SubscriptionLike],
    active_keywords: list[str] | None = None,
    profiles: list[ProfileKeywordCandidate] | None = None,
) -> DiscoveryAuthorizationSnapshot:
    entitlement = resolve_effective_discovery_entitlement(subscriptions=subscriptions)
    if profiles is not None:
        enabled_keywords = build_enabled_profile_keywords(
            profiles=profiles,
            entitlement=entitlement,
            effective_cycle_only=True,
        )
        keyword_limit = entitlement.keyword_limit
        over_keyword_limit = keyword_limit is not None and len(enabled_keywords) > int(
            keyword_limit
        )
        runnable = build_runnable_profile_keywords(
            profiles=profiles,
            entitlement=entitlement,
        )
        runnable_pairs = frozenset(
            (profile.profile_id, normalize_keyword(keyword).casefold())
            for profile in profiles
            if profile.enabled_by_user
            and profile_is_in_effective_cycle(
                profile_created_at=profile.created_at,
                entitlement=entitlement,
            )
            for keyword in profile.keywords
            if normalize_keyword(keyword)
        )
        if over_keyword_limit or not entitlement.has_active_subscription:
            runnable_pairs = frozenset()
        return DiscoveryAuthorizationSnapshot(
            has_active_subscription=entitlement.has_active_subscription,
            over_keyword_limit=over_keyword_limit,
            active_keywords=[item.keyword for item in runnable],
            runnable_profile_keywords=runnable_pairs,
        )

    resolved_active_keywords = list(active_keywords or [])
    keyword_limit = entitlement.keyword_limit
    over_keyword_limit = keyword_limit is not None and len(resolved_active_keywords) > int(
        keyword_limit
    )
    return DiscoveryAuthorizationSnapshot(
        has_active_subscription=entitlement.has_active_subscription,
        over_keyword_limit=over_keyword_limit,
        active_keywords=resolved_active_keywords,
    )


def profile_is_in_effective_cycle(
    *,
    profile_created_at: str | datetime,
    entitlement: EffectiveDiscoveryEntitlement,
) -> bool:
    cycle_started_at = entitlement.profile_cycle_started_at
    if cycle_started_at is None:
        return True
    created_at = (
        profile_created_at
        if isinstance(profile_created_at, datetime)
        else _parse_datetime(str(profile_created_at))
    )
    return created_at >= cycle_started_at


def build_enabled_profile_keywords(
    *,
    profiles: list[ProfileKeywordCandidate],
    entitlement: EffectiveDiscoveryEntitlement,
    effective_cycle_only: bool,
) -> list[str]:
    ordered: list[str] = []
    seen: set[str] = set()
    for profile in sorted(profiles, key=_profile_sort_key):
        if not profile.enabled_by_user:
            continue
        if effective_cycle_only and not profile_is_in_effective_cycle(
            profile_created_at=profile.created_at,
            entitlement=entitlement,
        ):
            continue
        for keyword in profile.keywords:
            normalized = normalize_keyword(keyword)
            dedupe_key = normalized.casefold()
            if not normalized or dedupe_key in seen:
                continue
            seen.add(dedupe_key)
            ordered.append(normalized)
    return ordered


def build_runnable_profile_keywords(
    *,
    profiles: list[ProfileKeywordCandidate],
    entitlement: EffectiveDiscoveryEntitlement,
) -> list[RunnableProfileKeyword]:
    if not entitlement.has_active_subscription:
        return []
    enabled_keywords = build_enabled_profile_keywords(
        profiles=profiles,
        entitlement=entitlement,
        effective_cycle_only=True,
    )
    if (
        entitlement.keyword_limit is not None
        and len(enabled_keywords) > int(entitlement.keyword_limit)
    ):
        return []
    runnable: list[RunnableProfileKeyword] = []
    seen: set[str] = set()
    for profile in sorted(profiles, key=_profile_sort_key):
        if not profile.enabled_by_user or not profile_is_in_effective_cycle(
            profile_created_at=profile.created_at,
            entitlement=entitlement,
        ):
            continue
        for keyword in profile.keywords:
            normalized = normalize_keyword(keyword)
            dedupe_key = normalized.casefold()
            if not normalized or dedupe_key in seen:
                continue
            seen.add(dedupe_key)
            runnable.append(
                RunnableProfileKeyword(
                    profile_id=profile.profile_id,
                    profile_type=profile.profile_type,
                    keyword=normalized,
                )
            )
    return runnable


def resolve_profile_effective_status(
    *,
    profile: ProfileKeywordCandidate,
    entitlement: EffectiveDiscoveryEntitlement,
    over_keyword_limit: bool,
) -> ProfileEffectiveStatus:
    if not profile.enabled_by_user:
        return ProfileEffectiveStatus(
            status=KeywordGroupEffectiveStatus.PAUSED_BY_USER,
            reason=None,
        )
    if not entitlement.has_active_subscription:
        return ProfileEffectiveStatus(
            status=KeywordGroupEffectiveStatus.PAUSED_BY_PLAN,
            reason=KeywordGroupStatusReason.SUBSCRIPTION_INACTIVE,
        )
    if not profile_is_in_effective_cycle(
        profile_created_at=profile.created_at,
        entitlement=entitlement,
    ):
        return ProfileEffectiveStatus(
            status=KeywordGroupEffectiveStatus.PAUSED_BY_PLAN,
            reason=KeywordGroupStatusReason.OUTSIDE_CURRENT_PLAN_CYCLE,
        )
    if over_keyword_limit:
        return ProfileEffectiveStatus(
            status=KeywordGroupEffectiveStatus.BLOCKED_QUOTA,
            reason=KeywordGroupStatusReason.KEYWORD_LIMIT_EXCEEDED,
        )
    if not any(normalize_keyword(keyword) for keyword in profile.keywords):
        return ProfileEffectiveStatus(
            status=KeywordGroupEffectiveStatus.PAUSED_BY_PLAN,
            reason=None,
        )
    return ProfileEffectiveStatus(
        status=KeywordGroupEffectiveStatus.RUNNING,
        reason=None,
    )


def _profile_sort_key(profile: ProfileKeywordCandidate) -> tuple[datetime, str]:
    return (_parse_datetime(profile.created_at), profile.profile_id)


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
            keyword_limit=_effective_keyword_limit(current_subscription),
            profile_cycle_started_at=_profile_cycle_start_for_active_subscription(
                current_subscription=current_subscription,
                subscriptions=subscriptions,
            ),
        )

    if (
        current_status == "expired"
        and current_plan_code in _EXPIRED_PLAN_CODES_THAT_FALL_BACK_TO_TRIAL
    ):
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
        keyword_limit=_effective_keyword_limit(current_subscription),
        profile_cycle_started_at=None,
    )


def _effective_keyword_limit(subscription: SubscriptionLike) -> int | None:
    plan_code = str(getattr(subscription, "plan_code", "") or "")
    if plan_code == "monthly_membership":
        return None
    return getattr(subscription, "keyword_limit", None)


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
