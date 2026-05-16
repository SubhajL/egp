"""Admin audit-log routes."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request

from egp_api.auth import require_admin_role, resolve_request_tenant_id
from egp_api.routes.admin.dependencies import audit_service_from_request
from egp_api.routes.admin.schemas import AuditLogListResponse
from egp_api.routes.admin.serializers import serialize_audit_log


router = APIRouter()


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
    service = audit_service_from_request(request)
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
    return serialize_audit_log(page)
