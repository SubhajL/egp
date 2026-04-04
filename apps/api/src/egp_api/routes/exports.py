"""Export routes for Excel download."""

from __future__ import annotations

from fastapi import APIRouter, Request
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
    project_state: str | None = None,
) -> Response:
    service = _service_from_request(request)
    resolved_tenant_id = resolve_request_tenant_id(request, tenant_id)
    excel_bytes = service.export_to_excel(
        tenant_id=resolved_tenant_id,
        project_state=project_state,
    )
    return Response(
        content=excel_bytes,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": "attachment; filename=egp_projects.xlsx",
        },
    )
