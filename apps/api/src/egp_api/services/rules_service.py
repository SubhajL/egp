"""Rules service for profiles and platform settings."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from egp_crawler_core.closure_rules import describe_closure_rules
from egp_db.repositories.profile_repo import CrawlProfileDetail, SqlProfileRepository
from egp_shared_types.enums import NotificationType

from egp_api.services.entitlement_service import (
    EntitlementError,
    TenantEntitlementService,
    TenantEntitlementSnapshot,
)

if TYPE_CHECKING:
    from egp_db.repositories.admin_repo import SqlAdminRepository
    from egp_db.repositories.discovery_job_repo import SqlDiscoveryJobRepository


DEFAULT_CRAWL_INTERVAL_HOURS = 24
VALID_PROFILE_TYPES = {"tor", "toe", "lue", "custom"}


@dataclass(frozen=True, slots=True)
class RuleProfile:
    id: str
    name: str
    profile_type: str
    is_active: bool
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
    queued_job_count: int
    queued_keywords: list[str]


def _map_profile(detail: CrawlProfileDetail) -> RuleProfile:
    return RuleProfile(
        id=detail.profile.id,
        name=detail.profile.name,
        profile_type=detail.profile.profile_type,
        is_active=detail.profile.is_active,
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
    ) -> None:
        self._repository = repository
        self._entitlement_service = entitlement_service
        self._notification_event_wiring_complete = notification_event_wiring_complete
        self._admin_repository = admin_repository
        self._discovery_job_repository = discovery_job_repository

    def create_profile(
        self,
        *,
        tenant_id: str,
        name: str,
        profile_type: str,
        is_active: bool,
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
        if not normalized_keywords:
            raise ValueError("at least one keyword is required")

        if is_active and self._entitlement_service is not None:
            snapshot = self._entitlement_service.require_active_subscription(
                tenant_id=tenant_id,
                capability="runs",
            )
            existing_keywords = snapshot.active_keywords
            prospective_keywords = _merge_keywords(existing_keywords, normalized_keywords)
            if snapshot.keyword_limit is not None and len(prospective_keywords) > int(
                snapshot.keyword_limit
            ):
                raise EntitlementError("active keyword configuration exceeds plan limit")

        detail = self._repository.create_profile(
            tenant_id=tenant_id,
            name=normalized_name,
            profile_type=normalized_profile_type,
            is_active=is_active,
            max_pages_per_keyword=max_pages_per_keyword,
            close_consulting_after_days=close_consulting_after_days,
            close_stale_after_days=close_stale_after_days,
            keywords=normalized_keywords,
            enqueue_discovery_jobs=True,
        )
        return _map_profile(detail)

    def update_profile(
        self,
        *,
        tenant_id: str,
        profile_id: str,
        name: str | None = None,
        is_active: bool | None = None,
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

        normalized_keywords = (
            _normalize_keywords(keywords) if keywords is not None else None
        )
        current_keywords = [keyword.keyword for keyword in existing.keywords]
        effective_keywords = (
            normalized_keywords if normalized_keywords is not None else current_keywords
        )
        effective_is_active = existing.profile.is_active if is_active is None else is_active
        if effective_is_active and not effective_keywords:
            raise ValueError("at least one keyword is required")

        if effective_is_active and self._entitlement_service is not None:
            snapshot = self._entitlement_service.require_active_subscription(
                tenant_id=tenant_id,
                capability="runs",
            )
            existing_active_keywords = _remove_keywords(
                snapshot.active_keywords,
                current_keywords if existing.profile.is_active else [],
            )
            prospective_keywords = _merge_keywords(
                existing_active_keywords,
                effective_keywords,
            )
            if snapshot.keyword_limit is not None and len(prospective_keywords) > int(
                snapshot.keyword_limit
            ):
                raise EntitlementError("active keyword configuration exceeds plan limit")

        detail = self._repository.update_profile(
            tenant_id=tenant_id,
            profile_id=profile_id,
            name=normalized_name,
            is_active=effective_is_active,
            keywords=normalized_keywords,
            max_pages_per_keyword=max_pages_per_keyword,
            close_consulting_after_days=close_consulting_after_days,
            close_stale_after_days=close_stale_after_days,
        )
        updated = _map_profile(detail)
        self._queue_profile_update_jobs(
            tenant_id=tenant_id,
            previous_keywords=current_keywords,
            previous_is_active=existing.profile.is_active,
            updated=updated,
            keywords_were_replaced=normalized_keywords is not None,
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
            profiles=[_map_profile(profile) for profile in profiles],
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
        if self._entitlement_service is not None:
            snapshot = self._entitlement_service.require_active_subscription(
                tenant_id=tenant_id,
                capability="runs",
            )
            if snapshot.active_keyword_count == 0:
                raise ValueError("at least one active keyword is required")
        if self._discovery_job_repository is None:
            raise RuntimeError("discovery job repository is not configured")

        active_jobs: list[tuple[str, str, str]] = []
        queued_keywords: list[str] = []
        queued_job_count = 0
        seen_keywords: set[str] = set()
        for detail in self._repository.list_profiles_with_keywords(tenant_id=tenant_id):
            if not detail.profile.is_active:
                continue
            for keyword in detail.keywords:
                normalized_keyword = keyword.keyword.strip()
                if not normalized_keyword:
                    continue
                if self._entitlement_service is not None:
                    self._entitlement_service.require_discover_keyword(
                        tenant_id=tenant_id,
                        keyword=normalized_keyword,
                    )
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
            requested_keyword_count = len(
                {normalized_keyword.casefold() for _, _, normalized_keyword in active_jobs}
            )
            self._entitlement_service.check_runs_admission(
                tenant_id=tenant_id,
                requested_keyword_count=requested_keyword_count,
            )

        for profile_id, profile_type, normalized_keyword in active_jobs:
            enqueue_result = self._discovery_job_repository.create_pending_discovery_job_if_absent(
                tenant_id=tenant_id,
                profile_id=profile_id,
                profile_type=profile_type,
                keyword=normalized_keyword,
                trigger_type="manual",
                live=True,
            )
            if not enqueue_result.created:
                continue
            queued_job_count += 1
            dedupe_key = normalized_keyword.casefold()
            if dedupe_key not in seen_keywords:
                seen_keywords.add(dedupe_key)
                queued_keywords.append(normalized_keyword)

        return ManualRecrawlRequest(
            queued_job_count=queued_job_count,
            queued_keywords=queued_keywords,
        )

    def _queue_profile_update_jobs(
        self,
        *,
        tenant_id: str,
        previous_keywords: list[str],
        previous_is_active: bool,
        updated: RuleProfile,
        keywords_were_replaced: bool,
    ) -> None:
        if self._discovery_job_repository is None or not updated.is_active:
            return
        if previous_is_active and not keywords_were_replaced:
            return
        previous_keyword_keys = {keyword.casefold() for keyword in previous_keywords}
        keywords_to_queue = updated.keywords
        if previous_is_active and keywords_were_replaced:
            keywords_to_queue = [
                keyword
                for keyword in updated.keywords
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


def _active_keywords_from_details(details: list[CrawlProfileDetail]) -> list[str]:
    ordered: list[str] = []
    seen: set[str] = set()
    for detail in details:
        if not detail.profile.is_active:
            continue
        for keyword in detail.keywords:
            normalized = keyword.keyword.strip()
            dedupe_key = normalized.casefold()
            if not normalized or dedupe_key in seen:
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
