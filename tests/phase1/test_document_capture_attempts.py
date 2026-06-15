from __future__ import annotations

from datetime import UTC, datetime, timedelta

from egp_db.artifact_store import LocalArtifactStore
from egp_db.repositories.document_capture_attempt_repo import (
    SqlDocumentCaptureAttemptRepository,
)
from egp_db.repositories.document_repo import SqlDocumentRepository
from egp_db.repositories.profile_repo import create_profile_repository
from egp_db.repositories.project_repo import (
    SqlProjectRepository,
    build_project_upsert_record,
)
from egp_shared_types.enums import (
    DocumentCaptureAttemptStatus,
    DocumentCaptureReason,
    ProcurementType,
    ProjectState,
)


TENANT_ID = "11111111-1111-1111-1111-111111111111"
SECOND_TENANT_ID = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
NOW = datetime(2026, 6, 7, 9, 0, tzinfo=UTC)


def _create_repositories(tmp_path):
    database_url = f"sqlite+pysqlite:///{tmp_path / 'capture-attempts.sqlite3'}"
    project_repository = SqlProjectRepository(
        database_url=database_url,
        bootstrap_schema=True,
    )
    document_repository = SqlDocumentRepository(
        database_url=database_url,
        artifact_store=LocalArtifactStore(tmp_path / "artifacts"),
        bootstrap_schema=False,
    )
    profile_repository = create_profile_repository(
        database_url=database_url,
        bootstrap_schema=True,
    )
    capture_repository = SqlDocumentCaptureAttemptRepository(
        database_url=database_url,
        bootstrap_schema=True,
    )
    return (
        database_url,
        project_repository,
        document_repository,
        profile_repository,
        capture_repository,
    )


def _create_profile(
    profile_repository, *, tenant_id: str = TENANT_ID, active: bool = True
):
    return profile_repository.create_profile(
        tenant_id=tenant_id,
        name="Watchlist",
        profile_type="custom",
        is_active=active,
        max_pages_per_keyword=7,
        close_consulting_after_days=30,
        close_stale_after_days=45,
        keywords=["analytics"],
    ).profile


def _create_project(
    project_repository: SqlProjectRepository,
    *,
    tenant_id: str = TENANT_ID,
    project_number: str = "69049163846",
    project_state: ProjectState = ProjectState.OPEN_INVITATION,
    proposal_submission_date: str | None = "2026-06-08",
):
    return project_repository.upsert_project(
        build_project_upsert_record(
            tenant_id=tenant_id,
            project_number=project_number,
            search_name=f"search {project_number}",
            detail_name=f"detail {project_number}",
            project_name=f"project {project_number}",
            organization_name="กรมตัวอย่าง",
            proposal_submission_date=proposal_submission_date,
            budget_amount="1000.00",
            procurement_type=ProcurementType.SERVICES,
            project_state=project_state,
        ),
        source_status_text="หนังสือเชิญชวน/ประกาศเชิญชวน",
    )


def test_lists_due_backfill_candidate_for_zero_invitation_tor_docs(tmp_path) -> None:
    _, project_repository, _, profile_repository, capture_repository = (
        _create_repositories(tmp_path)
    )
    profile = _create_profile(profile_repository)
    project = _create_project(project_repository)

    candidates = capture_repository.list_due_backfill_candidates(now=NOW, limit=10)

    assert [
        (candidate.project_id, candidate.project_number) for candidate in candidates
    ] == [(project.id, project.project_number)]
    assert candidates[0].profile_id == profile.id
    assert candidates[0].profile_type == "custom"
    assert candidates[0].attempt_count == 0
    assert candidates[0].target_document_count == 0


def test_candidate_selection_ignores_other_doc_types(tmp_path) -> None:
    (
        _,
        project_repository,
        document_repository,
        profile_repository,
        capture_repository,
    ) = _create_repositories(tmp_path)
    _create_profile(profile_repository)
    project = _create_project(project_repository)
    document_repository.store_document(
        tenant_id=TENANT_ID,
        project_id=project.id,
        file_name="memo.txt",
        file_bytes=b"memo",
        source_label="บันทึกอื่น",
        source_status_text="",
    )

    candidates = capture_repository.list_due_backfill_candidates(now=NOW, limit=10)

    assert [candidate.project_id for candidate in candidates] == [project.id]


def test_candidate_selection_skips_invitation_or_tor_docs(tmp_path) -> None:
    (
        _,
        project_repository,
        document_repository,
        profile_repository,
        capture_repository,
    ) = _create_repositories(tmp_path)
    _create_profile(profile_repository)
    project = _create_project(project_repository)
    document_repository.store_document(
        tenant_id=TENANT_ID,
        project_id=project.id,
        file_name="invite.pdf",
        file_bytes=b"invite",
        source_label="ประกาศเชิญชวน",
        source_status_text="หนังสือเชิญชวน/ประกาศเชิญชวน",
    )

    assert capture_repository.list_due_backfill_candidates(now=NOW, limit=10) == []


