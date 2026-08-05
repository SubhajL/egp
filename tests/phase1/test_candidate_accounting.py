"""Tests for durable accepted-candidate accounting (PR-CANARY-03)."""

from __future__ import annotations

from egp_crawler_core.candidate_key import compute_candidate_key
from egp_db.repositories.candidate_attempt_repo import (
    SqlCandidateAttemptRepository,
)


TENANT_ID = "11111111-1111-1111-1111-111111111111"
RUN_ID = "22222222-2222-2222-2222-222222222222"
PROJECT_ID = "33333333-3333-3333-3333-333333333333"


def _create_repo(tmp_path) -> SqlCandidateAttemptRepository:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'candidate-accounting.sqlite3'}"
    return SqlCandidateAttemptRepository(
        database_url=database_url,
        bootstrap_schema=True,
    )


# -- Repository tests -------------------------------------------------------


def test_record_accepted_creates_candidate(tmp_path):
    repo = _create_repo(tmp_path)
    record = repo.record_accepted(
        tenant_id=TENANT_ID,
        run_id=RUN_ID,
        candidate_key="abc123",
        keyword="analytics",
        page_number=1,
        row_ordinal=3,
    )
    assert record.tenant_id == TENANT_ID
    assert record.run_id == RUN_ID
    assert record.candidate_key == "abc123"
    assert record.keyword == "analytics"
    assert record.page_number == 1
    assert record.row_ordinal == 3
    assert record.candidate_status == "accepted"
    assert record.terminal_reason is None
    assert record.project_id is None


def test_finalize_persisted_updates_accepted_candidate(tmp_path):
    repo = _create_repo(tmp_path)
    repo.record_accepted(
        tenant_id=TENANT_ID,
        run_id=RUN_ID,
        candidate_key="abc123",
        keyword="analytics",
    )
    result = repo.finalize_persisted(
        tenant_id=TENANT_ID,
        run_id=RUN_ID,
        candidate_key="abc123",
        project_id=PROJECT_ID,
    )
    assert result is not None
    assert result.candidate_status == "persisted"
    assert result.project_id == PROJECT_ID


def test_finalize_failed_does_not_overwrite_terminal_state(tmp_path):
    repo = _create_repo(tmp_path)
    repo.record_accepted(
        tenant_id=TENANT_ID,
        run_id=RUN_ID,
        candidate_key="abc123",
        keyword="analytics",
    )
    # First finalization succeeds
    result = repo.finalize_persisted(
        tenant_id=TENANT_ID,
        run_id=RUN_ID,
        candidate_key="abc123",
        project_id=PROJECT_ID,
    )
    assert result is not None
    assert result.candidate_status == "persisted"

    # Second finalization with a different terminal state returns None
    second = repo.finalize_failed(
        tenant_id=TENANT_ID,
        run_id=RUN_ID,
        candidate_key="abc123",
        terminal_reason="some error",
    )
    assert second is None

    # Verify original terminal state is preserved
    summary = repo.get_run_candidate_summary(tenant_id=TENANT_ID, run_id=RUN_ID)
    assert summary.persisted == 1
    assert summary.failed == 0


def test_record_accepted_is_idempotent(tmp_path):
    repo = _create_repo(tmp_path)
    first = repo.record_accepted(
        tenant_id=TENANT_ID,
        run_id=RUN_ID,
        candidate_key="abc123",
        keyword="analytics",
        page_number=1,
        row_ordinal=3,
    )
    # Same (tenant_id, run_id, candidate_key) -- should not raise
    second = repo.record_accepted(
        tenant_id=TENANT_ID,
        run_id=RUN_ID,
        candidate_key="abc123",
        keyword="analytics",
        page_number=1,
        row_ordinal=3,
    )
    assert first.id == second.id
    assert first.candidate_status == second.candidate_status

    # Summary shows exactly one row, not two
    summary = repo.get_run_candidate_summary(tenant_id=TENANT_ID, run_id=RUN_ID)
    assert summary.total == 1
    assert summary.accepted == 1


def test_reconcile_open_candidates_marks_accepted_as_unknown(tmp_path):
    repo = _create_repo(tmp_path)
    # Two accepted candidates
    repo.record_accepted(
        tenant_id=TENANT_ID,
        run_id=RUN_ID,
        candidate_key="key1",
        keyword="analytics",
    )
    repo.record_accepted(
        tenant_id=TENANT_ID,
        run_id=RUN_ID,
        candidate_key="key2",
        keyword="analytics",
    )
    # Finalize one as persisted
    repo.finalize_persisted(
        tenant_id=TENANT_ID,
        run_id=RUN_ID,
        candidate_key="key1",
        project_id=PROJECT_ID,
    )

    # Reconcile: only key2 (still accepted) should become unknown
    count = repo.reconcile_open_candidates(run_id=RUN_ID, terminal_reason="worker_lost")
    assert count == 1

    summary = repo.get_run_candidate_summary(tenant_id=TENANT_ID, run_id=RUN_ID)
    assert summary.persisted == 1
    assert summary.unknown == 1
    assert summary.accepted == 0
    assert summary.total == 2


# -- Candidate key tests ----------------------------------------------------


def test_candidate_key_is_deterministic():
    key1 = compute_candidate_key(
        keyword="analytics",
        page_number=1,
        row_ordinal=3,
        project_name="Test Project",
    )
    key2 = compute_candidate_key(
        keyword="analytics",
        page_number=1,
        row_ordinal=3,
        project_name="Test Project",
    )
    assert key1 == key2
    assert len(key1) == 64  # SHA-256 hex digest


def test_candidate_key_differs_for_different_inputs():
    key_a = compute_candidate_key(
        keyword="analytics",
        page_number=1,
        row_ordinal=3,
        project_name="Project A",
    )
    key_b = compute_candidate_key(
        keyword="analytics",
        page_number=1,
        row_ordinal=3,
        project_name="Project B",
    )
    assert key_a != key_b

    # Also different when keyword changes
    key_c = compute_candidate_key(
        keyword="procurement",
        page_number=1,
        row_ordinal=3,
        project_name="Project A",
    )
    assert key_a != key_c

    # Also different when page changes
    key_d = compute_candidate_key(
        keyword="analytics",
        page_number=2,
        row_ordinal=3,
        project_name="Project A",
    )
    assert key_a != key_d
