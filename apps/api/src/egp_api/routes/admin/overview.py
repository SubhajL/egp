"""Admin overview routes."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from egp_api.auth import require_admin_role, resolve_request_tenant_id
from egp_api.routes.admin.dependencies import admin_service_from_request
from egp_api.routes.admin.schemas import AdminSnapshotResponse
from egp_api.routes.admin.serializers import serialize_snapshot


router = APIRouter()


@router.get("", response_model=AdminSnapshotResponse)
def get_admin_snapshot(request: Request, tenant_id: str | None = None) -> AdminSnapshotResponse:
    require_admin_role(request)
    service = admin_service_from_request(request)
    resolved_tenant_id = resolve_request_tenant_id(
        request,
        tenant_id,
        allow_support_override=True,
    )
    try:
        snapshot = service.get_snapshot(tenant_id=resolved_tenant_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="tenant not found") from exc
    return serialize_snapshot(snapshot)
