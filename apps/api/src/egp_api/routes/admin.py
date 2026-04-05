"""Admin routes for tenant settings, users, and billing visibility."""

from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, HTTPException, Query, Request, status
from pydantic import BaseModel, Field

from egp_api.auth import require_admin_role, require_support_role, resolve_request_tenant_id
from egp_api.services.admin_service import AdminService, AdminSnapshot, AdminUserView
from egp_api.services.audit_service import AuditService
from egp_api.services.support_service import SupportService
from egp_db.repositories.admin_repo import TenantSettingsRecord
from egp_shared_types.enums import UserRole


router = APIRouter(prefix="/v1/admin", tags=["admin"])


class AdminTenantResponse(BaseModel):
    id: str
    name: str
    slug: str
    plan_code: str
    is_active: bool
    created_at: str
    updated_at: str


class AdminTenantSettingsResponse(BaseModel):
    support_email: str | None
    billing_contact_email: str | None
    timezone: str
    locale: str
    daily_digest_enabled: bool
    weekly_digest_enabled: bool
    created_at: str | None
    updated_at: str | None


class AdminUserResponse(BaseModel):
    id: str
    email: str
    full_name: str | None
    role: str
    status: str
    created_at: str
    updated_at: str
    notification_preferences: dict[str, bool]


class AdminBillingRecordResponse(BaseModel):
    id: str
    tenant_id: str
    record_number: str
    plan_code: str
    status: str
    billing_period_start: str
    billing_period_end: str
    due_at: str | None
    issued_at: str | None
    paid_at: str | None
    currency: str
    amount_due: str
    reconciled_total: str
    outstanding_balance: str
    notes: str | None
    created_at: str
    updated_at: str


class AdminBillingSummaryResponse(BaseModel):
    open_records: int
    awaiting_reconciliation: int
    outstanding_amount: str
    collected_amount: str


class AdminSubscriptionResponse(BaseModel):
    id: str
    tenant_id: str
    billing_record_id: str
    plan_code: str
    subscription_status: str
    billing_period_start: str
    billing_period_end: str
    keyword_limit: int | None
    activated_at: str
    activated_by_payment_id: str | None
    created_at: str
    updated_at: str


class AdminBillingResponse(BaseModel):
    summary: AdminBillingSummaryResponse
    current_subscription: AdminSubscriptionResponse | None
    records: list[AdminBillingRecordResponse]


class AdminSnapshotResponse(BaseModel):
    tenant: AdminTenantResponse
    settings: AdminTenantSettingsResponse
    users: list[AdminUserResponse]
    billing: AdminBillingResponse


class AuditLogEventResponse(BaseModel):
    id: str
    tenant_id: str
    source: str
    entity_type: str
    entity_id: str
    project_id: str | None
    document_id: str | None
    actor_subject: str | None
    event_type: str
    summary: str
    metadata_json: dict[str, object] | None
    occurred_at: str
    created_at: str


class AuditLogListResponse(BaseModel):
    items: list[AuditLogEventResponse]
    total: int
    limit: int
    offset: int


class SupportTenantResponse(BaseModel):
    id: str
    name: str
    slug: str
    plan_code: str
    is_active: bool
    support_email: str | None
    billing_contact_email: str | None
    active_user_count: int


class SupportTenantListResponse(BaseModel):
    tenants: list[SupportTenantResponse]


class SupportTriageResponse(BaseModel):
    failed_runs_recent: int
    pending_document_reviews: int
    failed_webhook_deliveries: int
    outstanding_billing_records: int


class SupportFailedRunResponse(BaseModel):
    id: str
    trigger_type: str
    status: str
    error_count: int
    created_at: str


class SupportPendingReviewResponse(BaseModel):
    id: str
    project_id: str
    status: str
    created_at: str


class SupportFailedWebhookResponse(BaseModel):
    id: str
    webhook_subscription_id: str
    delivery_status: str
    last_response_status_code: int | None
    last_attempted_at: str | None


class SupportBillingIssueResponse(BaseModel):
    id: str
    record_number: str
    status: str
    amount_due: str
    due_at: str | None
    created_at: str


class SupportCostSummaryResponse(BaseModel):
    window_days: int
    currency: str
    estimated_total_thb: str
    crawl: dict[str, object]
    storage: dict[str, object]
    notifications: dict[str, object]
    payments: dict[str, object]


class SupportSummaryResponse(BaseModel):
    tenant: SupportTenantResponse
    triage: SupportTriageResponse
    cost_summary: SupportCostSummaryResponse
    recent_failed_runs: list[SupportFailedRunResponse]
    pending_reviews: list[SupportPendingReviewResponse]
    failed_webhooks: list[SupportFailedWebhookResponse]
    billing_issues: list[SupportBillingIssueResponse]


class CreateAdminUserRequest(BaseModel):
    tenant_id: str | None = None
    email: str = Field(min_length=1)
    full_name: str | None = None
    role: UserRole = UserRole.VIEWER
    status: str = Field(default="active", pattern="^(active|suspended|deactivated)$")


