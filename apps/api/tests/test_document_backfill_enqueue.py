"""TDD: targeted document backfill enqueuer for Track C discovery jobs."""

from __future__ import annotations

from types import SimpleNamespace

from egp_api.executors.document_backfill_enqueue import (
    enqueue_document_backfill_jobs,
    main,
)
from egp_db.repositories.document_capture_attempt_repo import (
    DocumentCaptureBackfillCandidate,
)
from egp_shared_types.enums import DocumentCaptureAttemptStatus


TENANT_ID = "11111111-1111-1111-1111-111111111111"
PROJECT_ID = "22222222-2222-2222-2222-222222222222"
PROFILE_ID = "33333333-3333-3333-3333-333333333333"


class _FakeCaptureRepository:
    def __init__(self, candidates: list[DocumentCaptureBackfillCandidate]) -> None:
        self.candidates = candidates
        self.recorded_attempts: list[dict[str, object]] = []
        self.requested: dict[str, object] | None = None

    def list_due_backfill_candidates(self, **kwargs):
        self.requested = kwargs
        return list(self.candidates)

    def record_attempt(self, **kwargs):
        self.recorded_attempts.append(kwargs)
        return SimpleNamespace(id=f"attempt-{len(self.recorded_attempts)}", **kwargs)


class _FakeDiscoveryJobRepository:
    def __init__(self, *, created: bool = True) -> None:
        self.created = created
        self.calls: list[dict[str, object]] = []

    def create_pending_discovery_job_if_absent(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(job=SimpleNamespace(id="job-1"), created=self.created)


def _candidate(project_number: str = "69049163846") -> DocumentCaptureBackfillCandidate:
    return DocumentCaptureBackfillCandidate(
        tenant_id=TENANT_ID,
        project_id=PROJECT_ID,
        project_number=project_number,
        project_state="open_invitation",
        proposal_submission_date="2026-06-08",
        profile_id=PROFILE_ID,
        profile_type="custom",
        attempt_count=0,
        latest_attempted_at=None,
        target_document_count=0,
    )


def test_enqueue_creates_project_number_backfill_job() -> None:
    capture_repository = _FakeCaptureRepository([_candidate()])
    discovery_repository = _FakeDiscoveryJobRepository(created=True)

    summary = enqueue_document_backfill_jobs(
        database_url="postgresql://example.test/egp",
        capture_attempt_repository=capture_repository,
        discovery_job_repository=discovery_repository,
        now="2026-06-07T00:00:00+00:00",
    )

    assert discovery_repository.calls == [
        {
            "tenant_id": TENANT_ID,
            "profile_id": PROFILE_ID,
            "profile_type": "custom",
            "keyword": "69049163846",
            "trigger_type": "backfill",
            "live": True,
        }
    ]
    assert capture_repository.recorded_attempts[0]["status"] is (
        DocumentCaptureAttemptStatus.ENQUEUED
    )
    assert capture_repository.recorded_attempts[0]["reason"] == "backfill_job_created"
    assert summary == {
        "candidate_count": 1,
        "enqueued_count": 1,
        "created_count": 1,
        "skipped_count": 0,
    }


def test_enqueue_forwards_retry_policy_knobs() -> None:
    capture_repository = _FakeCaptureRepository([])
    discovery_repository = _FakeDiscoveryJobRepository(created=True)

    enqueue_document_backfill_jobs(
        database_url="postgresql://example.test/egp",
        capture_attempt_repository=capture_repository,
        discovery_job_repository=discovery_repository,
        now="2026-06-07T00:00:00+00:00",
        enqueued_stale_after_seconds=7200,
        no_documents_retry_seconds=43200,
        no_documents_max_age_days=14,
    )

    assert capture_repository.requested is not None
    assert capture_repository.requested["enqueued_stale_after_seconds"] == 7200
    assert capture_repository.requested["no_documents_retry_seconds"] == 43200
    assert capture_repository.requested["no_documents_max_age_days"] == 14


def test_enqueue_does_not_record_attempt_for_existing_pending_job() -> None:
    capture_repository = _FakeCaptureRepository([_candidate()])
    discovery_repository = _FakeDiscoveryJobRepository(created=False)

    summary = enqueue_document_backfill_jobs(
        database_url="postgresql://example.test/egp",
        capture_attempt_repository=capture_repository,
        discovery_job_repository=discovery_repository,
    )

    assert len(discovery_repository.calls) == 1
    assert capture_repository.recorded_attempts == []
    assert summary["enqueued_count"] == 1
    assert summary["created_count"] == 0


def test_main_runs_backfill_enqueue_once() -> None:
    seen: dict[str, object] = {}

    def _fake_enqueue(**kwargs):
        seen.update(kwargs)
        return {
            "candidate_count": 2,
            "enqueued_count": 2,
            "created_count": 1,
            "skipped_count": 0,
        }

    code = main(
        [
            "--database-url",
            "postgresql://example.test/egp",
            "--limit",
            "25",
            "--max-attempts",
            "4",
        ],
        enqueue=_fake_enqueue,
    )

    assert code == 0
    assert seen["database_url"] == "postgresql://example.test/egp"
    assert seen["limit"] == 25
    assert seen["max_attempts"] == 4


def test_main_forwards_retry_policy_cli_flags() -> None:
    seen: dict[str, object] = {}

    def _fake_enqueue(**kwargs):
        seen.update(kwargs)
        return {
            "candidate_count": 0,
            "enqueued_count": 0,
            "created_count": 0,
            "skipped_count": 0,
        }

    code = main(
        [
            "--database-url",
            "postgresql://example.test/egp",
            "--enqueued-stale-after-seconds",
            "7200",
            "--no-documents-retry-seconds",
            "43200",
            "--no-documents-max-age-days",
            "14",
        ],
        enqueue=_fake_enqueue,
    )

    assert code == 0
    assert seen["enqueued_stale_after_seconds"] == 7200
    assert seen["no_documents_retry_seconds"] == 43200
    assert seen["no_documents_max_age_days"] == 14
