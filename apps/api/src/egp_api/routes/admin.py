"""Admin routes for tenant settings, users, and billing visibility."""

from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, Field

from egp_api.auth import require_admin_role, resolve_request_tenant_id
from egp_api.services.admin_service import AdminService, AdminSnapshot, AdminUserView
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


@router.get("", response_model=AdminSnapshotResponse)
def get_admin_snapshot(request: Request, tenant_id: str | None = None) -> AdminSnapshotResponse:
    require_admin_role(request)
    service = _service_from_request(request)
    resolved_tenant_id = resolve_request_tenant_id(request, tenant_id)
    try:
        snapshot = service.get_snapshot(tenant_id=resolved_tenant_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="tenant not found") from exc
    return _serialize_snapshot(snapshot)


@router.post("/users", response_model=AdminUserResponse, status_code=status.HTTP_201_CREATED)
def create_admin_user(request: Request, payload: CreateAdminUserRequest) -> AdminUserResponse:
    require_admin_role(request)
    service = _service_from_request(request)
    resolved_tenant_id = resolve_request_tenant_id(request, payload.tenant_id)
    try:
        user = service.create_user(
            tenant_id=resolved_tenant_id,
            email=payload.email,
            full_name=payload.full_name,
            role=payload.role,
            status=payload.status,
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
    resolved_tenant_id = resolve_request_tenant_id(request, payload.tenant_id)
    try:
        user = service.update_user(
            tenant_id=resolved_tenant_id,
            user_id=user_id,
            role=payload.role,
            status=payload.status,
            full_name=payload.full_name,
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
    resolved_tenant_id = resolve_request_tenant_id(request, payload.tenant_id)
    try:
        user = service.update_user_notification_preferences(
            tenant_id=resolved_tenant_id,
            user_id=user_id,
            email_preferences=payload.email_preferences,
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
    resolved_tenant_id = resolve_request_tenant_id(request, payload.tenant_id)
    try:
        settings = service.update_settings(
            tenant_id=resolved_tenant_id,
            support_email=payload.support_email,
            billing_contact_email=payload.billing_contact_email,
            timezone=payload.timezone,
            locale=payload.locale,
            daily_digest_enabled=payload.daily_digest_enabled,
            weekly_digest_enabled=payload.weekly_digest_enabled,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="tenant not found") from exc
    return _serialize_settings(settings)
