"""Admin routes for tenant settings, users, and billing visibility."""

from __future__ import annotations

from dataclasses import asdict
from urllib.parse import urlencode

from fastapi import APIRouter, HTTPException, Query, Request, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field

from egp_api.auth import require_admin_role, require_support_role, resolve_request_tenant_id
from egp_api.services.admin_service import AdminService, AdminSnapshot, AdminUserView
from egp_api.services.audit_service import AuditService
from egp_api.services.storage_settings_service import StorageSettingsService
from egp_api.services.support_service import SupportService
from egp_db.repositories.admin_repo import TenantSettingsRecord, TenantStorageSettingsRecord
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
    crawl_interval_hours: int | None
    created_at: str | None
    updated_at: str | None


class AdminTenantStorageSettingsResponse(BaseModel):
    provider: str
    connection_status: str
    account_email: str | None
    folder_label: str | None
    folder_path_hint: str | None
    provider_folder_id: str | None
    provider_folder_url: str | None
    managed_fallback_enabled: bool
    last_validated_at: str | None
    last_validation_error: str | None
    has_credentials: bool
    credential_type: str | None
    credential_updated_at: str | None
    created_at: str | None
    updated_at: str | None


class AdminUserResponse(BaseModel):
    id: str
    email: str
    full_name: str | None
    role: str
    status: str
    email_verified_at: str | None
    mfa_enabled: bool
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
    upgrade_from_subscription_id: str | None
    upgrade_mode: str
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
    upcoming_subscription: AdminSubscriptionResponse | None
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


class SupportStorageDiagnosticsResponse(BaseModel):
    provider: str
    connection_status: str
    account_email: str | None
    provider_folder_id: str | None
    provider_folder_url: str | None
    managed_fallback_enabled: bool
    has_credentials: bool
    last_validated_at: str | None
    last_validation_error: str | None


class SupportAlertResponse(BaseModel):
    severity: str
    code: str
    title: str
    detail: str


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
    storage_diagnostics: SupportStorageDiagnosticsResponse
    alerts: list[SupportAlertResponse]
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
    password: str | None = None


class UpdateAdminUserRequest(BaseModel):
    tenant_id: str | None = None
    full_name: str | None = None
    role: UserRole | None = None
    status: str | None = Field(default=None, pattern="^(active|suspended|deactivated)$")
    password: str | None = None


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
    crawl_interval_hours: int | None = Field(default=None, ge=1, le=168)


class UpdateTenantStorageSettingsRequest(BaseModel):
    tenant_id: str | None = None
    provider: str | None = Field(
        default=None,
        pattern="^(managed|google_drive|onedrive|local_agent)$",
    )
    connection_status: str | None = Field(
        default=None,
        pattern="^(managed|pending_setup|connected|error|disconnected)$",
    )
    account_email: str | None = None
    folder_label: str | None = None
    folder_path_hint: str | None = None
    provider_folder_id: str | None = None
    provider_folder_url: str | None = None
    managed_fallback_enabled: bool | None = None
    last_validated_at: str | None = None
    last_validation_error: str | None = None


class ConnectTenantStorageRequest(BaseModel):
    tenant_id: str | None = None
    provider: str = Field(pattern="^(google_drive|onedrive|local_agent)$")
    credential_type: str = Field(min_length=1)
    credentials: dict[str, object] = Field(default_factory=dict)


class DisconnectTenantStorageRequest(BaseModel):
    tenant_id: str | None = None
    provider: str = Field(pattern="^(google_drive|onedrive|local_agent)$")


class TestTenantStorageRequest(BaseModel):
    tenant_id: str | None = None


class StartGoogleDriveOAuthRequest(BaseModel):
    tenant_id: str | None = None


class GoogleDriveOAuthStartResponse(BaseModel):
    provider: str
    authorization_url: str
    state: str


class StartOneDriveOAuthRequest(BaseModel):
    tenant_id: str | None = None


class OneDriveOAuthStartResponse(BaseModel):
    provider: str
    authorization_url: str
    state: str


class SelectGoogleDriveFolderRequest(BaseModel):
    tenant_id: str | None = None
    folder_id: str = Field(min_length=1)
    folder_label: str | None = None
    folder_url: str | None = None


