"""Run tracking service for the Phase 1 API surface."""

from __future__ import annotations

from dataclasses import dataclass
import logging
from pathlib import Path
from typing import TYPE_CHECKING

from egp_api.services.entitlement_service import EntitlementError, TenantEntitlementService
from egp_db.abnormal_run_completion import complete_abnormal_run
from egp_db.repositories.run_repo import (
    CrawlRunDetail,
    CrawlRunRecord,
    CrawlTaskRecord,
    ProjectCrawlEvidencePage,
    SqlRunRepository,
)
from egp_db.repositories.candidate_attempt_repo import create_candidate_attempt_repository
from egp_observability.subprocess_evidence import (
    build_run_log_path,
    read_bounded_redacted_log,
)
from egp_shared_types.enums import CandidateTerminalReason, CrawlRunStatus, NotificationType

if TYPE_CHECKING:
    from egp_db.repositories.profile_repo import SqlProfileRepository
    from egp_db.repositories.project_repo import SqlProjectRepository
    from egp_notifications.dispatcher import NotificationDispatcher


logger = logging.getLogger(__name__)


def _candidate_reason_for_terminal_run(run: CrawlRunRecord) -> str:
    failure_reason = str((run.summary_json or {}).get("failure_reason") or "")
    return {
        "worker_timeout": CandidateTerminalReason.WORKER_TIMEOUT.value,
        "worker_terminated": CandidateTerminalReason.WORKER_TERMINATED.value,
        "lease_lost": CandidateTerminalReason.LEASE_LOST.value,
    }.get(failure_reason, CandidateTerminalReason.WORKER_LOST.value)


class _UnavailableCandidateRepository:
    def __init__(self, error: Exception) -> None:
        self._error = error

    def reconcile_open_candidates(self, **_kwargs: object) -> int:
        raise self._error

    def list_open_candidate_runs(self, *, limit: int = 100) -> list[tuple[str, str]]:
        del limit
        raise self._error


@dataclass(frozen=True, slots=True)
class RunDetailPage:
    items: list[CrawlRunDetail]
    total: int
    limit: int
    offset: int


class RunProjectNotFoundError(LookupError):
    """Raised when a task project is absent from the run tenant."""


class RunProfileNotFoundError(LookupError):
    """Raised when a run profile is absent from the run tenant."""


