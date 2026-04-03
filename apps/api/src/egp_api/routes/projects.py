"""Project routes for the Phase 1 control plane."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel

from egp_api.auth import resolve_request_tenant_id
from egp_api.services.project_service import ProjectService
from egp_db.repositories.project_repo import ProjectAliasRecord, ProjectDetail, ProjectRecord, ProjectStatusEventRecord


router = APIRouter(prefix="/v1/projects", tags=["projects"])


class ProjectResponse(BaseModel):
    id: str
    tenant_id: str
    canonical_project_id: str
    project_number: str | None
    project_name: str
    organization_name: str
    procurement_type: str
    proposal_submission_date: str | None
    budget_amount: str | None
    project_state: str
    closed_reason: str | None
    source_status_text: str | None
    first_seen_at: str
    last_seen_at: str
    last_changed_at: str
    created_at: str
    updated_at: str


class ProjectAliasResponse(BaseModel):
    id: str
    project_id: str
    alias_type: str
    alias_value: str
    created_at: str


class ProjectStatusEventResponse(BaseModel):
    id: str
    project_id: str
    observed_status_text: str
    normalized_status: str | None
    observed_at: str
    run_id: str | None
    raw_snapshot: dict[str, object] | None
    created_at: str


class ProjectListResponse(BaseModel):
    projects: list[ProjectResponse]
    total: int
    limit: int
    offset: int


class ProjectDetailResponse(BaseModel):
    project: ProjectResponse
    aliases: list[ProjectAliasResponse]
    status_events: list[ProjectStatusEventResponse]


def _service_from_request(request: Request) -> ProjectService:
    return request.app.state.project_service


def _serialize_project(project: ProjectRecord) -> ProjectResponse:
    return ProjectResponse(
        id=project.id,
        tenant_id=project.tenant_id,
        canonical_project_id=project.canonical_project_id,
        project_number=project.project_number,
        project_name=project.project_name,
        organization_name=project.organization_name,
        procurement_type=project.procurement_type.value,
        proposal_submission_date=project.proposal_submission_date,
        budget_amount=project.budget_amount,
        project_state=project.project_state.value,
        closed_reason=project.closed_reason.value if project.closed_reason else None,
        source_status_text=project.source_status_text,
        first_seen_at=project.first_seen_at,
        last_seen_at=project.last_seen_at,
        last_changed_at=project.last_changed_at,
        created_at=project.created_at,
        updated_at=project.updated_at,
    )


def _serialize_alias(alias: ProjectAliasRecord) -> ProjectAliasResponse:
    return ProjectAliasResponse(
        id=alias.id,
        project_id=alias.project_id,
        alias_type=alias.alias_type,
        alias_value=alias.alias_value,
        created_at=alias.created_at,
    )


def _serialize_status_event(event: ProjectStatusEventRecord) -> ProjectStatusEventResponse:
    return ProjectStatusEventResponse(
        id=event.id,
        project_id=event.project_id,
        observed_status_text=event.observed_status_text,
        normalized_status=event.normalized_status,
        observed_at=event.observed_at,
        run_id=event.run_id,
        raw_snapshot=event.raw_snapshot,
        created_at=event.created_at,
    )


def _serialize_project_detail(detail: ProjectDetail) -> ProjectDetailResponse:
    return ProjectDetailResponse(
        project=_serialize_project(detail.project),
        aliases=[_serialize_alias(alias) for alias in detail.aliases],
        status_events=[_serialize_status_event(event) for event in detail.status_events],
    )


@router.get("", response_model=ProjectListResponse)
def list_projects(
    request: Request,
    tenant_id: str | None = None,
    project_state: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> ProjectListResponse:
    service = _service_from_request(request)
    resolved_tenant_id = resolve_request_tenant_id(request, tenant_id)
    page = service.list_projects(
        tenant_id=resolved_tenant_id,
        project_state=project_state,
        limit=limit,
        offset=offset,
    )
    return ProjectListResponse(
        projects=[_serialize_project(project) for project in page.items],
        total=page.total,
        limit=page.limit,
        offset=page.offset,
    )


@router.get("/{project_id}", response_model=ProjectDetailResponse)
def get_project_detail(project_id: str, request: Request, tenant_id: str | None = None) -> ProjectDetailResponse:
    service = _service_from_request(request)
    resolved_tenant_id = resolve_request_tenant_id(request, tenant_id)
    detail = service.get_project_detail(tenant_id=resolved_tenant_id, project_id=project_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="project not found")
    return _serialize_project_detail(detail)
