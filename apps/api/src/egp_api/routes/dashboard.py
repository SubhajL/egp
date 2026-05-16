"""Dashboard routes for summary widgets."""

from __future__ import annotations

from fastapi import APIRouter, Request
from pydantic import BaseModel

from egp_api.auth import resolve_request_tenant_id
from egp_api.routes.admin.schemas import SupportCostSummaryResponse
from egp_api.services.dashboard_service import DashboardKpis, DashboardService, DashboardSummary
from egp_db.repositories.project_repo import (
    DashboardDailyDiscoveryPoint,
    DashboardRecentProjectChangeRecord,
    DashboardStateBreakdownPoint,
    DashboardWinnerProjectRecord,
)
from egp_db.repositories.run_repo import DashboardRecentRunRecord
from egp_db.repositories.support_repo import SupportCostSummary


router = APIRouter(prefix="/v1/dashboard", tags=["dashboard"])


class DashboardKpisResponse(BaseModel):
    active_projects: int
    discovered_today: int
    winner_projects_this_week: int
    closed_today: int
    changed_tor_projects: int
    crawl_success_rate_percent: float
    failed_runs_recent: int
    crawl_success_window_runs: int


class DashboardRecentRunResponse(BaseModel):
    id: str
    trigger_type: str
    status: str
    profile_id: str | None
    started_at: str | None
    finished_at: str | None
    created_at: str
    error_count: int
    discovered_projects: int


class DashboardRecentProjectChangeResponse(BaseModel):
    project_id: str
    project_name: str
    project_state: str
    last_changed_at: str


class DashboardWinnerProjectResponse(BaseModel):
    project_id: str
    project_name: str
    project_state: str
    awarded_at: str


class DashboardDailyDiscoveryPointResponse(BaseModel):
    date: str
    count: int


class DashboardStateBreakdownPointResponse(BaseModel):
    bucket: str
    count: int


class DashboardSummaryResponse(BaseModel):
    kpis: DashboardKpisResponse
    recent_runs: list[DashboardRecentRunResponse]
    recent_changes: list[DashboardRecentProjectChangeResponse]
    winner_projects: list[DashboardWinnerProjectResponse]
    daily_discovery: list[DashboardDailyDiscoveryPointResponse]
    project_state_breakdown: list[DashboardStateBreakdownPointResponse]
    cost_summary: SupportCostSummaryResponse


def _service_from_request(request: Request) -> DashboardService:
    return request.app.state.dashboard_service


def _serialize_kpis(kpis: DashboardKpis) -> DashboardKpisResponse:
    return DashboardKpisResponse(
        active_projects=kpis.active_projects,
        discovered_today=kpis.discovered_today,
        winner_projects_this_week=kpis.winner_projects_this_week,
        closed_today=kpis.closed_today,
        changed_tor_projects=kpis.changed_tor_projects,
        crawl_success_rate_percent=kpis.crawl_success_rate_percent,
        failed_runs_recent=kpis.failed_runs_recent,
        crawl_success_window_runs=kpis.crawl_success_window_runs,
    )


def _serialize_recent_run(run: DashboardRecentRunRecord) -> DashboardRecentRunResponse:
    return DashboardRecentRunResponse(
        id=run.id,
        trigger_type=run.trigger_type,
        status=run.status,
        profile_id=run.profile_id,
        started_at=run.started_at,
        finished_at=run.finished_at,
        created_at=run.created_at,
        error_count=run.error_count,
        discovered_projects=run.discovered_projects,
    )


def _serialize_recent_change(
    item: DashboardRecentProjectChangeRecord,
) -> DashboardRecentProjectChangeResponse:
    return DashboardRecentProjectChangeResponse(
        project_id=item.project_id,
        project_name=item.project_name,
        project_state=item.project_state,
        last_changed_at=item.last_changed_at,
    )


def _serialize_winner(item: DashboardWinnerProjectRecord) -> DashboardWinnerProjectResponse:
    return DashboardWinnerProjectResponse(
        project_id=item.project_id,
        project_name=item.project_name,
        project_state=item.project_state,
        awarded_at=item.awarded_at,
    )


def _serialize_daily_point(
    point: DashboardDailyDiscoveryPoint,
) -> DashboardDailyDiscoveryPointResponse:
    return DashboardDailyDiscoveryPointResponse(date=point.date, count=point.count)


def _serialize_state_breakdown(
    point: DashboardStateBreakdownPoint,
) -> DashboardStateBreakdownPointResponse:
    return DashboardStateBreakdownPointResponse(bucket=point.bucket, count=point.count)


def _serialize_cost_summary(summary: SupportCostSummary) -> SupportCostSummaryResponse:
    return SupportCostSummaryResponse(
        window_days=summary.window_days,
        currency=summary.currency,
        estimated_total_thb=summary.estimated_total_thb,
        crawl={
            "estimated_cost_thb": summary.crawl.estimated_cost_thb,
            "run_count": summary.crawl.run_count,
            "task_count": summary.crawl.task_count,
            "failed_run_count": summary.crawl.failed_run_count,
        },
        storage={
            "estimated_cost_thb": summary.storage.estimated_cost_thb,
            "document_count": summary.storage.document_count,
            "total_bytes": summary.storage.total_bytes,
        },
        notifications={
            "estimated_cost_thb": summary.notifications.estimated_cost_thb,
            "sent_count": summary.notifications.sent_count,
            "failed_webhook_delivery_count": summary.notifications.failed_webhook_delivery_count,
        },
        payments={
            "estimated_cost_thb": summary.payments.estimated_cost_thb,
            "billing_record_count": summary.payments.billing_record_count,
            "payment_request_count": summary.payments.payment_request_count,
            "collected_amount_thb": summary.payments.collected_amount_thb,
        },
    )


def _serialize_summary(summary: DashboardSummary) -> DashboardSummaryResponse:
    return DashboardSummaryResponse(
        kpis=_serialize_kpis(summary.kpis),
        recent_runs=[_serialize_recent_run(run) for run in summary.recent_runs],
        recent_changes=[_serialize_recent_change(item) for item in summary.recent_changes],
        winner_projects=[_serialize_winner(item) for item in summary.winner_projects],
        daily_discovery=[_serialize_daily_point(point) for point in summary.daily_discovery],
        project_state_breakdown=[
            _serialize_state_breakdown(point) for point in summary.project_state_breakdown
        ],
        cost_summary=_serialize_cost_summary(summary.cost_summary),
    )


@router.get("/summary", response_model=DashboardSummaryResponse)
def get_dashboard_summary(
    request: Request,
    tenant_id: str | None = None,
) -> DashboardSummaryResponse:
    service = _service_from_request(request)
    resolved_tenant_id = resolve_request_tenant_id(request, tenant_id)
    summary = service.get_summary(tenant_id=resolved_tenant_id)
    return _serialize_summary(summary)
