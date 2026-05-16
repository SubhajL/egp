"""Internal worker-facing project ingest routes."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, Response, status
from pydantic import BaseModel, Field

from egp_api.auth import require_internal_worker_token
from egp_api.routes.projects import ProjectResponse, _serialize_project
from egp_domain.project_ingest import (
    DiscoverProjectIngestResult,
    ProjectIngestService,
)
from egp_db.db_utils import normalize_uuid_string
from egp_shared_types.enums import ClosedReason, ProcurementType, ProjectState
from egp_shared_types.project_events import CloseCheckProjectEvent, DiscoveredProjectEvent


router = APIRouter(prefix="/internal/worker/projects", tags=["internal-worker"])


class DiscoverProjectIngestRequest(BaseModel):
    tenant_id: str = Field(min_length=1)
    run_id: str | None = None
    keyword: str = ""
    project_number: str | None = None
    search_name: str | None = None
    detail_name: str | None = None
    project_name: str = Field(min_length=1)
    organization_name: str = Field(min_length=1)
    proposal_submission_date: str | None = None
    budget_amount: str | None = None
    procurement_type: ProcurementType | str | None = None
    project_state: ProjectState | str = ProjectState.DISCOVERED
    source_status_text: str = ""
    raw_snapshot: dict[str, object] | None = None


class CloseCheckProjectIngestRequest(BaseModel):
    tenant_id: str = Field(min_length=1)
    run_id: str | None = None
    project_id: str = Field(min_length=1)
    closed_reason: ClosedReason
    source_status_text: str = Field(min_length=1)
    raw_snapshot: dict[str, object] | None = None


class DiscoverProjectIngestResponse(BaseModel):
    created: bool
    project: ProjectResponse


class CloseCheckProjectIngestResponse(BaseModel):
    project: ProjectResponse


def _service_from_request(request: Request) -> ProjectIngestService:
    return request.app.state.project_ingest_service


def _serialize_discover_result(
    result: DiscoverProjectIngestResult,
) -> DiscoverProjectIngestResponse:
    return DiscoverProjectIngestResponse(
        created=result.created,
        project=_serialize_project(result.project),
    )


@router.post("/discover", response_model=DiscoverProjectIngestResponse)
def ingest_discovered_project(
    payload: DiscoverProjectIngestRequest,
    request: Request,
    response: Response,
) -> DiscoverProjectIngestResponse:
    service = _service_from_request(request)
    require_internal_worker_token(request)
    resolved_tenant_id = normalize_uuid_string(payload.tenant_id)
    result = service.ingest_discovered_project(
        event=DiscoveredProjectEvent(
            tenant_id=resolved_tenant_id,
            run_id=payload.run_id,
            keyword=payload.keyword,
            project_number=payload.project_number,
            search_name=payload.search_name,
            detail_name=payload.detail_name,
            project_name=payload.project_name,
            organization_name=payload.organization_name,
            proposal_submission_date=payload.proposal_submission_date,
            budget_amount=payload.budget_amount,
            procurement_type=payload.procurement_type,
            project_state=payload.project_state,
            source_status_text=payload.source_status_text,
            raw_snapshot=payload.raw_snapshot,
        )
    )
    response.status_code = status.HTTP_201_CREATED if result.created else status.HTTP_200_OK
    return _serialize_discover_result(result)


@router.post("/close-check", response_model=CloseCheckProjectIngestResponse)
def ingest_close_check_project(
    payload: CloseCheckProjectIngestRequest,
    request: Request,
) -> CloseCheckProjectIngestResponse:
    service = _service_from_request(request)
    require_internal_worker_token(request)
    resolved_tenant_id = normalize_uuid_string(payload.tenant_id)
    try:
        project = service.ingest_close_check_event(
            event=CloseCheckProjectEvent(
                tenant_id=resolved_tenant_id,
                run_id=payload.run_id,
                project_id=payload.project_id,
                closed_reason=payload.closed_reason,
                source_status_text=payload.source_status_text,
                raw_snapshot=payload.raw_snapshot,
            )
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="project not found") from exc
    return CloseCheckProjectIngestResponse(project=_serialize_project(project))