class SelectOneDriveFolderRequest(BaseModel):
    tenant_id: str | None = None
    folder_id: str = Field(min_length=1)
    folder_label: str | None = None
    folder_url: str | None = None


class AdminInviteUserRequest(BaseModel):
    tenant_id: str | None = None


class AdminInviteUserResponse(BaseModel):
    status: str
    delivery_email: str


def _service_from_request(request: Request) -> AdminService:
    return request.app.state.admin_service


def _storage_service_from_request(request: Request) -> StorageSettingsService:
    return request.app.state.storage_settings_service


def _accepts_html(request: Request) -> bool:
    accept = request.headers.get("accept", "")
    return "text/html" in accept and "application/json" not in accept


def _storage_settings_redirect(
    request: Request,
    *,
    provider: str,
    outcome: str,
) -> RedirectResponse:
    web_base_url = str(getattr(request.app.state, "web_base_url", "http://localhost:3000")).rstrip(
        "/"
    )
    query = urlencode({"provider": provider, "status": outcome})
    return RedirectResponse(
        f"{web_base_url}/admin/storage?{query}",
        status_code=status.HTTP_303_SEE_OTHER,
    )


def _audit_service_from_request(request: Request) -> AuditService:
    return request.app.state.audit_service


def _support_service_from_request(request: Request) -> SupportService:
    return request.app.state.support_service


def _auth_service_from_request(request: Request):
    return request.app.state.auth_service


def _actor_subject_from_request(request: Request) -> str:
    auth_context = getattr(request.state, "auth_context", None)
    if auth_context is not None and getattr(auth_context, "subject", None):
        return str(auth_context.subject)
    return "manual-operator"


def _serialize_user(user: AdminUserView) -> AdminUserResponse:
    return AdminUserResponse(**asdict(user))


def _serialize_settings(settings: TenantSettingsRecord) -> AdminTenantSettingsResponse:
    return AdminTenantSettingsResponse(**asdict(settings))


def _serialize_storage_settings(
    settings: TenantStorageSettingsRecord,
) -> AdminTenantStorageSettingsResponse:
    return AdminTenantStorageSettingsResponse(**asdict(settings))


def _serialize_snapshot(snapshot: AdminSnapshot) -> AdminSnapshotResponse:
    current_subscription = snapshot.billing.current_subscription
    upcoming_subscription = snapshot.billing.upcoming_subscription
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
            upcoming_subscription=(
                AdminSubscriptionResponse(
                    id=upcoming_subscription.id,
                    tenant_id=upcoming_subscription.tenant_id,
                    billing_record_id=upcoming_subscription.billing_record_id,
                    plan_code=upcoming_subscription.plan_code,
                    subscription_status=upcoming_subscription.subscription_status.value,
                    billing_period_start=upcoming_subscription.billing_period_start,
                    billing_period_end=upcoming_subscription.billing_period_end,
                    keyword_limit=upcoming_subscription.keyword_limit,
                    activated_at=upcoming_subscription.activated_at,
                    activated_by_payment_id=upcoming_subscription.activated_by_payment_id,
                    created_at=upcoming_subscription.created_at,
                    updated_at=upcoming_subscription.updated_at,
                )
                if upcoming_subscription is not None
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
                    upgrade_from_subscription_id=record.upgrade_from_subscription_id,
                    upgrade_mode=record.upgrade_mode,
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
        storage_diagnostics=SupportStorageDiagnosticsResponse(
            **asdict(summary.storage_diagnostics)
        ),
        alerts=[SupportAlertResponse(**asdict(item)) for item in summary.alerts],
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
    return SupportTenantListResponse(tenants=[_serialize_support_tenant(item) for item in tenants])


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
            password=payload.password,
            actor_subject=_actor_subject_from_request(request),
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="tenant not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
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
            password=payload.password,
            actor_subject=_actor_subject_from_request(request),
        )
    except KeyError as exc:
        raise HTTPException(status_code=403, detail="user does not belong to tenant") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _serialize_user(user)


