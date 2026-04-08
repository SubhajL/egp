"""Tenant entitlement and quota evaluation based on subscriptions and active keywords."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from egp_crawler_core.discovery_authorization import (
    DiscoveryAuthorizationSnapshot,
    normalize_keyword as _normalize_discovery_keyword,
    require_discovery_authorization,
)
from egp_shared_types.billing_plans import get_billing_plan_definition
from egp_shared_types.enums import BillingSubscriptionStatus

if TYPE_CHECKING:
    from egp_db.repositories.billing_repo import BillingSubscriptionRecord, SqlBillingRepository
    from egp_db.repositories.profile_repo import SqlProfileRepository
    from egp_notifications.dispatcher import NotificationDispatcher
    from egp_notifications.service import Notification


ENTITLEMENT_SOURCE = "billing_subscriptions + crawl_profile_keywords"


class EntitlementError(PermissionError):
    """Raised when a tenant attempts an action without entitlement."""


@dataclass(frozen=True, slots=True)
class TenantEntitlementSnapshot:
    plan_code: str | None
    plan_label: str | None
    subscription_status: str | None
    has_active_subscription: bool
    keyword_limit: int | None
    active_keyword_count: int
    remaining_keyword_slots: int | None
    active_keywords: list[str]
    over_keyword_limit: bool
    runs_allowed: bool
    exports_allowed: bool
    document_download_allowed: bool
    notifications_allowed: bool
    source: str = ENTITLEMENT_SOURCE


def _select_current_subscription(
    subscriptions: list[BillingSubscriptionRecord],
) -> BillingSubscriptionRecord | None:
    if not subscriptions:
        return None
    priorities = {
        BillingSubscriptionStatus.ACTIVE: 0,
        BillingSubscriptionStatus.PENDING_ACTIVATION: 1,
        BillingSubscriptionStatus.EXPIRED: 2,
        BillingSubscriptionStatus.CANCELLED: 3,
    }
    return min(
        subscriptions,
        key=lambda subscription: (
            priorities.get(subscription.subscription_status, 99),
            -int(subscription.billing_period_end.replace("-", "")),
            -int(subscription.billing_period_start.replace("-", "")),
            subscription.created_at,
        ),
    )


def _normalize_keyword(value: str) -> str:
    return _normalize_discovery_keyword(value)


class TenantEntitlementService:
    def __init__(
        self,
        billing_repository: SqlBillingRepository,
        profile_repository: SqlProfileRepository,
    ) -> None:
        self._billing_repository = billing_repository
        self._profile_repository = profile_repository

    def get_snapshot(self, *, tenant_id: str) -> TenantEntitlementSnapshot:
        subscriptions = self._billing_repository.list_subscriptions_for_tenant(tenant_id=tenant_id)
        subscription = _select_current_subscription(subscriptions)
        active_keywords = self._profile_repository.list_active_keywords(tenant_id=tenant_id)
        active_keyword_count = len(active_keywords)

        if subscription is None:
            return TenantEntitlementSnapshot(
                plan_code=None,
                plan_label=None,
                subscription_status=None,
                has_active_subscription=False,
                keyword_limit=None,
                active_keyword_count=active_keyword_count,
                remaining_keyword_slots=None,
                active_keywords=active_keywords,
                over_keyword_limit=False,
                runs_allowed=False,
                exports_allowed=False,
                document_download_allowed=False,
                notifications_allowed=False,
            )

        plan_definition = get_billing_plan_definition(subscription.plan_code)
        keyword_limit = subscription.keyword_limit
        has_active_subscription = (
            subscription.subscription_status is BillingSubscriptionStatus.ACTIVE
        )
        over_keyword_limit = keyword_limit is not None and active_keyword_count > int(keyword_limit)
        remaining_keyword_slots = None
        if keyword_limit is not None:
            remaining_keyword_slots = max(int(keyword_limit) - active_keyword_count, 0)
        runs_allowed = has_active_subscription
        exports_allowed = has_active_subscription
        document_download_allowed = has_active_subscription
        notifications_allowed = has_active_subscription
        if has_active_subscription and subscription.plan_code == "free_trial":
            exports_allowed = False
            document_download_allowed = False
            notifications_allowed = False

        return TenantEntitlementSnapshot(
            plan_code=subscription.plan_code,
            plan_label=plan_definition.label if plan_definition is not None else None,
            subscription_status=subscription.subscription_status.value,
            has_active_subscription=has_active_subscription,
            keyword_limit=keyword_limit,
            active_keyword_count=active_keyword_count,
            remaining_keyword_slots=remaining_keyword_slots,
            active_keywords=active_keywords,
            over_keyword_limit=over_keyword_limit,
            runs_allowed=runs_allowed,
            exports_allowed=exports_allowed,
            document_download_allowed=document_download_allowed,
            notifications_allowed=notifications_allowed,
        )

    def require_active_subscription(
        self, *, tenant_id: str, capability: str
    ) -> TenantEntitlementSnapshot:
        snapshot = self.get_snapshot(tenant_id=tenant_id)
        if not snapshot.has_active_subscription:
            raise EntitlementError(f"active subscription required for {capability}")
        return snapshot

    def require_discover_keyword(
        self, *, tenant_id: str, keyword: str
    ) -> TenantEntitlementSnapshot:
        snapshot = self.require_active_subscription(tenant_id=tenant_id, capability="runs")
        try:
            require_discovery_authorization(
                snapshot=DiscoveryAuthorizationSnapshot(
                    has_active_subscription=snapshot.has_active_subscription,
                    over_keyword_limit=snapshot.over_keyword_limit,
                    active_keywords=snapshot.active_keywords,
                ),
                keyword=keyword,
            )
        except PermissionError as exc:
            raise EntitlementError(str(exc)) from exc
        return snapshot

    def notifications_allowed(self, *, tenant_id: str) -> bool:
        return self.get_snapshot(tenant_id=tenant_id).notifications_allowed


class EntitlementAwareNotificationDispatcher:
    def __init__(
        self,
        dispatcher: NotificationDispatcher,
        entitlement_service: TenantEntitlementService,
    ) -> None:
        self._dispatcher = dispatcher
        self._entitlement_service = entitlement_service

    def dispatch(
        self,
        *,
        tenant_id: str,
        notification_type,
        project_id: str | None = None,
        template_vars: dict[str, str] | None = None,
    ) -> Notification | None:
        if not self._entitlement_service.notifications_allowed(tenant_id=tenant_id):
            return None
        return self._dispatcher.dispatch(
            tenant_id=tenant_id,
            notification_type=notification_type,
            project_id=project_id,
            template_vars=template_vars,
        )
