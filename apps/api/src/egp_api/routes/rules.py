"""Rules routes for profiles and platform logic."""

from __future__ import annotations

import logging
from dataclasses import asdict

from fastapi import APIRouter, HTTPException, Request, Response, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from egp_api.auth import require_admin_role, resolve_request_tenant_id
from egp_api.services.entitlement_service import EntitlementError, RunAdmissionError
from egp_api.services.rules_service import RulesService, RulesSnapshot

logger = logging.getLogger(__name__)


router = APIRouter(prefix="/v1/rules", tags=["rules"])


RULES_ERROR_CODES = {
    "profile name is required": "profile_name_required",
    "unsupported profile type": "unsupported_profile_type",
    "at least one keyword is required": "keywords_required",
    "at least one active keyword is required": "active_keywords_required",
    "active keyword configuration exceeds plan limit": "active_keyword_limit_exceeded",
}


def _json_error(*, status_code: int, detail: str, code: str | None = None) -> JSONResponse:
    content: dict[str, str] = {"detail": detail}
    if code:
        content["code"] = code
    return JSONResponse(status_code=status_code, content=content)


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
    tenant_crawl_interval_hours: int | None
    default_crawl_interval_hours: int
    effective_crawl_interval_hours: int
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


class CreateRuleProfileRequest(BaseModel):
    tenant_id: str | None = None
    name: str = Field(min_length=1)
    profile_type: str = Field(default="custom", min_length=1)
    is_active: bool = True
    keywords: list[str] = Field(min_length=1)
    max_pages_per_keyword: int = Field(default=15, ge=1, le=100)
    close_consulting_after_days: int = Field(default=30, ge=1, le=365)
    close_stale_after_days: int = Field(default=45, ge=1, le=365)


class UpdateRuleProfileRequest(BaseModel):
    tenant_id: str | None = None
    name: str | None = None
    is_active: bool | None = None
    keywords: list[str] | None = None
    max_pages_per_keyword: int | None = Field(default=None, ge=1, le=100)
    close_consulting_after_days: int | None = Field(default=None, ge=1, le=365)
    close_stale_after_days: int | None = Field(default=None, ge=1, le=365)


class ManualRecrawlRequest(BaseModel):
    tenant_id: str | None = None


class ManualRecrawlResponse(BaseModel):
    queued_job_count: int
    queued_keywords: list[str]


class ManualRecrawlQueuedResponse(BaseModel):
    detail: str
    code: str
    status: str
    inflight_run_count: int
    max_concurrent_runs: int
    queued_keyword_count: int
    max_queued_keywords: int


def _service_from_request(request: Request) -> RulesService:
    return request.app.state.rules_service


def _wake_discovery_dispatch(
    request: Request,
    *,
    pending_job_count: int,
) -> None:
    if pending_job_count <= 0:
        return
    route_kick_enabled = bool(
        getattr(request.app.state, "discovery_dispatch_route_kick_enabled", False)
    )
    if not route_kick_enabled:
        return
    wake_signal = getattr(request.app.state, "discovery_dispatch_wake_signal", None)
    if wake_signal is None:
        logger.debug("Discovery dispatch route kick requested with no wake signal")
        return
    try:
        wake_signal.wake()
    except Exception:
        logger.warning("Failed to wake discovery dispatch loop", exc_info=True)
        return
    logger.info("Woke discovery dispatcher for %d queued job(s)", pending_job_count)


def _serialize_rules(snapshot: RulesSnapshot) -> RulesResponse:
    return RulesResponse(
        profiles=[RuleProfileResponse(**asdict(profile)) for profile in snapshot.profiles],
        entitlements=EntitlementSummaryResponse(**asdict(snapshot.entitlements)),
        closure_rules=ClosureRulesResponse(**asdict(snapshot.closure_rules)),
        notification_rules=NotificationRulesResponse(**asdict(snapshot.notification_rules)),
        schedule_rules=ScheduleRulesResponse(**asdict(snapshot.schedule_rules)),
    )


def _run_admission_error(exc: RunAdmissionError) -> JSONResponse:
    snapshot = exc.snapshot
    return JSONResponse(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        content={
            "detail": snapshot.detail,
            "code": snapshot.code,
            "status": snapshot.status,
            "inflight_run_count": snapshot.inflight_run_count,
            "max_concurrent_runs": snapshot.max_concurrent_runs,
            "queued_keyword_count": snapshot.queued_keyword_count,
            "max_queued_keywords": snapshot.max_queued_keywords,
        },
    )