class RunService:
    def __init__(
        self,
        repository: SqlRunRepository,
        *,
        project_repository: SqlProjectRepository | None = None,
        profile_repository: SqlProfileRepository | None = None,
        artifact_root: Path | None = None,
        database_url: str | None = None,
        entitlement_service: TenantEntitlementService | None = None,
        notification_dispatcher: NotificationDispatcher | None = None,
    ) -> None:
        self._repository = repository
        self._project_repository = project_repository
        self._profile_repository = profile_repository
        self._artifact_root = artifact_root
        self._database_url = database_url
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
        if profile_id is not None:
            if self._profile_repository is None:
                raise RunProfileNotFoundError(profile_id)
            profile = self._profile_repository.get_profile_detail(
                tenant_id=tenant_id,
                profile_id=profile_id,
            )
            if profile is None:
                raise RunProfileNotFoundError(profile_id)
        if self._entitlement_service is not None:
            snapshot = self._entitlement_service.require_active_subscription(
                tenant_id=tenant_id,
                capability="runs",
            )
            if snapshot.over_keyword_limit:
                raise EntitlementError("active keyword configuration exceeds plan limit")
            if snapshot.active_keyword_count == 0:
                raise EntitlementError("at least one active keyword is required for runs")
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
        run = self._repository.find_run_by_id_for_tenant(
            tenant_id=tenant_id,
            run_id=run_id,
        )
        if run is None:
            raise KeyError(run_id)
        if project_id is not None:
            if self._project_repository is None:
                raise RunProjectNotFoundError(project_id)
            project = self._project_repository.get_project(
                tenant_id=tenant_id,
                project_id=project_id,
            )
            if project is None:
                raise RunProjectNotFoundError(project_id)
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
        run_before = self._repository.find_run_by_id_for_tenant(
            tenant_id=tenant_id,
            run_id=run_id,
        )
        if run_before is None:
            raise KeyError(run_id)
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
        run = self._repository.find_run_by_id_for_tenant(
            tenant_id=tenant_id,
            run_id=run_id,
        )
        if run is None:
            raise KeyError(run_id)
        if self._artifact_root is None:
            return None
        raw_path = (run.summary_json or {}).get("worker_log_path")
        expected_log_path = build_run_log_path(
            artifact_root=self._artifact_root,
            tenant_id=tenant_id,
            run_id=run_id,
        )
        if not isinstance(raw_path, str) or not raw_path.strip():
            return None
        for log_path in _resolve_run_log_candidates(raw_path, artifact_root=self._artifact_root):
            if log_path != expected_log_path:
                continue
            if not log_path.is_file():
                return None
            return read_bounded_redacted_log(log_path)
        return None

    def reconcile_missing_workers(self, *, owner_pid: int) -> list[CrawlRunRecord]:
        failed_runs = self._repository.fail_runs_with_missing_workers(owner_pid=owner_pid)
        if self._database_url is None:
            return failed_runs
        try:
            candidate_repository = create_candidate_attempt_repository(
                database_url=self._database_url,
            )
        except Exception as exc:  # preserve per-run terminalization/reporting
            candidate_repository = _UnavailableCandidateRepository(exc)
        newly_failed_keys = {(run.tenant_id, run.id) for run in failed_runs}
        for run in failed_runs:
            report = complete_abnormal_run(
                tenant_id=run.tenant_id,
                run_id=run.id,
                failure_code="worker_lost",
                candidate_reason=_candidate_reason_for_terminal_run(run),
                error=f"discover worker for run {run.id} disappeared before completion",
                candidate_repository=candidate_repository,
                run_repository=self._repository,
            )
            if not report.succeeded:
                logger.error(
                    "Missing-worker abnormal completion incomplete "
                    "(tenant_id=%s run_id=%s candidate_error=%s run_error=%s)",
                    run.tenant_id,
                    run.id,
                    report.candidate_reconciliation_error_type,
                    report.run_terminalization_error_type,
                )
                try:
                    self._repository.update_run_summary(
                        run.id,
                        summary_json={"abnormal_completion": report.evidence()},
                    )
                except Exception:
                    logger.exception(
                        "Failed to persist incomplete abnormal completion (tenant_id=%s run_id=%s)",
                        run.tenant_id,
                        run.id,
                    )
        try:
            open_candidate_runs = candidate_repository.list_open_candidate_runs(limit=100)
        except Exception:
            logger.exception("Failed to enumerate accepted candidates needing repair")
            open_candidate_runs = []
        for tenant_id, run_id in open_candidate_runs:
            if (tenant_id, run_id) in newly_failed_keys:
                continue
            run = self._repository.find_run_by_id_for_tenant(
                tenant_id=tenant_id,
                run_id=run_id,
            )
            if run is None or run.status not in {
                CrawlRunStatus.FAILED,
                CrawlRunStatus.CANCELLED,
            }:
                continue
            report = complete_abnormal_run(
                tenant_id=tenant_id,
                run_id=run_id,
                failure_code="worker_lost",
                candidate_reason=_candidate_reason_for_terminal_run(run),
                error=f"retrying incomplete candidate cleanup for run {run_id}",
                candidate_repository=candidate_repository,
                run_repository=self._repository,
            )
            if report.succeeded:
                continue
            logger.error(
                "Terminal-run candidate cleanup remains incomplete "
                "(tenant_id=%s run_id=%s candidate_error=%s run_error=%s)",
                tenant_id,
                run_id,
                report.candidate_reconciliation_error_type,
                report.run_terminalization_error_type,
            )
        return failed_runs


def _resolve_run_log_candidates(raw_path: str, *, artifact_root: Path) -> list[Path]:
    raw = Path(raw_path.strip())
    candidates: list[Path] = [raw.resolve()]

    parts = raw.parts
    if "tenants" not in parts:
        return candidates

    tenant_index = parts.index("tenants")
    candidates.append((artifact_root / Path(*parts[tenant_index:])).resolve())
    return candidates