@router.post(
    "/users/{user_id}/invite",
    response_model=AdminInviteUserResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def invite_admin_user(
    user_id: str,
    request: Request,
    payload: AdminInviteUserRequest | None = None,
) -> AdminInviteUserResponse:
    require_admin_role(request)
    resolved_tenant_id = resolve_request_tenant_id(
        request,
        payload.tenant_id if payload is not None else None,
        allow_support_override=True,
    )
    service = _auth_service_from_request(request)
    try:
        delivery_email = service.issue_user_invite(
            tenant_id=resolved_tenant_id,
            user_id=user_id,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="user not found") from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc) or "account is not active") from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return AdminInviteUserResponse(status="sent", delivery_email=delivery_email)


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
            crawl_interval_hours=payload.crawl_interval_hours,
            actor_subject=_actor_subject_from_request(request),
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="tenant not found") from exc
    return _serialize_settings(settings)


@router.get("/storage", response_model=AdminTenantStorageSettingsResponse)
def get_tenant_storage_settings(
    request: Request,
    tenant_id: str | None = None,
) -> AdminTenantStorageSettingsResponse:
    require_admin_role(request)
    service = _storage_service_from_request(request)
    resolved_tenant_id = resolve_request_tenant_id(
        request,
        tenant_id,
        allow_support_override=True,
    )
    try:
        settings = service.get_storage_settings(tenant_id=resolved_tenant_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="tenant not found") from exc
    return _serialize_storage_settings(settings)


