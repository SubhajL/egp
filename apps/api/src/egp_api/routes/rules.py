"""Read-only rules routes for profiles and platform logic."""

from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, Request
from pydantic import BaseModel

from egp_api.auth import resolve_request_tenant_id
from egp_api.services.rules_service import RulesService, RulesSnapshot


router = APIRouter(prefix="/v1/rules", tags=["rules"])


class RuleProfileResponse(BaseModel):
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


class ClosureRulesResponse(BaseModel):
    close_on_winner_status: bool
    close_on_contract_status: bool
    winner_status_terms: list[str]
    contract_status_terms: list[str]
    consulting_timeout_days: int
    stale_no_tor_days: int
    stale_eligible_states: list[str]
    source: str


class NotificationRulesResponse(BaseModel):
    supported_channels: list[str]
    supported_types: list[str]
    event_wiring_complete: bool
    source: str


class ScheduleRulesResponse(BaseModel):
    supported_trigger_types: list[str]
    schedule_execution_supported: bool
    editable_in_product: bool
    source: str


class EntitlementSummaryResponse(BaseModel):
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
    source: str


class RulesResponse(BaseModel):
    profiles: list[RuleProfileResponse]
    entitlements: EntitlementSummaryResponse
    closure_rules: ClosureRulesResponse
    notification_rules: NotificationRulesResponse
    schedule_rules: ScheduleRulesResponse


def _service_from_request(request: Request) -> RulesService:
    return request.app.state.rules_service


def _serialize_rules(snapshot: RulesSnapshot) -> RulesResponse:
    return RulesResponse(
        profiles=[RuleProfileResponse(**asdict(profile)) for profile in snapshot.profiles],
        entitlements=EntitlementSummaryResponse(**asdict(snapshot.entitlements)),
        closure_rules=ClosureRulesResponse(**asdict(snapshot.closure_rules)),
        notification_rules=NotificationRulesResponse(**asdict(snapshot.notification_rules)),
        schedule_rules=ScheduleRulesResponse(**asdict(snapshot.schedule_rules)),
    )


@router.get("", response_model=RulesResponse)
def get_rules(request: Request, tenant_id: str | None = None) -> RulesResponse:
    service = _service_from_request(request)
    resolved_tenant_id = resolve_request_tenant_id(request, tenant_id)
    snapshot = service.get_rules(tenant_id=resolved_tenant_id)
    return _serialize_rules(snapshot)
