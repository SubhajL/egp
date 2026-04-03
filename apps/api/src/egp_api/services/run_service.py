"""Run tracking service for the Phase 1 API surface."""

from __future__ import annotations

from dataclasses import dataclass

from egp_db.repositories.run_repo import CrawlRunDetail, CrawlTaskRecord, SqlRunRepository


@dataclass(frozen=True, slots=True)
class RunDetailPage:
    items: list[CrawlRunDetail]
    total: int
    limit: int
    offset: int


class RunService:
    def __init__(self, repository: SqlRunRepository) -> None:
        self._repository = repository

    def create_run(
        self,
        *,
        tenant_id: str,
        trigger_type: str,
        profile_id: str | None = None,
        summary_json: dict[str, object] | None = None,
    ) -> CrawlRunDetail:
        run = self._repository.create_run(
            tenant_id=tenant_id,
            trigger_type=trigger_type,
            profile_id=profile_id,
            summary_json=summary_json,
        )
        detail = self._repository.get_run_detail(tenant_id=tenant_id, run_id=run.id)
        if detail is None:
            raise KeyError(run.id)
        return detail

    def create_task(
        self,
        *,
        tenant_id: str,
        run_id: str,
        task_type: str,
        project_id: str | None = None,
        keyword: str | None = None,
        payload: dict[str, object] | None = None,
    ) -> CrawlTaskRecord:
        run = self._repository.find_run_by_id(run_id)
        if run is None:
            raise KeyError(run_id)
        if run.tenant_id != tenant_id:
            raise PermissionError(run_id)
        task = self._repository.create_task(
            run_id=run_id,
            task_type=task_type,
            project_id=project_id,
            keyword=keyword,
            payload=payload,
        )
        return task

    def finish_run(
        self,
        *,
        tenant_id: str,
        run_id: str,
        status: str,
        summary_json: dict[str, object] | None = None,
        error_count: int = 0,
    ) -> CrawlRunDetail:
        run_before = self._repository.find_run_by_id(run_id)
        if run_before is None:
            raise KeyError(run_id)
        if run_before.tenant_id != tenant_id:
            raise PermissionError(run_id)
        if run_before.started_at is None:
            self._repository.mark_run_started(run_id)
        run = self._repository.mark_run_finished(
            run_id,
            status=status,
            summary_json=summary_json,
            error_count=error_count,
        )
        detail = self._repository.get_run_detail(tenant_id=run.tenant_id, run_id=run.id)
        if detail is None:
            raise KeyError(run.id)
        return detail

    def list_runs(self, *, tenant_id: str, limit: int = 50, offset: int = 0) -> RunDetailPage:
        run_page = self._repository.list_runs(tenant_id=tenant_id, limit=limit, offset=offset)
        details: list[CrawlRunDetail] = []
        for run in run_page.items:
            detail = self._repository.get_run_detail(tenant_id=tenant_id, run_id=run.id)
            if detail is not None:
                details.append(detail)
        return RunDetailPage(
            items=details,
            total=run_page.total,
            limit=run_page.limit,
            offset=run_page.offset,
        )
