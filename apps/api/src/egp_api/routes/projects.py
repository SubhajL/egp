"""Project routes for the Phase 1 control plane."""

from __future__ import annotations

from decimal import Decimal

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel

from egp_api.auth import resolve_request_tenant_id
from egp_api.services.project_service import ProjectService
from egp_api.services.run_service import RunService
from egp_db.repositories.project_repo import (
    ProjectAliasRecord,
    ProjectDetail,
    ProjectRecord,
    ProjectStatusEventRecord,
)
from egp_db.repositories.run_repo import ProjectCrawlEvidenceRecord


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
    has_changed_tor: bool = False
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


class ProjectCrawlEvidenceResponse(BaseModel):
    task_id: str
    run_id: str
    trigger_type: str
    run_status: str
    task_type: str
    task_status: str
    attempts: int
    keyword: str | None
    started_at: str | None
    finished_at: str | None
    created_at: str
    payload: dict[str, object] | None
    result_json: dict[str, object] | None
    run_summary_json: dict[str, object] | None
    run_error_count: int


class ProjectCrawlEvidenceListResponse(BaseModel):
    evidence: list[ProjectCrawlEvidenceResponse]
    total: int
    limit: int
    offset: int


def _service_from_request(request: Request) -> ProjectService:
    return request.app.state.project_service


def _run_service_from_request(request: Request) -> RunService:
    return request.app.state.run_service


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
        has_changed_tor=project.has_changed_tor,
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


def _serialize_project_crawl_evidence(
    evidence: ProjectCrawlEvidenceRecord,
) -> ProjectCrawlEvidenceResponse:
    return ProjectCrawlEvidenceResponse(
        task_id=evidence.task_id,
        run_id=evidence.run_id,
        trigger_type=evidence.trigger_type,
        run_status=evidence.run_status.value,
        task_type=evidence.task_type,
        task_status=evidence.task_status,
        attempts=evidence.attempts,
        keyword=evidence.keyword,
        started_at=evidence.started_at,
        finished_at=evidence.finished_at,
        created_at=evidence.created_at,
        payload=evidence.payload,
        result_json=evidence.result_json,
        run_summary_json=evidence.run_summary_json,
        run_error_count=evidence.run_error_count,
    )


@router.get("", response_model=ProjectListResponse)
def list_projects(
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
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> ProjectListResponse:
    service = _service_from_request(request)
    resolved_tenant_id = resolve_request_tenant_id(request, tenant_id)
    try:
        page = service.list_projects(
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
            limit=limit,
            offset=offset,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return ProjectListResponse(
        projects=[_serialize_project(project) for project in page.items],
        total=page.total,
        limit=page.limit,
        offset=page.offset,
    )


@router.get("/{project_id}", response_model=ProjectDetailResponse)
def get_project_detail(
    project_id: str, request: Request, tenant_id: str | None = None
) -> ProjectDetailResponse:
    service = _service_from_request(request)
    resolved_tenant_id = resolve_request_tenant_id(request, tenant_id)
    detail = service.get_project_detail(tenant_id=resolved_tenant_id, project_id=project_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="project not found")
    return _serialize_project_detail(detail)


@router.get("/{project_id}/crawl-evidence", response_model=ProjectCrawlEvidenceListResponse)
def list_project_crawl_evidence(
    project_id: str,
    request: Request,
    tenant_id: str | None = None,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> ProjectCrawlEvidenceListResponse:
    project_service = _service_from_request(request)
    run_service = _run_service_from_request(request)
    resolved_tenant_id = resolve_request_tenant_id(request, tenant_id)
    detail = project_service.get_project_detail(tenant_id=resolved_tenant_id, project_id=project_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="project not found")
    page = run_service.list_project_crawl_evidence(
        tenant_id=resolved_tenant_id,
        project_id=project_id,
        limit=limit,
        offset=offset,
    )
    return ProjectCrawlEvidenceListResponse(
        evidence=[_serialize_project_crawl_evidence(item) for item in page.items],
        total=page.total,
        limit=page.limit,
        offset=page.offset,
    )
