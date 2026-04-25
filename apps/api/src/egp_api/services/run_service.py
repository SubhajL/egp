"""Run tracking service for the Phase 1 API surface."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from egp_api.services.entitlement_service import TenantEntitlementService
from egp_db.repositories.run_repo import (
    CrawlRunDetail,
    CrawlRunRecord,
    CrawlTaskRecord,
    ProjectCrawlEvidencePage,
    SqlRunRepository,
)
from egp_shared_types.enums import CrawlRunStatus, NotificationType

if TYPE_CHECKING:
    from egp_notifications.dispatcher import NotificationDispatcher


@dataclass(frozen=True, slots=True)
class RunDetailPage:
    items: list[CrawlRunDetail]
    total: int
    limit: int
    offset: int


class RunService:
    def __init__(
        self,
        repository: SqlRunRepository,
        *,
        artifact_root: Path | None = None,
        entitlement_service: TenantEntitlementService | None = None,
        notification_dispatcher: NotificationDispatcher | None = None,
    ) -> None:
        self._repository = repository
        self._artifact_root = artifact_root
        self._entitlement_service = entitlement_service
        self._notification_dispatcher = notification_dispatcher

    def create_run(
        self,
        *,
        tenant_id: str,
        trigger_type: str,
        profile_id: str | None = None,
        summary_json: dict[str, object] | None = None,
    ) -> CrawlRunDetail:
        if self._entitlement_service is not None:
            self._entitlement_service.require_active_subscription(
                tenant_id=tenant_id,
                capability="runs",
            )
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
        if self._entitlement_service is not None:
            self._entitlement_service.require_active_subscription(
                tenant_id=tenant_id,
                capability="runs",
            )
            if task_type.strip().casefold() == "discover":
                self._entitlement_service.require_discover_keyword(
                    tenant_id=tenant_id,
                    keyword=keyword or "",
                )
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
        if self._notification_dispatcher is not None and run.status is CrawlRunStatus.FAILED:
            self._notification_dispatcher.dispatch(
                tenant_id=run.tenant_id,
                notification_type=NotificationType.RUN_FAILED,
                template_vars={
                    "run_id": run.id,
                    "error_count": str(run.error_count),
                },
            )
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

    def list_project_crawl_evidence(
        self,
        *,
        tenant_id: str,
        project_id: str,
        limit: int = 20,
        offset: int = 0,
    ) -> ProjectCrawlEvidencePage:
        return self._repository.list_project_crawl_evidence(
            tenant_id=tenant_id,
            project_id=project_id,
            limit=limit,
            offset=offset,
        )

    def get_run_log(self, *, tenant_id: str, run_id: str) -> str | None:
        run = self._repository.find_run_by_id(run_id)
        if run is None:
            raise KeyError(run_id)
        if run.tenant_id != tenant_id:
            raise PermissionError(run_id)
        if self._artifact_root is None:
            return None
        raw_path = (run.summary_json or {}).get("worker_log_path")
        expected_log_path = (
            self._artifact_root / "tenants" / tenant_id / "runs" / run_id / "worker.log"
        ).resolve()
        if not isinstance(raw_path, str) or not raw_path.strip():
            return None
        log_path = Path(raw_path).resolve()
        if log_path != expected_log_path:
            return None
        if not log_path.is_file():
            return None
        return log_path.read_text(encoding="utf-8", errors="replace")

    def reconcile_missing_workers(self, *, owner_pid: int) -> list[CrawlRunRecord]:
        return self._repository.fail_runs_with_missing_workers(owner_pid=owner_pid)
