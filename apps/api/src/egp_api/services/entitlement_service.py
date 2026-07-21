"""Tenant entitlement and quota evaluation based on subscriptions and active keywords."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from egp_crawler_core.discovery_authorization import (
    DiscoveryAuthorizationSnapshot,
    ProfileKeywordCandidate,
    ProfileEffectiveStatus,
    RunnableProfileKeyword,
    build_discovery_authorization_snapshot,
    build_enabled_profile_keywords,
    build_runnable_profile_keywords,
    normalize_keyword as _normalize_discovery_keyword,
    require_discovery_authorization,
    resolve_profile_effective_status,
    resolve_effective_discovery_entitlement,
)
from egp_db.repositories.tenant_entitlement_repo import (
    DEFAULT_MAX_CONCURRENT_RUNS,
    DEFAULT_MAX_QUEUED_KEYWORDS,
    TenantRunAdmissionCaps,
)
from egp_shared_types.billing_plans import get_billing_plan_definition

if TYPE_CHECKING:
    from egp_db.repositories.billing_repo import SqlBillingRepository
    from egp_db.repositories.discovery_job_repo import SqlDiscoveryJobRepository
    from egp_db.repositories.profile_repo import SqlProfileRepository
    from egp_db.repositories.run_repo import SqlRunRepository
    from egp_db.repositories.tenant_entitlement_repo import SqlTenantEntitlementRepository
    from egp_notifications.dispatcher import NotificationDispatcher
    from egp_notifications.service import Notification


ENTITLEMENT_SOURCE = "billing_subscriptions + crawl_profiles + crawl_profile_keywords"
_PAID_ARCHIVE_PLAN_CODES = {"one_time_search_pack", "monthly_membership"}
CapabilityKey = Literal["exports", "document_downloads", "notifications"]


class EntitlementError(PermissionError):
    """Raised when a tenant attempts an action without entitlement."""


class RunAdmissionError(PermissionError):
    """Raised when tenant run admission caps deny a new run request."""

    def __init__(self, snapshot: "RunAdmissionSnapshot") -> None:
        super().__init__(snapshot.detail)
        self.snapshot = snapshot


@dataclass(frozen=True, slots=True)
class TenantEntitlementSnapshot:
    plan_code: str | None
    plan_label: str | None
    subscription_status: str | None
    has_active_subscription: bool
    keyword_limit: int | None
    saved_keyword_count: int
    enabled_keyword_count: int
    runnable_keyword_count: int
    runnable_keywords: list[str]
    quota_keywords: list[str]
    runnable_profile_keywords: list[RunnableProfileKeyword]
    profile_effective_statuses: dict[str, ProfileEffectiveStatus]
    active_keyword_count: int
    remaining_keyword_slots: int | None
    active_keywords: list[str]
    over_keyword_limit: bool
    runs_allowed: bool
    exports_allowed: bool
    document_download_allowed: bool
    notifications_allowed: bool
    source: str = ENTITLEMENT_SOURCE


@dataclass(frozen=True, slots=True)
class RunAdmissionSnapshot:
    allowed: bool
    detail: str
    code: str
    status: str
    inflight_run_count: int
    max_concurrent_runs: int
    queued_keyword_count: int
    max_queued_keywords: int


@dataclass(frozen=True, slots=True)
class _CapabilitySpec:
    snapshot_field: str
    label: str


_CAPABILITY_SPECS: dict[str, _CapabilitySpec] = {
    "exports": _CapabilitySpec(snapshot_field="exports_allowed", label="exports"),
    "document_downloads": _CapabilitySpec(
        snapshot_field="document_download_allowed",
        label="document downloads",
    ),
    "notifications": _CapabilitySpec(
        snapshot_field="notifications_allowed",
        label="notifications",
    ),
}


def _normalize_keyword(value: str) -> str:
    return _normalize_discovery_keyword(value)


class TenantEntitlementService:
    def __init__(
        self,
        billing_repository: SqlBillingRepository,
        profile_repository: SqlProfileRepository,
        *,
        run_repository: SqlRunRepository | None = None,
        discovery_job_repository: SqlDiscoveryJobRepository | None = None,
        tenant_entitlement_repository: SqlTenantEntitlementRepository | None = None,
    ) -> None:
        self._billing_repository = billing_repository
        self._profile_repository = profile_repository
        self._run_repository = run_repository
        self._discovery_job_repository = discovery_job_repository
        self._tenant_entitlement_repository = tenant_entitlement_repository

    def get_snapshot(self, *, tenant_id: str) -> TenantEntitlementSnapshot:
        subscriptions = self._billing_repository.list_subscriptions_for_tenant(tenant_id=tenant_id)
        entitlement = resolve_effective_discovery_entitlement(subscriptions=subscriptions)
        profile_details = self._profile_repository.list_profiles_with_keywords(
            tenant_id=tenant_id
        )
        profiles = _profile_candidates(profile_details)
        saved_keywords = _unique_keywords(
            keyword.keyword
            for detail in profile_details
            for keyword in detail.keywords
        )
        enabled_keywords = build_enabled_profile_keywords(
            profiles=profiles,
            entitlement=entitlement,
            effective_cycle_only=False,
        )
        quota_keywords = build_enabled_profile_keywords(
            profiles=profiles,
            entitlement=entitlement,
            effective_cycle_only=True,
        )
        authorization = build_discovery_authorization_snapshot(
            subscriptions=subscriptions,
            profiles=profiles,
        )
        runnable_keywords = authorization.active_keywords
        runnable_profile_keywords = build_runnable_profile_keywords(
            profiles=profiles,
            entitlement=entitlement,
        )
        profile_effective_statuses = {
            profile.profile_id: resolve_profile_effective_status(
                profile=profile,
                entitlement=entitlement,
                over_keyword_limit=authorization.over_keyword_limit,
            )
            for profile in profiles
        }
        runnable_keyword_count = len(runnable_keywords)
        has_paid_archive_access = any(
            subscription.plan_code in _PAID_ARCHIVE_PLAN_CODES
            for subscription in subscriptions
        )

        if entitlement.plan_code is None:
            return TenantEntitlementSnapshot(
                plan_code=None,
                plan_label=None,
                subscription_status=None,
                has_active_subscription=False,
                keyword_limit=None,
                saved_keyword_count=len(saved_keywords),
                enabled_keyword_count=len(enabled_keywords),
                runnable_keyword_count=0,
                runnable_keywords=[],
                quota_keywords=[],
                runnable_profile_keywords=[],
                profile_effective_statuses=profile_effective_statuses,
                active_keyword_count=0,
                remaining_keyword_slots=None,
                active_keywords=[],
                over_keyword_limit=False,
                runs_allowed=False,
                exports_allowed=False,
                document_download_allowed=False,
                notifications_allowed=False,
            )

        plan_definition = get_billing_plan_definition(entitlement.plan_code)
        keyword_limit = entitlement.keyword_limit
        has_active_subscription = entitlement.has_active_subscription
        over_keyword_limit = authorization.over_keyword_limit
        remaining_keyword_slots = None
        if keyword_limit is not None:
            remaining_keyword_slots = max(int(keyword_limit) - len(quota_keywords), 0)
        runs_allowed = has_active_subscription
        exports_allowed = has_active_subscription
        document_download_allowed = has_active_subscription
        notifications_allowed = has_active_subscription
        if has_active_subscription and entitlement.plan_code == "free_trial":
            exports_allowed = has_paid_archive_access
            document_download_allowed = has_paid_archive_access
            notifications_allowed = False
        if not has_active_subscription and has_paid_archive_access:
            exports_allowed = True
            document_download_allowed = True

        return TenantEntitlementSnapshot(
            plan_code=entitlement.plan_code,
            plan_label=plan_definition.label if plan_definition is not None else None,
            subscription_status=entitlement.subscription_status,
            has_active_subscription=has_active_subscription,
            keyword_limit=keyword_limit,
            saved_keyword_count=len(saved_keywords),
            enabled_keyword_count=len(enabled_keywords),
            runnable_keyword_count=runnable_keyword_count,
            runnable_keywords=runnable_keywords,
            quota_keywords=quota_keywords,
            runnable_profile_keywords=runnable_profile_keywords,
            profile_effective_statuses=profile_effective_statuses,
            active_keyword_count=runnable_keyword_count,
            remaining_keyword_slots=remaining_keyword_slots,
            active_keywords=runnable_keywords,
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

    def require_capability(
        self, *, tenant_id: str, capability: CapabilityKey
    ) -> TenantEntitlementSnapshot:
        spec = _CAPABILITY_SPECS.get(capability)
        if spec is None:
            raise ValueError(f"unknown entitlement capability: {capability}")
        snapshot = self.get_snapshot(tenant_id=tenant_id)
        if not bool(getattr(snapshot, spec.snapshot_field)):
            if not snapshot.has_active_subscription:
                raise EntitlementError(f"active subscription required for {spec.label}")
            raise EntitlementError(
                f"{spec.label} capability is not included in current plan"
            )
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

    def check_runs_admission(
        self,
        *,
        tenant_id: str,
        requested_keyword_count: int,
    ) -> RunAdmissionSnapshot:
        caps = self._get_run_admission_caps(tenant_id=tenant_id)
        inflight_run_count = (
            self._run_repository.count_active_runs(tenant_id=tenant_id)
            if self._run_repository is not None
            else caps.max_concurrent_runs
        )
        queued_discovery_jobs = (
            self._discovery_job_repository.count_pending_discovery_jobs(tenant_id=tenant_id)
            if self._discovery_job_repository is not None
            else 0
        )
        queued_keyword_count = queued_discovery_jobs + max(0, int(requested_keyword_count))
        if inflight_run_count >= caps.max_concurrent_runs:
            snapshot = RunAdmissionSnapshot(
                allowed=False,
                detail="queued — previous run still in progress",
                code="run_admission_queued",
                status="queued",
                inflight_run_count=inflight_run_count,
                max_concurrent_runs=caps.max_concurrent_runs,
                queued_keyword_count=queued_keyword_count,
                max_queued_keywords=caps.max_queued_keywords,
            )
            raise RunAdmissionError(snapshot)
        if queued_keyword_count > caps.max_queued_keywords:
            snapshot = RunAdmissionSnapshot(
                allowed=False,
                detail="queued keyword limit exceeded",
                code="queued_keyword_limit_exceeded",
                status="queued",
                inflight_run_count=inflight_run_count,
                max_concurrent_runs=caps.max_concurrent_runs,
                queued_keyword_count=queued_keyword_count,
                max_queued_keywords=caps.max_queued_keywords,
            )
            raise RunAdmissionError(snapshot)
        return RunAdmissionSnapshot(
            allowed=True,
            detail="admitted",
            code="run_admission_allowed",
            status="admitted",
            inflight_run_count=inflight_run_count,
            max_concurrent_runs=caps.max_concurrent_runs,
            queued_keyword_count=queued_keyword_count,
            max_queued_keywords=caps.max_queued_keywords,
        )

    def notifications_allowed(self, *, tenant_id: str) -> bool:
        try:
            self.require_capability(tenant_id=tenant_id, capability="notifications")
        except EntitlementError:
            return False
        return True

    def _get_run_admission_caps(self, *, tenant_id: str) -> TenantRunAdmissionCaps:
        if self._tenant_entitlement_repository is None:
            return TenantRunAdmissionCaps(
                max_concurrent_runs=DEFAULT_MAX_CONCURRENT_RUNS,
                max_queued_keywords=DEFAULT_MAX_QUEUED_KEYWORDS,
            )
        return self._tenant_entitlement_repository.get_run_admission_caps(
            tenant_id=tenant_id
        )


def _profile_candidates(details) -> list[ProfileKeywordCandidate]:
    return [
        ProfileKeywordCandidate(
            profile_id=detail.profile.id,
            profile_type=detail.profile.profile_type,
            enabled_by_user=detail.profile.enabled_by_user,
            created_at=detail.profile.created_at,
            keywords=[keyword.keyword for keyword in detail.keywords],
        )
        for detail in details
    ]


def _unique_keywords(values) -> list[str]:
    ordered: list[str] = []
    seen: set[str] = set()
    for value in values:
        normalized = _normalize_keyword(value)
        dedupe_key = normalized.casefold()
        if not normalized or dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        ordered.append(normalized)
    return ordered


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
        try:
            self._entitlement_service.require_capability(
                tenant_id=tenant_id,
                capability="notifications",
            )
        except EntitlementError:
            return None
        return self._dispatcher.dispatch(
            tenant_id=tenant_id,
            notification_type=notification_type,
            project_id=project_id,
            template_vars=template_vars,
        )