def _record(capture_repository, project, status, *, ago, reason="x"):
    capture_repository.record_attempt(
        tenant_id=TENANT_ID,
        project_id=project.id,
        status=status,
        reason=reason,
        doc_count=0,
        attempted_at=NOW - ago,
    )


def _due_project_ids(capture_repository, *, now=NOW, **kwargs):
    return [
        c.project_id
        for c in capture_repository.list_due_backfill_candidates(now=now, limit=10, **kwargs)
    ]


def test_retry_cap_counts_only_terminal_attempts_not_enqueued(tmp_path) -> None:
    # P1a: many enqueued (non-terminal) attempts must NOT burn the retry cap.
    _, project_repository, _, profile_repository, capture_repository = (
        _create_repositories(tmp_path)
    )
    _create_profile(profile_repository)
    project = _create_project(project_repository)
    for index in range(5):
        _record(
            capture_repository,
            project,
            DocumentCaptureAttemptStatus.ENQUEUED,
            ago=timedelta(hours=4 + index),  # all stale (>3h) so no throttle
        )

    assert _due_project_ids(capture_repository, max_attempts=3) == [project.id]


def test_recent_enqueued_throttles_then_stale_enqueued_reenqueues(tmp_path) -> None:
    # P1a: a fresh enqueued throttles; once past the stale horizon it no longer does.
    _, project_repository, _, profile_repository, capture_repository = (
        _create_repositories(tmp_path)
    )
    _create_profile(profile_repository)
    project = _create_project(project_repository)
    _record(capture_repository, project, DocumentCaptureAttemptStatus.ENQUEUED, ago=timedelta(minutes=30))

    assert _due_project_ids(capture_repository, enqueued_stale_after_seconds=10800) == []

    # Same row is now 4h old (> 3h horizon) → no longer throttles.
    assert _due_project_ids(
        capture_repository,
        now=NOW + timedelta(hours=4),
        enqueued_stale_after_seconds=10800,
    ) == [project.id]


def test_terminal_after_enqueued_clears_throttle(tmp_path) -> None:
    # P1a: a terminal outcome after the enqueued supersedes the throttle.
    _, project_repository, _, profile_repository, capture_repository = (
        _create_repositories(tmp_path)
    )
    _create_profile(profile_repository)
    project = _create_project(project_repository)
    _record(capture_repository, project, DocumentCaptureAttemptStatus.ENQUEUED, ago=timedelta(hours=2))
    _record(capture_repository, project, DocumentCaptureAttemptStatus.FAILED, ago=timedelta(hours=1, minutes=30))

    # transient: 1 terminal < cap, backoff 1h elapsed (90m) → due.
    assert _due_project_ids(capture_repository) == [project.id]


def test_no_documents_uses_daily_cadence_not_count_cap(tmp_path) -> None:
    # P1b: no_documents retries once/day and ignores the transient attempt cap.
    _, project_repository, _, profile_repository, capture_repository = (
        _create_repositories(tmp_path)
    )
    _create_profile(profile_repository)
    fresh = _create_project(project_repository, project_number="69049163851")
    daily_due = _create_project(project_repository, project_number="69049163852")
    _record(capture_repository, fresh, DocumentCaptureAttemptStatus.NO_DOCUMENTS, ago=timedelta(hours=12))
    for index in range(5):  # 5 > max_attempts=3, but no_documents ignores the count cap
        _record(
            capture_repository,
            daily_due,
            DocumentCaptureAttemptStatus.NO_DOCUMENTS,
            ago=timedelta(hours=25 + index * 24),
        )

    assert _due_project_ids(capture_repository, max_attempts=3) == [daily_due.id]


def test_no_documents_stops_after_30_day_cap_when_deadline_unknown(tmp_path) -> None:
    # P1b: with no proposal deadline, no_documents stops after the 30-day horizon.
    _, project_repository, _, profile_repository, capture_repository = (
        _create_repositories(tmp_path)
    )
    _create_profile(profile_repository)
    project = _create_project(
        project_repository, project_number="69049163853", proposal_submission_date=None
    )
    _record(capture_repository, project, DocumentCaptureAttemptStatus.NO_DOCUMENTS, ago=timedelta(days=31))
    _record(capture_repository, project, DocumentCaptureAttemptStatus.NO_DOCUMENTS, ago=timedelta(hours=25))

    assert _due_project_ids(capture_repository, no_documents_max_age_days=30) == []


