"""Read-only rules service for profiles and platform settings."""

from __future__ import annotations

from dataclasses import dataclass

from egp_crawler_core.closure_rules import describe_closure_rules
from egp_db.repositories.profile_repo import CrawlProfileDetail, SqlProfileRepository
from egp_shared_types.enums import NotificationType


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
    source: str


@dataclass(frozen=True, slots=True)
class RulesSnapshot:
    profiles: list[RuleProfile]
    closure_rules: ClosureRulesView
    notification_rules: NotificationRulesView
    schedule_rules: ScheduleRulesView


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
    def __init__(self, repository: SqlProfileRepository) -> None:
        self._repository = repository

    def get_rules(self, *, tenant_id: str) -> RulesSnapshot:
        profiles = self._repository.list_profiles_with_keywords(tenant_id=tenant_id)
        closure_metadata = describe_closure_rules()
        return RulesSnapshot(
            profiles=[_map_profile(profile) for profile in profiles],
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
                supported_channels=["in_app", "email"],
                supported_types=[notification_type.value for notification_type in NotificationType],
                event_wiring_complete=False,
                source="packages/notification-core/src/egp_notifications/service.py",
            ),
            schedule_rules=ScheduleRulesView(
                supported_trigger_types=["schedule", "manual", "retry", "backfill"],
                schedule_execution_supported=True,
                editable_in_product=False,
                source="packages/db/src/migrations/001_initial_schema.sql",
            ),
        )
