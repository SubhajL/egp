"""Project read service for the Phase 1 API surface."""

from __future__ import annotations

from egp_db.repositories.project_repo import ProjectDetail, ProjectPage, SqlProjectRepository


class ProjectService:
    def __init__(self, repository: SqlProjectRepository) -> None:
        self._repository = repository

    def list_projects(
        self,
        *,
        tenant_id: str,
        project_state: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> ProjectPage:
        return self._repository.list_projects(
            tenant_id=tenant_id,
            project_state=project_state,
            limit=limit,
            offset=offset,
        )

    def get_project_detail(self, *, tenant_id: str, project_id: str) -> ProjectDetail | None:
        return self._repository.get_project_detail(tenant_id=tenant_id, project_id=project_id)
