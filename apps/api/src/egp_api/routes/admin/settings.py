"""Admin tenant settings and user-management routes."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, status

from egp_api.auth import require_admin_role, resolve_request_tenant_id
from egp_api.routes.admin.dependencies import (
    actor_subject_from_request,
    admin_service_from_request,
    auth_service_from_request,
)
from egp_api.routes.admin.schemas import (
    AdminInviteUserRequest,
    AdminInviteUserResponse,
    AdminTenantSettingsResponse,
    AdminUserResponse,
    CreateAdminUserRequest,
    UpdateAdminUserRequest,
    UpdateTenantSettingsRequest,
    UpdateUserNotificationPreferencesRequest,
)
from egp_api.routes.admin.serializers import serialize_settings, serialize_user


router = APIRouter()


@router.post("/users", response_model=AdminUserResponse, status_code=status.HTTP_201_CREATED)
def create_admin_user(request: Request, payload: CreateAdminUserRequest) -> AdminUserResponse:
    require_admin_role(request)
    service = admin_service_from_request(request)
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
            actor_subject=actor_subject_from_request(request),
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="tenant not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return serialize_user(user)


@router.patch("/users/{user_id}", response_model=AdminUserResponse)
def update_admin_user(
    user_id: str,
    payload: UpdateAdminUserRequest,
    request: Request,
) -> AdminUserResponse:
    require_admin_role(request)
    service = admin_service_from_request(request)
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
            actor_subject=actor_subject_from_request(request),
        )
    except KeyError as exc:
        raise HTTPException(status_code=403, detail="user does not belong to tenant") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return serialize_user(user)


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
    service = auth_service_from_request(request)
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
    service = admin_service_from_request(request)
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
            actor_subject=actor_subject_from_request(request),
        )
    except KeyError as exc:
        raise HTTPException(status_code=403, detail="user does not belong to tenant") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return serialize_user(user)


@router.patch("/settings", response_model=AdminTenantSettingsResponse)
def update_tenant_settings(
    payload: UpdateTenantSettingsRequest,
    request: Request,
) -> AdminTenantSettingsResponse:
    require_admin_role(request)
    service = admin_service_from_request(request)
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
            actor_subject=actor_subject_from_request(request),
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="tenant not found") from exc
    return serialize_settings(settings)
