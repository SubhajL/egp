"""Export routes for Excel download."""

from __future__ import annotations

from decimal import Decimal

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import Response

from egp_api.auth import resolve_request_tenant_id
from egp_api.services.export_service import ExportService


router = APIRouter(prefix="/v1/exports", tags=["exports"])


def _service_from_request(request: Request) -> ExportService:
    return request.app.state.export_service


@router.get("/excel")
def export_excel(
    request: Request,
    tenant_id: str | None = None,
    project_state: list[str] | None = Query(default=None),
    procurement_type: list[str] | None = Query(default=None),
    closed_reason: list[str] | None = Query(default=None),
    organization: str | None = None,
    keyword: str | None = None,
    budget_min: Decimal | None = None,
    budget_max: Decimal | None = None,
    updated_after: str | None = None,
    has_changed_tor: bool | None = None,
    has_winner: bool | None = None,
) -> Response:
    service = _service_from_request(request)
    resolved_tenant_id = resolve_request_tenant_id(request, tenant_id)
    try:
        excel_bytes = service.export_to_excel(
            tenant_id=resolved_tenant_id,
            project_states=project_state,
            procurement_types=procurement_type,
            closed_reasons=closed_reason,
            organization=organization,
            keyword=keyword,
            budget_min=budget_min,
            budget_max=budget_max,
            updated_after=updated_after,
            has_changed_tor=has_changed_tor,
            has_winner=has_winner,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return Response(
        content=excel_bytes,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": "attachment; filename=egp_projects.xlsx",
        },
    )
