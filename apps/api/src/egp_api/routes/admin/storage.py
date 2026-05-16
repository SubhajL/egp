"""Admin tenant storage routes."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse

from egp_api.auth import require_admin_role, resolve_request_tenant_id
from egp_api.routes.admin.dependencies import (
    accepts_html,
    actor_subject_from_request,
    storage_service_from_request,
    storage_settings_redirect,
)
from egp_api.routes.admin.schemas import (
    AdminTenantStorageSettingsResponse,
    ConnectTenantStorageRequest,
    DisconnectTenantStorageRequest,
    GoogleDriveOAuthStartResponse,
    OneDriveOAuthStartResponse,
    SelectGoogleDriveFolderRequest,
    SelectOneDriveFolderRequest,
    StartGoogleDriveOAuthRequest,
    StartOneDriveOAuthRequest,
    TestTenantStorageRequest,
    UpdateTenantStorageSettingsRequest,
)
from egp_api.routes.admin.serializers import serialize_storage_settings


router = APIRouter()


@router.get("/storage", response_model=AdminTenantStorageSettingsResponse)
def get_tenant_storage_settings(
    request: Request,
    tenant_id: str | None = None,
) -> AdminTenantStorageSettingsResponse:
    require_admin_role(request)
    service = storage_service_from_request(request)
    resolved_tenant_id = resolve_request_tenant_id(
        request,
        tenant_id,
        allow_support_override=True,
    )
    try:
        settings = service.get_storage_settings(tenant_id=resolved_tenant_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="tenant not found") from exc
    return serialize_storage_settings(settings)


@router.patch("/storage", response_model=AdminTenantStorageSettingsResponse)
def update_tenant_storage_settings(
    payload: UpdateTenantStorageSettingsRequest,
    request: Request,
) -> AdminTenantStorageSettingsResponse:
    require_admin_role(request)
    service = storage_service_from_request(request)
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
            managed_backup_enabled=payload.managed_backup_enabled,
            last_validated_at=payload.last_validated_at,
            last_validation_error=payload.last_validation_error,
            actor_subject=actor_subject_from_request(request),
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="tenant not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return serialize_storage_settings(settings)


@router.post("/storage/connect", response_model=AdminTenantStorageSettingsResponse)
def connect_tenant_storage(
    payload: ConnectTenantStorageRequest,
    request: Request,
) -> AdminTenantStorageSettingsResponse:
    require_admin_role(request)
    service = storage_service_from_request(request)
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
            actor_subject=actor_subject_from_request(request),
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="tenant not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return serialize_storage_settings(settings)


@router.post("/storage/google-drive/oauth/start", response_model=GoogleDriveOAuthStartResponse)
def start_google_drive_oauth(
    payload: StartGoogleDriveOAuthRequest,
    request: Request,
) -> GoogleDriveOAuthStartResponse:
    require_admin_role(request)
    service = storage_service_from_request(request)
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
    service = storage_service_from_request(request)
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
            actor_subject=actor_subject_from_request(request),
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="tenant not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if accepts_html(request):
        return storage_settings_redirect(request, provider="google_drive", outcome="connected")
    return serialize_storage_settings(settings)


@router.post("/storage/google-drive/folder", response_model=AdminTenantStorageSettingsResponse)
def select_google_drive_folder(
    payload: SelectGoogleDriveFolderRequest,
    request: Request,
) -> AdminTenantStorageSettingsResponse:
    require_admin_role(request)
    service = storage_service_from_request(request)
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
            actor_subject=actor_subject_from_request(request),
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="tenant not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return serialize_storage_settings(settings)


@router.post("/storage/onedrive/oauth/start", response_model=OneDriveOAuthStartResponse)
def start_onedrive_oauth(
    payload: StartOneDriveOAuthRequest,
    request: Request,
) -> OneDriveOAuthStartResponse:
    require_admin_role(request)
    service = storage_service_from_request(request)
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
    service = storage_service_from_request(request)
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
            actor_subject=actor_subject_from_request(request),
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="tenant not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if accepts_html(request):
        return storage_settings_redirect(request, provider="onedrive", outcome="connected")
    return serialize_storage_settings(settings)


@router.post("/storage/onedrive/folder", response_model=AdminTenantStorageSettingsResponse)
def select_onedrive_folder(
    payload: SelectOneDriveFolderRequest,
    request: Request,
) -> AdminTenantStorageSettingsResponse:
    require_admin_role(request)
    service = storage_service_from_request(request)
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
            actor_subject=actor_subject_from_request(request),
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="tenant not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return serialize_storage_settings(settings)


@router.post("/storage/disconnect", response_model=AdminTenantStorageSettingsResponse)
def disconnect_tenant_storage(
    payload: DisconnectTenantStorageRequest,
    request: Request,
) -> AdminTenantStorageSettingsResponse:
    require_admin_role(request)
    service = storage_service_from_request(request)
    resolved_tenant_id = resolve_request_tenant_id(
        request,
        payload.tenant_id,
        allow_support_override=True,
    )
    try:
        settings = service.disconnect_provider(
            tenant_id=resolved_tenant_id,
            provider=payload.provider,
            actor_subject=actor_subject_from_request(request),
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="tenant not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return serialize_storage_settings(settings)


@router.post("/storage/test-write", response_model=AdminTenantStorageSettingsResponse)
def test_tenant_storage_write(
    payload: TestTenantStorageRequest,
    request: Request,
) -> AdminTenantStorageSettingsResponse:
    require_admin_role(request)
    service = storage_service_from_request(request)
    resolved_tenant_id = resolve_request_tenant_id(
        request,
        payload.tenant_id,
        allow_support_override=True,
    )
    try:
        settings = service.test_write(
            tenant_id=resolved_tenant_id,
            actor_subject=actor_subject_from_request(request),
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="tenant not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return serialize_storage_settings(settings)
