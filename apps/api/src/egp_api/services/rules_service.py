"""Rules service for profiles and platform settings."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING

from egp_crawler_core.closure_rules import describe_closure_rules
from egp_crawler_core.discovery_authorization import RunnableProfileKeyword
from egp_crawler_core.recovery_policy import RecoveryDecision, evaluate_recovery_decision
from egp_db.repositories.crawler_runtime_repo import CrawlerRuntimeSnapshot
from egp_db.repositories.profile_repo import CrawlProfileDetail, SqlProfileRepository
from egp_db.repositories.recrawl_request_repo import RecrawlJobInput, RecrawlRequestStatus
from egp_shared_types.enums import (
    KeywordGroupEffectiveStatus,
    KeywordGroupStatusReason,
    NotificationType,
)

from egp_api.services.entitlement_service import (
    EntitlementError,
    TenantEntitlementService,
    TenantEntitlementSnapshot,
)

if TYPE_CHECKING:
    from egp_db.repositories.admin_repo import SqlAdminRepository
    from egp_db.repositories.crawler_runtime_repo import SqlCrawlerRuntimeRepository
    from egp_db.repositories.discovery_job_repo import SqlDiscoveryJobRepository
    from egp_db.repositories.recrawl_request_repo import SqlRecrawlRequestRepository


DEFAULT_CRAWL_INTERVAL_HOURS = 24
VALID_PROFILE_TYPES = {"tor", "toe", "lue", "custom"}


@dataclass(frozen=True, slots=True)
class RuleProfile:
    id: str
    name: str
    profile_type: str
    enabled_by_user: bool
    is_active: bool
    effective_status: str
    status_reason: str | None
    max_pages_per_keyword: int
    close_consulting_after_days: int
    close_stale_after_days: int
    keywords: list[str]
    created_at: str
    updated_at: str


@dataclass(frozen=True, slots=True)
class ClosureRulesView:
    close_on_winner_status: bool
    close_on_contract_status: bool
    winner_status_terms: list[str]
    contract_status_terms: list[str]
    consulting_timeout_days: int
    stale_no_tor_days: int
    stale_eligible_states: list[str]
    source: str


@dataclass(frozen=True, slots=True)
class NotificationRulesView:
    supported_channels: list[str]
    supported_types: list[str]
    event_wiring_complete: bool
    source: str


@dataclass(frozen=True, slots=True)
class ScheduleRulesView:
    supported_trigger_types: list[str]
    schedule_execution_supported: bool
    editable_in_product: bool
    tenant_crawl_interval_hours: int | None
    default_crawl_interval_hours: int
    effective_crawl_interval_hours: int
    source: str


@dataclass(frozen=True, slots=True)
class RulesSnapshot:
    profiles: list[RuleProfile]
    entitlements: TenantEntitlementSnapshot
    closure_rules: ClosureRulesView
    notification_rules: NotificationRulesView
    schedule_rules: ScheduleRulesView


@dataclass(frozen=True, slots=True)
class ManualRecrawlRequest:
    request_id: str
    queued_job_count: int
    queued_keywords: list[str]


@dataclass(frozen=True, slots=True)
class ManualRecrawlStatus(RecrawlRequestStatus):
    runtime: CrawlerRuntimeSnapshot
    recovery_decision: RecoveryDecision


def _map_profile(
    detail: CrawlProfileDetail,
    entitlements: TenantEntitlementSnapshot | None = None,
) -> RuleProfile:
    effective_status, status_reason = _resolve_profile_presentation_status(
        detail=detail,
        entitlements=entitlements,
    )
    return RuleProfile(
        id=detail.profile.id,
        name=detail.profile.name,
        profile_type=detail.profile.profile_type,
        enabled_by_user=detail.profile.enabled_by_user,
        is_active=detail.profile.is_active,
        effective_status=effective_status,
        status_reason=status_reason,
        max_pages_per_keyword=detail.profile.max_pages_per_keyword,
        close_consulting_after_days=detail.profile.close_consulting_after_days,
        close_stale_after_days=detail.profile.close_stale_after_days,
        keywords=[keyword.keyword for keyword in detail.keywords],
        created_at=detail.profile.created_at,
        updated_at=detail.profile.updated_at,
    )


class RulesService:
    def __init__(
        self,
        repository: SqlProfileRepository,
        *,
        entitlement_service: TenantEntitlementService | None = None,
        notification_event_wiring_complete: bool = True,
        admin_repository: SqlAdminRepository | None = None,
        discovery_job_repository: SqlDiscoveryJobRepository | None = None,
        recrawl_request_repository: SqlRecrawlRequestRepository | None = None,
        crawler_runtime_repository: SqlCrawlerRuntimeRepository | None = None,
        background_runtime_mode: str = "embedded",
        crawler_heartbeat_stale_after_seconds: float = 90.0,
    ) -> None:
        self._repository = repository
        self._entitlement_service = entitlement_service
        self._notification_event_wiring_complete = notification_event_wiring_complete
        self._admin_repository = admin_repository
        self._discovery_job_repository = discovery_job_repository
        self._recrawl_request_repository = recrawl_request_repository
        self._crawler_runtime_repository = crawler_runtime_repository
        self._background_runtime_mode = background_runtime_mode
        self._crawler_heartbeat_stale_after_seconds = (
            crawler_heartbeat_stale_after_seconds
        )

    def create_profile(
        self,
        *,
        tenant_id: str,
        name: str,
        profile_type: str,
        enabled_by_user: bool,
        keywords: list[str],
        max_pages_per_keyword: int = 15,
        close_consulting_after_days: int = 30,
        close_stale_after_days: int = 45,
    ) -> RuleProfile:
        normalized_name = name.strip()
        if not normalized_name:
            raise ValueError("profile name is required")
        normalized_profile_type = profile_type.strip().casefold()
        if normalized_profile_type not in VALID_PROFILE_TYPES:
            raise ValueError("unsupported profile type")
        normalized_keywords = _normalize_keywords(keywords)
        snapshot = (
            self._entitlement_service.get_snapshot(tenant_id=tenant_id)
            if self._entitlement_service is not None
            else None
        )
        if (
            enabled_by_user
            and normalized_keywords
            and snapshot is not None
            and snapshot.has_active_subscription
        ):
            prospective_keywords = _merge_keywords(snapshot.quota_keywords, normalized_keywords)
            if snapshot.keyword_limit is not None and len(prospective_keywords) > int(
                snapshot.keyword_limit
            ):
                raise EntitlementError("active keyword configuration exceeds plan limit")
            existing_keyword_keys = {
                keyword.casefold() for keyword in snapshot.quota_keywords
            }
            requested_keyword_count = sum(
                keyword.casefold() not in existing_keyword_keys
                for keyword in normalized_keywords
            )
            if requested_keyword_count:
                self._entitlement_service.check_runs_admission(
                    tenant_id=tenant_id,
                    requested_keyword_count=requested_keyword_count,
                )

        detail = self._repository.create_profile(
            tenant_id=tenant_id,
            name=normalized_name,
            profile_type=normalized_profile_type,
            enabled_by_user=enabled_by_user,
            max_pages_per_keyword=max_pages_per_keyword,
            close_consulting_after_days=close_consulting_after_days,
            close_stale_after_days=close_stale_after_days,
            keywords=normalized_keywords,
        )
        refreshed_snapshot = (
            self._entitlement_service.get_snapshot(tenant_id=tenant_id)
            if self._entitlement_service is not None
            else snapshot
        )
        created = _map_profile(detail, refreshed_snapshot)
        self._queue_profile_created_jobs(
            tenant_id=tenant_id,
            created=created,
            runnable_profile_keywords=(
                refreshed_snapshot.runnable_profile_keywords
                if refreshed_snapshot is not None
                else []
            ),
        )
        return created

    def update_profile(
        self,
        *,
        tenant_id: str,
        profile_id: str,
        name: str | None = None,
        enabled_by_user: bool | None = None,
        keywords: list[str] | None = None,
        max_pages_per_keyword: int | None = None,
        close_consulting_after_days: int | None = None,
        close_stale_after_days: int | None = None,
    ) -> RuleProfile:
        existing = self._repository.get_profile_detail(
            tenant_id=tenant_id,
            profile_id=profile_id,
        )
        if existing is None:
            raise KeyError(profile_id)

        normalized_name = None
        if name is not None:
            normalized_name = name.strip()
            if not normalized_name:
                raise ValueError("profile name is required")

        normalized_keywords = _normalize_keywords(keywords) if keywords is not None else None
        current_keywords = [keyword.keyword for keyword in existing.keywords]
        effective_keywords = (
            normalized_keywords if normalized_keywords is not None else current_keywords
        )
        effective_enabled = (
            existing.profile.enabled_by_user
            if enabled_by_user is None
            else enabled_by_user
        )
        if enabled_by_user is False and normalized_keywords == [] and current_keywords:
            normalized_keywords = None
            effective_keywords = current_keywords

        changes_enabled_keyword_configuration = normalized_keywords is not None or (
            enabled_by_user is True and not existing.profile.enabled_by_user
        )
        if (
            effective_enabled
            and changes_enabled_keyword_configuration
            and self._entitlement_service is not None
        ):
            snapshot = self._entitlement_service.get_snapshot(tenant_id=tenant_id)
            existing_active_keywords = _remove_keywords(
                snapshot.quota_keywords,
                current_keywords if existing.profile.enabled_by_user else [],
            )
            prospective_keywords = _merge_keywords(
                existing_active_keywords,
                effective_keywords,
            )
            if (
                snapshot.has_active_subscription
                and snapshot.keyword_limit is not None
                and len(prospective_keywords) > int(
                snapshot.keyword_limit
                )
            ):
                raise EntitlementError("active keyword configuration exceeds plan limit")
            admission_existing_keywords = _merge_keywords(
                existing_active_keywords,
                current_keywords if existing.profile.enabled_by_user else [],
            )
            admission_existing_keys = {
                keyword.casefold() for keyword in admission_existing_keywords
            }
            requested_keyword_count = sum(
                keyword.casefold() not in admission_existing_keys
                for keyword in effective_keywords
            )
            if snapshot.has_active_subscription and requested_keyword_count:
                self._entitlement_service.check_runs_admission(
                    tenant_id=tenant_id,
                    requested_keyword_count=requested_keyword_count,
                )

        detail = self._repository.update_profile(
            tenant_id=tenant_id,
            profile_id=profile_id,
            name=normalized_name,
            enabled_by_user=effective_enabled,
            keywords=normalized_keywords,
            max_pages_per_keyword=max_pages_per_keyword,
            close_consulting_after_days=close_consulting_after_days,
            close_stale_after_days=close_stale_after_days,
        )
        refreshed_snapshot = (
            self._entitlement_service.get_snapshot(tenant_id=tenant_id)
            if self._entitlement_service is not None
            else None
        )
        updated = _map_profile(detail, refreshed_snapshot)
        self._queue_profile_update_jobs(
            tenant_id=tenant_id,
            previous_keywords=current_keywords,
            previous_is_active=existing.profile.enabled_by_user,
            updated=updated,
            keywords_were_replaced=normalized_keywords is not None,
            runnable_profile_keywords=(
                refreshed_snapshot.runnable_profile_keywords
                if refreshed_snapshot is not None
                else []
            ),
        )
        return updated

    def get_rules(self, *, tenant_id: str) -> RulesSnapshot:
        entitlements = (
            self._entitlement_service.get_snapshot(tenant_id=tenant_id)
            if self._entitlement_service is not None
            else TenantEntitlementSnapshot(
                plan_code=None,
                plan_label=None,
                subscription_status=None,
                has_active_subscription=False,
                keyword_limit=None,
                saved_keyword_count=0,
                enabled_keyword_count=0,
                runnable_keyword_count=0,
                runnable_keywords=[],
                quota_keywords=[],
                runnable_profile_keywords=[],
                profile_effective_statuses={},
                active_keyword_count=0,
                remaining_keyword_slots=None,
                active_keywords=[],
                over_keyword_limit=False,
                runs_allowed=False,
                exports_allowed=False,
                document_download_allowed=False,
                notifications_allowed=False,
            )
        )
        profiles = self._repository.list_profiles_with_keywords(tenant_id=tenant_id)
        closure_metadata = describe_closure_rules()
        tenant_settings = (
            self._admin_repository.get_tenant_settings(tenant_id=tenant_id)
            if self._admin_repository is not None
            else None
        )
        tenant_crawl_interval_hours = (
            tenant_settings.crawl_interval_hours if tenant_settings is not None else None
        )
        effective_crawl_interval_hours = tenant_crawl_interval_hours or DEFAULT_CRAWL_INTERVAL_HOURS
        return RulesSnapshot(
            profiles=[_map_profile(profile, entitlements) for profile in profiles],
            entitlements=entitlements,
            closure_rules=ClosureRulesView(
                close_on_winner_status=bool(closure_metadata["close_on_winner_status"]),
                close_on_contract_status=bool(closure_metadata["close_on_contract_status"]),
                winner_status_terms=list(closure_metadata["winner_status_terms"]),
                contract_status_terms=list(closure_metadata["contract_status_terms"]),
                consulting_timeout_days=int(closure_metadata["consulting_timeout_days"]),
                stale_no_tor_days=int(closure_metadata["stale_no_tor_days"]),
                stale_eligible_states=list(closure_metadata["stale_eligible_states"]),
                source=str(closure_metadata["source"]),
            ),
            notification_rules=NotificationRulesView(
                supported_channels=["in_app", "email", "webhook"],
                supported_types=[notification_type.value for notification_type in NotificationType],
                event_wiring_complete=self._notification_event_wiring_complete,
                source="packages/notification-core/src/egp_notifications/service.py",
            ),
            schedule_rules=ScheduleRulesView(
                supported_trigger_types=["schedule", "manual", "retry", "backfill"],
                schedule_execution_supported=True,
                editable_in_product=True,
                tenant_crawl_interval_hours=tenant_crawl_interval_hours,
                default_crawl_interval_hours=DEFAULT_CRAWL_INTERVAL_HOURS,
                effective_crawl_interval_hours=effective_crawl_interval_hours,
                source="tenant_settings + default schedule policy",
            ),
        )

    def queue_active_discovery_jobs(self, *, tenant_id: str) -> ManualRecrawlRequest:
        snapshot = None
        if self._entitlement_service is not None:
            snapshot = self._entitlement_service.require_active_subscription(
                tenant_id=tenant_id,
                capability="runs",
            )
            if snapshot.active_keyword_count == 0:
                raise ValueError("at least one active keyword is required")
        if self._discovery_job_repository is None:
            raise RuntimeError("discovery job repository is not configured")
        if self._recrawl_request_repository is None:
            raise RuntimeError("recrawl request repository is not configured")

        active_jobs: list[tuple[str, str, str]] = []
        if snapshot is not None:
            active_jobs = [
                (item.profile_id, item.profile_type, item.keyword)
                for item in snapshot.runnable_profile_keywords
            ]
        else:
            for detail in self._repository.list_enabled_profiles_with_keywords(
                tenant_id=tenant_id
            ):
                for keyword in detail.keywords:
                    normalized_keyword = keyword.keyword.strip()
                    if normalized_keyword:
                        active_jobs.append(
                            (
                                detail.profile.id,
                                detail.profile.profile_type,
                                normalized_keyword,
                            )
                        )

        if not active_jobs:
            raise ValueError("at least one active keyword is required")

        if self._entitlement_service is not None:
            selected_active_jobs: list[tuple[str, str, str]] = []
            selected_keyword_keys: set[str] = set()
            for active_job in active_jobs:
                keyword_key = active_job[2].casefold()
                if keyword_key in selected_keyword_keys:
                    continue
                selected_keyword_keys.add(keyword_key)
                selected_active_jobs.append(active_job)
            active_jobs = selected_active_jobs
            stored_jobs = self._discovery_job_repository.list_discovery_jobs(
                tenant_id=tenant_id
            )
            pending_job_keys = {
                (job.profile_id, job.keyword.casefold())
                for job in stored_jobs
                if job.job_status == "pending" and job.live
            }
            desired_job_keys = {
                (profile_id, normalized_keyword.casefold())
                for profile_id, _, normalized_keyword in active_jobs
            }
            active_request_ids = {
                job.recrawl_request_id
                for job in stored_jobs
                if job.recrawl_request_id is not None
                and job.job_status == "pending"
                and (job.profile_id, job.keyword.casefold()) in desired_job_keys
            }
            if len(active_request_ids) == 1:
                active_request_id = next(iter(active_request_ids))
                pending_job_keys.update(
                    (job.profile_id, job.keyword.casefold())
                    for job in stored_jobs
                    if job.recrawl_request_id == active_request_id
                )
            requested_keyword_count = sum(
                (profile_id, normalized_keyword.casefold()) not in pending_job_keys
                for profile_id, _, normalized_keyword in active_jobs
            )
            self._entitlement_service.check_runs_admission(
                tenant_id=tenant_id,
                requested_keyword_count=requested_keyword_count,
            )

        created = self._recrawl_request_repository.create_request(
            tenant_id=tenant_id,
            jobs=[
                RecrawlJobInput(
                    profile_id=profile_id,
                    profile_type=profile_type,
                    keyword=normalized_keyword,
                )
                for profile_id, profile_type, normalized_keyword in active_jobs
            ],
        )

        return ManualRecrawlRequest(
            request_id=created.request_id,
            queued_job_count=created.queued_job_count,
            queued_keywords=created.queued_keywords,
        )

    def get_recrawl_request_status(
        self,
        *,
        tenant_id: str,
        request_id: str,
    ) -> ManualRecrawlStatus:
        if self._recrawl_request_repository is None:
            raise RuntimeError("recrawl request repository is not configured")
        request_status = self._recrawl_request_repository.get_status(
            tenant_id=tenant_id,
            request_id=request_id,
        )
        runtime = self.get_crawler_runtime_status()
        decision = evaluate_recovery_decision(
            is_terminal=request_status.is_terminal,
            correlation_matches=request_status.correlation_matches,
            runtime_blocker=runtime.blocker_code,
            job_failure_codes=tuple(
                job.last_error_code
                for job in request_status.jobs
                if job.last_error_code is not None
            ),
        )
        return ManualRecrawlStatus(
            **asdict(request_status),
            runtime=runtime,
            recovery_decision=decision,
        )

    def get_crawler_runtime_status(self) -> CrawlerRuntimeSnapshot:
        if self._crawler_runtime_repository is None:
            raise RuntimeError("crawler runtime repository is not configured")
        return self._crawler_runtime_repository.get_freshest_status(
            runtime_mode=self._background_runtime_mode,
            stale_after_seconds=self._crawler_heartbeat_stale_after_seconds,
        )

    def _queue_profile_created_jobs(
        self,
        *,
        tenant_id: str,
        created: RuleProfile,
        runnable_profile_keywords: list[RunnableProfileKeyword],
    ) -> None:
        if (
            self._discovery_job_repository is None
            or created.effective_status != KeywordGroupEffectiveStatus.RUNNING
        ):
            return
        for item in runnable_profile_keywords:
            if item.profile_id != created.id:
                continue
            self._discovery_job_repository.create_pending_discovery_job_if_absent(
                tenant_id=tenant_id,
                profile_id=created.id,
                profile_type=created.profile_type,
                keyword=item.keyword,
                trigger_type="profile_created",
                live=True,
            )

    def _queue_profile_update_jobs(
        self,
        *,
        tenant_id: str,
        previous_keywords: list[str],
        previous_is_active: bool,
        updated: RuleProfile,
        keywords_were_replaced: bool,
        runnable_profile_keywords: list[RunnableProfileKeyword],
    ) -> None:
        if (
            self._discovery_job_repository is None
            or updated.effective_status != KeywordGroupEffectiveStatus.RUNNING
        ):
            return
        if previous_is_active and not keywords_were_replaced:
            return
        previous_keyword_keys = {keyword.casefold() for keyword in previous_keywords}
        keywords_to_queue = [
            item.keyword
            for item in runnable_profile_keywords
            if item.profile_id == updated.id
        ]
        if previous_is_active and keywords_were_replaced:
            keywords_to_queue = [
                keyword
                for keyword in keywords_to_queue
                if keyword.casefold() not in previous_keyword_keys
            ]
        if not keywords_to_queue:
            return
        for keyword in keywords_to_queue:
            self._discovery_job_repository.create_pending_discovery_job_if_absent(
                tenant_id=tenant_id,
                profile_id=updated.id,
                profile_type=updated.profile_type,
                keyword=keyword,
                trigger_type="profile_updated",
                live=True,
            )


def _normalize_keywords(values: list[str]) -> list[str]:
    ordered: list[str] = []
    seen: set[str] = set()
    for value in values:
        normalized = str(value).strip()
        if not normalized:
            continue
        dedupe_key = normalized.casefold()
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        ordered.append(normalized)
    return ordered


def _merge_keywords(existing: list[str], new_values: list[str]) -> list[str]:
    ordered = list(existing)
    seen = {value.casefold() for value in existing}
    for value in new_values:
        dedupe_key = value.casefold()
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        ordered.append(value)
    return ordered


def _remove_keywords(values: list[str], values_to_remove: list[str]) -> list[str]:
    removed = {value.casefold() for value in values_to_remove}
    return [value for value in values if value.casefold() not in removed]


def _resolve_profile_presentation_status(
    *,
    detail: CrawlProfileDetail,
    entitlements: TenantEntitlementSnapshot | None,
) -> tuple[str, str | None]:
    if entitlements is not None:
        resolved = entitlements.profile_effective_statuses.get(detail.profile.id)
        if resolved is not None:
            return (
                resolved.status.value,
                resolved.reason.value if resolved.reason is not None else None,
            )
    if not detail.profile.enabled_by_user:
        return KeywordGroupEffectiveStatus.PAUSED_BY_USER, None
    if entitlements is None or not entitlements.has_active_subscription:
        return (
            KeywordGroupEffectiveStatus.PAUSED_BY_PLAN,
            KeywordGroupStatusReason.SUBSCRIPTION_INACTIVE,
        )
    if entitlements.over_keyword_limit:
        return (
            KeywordGroupEffectiveStatus.BLOCKED_QUOTA,
            KeywordGroupStatusReason.KEYWORD_LIMIT_EXCEEDED,
        )
    entitled_keyword_keys = {
        keyword.casefold() for keyword in entitlements.active_keywords
    }
    if any(
        keyword.keyword.strip().casefold() in entitled_keyword_keys
        for keyword in detail.keywords
        if keyword.keyword.strip()
    ):
        return KeywordGroupEffectiveStatus.RUNNING, None
    return (
        KeywordGroupEffectiveStatus.PAUSED_BY_PLAN,
        KeywordGroupStatusReason.OUTSIDE_CURRENT_PLAN_CYCLE,
    )
