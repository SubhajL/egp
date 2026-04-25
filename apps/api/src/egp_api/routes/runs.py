"""Run routes for crawl tracking."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request, Response, status
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field

from egp_api.auth import resolve_request_tenant_id
from egp_api.services.entitlement_service import EntitlementError
from egp_api.services.run_service import RunService
from egp_db.repositories.run_repo import CrawlRunDetail, CrawlRunRecord, CrawlTaskRecord


router = APIRouter(prefix="/v1/runs", tags=["runs"])


class CreateRunRequest(BaseModel):
    tenant_id: str | None = None
    trigger_type: str = Field(min_length=1)
    profile_id: str | None = None
    summary_json: dict[str, object] | None = None


class CreateTaskRequest(BaseModel):
    task_type: str = Field(min_length=1)
    project_id: str | None = None
    keyword: str | None = None
    payload: dict[str, object] | None = None


class FinishRunRequest(BaseModel):
    status: str = Field(min_length=1)
    summary_json: dict[str, object] | None = None
    error_count: int = 0


class RunResponse(BaseModel):
    id: str
    tenant_id: str
    trigger_type: str
    status: str
    profile_id: str | None
    started_at: str | None
    finished_at: str | None
    summary_json: dict[str, object] | None
    error_count: int
    created_at: str


class TaskResponse(BaseModel):
    id: str
    run_id: str
    task_type: str
    project_id: str | None
    keyword: str | None
    status: str
    attempts: int
    started_at: str | None
    finished_at: str | None
    payload: dict[str, object] | None
    result_json: dict[str, object] | None
    created_at: str


class RunDetailResponse(BaseModel):
    run: RunResponse
    tasks: list[TaskResponse]


class RunListResponse(BaseModel):
    runs: list[RunDetailResponse]
    total: int
    limit: int
    offset: int


def _service_from_request(request: Request) -> RunService:
    return request.app.state.run_service


def _serialize_run(run: CrawlRunRecord) -> RunResponse:
    return RunResponse(
        id=run.id,
        tenant_id=run.tenant_id,
        trigger_type=run.trigger_type,
        status=run.status.value,
        profile_id=run.profile_id,
        started_at=run.started_at,
        finished_at=run.finished_at,
        summary_json=run.summary_json,
        error_count=run.error_count,
        created_at=run.created_at,
    )


def _serialize_task(task: CrawlTaskRecord) -> TaskResponse:
    return TaskResponse(
        id=task.id,
        run_id=task.run_id,
        task_type=task.task_type,
        project_id=task.project_id,
        keyword=task.keyword,
        status=task.status,
        attempts=task.attempts,
        started_at=task.started_at,
        finished_at=task.finished_at,
        payload=task.payload,
        result_json=task.result_json,
        created_at=task.created_at,
    )


def _serialize_detail(detail: CrawlRunDetail) -> RunDetailResponse:
    return RunDetailResponse(
        run=_serialize_run(detail.run),
        tasks=[_serialize_task(task) for task in detail.tasks],
    )


@router.post("", response_model=RunDetailResponse)
def create_run(
    payload: CreateRunRequest, request: Request, response: Response
) -> RunDetailResponse:
    service = _service_from_request(request)
    resolved_tenant_id = resolve_request_tenant_id(request, payload.tenant_id)
    try:
        detail = service.create_run(
            tenant_id=resolved_tenant_id,
            trigger_type=payload.trigger_type,
            profile_id=payload.profile_id,
            summary_json=payload.summary_json,
        )
    except EntitlementError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    response.status_code = status.HTTP_201_CREATED
    return _serialize_detail(detail)


@router.post("/{run_id}/tasks", response_model=TaskResponse)
def create_task(
    run_id: str,
    payload: CreateTaskRequest,
    request: Request,
    response: Response,
    tenant_id: str | None = None,
) -> TaskResponse:
    service = _service_from_request(request)
    resolved_tenant_id = resolve_request_tenant_id(request, tenant_id)
    try:
        task = service.create_task(
            tenant_id=resolved_tenant_id,
            run_id=run_id,
            task_type=payload.task_type,
            project_id=payload.project_id,
            keyword=payload.keyword,
            payload=payload.payload,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="run not found") from exc
    except EntitlementError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail="run not found for tenant") from exc
    response.status_code = status.HTTP_201_CREATED
    return _serialize_task(task)


@router.post("/{run_id}/finish", response_model=RunDetailResponse)
def finish_run(
    run_id: str,
    payload: FinishRunRequest,
    request: Request,
    tenant_id: str | None = None,
) -> RunDetailResponse:
    service = _service_from_request(request)
    resolved_tenant_id = resolve_request_tenant_id(request, tenant_id)
    try:
        detail = service.finish_run(
            tenant_id=resolved_tenant_id,
            run_id=run_id,
            status=payload.status,
            summary_json=payload.summary_json,
            error_count=payload.error_count,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="run not found") from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail="run not found for tenant") from exc
    return _serialize_detail(detail)


@router.get("", response_model=RunListResponse)
def list_runs(
    request: Request,
    tenant_id: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> RunListResponse:
    service = _service_from_request(request)
    resolved_tenant_id = resolve_request_tenant_id(request, tenant_id)
    page = service.list_runs(tenant_id=resolved_tenant_id, limit=limit, offset=offset)
    return RunListResponse(
        runs=[_serialize_detail(detail) for detail in page.items],
        total=page.total,
        limit=page.limit,
        offset=page.offset,
    )


@router.get("/{run_id}/log", response_class=PlainTextResponse)
def get_run_log(
    run_id: str,
    request: Request,
    tenant_id: str | None = None,
) -> PlainTextResponse:
    service = _service_from_request(request)
    resolved_tenant_id = resolve_request_tenant_id(request, tenant_id)
    try:
        log_text = service.get_run_log(
            tenant_id=resolved_tenant_id,
            run_id=run_id,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="run not found") from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail="run not found for tenant") from exc
    if log_text is None:
        raise HTTPException(status_code=404, detail="run log not found")
    return PlainTextResponse(log_text)
