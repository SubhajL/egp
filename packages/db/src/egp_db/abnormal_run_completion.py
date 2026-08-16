"""Tenant-scoped completion of abnormal discovery runs."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from egp_db.repositories.run_repo import CrawlRunRecord


class CandidateReconciliationRepository(Protocol):
    def reconcile_open_candidates(
        self,
        *,
        tenant_id: str,
        run_id: str,
        terminal_reason: str,
    ) -> int: ...


class ActiveRunFailureRepository(Protocol):
    def fail_run_if_active(
        self,
        *,
        tenant_id: str,
        run_id: str,
        error: str,
        failure_reason: str,
    ) -> CrawlRunRecord | None: ...

    def find_run_by_id_for_tenant(
        self,
        *,
        tenant_id: str,
        run_id: str,
    ) -> CrawlRunRecord | None: ...


@dataclass(frozen=True, slots=True)
class AbnormalRunCompletionReport:
    tenant_id: str
    run_id: str
    candidate_reconciliation_succeeded: bool
    reconciled_candidate_count: int | None
    candidate_reconciliation_error_type: str | None
    run_terminalized: bool
    run_already_terminal: bool
    run_terminalization_error_type: str | None

    @property
    def succeeded(self) -> bool:
        return self.candidate_reconciliation_succeeded and (
            self.run_terminalized or self.run_already_terminal
        )

    def evidence(self) -> dict[str, object]:
        """Return bounded, secret-free fields suitable for durable diagnostics."""

        return {
            "succeeded": self.succeeded,
            "candidate_reconciliation_succeeded": (
                self.candidate_reconciliation_succeeded
            ),
            "reconciled_candidate_count": self.reconciled_candidate_count,
            "candidate_reconciliation_error_type": (
                self.candidate_reconciliation_error_type
            ),
            "run_terminalized": self.run_terminalized,
            "run_already_terminal": self.run_already_terminal,
            "run_terminalization_error_type": self.run_terminalization_error_type,
        }


def complete_abnormal_run(
    *,
    tenant_id: str,
    run_id: str,
    failure_code: str,
    candidate_reason: str,
    error: str,
    candidate_repository: CandidateReconciliationRepository,
    run_repository: ActiveRunFailureRepository,
) -> AbnormalRunCompletionReport:
    """Reconcile candidates and terminalize one abnormal tenant/run.

    Each durable operation is attempted independently. A reconciliation outage
    must not prevent the run row from becoming terminal, and a run-write outage
    must not erase successful candidate reconciliation evidence.
    """

    reconciled_count: int | None = None
    candidate_error_type: str | None = None
    try:
        reconciled_count = candidate_repository.reconcile_open_candidates(
            tenant_id=tenant_id,
            run_id=run_id,
            terminal_reason=candidate_reason,
        )
    except Exception as exc:  # noqa: BLE001 - the report preserves independent cleanup
        candidate_error_type = type(exc).__name__

    failed_run: CrawlRunRecord | None = None
    run_error_type: str | None = None
    try:
        failed_run = run_repository.fail_run_if_active(
            tenant_id=tenant_id,
            run_id=run_id,
            error=error,
            failure_reason=failure_code,
        )
    except Exception as exc:  # noqa: BLE001 - candidate cleanup already happened
        run_error_type = type(exc).__name__

    run_already_terminal = False
    if failed_run is None and run_error_type is None:
        try:
            current_run = run_repository.find_run_by_id_for_tenant(
                tenant_id=tenant_id,
                run_id=run_id,
            )
            run_already_terminal = current_run is not None and current_run.status.value in {
                "failed",
                "cancelled",
            }
        except Exception as exc:  # noqa: BLE001 - report the read failure without raising
            run_error_type = type(exc).__name__

    return AbnormalRunCompletionReport(
        tenant_id=tenant_id,
        run_id=run_id,
        candidate_reconciliation_succeeded=candidate_error_type is None,
        reconciled_candidate_count=reconciled_count,
        candidate_reconciliation_error_type=candidate_error_type,
        run_terminalized=failed_run is not None,
        run_already_terminal=run_already_terminal,
        run_terminalization_error_type=run_error_type,
    )