class UpdateAdminUserRequest(BaseModel):
    tenant_id: str | None = None
    full_name: str | None = None
    role: UserRole | None = None
    status: str | None = Field(default=None, pattern="^(active|suspended|deactivated)$")


class UpdateUserNotificationPreferencesRequest(BaseModel):
    tenant_id: str | None = None
    email_preferences: dict[str, bool]


class UpdateTenantSettingsRequest(BaseModel):
    tenant_id: str | None = None
    support_email: str | None = None
    billing_contact_email: str | None = None
    timezone: str | None = None
    locale: str | None = None
    daily_digest_enabled: bool | None = None
    weekly_digest_enabled: bool | None = None


def _service_from_request(request: Request) -> AdminService:
    return request.app.state.admin_service


def _audit_service_from_request(request: Request) -> AuditService:
    return request.app.state.audit_service


def _support_service_from_request(request: Request) -> SupportService:
    return request.app.state.support_service


def _actor_subject_from_request(request: Request) -> str:
    auth_context = getattr(request.state, "auth_context", None)
    if auth_context is not None and getattr(auth_context, "subject", None):
        return str(auth_context.subject)
    return "manual-operator"


def _serialize_user(user: AdminUserView) -> AdminUserResponse:
    return AdminUserResponse(**asdict(user))


def _serialize_settings(settings: TenantSettingsRecord) -> AdminTenantSettingsResponse:
    return AdminTenantSettingsResponse(**asdict(settings))


def _serialize_snapshot(snapshot: AdminSnapshot) -> AdminSnapshotResponse:
    current_subscription = snapshot.billing.current_subscription
    return AdminSnapshotResponse(
        tenant=AdminTenantResponse(**asdict(snapshot.tenant)),
        settings=_serialize_settings(snapshot.settings),
        users=[_serialize_user(user) for user in snapshot.users],
        billing=AdminBillingResponse(
            summary=AdminBillingSummaryResponse(**asdict(snapshot.billing.summary)),
            current_subscription=(
                AdminSubscriptionResponse(
                    id=current_subscription.id,
                    tenant_id=current_subscription.tenant_id,
                    billing_record_id=current_subscription.billing_record_id,
                    plan_code=current_subscription.plan_code,
                    subscription_status=current_subscription.subscription_status.value,
                    billing_period_start=current_subscription.billing_period_start,
                    billing_period_end=current_subscription.billing_period_end,
                    keyword_limit=current_subscription.keyword_limit,
                    activated_at=current_subscription.activated_at,
                    activated_by_payment_id=current_subscription.activated_by_payment_id,
                    created_at=current_subscription.created_at,
                    updated_at=current_subscription.updated_at,
                )
                if current_subscription is not None
                else None
            ),
            records=[
                AdminBillingRecordResponse(
                    id=record.id,
                    tenant_id=record.tenant_id,
                    record_number=record.record_number,
                    plan_code=record.plan_code,
                    status=record.status.value,
                    billing_period_start=record.billing_period_start,
                    billing_period_end=record.billing_period_end,
                    due_at=record.due_at,
                    issued_at=record.issued_at,
                    paid_at=record.paid_at,
                    currency=record.currency,
                    amount_due=record.amount_due,
                    reconciled_total=record.reconciled_total,
                    outstanding_balance=record.outstanding_balance,
                    notes=record.notes,
                    created_at=record.created_at,
                    updated_at=record.updated_at,
                )
                for record in snapshot.billing.records
            ],
        ),
    )


def _serialize_audit_log(page) -> AuditLogListResponse:
    return AuditLogListResponse(
        items=[AuditLogEventResponse(**asdict(item)) for item in page.items],
        total=page.total,
        limit=page.limit,
        offset=page.offset,
    )


def _serialize_support_tenant(tenant) -> SupportTenantResponse:
    return SupportTenantResponse(**asdict(tenant))


def _serialize_support_cost_summary(summary) -> SupportCostSummaryResponse:
    return SupportCostSummaryResponse(
        window_days=summary.window_days,
        currency=summary.currency,
        estimated_total_thb=summary.estimated_total_thb,
        crawl=asdict(summary.crawl),
        storage=asdict(summary.storage),
        notifications=asdict(summary.notifications),
        payments=asdict(summary.payments),
    )


def _serialize_support_summary(summary) -> SupportSummaryResponse:
    return SupportSummaryResponse(
        tenant=_serialize_support_tenant(summary.tenant),
        triage=SupportTriageResponse(**asdict(summary.triage)),
        cost_summary=_serialize_support_cost_summary(summary.cost_summary),
        recent_failed_runs=[
            SupportFailedRunResponse(**asdict(item)) for item in summary.recent_failed_runs
        ],
        pending_reviews=[
            SupportPendingReviewResponse(**asdict(item)) for item in summary.pending_reviews
        ],
        failed_webhooks=[
            SupportFailedWebhookResponse(**asdict(item)) for item in summary.failed_webhooks
        ],
        billing_issues=[
            SupportBillingIssueResponse(**asdict(item)) for item in summary.billing_issues
        ],
    )


