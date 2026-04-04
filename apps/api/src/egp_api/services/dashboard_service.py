"""Dashboard summary service."""

from __future__ import annotations

from dataclasses import dataclass

from egp_db.repositories.project_repo import (
    DashboardDailyDiscoveryPoint,
    DashboardProjectSummary,
    DashboardRecentProjectChangeRecord,
    DashboardStateBreakdownPoint,
    DashboardWinnerProjectRecord,
    SqlProjectRepository,
)
from egp_db.repositories.run_repo import (
    DashboardRecentRunRecord,
    DashboardRunSummary,
    SqlRunRepository,
)


@dataclass(frozen=True, slots=True)
class DashboardKpis:
    active_projects: int
    discovered_today: int
    winner_projects_this_week: int
    closed_today: int
    changed_tor_projects: int
    crawl_success_rate_percent: float
    failed_runs_recent: int
    crawl_success_window_runs: int


@dataclass(frozen=True, slots=True)
class DashboardSummary:
    kpis: DashboardKpis
    recent_runs: list[DashboardRecentRunRecord]
    recent_changes: list[DashboardRecentProjectChangeRecord]
    winner_projects: list[DashboardWinnerProjectRecord]
    daily_discovery: list[DashboardDailyDiscoveryPoint]
    project_state_breakdown: list[DashboardStateBreakdownPoint]


class DashboardService:
    def __init__(
        self,
        project_repository: SqlProjectRepository,
        run_repository: SqlRunRepository,
    ) -> None:
        self._project_repository = project_repository
        self._run_repository = run_repository

    def get_summary(self, *, tenant_id: str) -> DashboardSummary:
        project_summary: DashboardProjectSummary = (
            self._project_repository.get_dashboard_project_summary(tenant_id=tenant_id)
        )
        run_summary: DashboardRunSummary = self._run_repository.get_dashboard_run_summary(
            tenant_id=tenant_id
        )
        return DashboardSummary(
            kpis=DashboardKpis(
                active_projects=project_summary.active_projects,
                discovered_today=project_summary.discovered_today,
                winner_projects_this_week=project_summary.winner_projects_this_week,
                closed_today=project_summary.closed_today,
                changed_tor_projects=project_summary.changed_tor_projects,
                crawl_success_rate_percent=run_summary.crawl_success_rate_percent,
                failed_runs_recent=run_summary.failed_runs_recent,
                crawl_success_window_runs=run_summary.crawl_success_window_runs,
            ),
            recent_runs=run_summary.recent_runs,
            recent_changes=project_summary.recent_changes,
            winner_projects=project_summary.winner_projects,
            daily_discovery=project_summary.daily_discovery,
            project_state_breakdown=project_summary.project_state_breakdown,
        )
