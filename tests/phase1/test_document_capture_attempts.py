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


def test_candidate_selection_honors_backoff_and_cap(tmp_path) -> None:
    _, project_repository, _, profile_repository, capture_repository = (
        _create_repositories(tmp_path)
    )
    _create_profile(profile_repository)
    recent = _create_project(project_repository, project_number="69049163846")
    capped = _create_project(project_repository, project_number="69049163847")
    due = _create_project(project_repository, project_number="69049163848")

    capture_repository.record_attempt(
        tenant_id=TENANT_ID,
        project_id=recent.id,
        status=DocumentCaptureAttemptStatus.ENQUEUED,
        reason="backfill_job_created",
        doc_count=0,
        attempted_at=NOW - timedelta(minutes=30),
    )
    for index in range(3):
        capture_repository.record_attempt(
            tenant_id=TENANT_ID,
            project_id=capped.id,
            status=DocumentCaptureAttemptStatus.NO_DOCUMENTS,
            reason=f"attempt_{index}",
            doc_count=0,
            attempted_at=NOW - timedelta(days=index + 1),
        )
    capture_repository.record_attempt(
        tenant_id=TENANT_ID,
        project_id=due.id,
        status=DocumentCaptureAttemptStatus.NO_DOCUMENTS,
        reason="old_attempt",
        doc_count=0,
        attempted_at=NOW - timedelta(hours=3),
    )

    candidates = capture_repository.list_due_backfill_candidates(
        now=NOW,
        max_attempts=3,
        base_backoff_seconds=3600,
        max_backoff_seconds=86400,
        limit=10,
    )

    assert [candidate.project_id for candidate in candidates] == [due.id]


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