@router.get("", response_model=AdminSnapshotResponse)
def get_admin_snapshot(request: Request, tenant_id: str | None = None) -> AdminSnapshotResponse:
    require_admin_role(request)
    service = _service_from_request(request)
    resolved_tenant_id = resolve_request_tenant_id(
        request,
        tenant_id,
        allow_support_override=True,
    )
    try:
        snapshot = service.get_snapshot(tenant_id=resolved_tenant_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="tenant not found") from exc
    return _serialize_snapshot(snapshot)


@router.get("/audit-log", response_model=AuditLogListResponse)
def get_admin_audit_log(
    request: Request,
    tenant_id: str | None = None,
    source: str | None = None,
    entity_type: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> AuditLogListResponse:
    require_admin_role(request)
    service = _audit_service_from_request(request)
    resolved_tenant_id = resolve_request_tenant_id(
        request,
        tenant_id,
        allow_support_override=True,
    )
    try:
        page = service.list_events(
            tenant_id=resolved_tenant_id,
            source=source,
            entity_type=entity_type,
            limit=limit,
            offset=offset,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _serialize_audit_log(page)


@router.get("/support/tenants", response_model=SupportTenantListResponse)
def search_support_tenants(
    request: Request,
    query: str = Query(default=""),
    limit: int = Query(default=20, ge=1, le=50),
) -> SupportTenantListResponse:
    require_support_role(request)
    service = _support_service_from_request(request)
    tenants = service.search_tenants(query=query, limit=limit)
    return SupportTenantListResponse(
        tenants=[_serialize_support_tenant(item) for item in tenants]
    )


@router.get("/support/tenants/{tenant_id}/summary", response_model=SupportSummaryResponse)
def get_support_summary(
    tenant_id: str,
    request: Request,
    window_days: int = Query(default=30, ge=1, le=90),
) -> SupportSummaryResponse:
    require_support_role(request)
    service = _support_service_from_request(request)
    try:
        summary = service.get_summary(tenant_id=tenant_id, window_days=window_days)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="tenant not found") from exc
    return _serialize_support_summary(summary)


@router.post("/users", response_model=AdminUserResponse, status_code=status.HTTP_201_CREATED)
def create_admin_user(request: Request, payload: CreateAdminUserRequest) -> AdminUserResponse:
    require_admin_role(request)
    service = _service_from_request(request)
    resolved_tenant_id = resolve_request_tenant_id(
        request,
        payload.tenant_id,
        allow_support_override=True,
    )
    try:
        user = service.create_user(
            tenant_id=resolved_tenant_id,
            email=payload.email,
            full_name=payload.full_name,
            role=payload.role,
            status=payload.status,
            actor_subject=_actor_subject_from_request(request),
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="tenant not found") from exc
    return _serialize_user(user)


@router.patch("/users/{user_id}", response_model=AdminUserResponse)
def update_admin_user(
    user_id: str,
    payload: UpdateAdminUserRequest,
    request: Request,
) -> AdminUserResponse:
    require_admin_role(request)
    service = _service_from_request(request)
    resolved_tenant_id = resolve_request_tenant_id(
        request,
        payload.tenant_id,
        allow_support_override=True,
    )
    try:
        user = service.update_user(
            tenant_id=resolved_tenant_id,
            user_id=user_id,
            role=payload.role,
            status=payload.status,
            full_name=payload.full_name,
            actor_subject=_actor_subject_from_request(request),
        )
    except KeyError as exc:
        raise HTTPException(status_code=403, detail="user does not belong to tenant") from exc
    return _serialize_user(user)


@router.put("/users/{user_id}/notification-preferences", response_model=AdminUserResponse)
def update_user_notification_preferences(
    user_id: str,
    payload: UpdateUserNotificationPreferencesRequest,
    request: Request,
) -> AdminUserResponse:
    require_admin_role(request)
    service = _service_from_request(request)
    resolved_tenant_id = resolve_request_tenant_id(
        request,
        payload.tenant_id,
        allow_support_override=True,
    )
    try:
        user = service.update_user_notification_preferences(
            tenant_id=resolved_tenant_id,
            user_id=user_id,
            email_preferences=payload.email_preferences,
            actor_subject=_actor_subject_from_request(request),
        )
    except KeyError as exc:
        raise HTTPException(status_code=403, detail="user does not belong to tenant") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _serialize_user(user)


@router.patch("/settings", response_model=AdminTenantSettingsResponse)
def update_tenant_settings(
    payload: UpdateTenantSettingsRequest,
    request: Request,
) -> AdminTenantSettingsResponse:
    require_admin_role(request)
    service = _service_from_request(request)
    resolved_tenant_id = resolve_request_tenant_id(
        request,
        payload.tenant_id,
        allow_support_override=True,
    )
    try:
        settings = service.update_settings(
            tenant_id=resolved_tenant_id,
            support_email=payload.support_email,
            billing_contact_email=payload.billing_contact_email,
            timezone=payload.timezone,
            locale=payload.locale,
            daily_digest_enabled=payload.daily_digest_enabled,
            weekly_digest_enabled=payload.weekly_digest_enabled,
            actor_subject=_actor_subject_from_request(request),
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="tenant not found") from exc
    return _serialize_settings(settings)
