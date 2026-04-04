"""Project read service for the Phase 1 API surface."""

from __future__ import annotations

from decimal import Decimal

from egp_db.repositories.project_repo import ProjectDetail, ProjectPage, SqlProjectRepository


class ProjectService:
    def __init__(self, repository: SqlProjectRepository) -> None:
        self._repository = repository

    def list_projects(
        self,
        *,
        tenant_id: str,
        project_states: list[str] | None = None,
        procurement_types: list[str] | None = None,
        closed_reasons: list[str] | None = None,
        organization: str | None = None,
        keyword: str | None = None,
        budget_min: Decimal | str | None = None,
        budget_max: Decimal | str | None = None,
        updated_after: str | None = None,
        has_changed_tor: bool | None = None,
        has_winner: bool | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> ProjectPage:
        return self._repository.list_projects(
            tenant_id=tenant_id,
            project_states=project_states,
            procurement_types=procurement_types,
            closed_reasons=closed_reasons,
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

    def get_project_detail(self, *, tenant_id: str, project_id: str) -> ProjectDetail | None:
        return self._repository.get_project_detail(tenant_id=tenant_id, project_id=project_id)