def test_transient_failed_honors_backoff_and_attempt_cap(tmp_path) -> None:
    # P1b: failed/timeout keep exponential backoff + the attempt-count cap.
    _, project_repository, _, profile_repository, capture_repository = (
        _create_repositories(tmp_path)
    )
    _create_profile(profile_repository)
    capped = _create_project(project_repository, project_number="69049163854")
    due = _create_project(project_repository, project_number="69049163855")
    for index in range(3):
        _record(capture_repository, capped, DocumentCaptureAttemptStatus.FAILED, ago=timedelta(hours=index + 1))
    _record(capture_repository, due, DocumentCaptureAttemptStatus.TIMEOUT, ago=timedelta(hours=3))

    assert _due_project_ids(capture_repository, max_attempts=3) == [due.id]


def test_record_attempt_persists_reason_enum_value(tmp_path) -> None:
    _, project_repository, _, profile_repository, capture_repository = (
        _create_repositories(tmp_path)
    )
    _create_profile(profile_repository)
    project = _create_project(project_repository)

    record = capture_repository.record_attempt(
        tenant_id=TENANT_ID,
        project_id=project.id,
        status=DocumentCaptureAttemptStatus.NO_DOCUMENTS,
        reason=DocumentCaptureReason.NO_DOCUMENTS,
    )

    assert record.reason == "no_documents"
    latest = capture_repository.get_latest_attempt_for_project(
        tenant_id=TENANT_ID, project_id=project.id
    )
    assert latest is not None and latest.reason == "no_documents"


def test_throttled_enqueued_flood_does_not_starve_due_candidate(tmp_path) -> None:
    # HIGH regression: a flood of recently-enqueued (throttled) projects sorts
    # ahead of due rows; they must be excluded in SQL so the due project is not
    # crowded out of the bounded prefetch window (limit * 5).
    _, project_repository, _, profile_repository, capture_repository = (
        _create_repositories(tmp_path)
    )
    _create_profile(profile_repository)
    for index in range(11):  # > limit(2) * 5 prefetch
        throttled = _create_project(
            project_repository, project_number=f"700000{index:05d}"
        )
        _record(
            capture_repository,
            throttled,
            DocumentCaptureAttemptStatus.ENQUEUED,
            ago=timedelta(minutes=20),
        )
    due = _create_project(project_repository, project_number="69049163860")
    _record(capture_repository, due, DocumentCaptureAttemptStatus.FAILED, ago=timedelta(hours=3))

    candidates = capture_repository.list_due_backfill_candidates(now=NOW, limit=2)

    assert due.id in [candidate.project_id for candidate in candidates]


def test_old_transient_plus_fresh_no_documents_flood_does_not_starve(tmp_path) -> None:
    # HIGH (round 2): "latest terminal" must use the truly-newest terminal time.
    # Old failed + fresh no_documents rows are not-due (24h cadence) but must NOT
    # sort to the front (by their old transient time) and starve a due row.
    _, project_repository, _, profile_repository, capture_repository = (
        _create_repositories(tmp_path)
    )
    _create_profile(profile_repository)
    for index in range(11):  # > limit(2) * 5 prefetch
        noisy = _create_project(project_repository, project_number=f"710000{index:05d}")
        _record(capture_repository, noisy, DocumentCaptureAttemptStatus.FAILED, ago=timedelta(days=10))
        _record(capture_repository, noisy, DocumentCaptureAttemptStatus.NO_DOCUMENTS, ago=timedelta(hours=1))
    due = _create_project(project_repository, project_number="69049163861")
    _record(capture_repository, due, DocumentCaptureAttemptStatus.FAILED, ago=timedelta(hours=3))

    candidates = capture_repository.list_due_backfill_candidates(now=NOW, limit=2)

    assert due.id in [candidate.project_id for candidate in candidates]


def test_no_documents_history_then_timeout_is_not_immediately_exhausted(tmp_path) -> None:
    # MEDIUM-1 regression: the transient attempt cap counts only failed/timeout,
    # NOT prior no_documents heartbeats.
    _, project_repository, _, profile_repository, capture_repository = (
        _create_repositories(tmp_path)
    )
    _create_profile(profile_repository)
    project = _create_project(project_repository)
    for index in range(3):
        _record(
            capture_repository,
            project,
            DocumentCaptureAttemptStatus.NO_DOCUMENTS,
            ago=timedelta(hours=25 + index * 24),
        )
    _record(capture_repository, project, DocumentCaptureAttemptStatus.TIMEOUT, ago=timedelta(hours=2))

    assert _due_project_ids(capture_repository, max_attempts=3) == [project.id]


def test_candidate_selection_skips_past_proposal_deadline_and_missing_profile(
    tmp_path,
) -> None:
    _, project_repository, _, profile_repository, capture_repository = (
        _create_repositories(tmp_path)
    )
    _create_profile(profile_repository, active=False)
    _create_project(
        project_repository,
        project_number="69049163846",
        proposal_submission_date="2026-06-06",
    )
    _create_project(
        project_repository,
        tenant_id=SECOND_TENANT_ID,
        project_number="69049163847",
        proposal_submission_date="2026-06-08",
    )

    assert capture_repository.list_due_backfill_candidates(now=NOW, limit=10) == []
