"""Tests for shared tenant-scoped abnormal run completion."""

from __future__ import annotations

from dataclasses import replace

import pytest

from egp_db.abnormal_run_completion import complete_abnormal_run
from egp_db.repositories.run_repo import CrawlRunRecord
from egp_shared_types.enums import CrawlRunStatus


TENANT_ID = "11111111-1111-1111-1111-111111111111"
RUN_ID = "22222222-2222-2222-2222-222222222222"


def _run(status: CrawlRunStatus) -> CrawlRunRecord:
    return CrawlRunRecord(
        id=RUN_ID,
        tenant_id=TENANT_ID,
        trigger_type="manual",
        status=status,
        profile_id=None,
        discovery_job_id=None,
        recrawl_request_id=None,
        started_at=None,
        finished_at=None,
        last_activity_at="2026-08-16T00:00:00+00:00",
        summary_json=None,
        error_count=0,
        created_at="2026-08-16T00:00:00+00:00",
    )


class CandidateRepo:
    def __init__(self, *, error: Exception | None = None) -> None:
        self.error = error
        self.calls: list[dict[str, str]] = []

    def reconcile_open_candidates(self, **kwargs) -> int:
        self.calls.append(dict(kwargs))
        if self.error is not None:
            raise self.error
        return 3


class RunRepo:
    def __init__(self, *, error: Exception | None = None) -> None:
        self.error = error
        self.fail_calls: list[dict[str, str]] = []
        self.current = _run(CrawlRunStatus.RUNNING)

    def fail_run_if_active(self, **kwargs) -> CrawlRunRecord | None:
        self.fail_calls.append(dict(kwargs))
        if self.error is not None:
            raise self.error
        self.current = replace(self.current, status=CrawlRunStatus.FAILED)
        return self.current

    def find_run_by_id_for_tenant(self, **kwargs) -> CrawlRunRecord | None:
        assert kwargs == {"tenant_id": TENANT_ID, "run_id": RUN_ID}
        return self.current


def test_complete_abnormal_run_attempts_both_operations() -> None:
    candidates = CandidateRepo(error=RuntimeError("candidate write unavailable"))
    runs = RunRepo()

    report = complete_abnormal_run(
        tenant_id=TENANT_ID,
        run_id=RUN_ID,
        failure_code="worker_exit_nonzero",
        candidate_reason="worker_lost",
        error="worker exited nonzero",
        candidate_repository=candidates,
        run_repository=runs,
    )

    assert candidates.calls == [
        {
            "tenant_id": TENANT_ID,
            "run_id": RUN_ID,
            "terminal_reason": "worker_lost",
        }
    ]
    assert runs.fail_calls == [
        {
            "tenant_id": TENANT_ID,
            "run_id": RUN_ID,
            "error": "worker exited nonzero",
            "failure_reason": "worker_exit_nonzero",
        }
    ]
    assert report.candidate_reconciliation_succeeded is False
    assert report.candidate_reconciliation_error_type == "RuntimeError"
    assert report.run_terminalized is True
    assert report.succeeded is False


@pytest.mark.parametrize(
    "terminal_status",
    [
        CrawlRunStatus.FAILED,
        CrawlRunStatus.CANCELLED,
        CrawlRunStatus.SUCCEEDED,
        CrawlRunStatus.PARTIAL,
    ],
)
def test_complete_abnormal_run_reports_terminal_status(
    terminal_status: CrawlRunStatus,
) -> None:
    candidates = CandidateRepo()
    runs = RunRepo()
    runs.current = _run(terminal_status)
    runs.fail_run_if_active = lambda **kwargs: None  # type: ignore[method-assign]

    report = complete_abnormal_run(
        tenant_id=TENANT_ID,
        run_id=RUN_ID,
        failure_code="worker_lost",
        candidate_reason="worker_lost",
        error="worker lost",
        candidate_repository=candidates,
        run_repository=runs,
    )

    assert report.run_terminalized is False
    assert report.run_already_terminal is True
    assert report.succeeded is True
    if terminal_status in {CrawlRunStatus.SUCCEEDED, CrawlRunStatus.PARTIAL}:
        assert candidates.calls == []
        assert report.reconciled_candidate_count == 0
    else:
        assert len(candidates.calls) == 1
        assert report.reconciled_candidate_count == 3


@pytest.mark.parametrize(
    "terminal_status",
    [CrawlRunStatus.SUCCEEDED, CrawlRunStatus.PARTIAL],
)
def test_failed_terminal_write_reads_back_success_before_candidate_reconciliation(
    terminal_status: CrawlRunStatus,
) -> None:
    candidates = CandidateRepo()
    runs = RunRepo(error=RuntimeError("terminal write unavailable"))
    runs.current = _run(terminal_status)

    report = complete_abnormal_run(
        tenant_id=TENANT_ID,
        run_id=RUN_ID,
        failure_code="worker_lost",
        candidate_reason="worker_lost",
        error="worker lost",
        candidate_repository=candidates,
        run_repository=runs,
    )

    assert candidates.calls == []
    assert report.run_already_terminal is True
    assert report.reconciled_candidate_count == 0


def test_unconfirmed_terminal_status_never_reconciles_candidates() -> None:
    candidates = CandidateRepo()
    runs = RunRepo(error=RuntimeError("terminal write unavailable"))
    runs.find_run_by_id_for_tenant = (  # type: ignore[method-assign]
        lambda **kwargs: (_ for _ in ()).throw(RuntimeError("read unavailable"))
    )

    report = complete_abnormal_run(
        tenant_id=TENANT_ID,
        run_id=RUN_ID,
        failure_code="worker_lost",
        candidate_reason="worker_lost",
        error="worker lost",
        candidate_repository=candidates,
        run_repository=runs,
    )

    assert candidates.calls == []
    assert report.run_terminalized is False
    assert report.run_already_terminal is False
    assert report.candidate_reconciliation_succeeded is False