@router.patch("/storage", response_model=AdminTenantStorageSettingsResponse)
def update_tenant_storage_settings(
    payload: UpdateTenantStorageSettingsRequest,
    request: Request,
) -> AdminTenantStorageSettingsResponse:
    require_admin_role(request)
    service = _storage_service_from_request(request)
    resolved_tenant_id = resolve_request_tenant_id(
        request,
        payload.tenant_id,
        allow_support_override=True,
    )
    try:
        settings = service.update_config(
            tenant_id=resolved_tenant_id,
            provider=payload.provider,
            connection_status=payload.connection_status,
            account_email=payload.account_email,
            folder_label=payload.folder_label,
            folder_path_hint=payload.folder_path_hint,
            provider_folder_id=payload.provider_folder_id,
            provider_folder_url=payload.provider_folder_url,
            managed_fallback_enabled=payload.managed_fallback_enabled,
            last_validated_at=payload.last_validated_at,
            last_validation_error=payload.last_validation_error,
            actor_subject=_actor_subject_from_request(request),
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="tenant not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _serialize_storage_settings(settings)


@router.post("/storage/connect", response_model=AdminTenantStorageSettingsResponse)
def connect_tenant_storage(
    payload: ConnectTenantStorageRequest,
    request: Request,
) -> AdminTenantStorageSettingsResponse:
    require_admin_role(request)
    service = _storage_service_from_request(request)
    resolved_tenant_id = resolve_request_tenant_id(
        request,
        payload.tenant_id,
        allow_support_override=True,
    )
    try:
        settings = service.connect_provider(
            tenant_id=resolved_tenant_id,
            provider=payload.provider,
            credential_type=payload.credential_type,
            credentials=payload.credentials,
            actor_subject=_actor_subject_from_request(request),
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="tenant not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _serialize_storage_settings(settings)


@router.post("/storage/google-drive/oauth/start", response_model=GoogleDriveOAuthStartResponse)
def start_google_drive_oauth(
    payload: StartGoogleDriveOAuthRequest,
    request: Request,
) -> GoogleDriveOAuthStartResponse:
    require_admin_role(request)
    service = _storage_service_from_request(request)
    resolved_tenant_id = resolve_request_tenant_id(
        request,
        payload.tenant_id,
        allow_support_override=True,
    )
    try:
        result = service.start_google_drive_oauth(tenant_id=resolved_tenant_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="tenant not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return GoogleDriveOAuthStartResponse(**result)


@router.get(
    "/storage/google-drive/oauth/callback", response_model=AdminTenantStorageSettingsResponse
)
def handle_google_drive_oauth_callback(
    request: Request,
    code: str,
    state: str,
) -> AdminTenantStorageSettingsResponse | RedirectResponse:
    require_admin_role(request)
    service = _storage_service_from_request(request)
    auth_tenant_id = resolve_request_tenant_id(
        request,
        None,
        allow_support_override=True,
    )
    try:
        settings = service.handle_google_drive_oauth_callback(
            code=code,
            state=state,
            expected_tenant_id=auth_tenant_id,
            actor_subject=_actor_subject_from_request(request),
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="tenant not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if _accepts_html(request):
        return _storage_settings_redirect(request, provider="google_drive", outcome="connected")
    return _serialize_storage_settings(settings)


@router.post("/storage/google-drive/folder", response_model=AdminTenantStorageSettingsResponse)
def select_google_drive_folder(
    payload: SelectGoogleDriveFolderRequest,
    request: Request,
) -> AdminTenantStorageSettingsResponse:
    require_admin_role(request)
    service = _storage_service_from_request(request)
    resolved_tenant_id = resolve_request_tenant_id(
        request,
        payload.tenant_id,
        allow_support_override=True,
    )
    try:
        settings = service.select_google_drive_folder(
            tenant_id=resolved_tenant_id,
            folder_id=payload.folder_id,
            folder_label=payload.folder_label,
            folder_url=payload.folder_url,
            actor_subject=_actor_subject_from_request(request),
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="tenant not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _serialize_storage_settings(settings)


@router.post("/storage/onedrive/oauth/start", response_model=OneDriveOAuthStartResponse)
def start_onedrive_oauth(
    payload: StartOneDriveOAuthRequest,
    request: Request,
) -> OneDriveOAuthStartResponse:
    require_admin_role(request)
    service = _storage_service_from_request(request)
    resolved_tenant_id = resolve_request_tenant_id(
        request,
        payload.tenant_id,
        allow_support_override=True,
    )
    try:
        result = service.start_onedrive_oauth(tenant_id=resolved_tenant_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="tenant not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return OneDriveOAuthStartResponse(**result)


@router.get("/storage/onedrive/oauth/callback", response_model=AdminTenantStorageSettingsResponse)
def handle_onedrive_oauth_callback(
    request: Request,
    code: str,
    state: str,
) -> AdminTenantStorageSettingsResponse | RedirectResponse:
    require_admin_role(request)
    service = _storage_service_from_request(request)
    auth_tenant_id = resolve_request_tenant_id(
        request,
        None,
        allow_support_override=True,
    )
    try:
        settings = service.handle_onedrive_oauth_callback(
            code=code,
            state=state,
            expected_tenant_id=auth_tenant_id,
            actor_subject=_actor_subject_from_request(request),
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="tenant not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if _accepts_html(request):
        return _storage_settings_redirect(request, provider="onedrive", outcome="connected")
    return _serialize_storage_settings(settings)


@router.post("/storage/onedrive/folder", response_model=AdminTenantStorageSettingsResponse)
def select_onedrive_folder(
    payload: SelectOneDriveFolderRequest,
    request: Request,
) -> AdminTenantStorageSettingsResponse:
    require_admin_role(request)
    service = _storage_service_from_request(request)
    resolved_tenant_id = resolve_request_tenant_id(
        request,
        payload.tenant_id,
        allow_support_override=True,
    )
    try:
        settings = service.select_onedrive_folder(
            tenant_id=resolved_tenant_id,
            folder_id=payload.folder_id,
            folder_label=payload.folder_label,
            folder_url=payload.folder_url,
            actor_subject=_actor_subject_from_request(request),
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="tenant not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _serialize_storage_settings(settings)


@router.post("/storage/disconnect", response_model=AdminTenantStorageSettingsResponse)
def disconnect_tenant_storage(
    payload: DisconnectTenantStorageRequest,
    request: Request,
) -> AdminTenantStorageSettingsResponse:
    require_admin_role(request)
    service = _storage_service_from_request(request)
    resolved_tenant_id = resolve_request_tenant_id(
        request,
        payload.tenant_id,
        allow_support_override=True,
    )
    try:
        settings = service.disconnect_provider(
            tenant_id=resolved_tenant_id,
            provider=payload.provider,
            actor_subject=_actor_subject_from_request(request),
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="tenant not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _serialize_storage_settings(settings)


@router.post("/storage/test-write", response_model=AdminTenantStorageSettingsResponse)
def test_tenant_storage_write(
    payload: TestTenantStorageRequest,
    request: Request,
) -> AdminTenantStorageSettingsResponse:
    require_admin_role(request)
    service = _storage_service_from_request(request)
    resolved_tenant_id = resolve_request_tenant_id(
        request,
        payload.tenant_id,
        allow_support_override=True,
    )
    try:
        settings = service.test_write(
            tenant_id=resolved_tenant_id,
            actor_subject=_actor_subject_from_request(request),
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="tenant not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _serialize_storage_settings(settings)