@router.get("", response_model=RulesResponse)
def get_rules(request: Request, tenant_id: str | None = None) -> RulesResponse:
    service = _service_from_request(request)
    resolved_tenant_id = resolve_request_tenant_id(request, tenant_id)
    snapshot = service.get_rules(tenant_id=resolved_tenant_id)
    return _serialize_rules(snapshot)


@router.post("/profiles", response_model=RuleProfileResponse)
def create_rule_profile(
    payload: CreateRuleProfileRequest,
    request: Request,
    response: Response,
) -> RuleProfileResponse:
    require_admin_role(request)
    service = _service_from_request(request)
    resolved_tenant_id = resolve_request_tenant_id(request, payload.tenant_id)
    try:
        profile = service.create_profile(
            tenant_id=resolved_tenant_id,
            name=payload.name,
            profile_type=payload.profile_type,
            is_active=payload.is_active,
            keywords=payload.keywords,
            max_pages_per_keyword=payload.max_pages_per_keyword,
            close_consulting_after_days=payload.close_consulting_after_days,
            close_stale_after_days=payload.close_stale_after_days,
        )
    except EntitlementError as exc:
        detail = str(exc)
        return _json_error(status_code=403, detail=detail, code=RULES_ERROR_CODES.get(detail))
    except ValueError as exc:
        detail = str(exc)
        return _json_error(status_code=400, detail=detail, code=RULES_ERROR_CODES.get(detail))

    _wake_discovery_dispatch(request, pending_job_count=len(profile.keywords))

    response.status_code = status.HTTP_201_CREATED
    return RuleProfileResponse(**asdict(profile))


@router.patch("/profiles/{profile_id}", response_model=RuleProfileResponse)
def update_rule_profile(
    profile_id: str,
    payload: UpdateRuleProfileRequest,
    request: Request,
) -> RuleProfileResponse:
    require_admin_role(request)
    service = _service_from_request(request)
    resolved_tenant_id = resolve_request_tenant_id(request, payload.tenant_id)
    try:
        profile = service.update_profile(
            tenant_id=resolved_tenant_id,
            profile_id=profile_id,
            name=payload.name,
            is_active=payload.is_active,
            keywords=payload.keywords,
            max_pages_per_keyword=payload.max_pages_per_keyword,
            close_consulting_after_days=payload.close_consulting_after_days,
            close_stale_after_days=payload.close_stale_after_days,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="profile not found") from exc
    except EntitlementError as exc:
        detail = str(exc)
        return _json_error(status_code=403, detail=detail, code=RULES_ERROR_CODES.get(detail))
    except ValueError as exc:
        detail = str(exc)
        return _json_error(status_code=400, detail=detail, code=RULES_ERROR_CODES.get(detail))

    if profile.is_active:
        _wake_discovery_dispatch(request, pending_job_count=len(profile.keywords))

    return RuleProfileResponse(**asdict(profile))


@router.post(
    "/recrawl",
    response_model=ManualRecrawlResponse,
    responses={429: {"model": ManualRecrawlQueuedResponse}},
)
def recrawl_active_keywords(
    payload: ManualRecrawlRequest,
    request: Request,
    response: Response,
) -> ManualRecrawlResponse:
    require_admin_role(request)
    service = _service_from_request(request)
    resolved_tenant_id = resolve_request_tenant_id(request, payload.tenant_id)
    try:
        queued = service.queue_active_discovery_jobs(tenant_id=resolved_tenant_id)
    except RunAdmissionError as exc:
        return _run_admission_error(exc)
    except EntitlementError as exc:
        detail = str(exc)
        return _json_error(status_code=403, detail=detail, code=RULES_ERROR_CODES.get(detail))
    except ValueError as exc:
        detail = str(exc)
        return _json_error(status_code=400, detail=detail, code=RULES_ERROR_CODES.get(detail))

    _wake_discovery_dispatch(request, pending_job_count=queued.queued_job_count)

    response.status_code = status.HTTP_202_ACCEPTED
    return ManualRecrawlResponse(**asdict(queued))
