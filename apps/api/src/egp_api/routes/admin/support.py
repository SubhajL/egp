"""Admin support routes."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request

from egp_api.auth import require_support_role
from egp_api.routes.admin.dependencies import support_service_from_request
from egp_api.routes.admin.schemas import SupportSummaryResponse, SupportTenantListResponse
from egp_api.routes.admin.serializers import serialize_support_summary, serialize_support_tenant


router = APIRouter()


@router.get("/support/tenants", response_model=SupportTenantListResponse)
def search_support_tenants(
    request: Request,
    query: str = Query(default=""),
    limit: int = Query(default=20, ge=1, le=50),
) -> SupportTenantListResponse:
    require_support_role(request)
    service = support_service_from_request(request)
    tenants = service.search_tenants(query=query, limit=limit)
    return SupportTenantListResponse(
        tenants=[serialize_support_tenant(item) for item in tenants]
    )


@router.get("/support/tenants/{tenant_id}/summary", response_model=SupportSummaryResponse)
def get_support_summary(
    tenant_id: str,
    request: Request,
    window_days: int = Query(default=30, ge=1, le=90),
) -> SupportSummaryResponse:
    require_support_role(request)
    service = support_service_from_request(request)
    try:
        summary = service.get_summary(tenant_id=tenant_id, window_days=window_days)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="tenant not found") from exc
    return serialize_support_summary(summary)
