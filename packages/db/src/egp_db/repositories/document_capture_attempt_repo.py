"""Document capture attempt audit and backfill candidate persistence."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from uuid import uuid4

from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Table,
    and_,
    desc,
    func,
    insert,
    or_,
    select,
)
from sqlalchemy.engine import Engine, RowMapping

from egp_db.connection import DB_METADATA, create_shared_engine
from egp_db.db_utils import UUID_SQL_TYPE, normalize_database_url, normalize_uuid_string
from egp_shared_types.enums import (
    DocumentCaptureAttemptStatus,
    DocumentType,
    ProjectState,
)
from egp_observability.metrics import record_document_capture_attempt

from .document_schema import DOCUMENTS_TABLE
from .profile_repo import CRAWL_PROFILES_TABLE
from .project_schema import PROJECTS_TABLE


METADATA = DB_METADATA

DOCUMENT_CAPTURE_ATTEMPTS_TABLE = Table(
    "document_capture_attempts",
    METADATA,
    Column("id", UUID_SQL_TYPE, primary_key=True),
    Column("tenant_id", UUID_SQL_TYPE, nullable=False),
    Column(
        "project_id",
        UUID_SQL_TYPE,
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("run_id", UUID_SQL_TYPE, nullable=True),
    Column("status", String, nullable=False),
    Column("reason", String, nullable=True),
    Column("doc_count", Integer, nullable=False, default=0),
    Column("attempted_at", DateTime(timezone=True), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    CheckConstraint(
        "status IN ('enqueued', 'succeeded', 'no_documents', 'failed', 'timeout', 'skipped')",
        name="document_capture_attempts_status_check",
    ),
    CheckConstraint(
        "doc_count >= 0",
        name="document_capture_attempts_doc_count_check",
    ),
)

Index(
    "idx_document_capture_attempts_project_attempted",
    DOCUMENT_CAPTURE_ATTEMPTS_TABLE.c.tenant_id,
    DOCUMENT_CAPTURE_ATTEMPTS_TABLE.c.project_id,
    DOCUMENT_CAPTURE_ATTEMPTS_TABLE.c.attempted_at,
)
Index(
    "idx_document_capture_attempts_status_attempted",
    DOCUMENT_CAPTURE_ATTEMPTS_TABLE.c.tenant_id,
    DOCUMENT_CAPTURE_ATTEMPTS_TABLE.c.status,
    DOCUMENT_CAPTURE_ATTEMPTS_TABLE.c.attempted_at,
)
Index(
    "idx_document_capture_attempts_run",
    DOCUMENT_CAPTURE_ATTEMPTS_TABLE.c.run_id,
)


@dataclass(frozen=True, slots=True)
class DocumentCaptureAttemptRecord:
    id: str
    tenant_id: str
    project_id: str
    run_id: str | None
    status: DocumentCaptureAttemptStatus
    reason: str | None
    doc_count: int
    attempted_at: str
    created_at: str


@dataclass(frozen=True, slots=True)
class DocumentCaptureBackfillCandidate:
    tenant_id: str
    project_id: str
    project_number: str
    project_state: str
    proposal_submission_date: str | None
    profile_id: str
    profile_type: str
    attempt_count: int
    latest_attempted_at: str | None
    target_document_count: int


def _now() -> datetime:
    return datetime.now(UTC)


def _coerce_datetime(value: datetime | str | None) -> datetime:
    if value is None:
        return _now()
    if isinstance(value, datetime):
        parsed = value
    else:
        parsed = datetime.fromisoformat(str(value))
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed


def _coerce_date(value: date | datetime | str | None) -> date | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value))


def _dt_to_iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.isoformat()


def _attempt_from_mapping(row: RowMapping) -> DocumentCaptureAttemptRecord:
    return DocumentCaptureAttemptRecord(
        id=str(row["id"]),
        tenant_id=str(row["tenant_id"]),
        project_id=str(row["project_id"]),
        run_id=str(row["run_id"]) if row["run_id"] is not None else None,
        status=DocumentCaptureAttemptStatus(str(row["status"])),
        reason=str(row["reason"]) if row["reason"] is not None else None,
        doc_count=int(row["doc_count"]),
        attempted_at=_dt_to_iso(row["attempted_at"]) or "",
        created_at=_dt_to_iso(row["created_at"]) or "",
    )


def _candidate_from_mapping(row: RowMapping) -> DocumentCaptureBackfillCandidate:
    proposal_date = _coerce_date(row["proposal_submission_date"])
    return DocumentCaptureBackfillCandidate(
        tenant_id=str(row["tenant_id"]),
        project_id=str(row["project_id"]),
        project_number=str(row["project_number"]),
        project_state=str(row["project_state"]),
        proposal_submission_date=proposal_date.isoformat() if proposal_date else None,
        profile_id=str(row["profile_id"]),
        profile_type=str(row["profile_type"]),
        attempt_count=int(row["attempt_count"] or 0),
        latest_attempted_at=_dt_to_iso(row["latest_attempted_at"]),
        target_document_count=int(row["target_document_count"] or 0),
    )


def _normalize_status(
    status: DocumentCaptureAttemptStatus | str,
) -> DocumentCaptureAttemptStatus:
    try:
        return (
            status
            if isinstance(status, DocumentCaptureAttemptStatus)
            else (DocumentCaptureAttemptStatus(str(status).strip()))
        )
    except ValueError as exc:
        raise ValueError("invalid document capture attempt status") from exc


def _is_backoff_due(
    *,
    latest_attempted_at: datetime | None,
    attempt_count: int,
    now: datetime,
    base_backoff_seconds: int,
    max_backoff_seconds: int,
) -> bool:
    if latest_attempted_at is None or attempt_count <= 0:
        return True
    delay_seconds = min(
        max(0, int(max_backoff_seconds)),
        max(0, int(base_backoff_seconds)) * (2 ** max(0, int(attempt_count) - 1)),
    )
    return latest_attempted_at <= now - timedelta(seconds=delay_seconds)


class SqlDocumentCaptureAttemptRepository:
    def __init__(
        self,
        *,
        database_url: str | None = None,
        engine: Engine | None = None,
        bootstrap_schema: bool = False,
    ) -> None:
        if engine is None and database_url is None:
            raise ValueError("database_url or engine is required")
        self._database_url = (
            normalize_database_url(database_url) if database_url is not None else None
        )
        self._engine = engine or create_shared_engine(self._database_url or "")
        if bootstrap_schema:
            self._ensure_schema()

    def _ensure_schema(self) -> None:
        METADATA.create_all(self._engine)

    def record_attempt(
        self,
        *,
        tenant_id: str,
        project_id: str,
        status: DocumentCaptureAttemptStatus | str,
        reason: str | None = None,
        doc_count: int = 0,
        run_id: str | None = None,
        attempted_at: datetime | str | None = None,
    ) -> DocumentCaptureAttemptRecord:
        normalized_status = _normalize_status(status)
        now = _coerce_datetime(attempted_at)
        values = {
            "id": str(uuid4()),
            "tenant_id": normalize_uuid_string(tenant_id),
            "project_id": normalize_uuid_string(project_id),
            "run_id": normalize_uuid_string(run_id) if run_id else None,
            "status": normalized_status.value,
            "reason": str(reason).strip()[:1000] if reason else None,
            "doc_count": max(0, int(doc_count)),
            "attempted_at": now,
            "created_at": _now(),
        }
        with self._engine.begin() as connection:
            connection.execute(insert(DOCUMENT_CAPTURE_ATTEMPTS_TABLE).values(**values))
            row = (
                connection.execute(
                    select(DOCUMENT_CAPTURE_ATTEMPTS_TABLE)
                    .where(DOCUMENT_CAPTURE_ATTEMPTS_TABLE.c.id == values["id"])
                    .limit(1)
                )
                .mappings()
                .one()
            )
        record_document_capture_attempt(status=normalized_status.value)
        return _attempt_from_mapping(row)

    def find_project_by_number(
        self,
        *,
        tenant_id: str,
        project_number: str,
    ) -> str | None:
        normalized_tenant_id = normalize_uuid_string(tenant_id)
        normalized_project_number = str(project_number).strip()
        if not normalized_project_number:
            return None
        with self._engine.connect() as connection:
            row = (
                connection.execute(
                    select(PROJECTS_TABLE.c.id)
                    .where(
                        and_(
                            PROJECTS_TABLE.c.tenant_id == normalized_tenant_id,
                            PROJECTS_TABLE.c.project_number
                            == normalized_project_number,
                        )
                    )
                    .limit(1)
                )
                .mappings()
                .first()
            )
        return str(row["id"]) if row is not None else None

    def get_latest_attempt_for_project(
        self,
        *,
        tenant_id: str,
        project_id: str | None = None,
        project_number: str | None = None,
    ) -> DocumentCaptureAttemptRecord | None:
        normalized_tenant_id = normalize_uuid_string(tenant_id)
        normalized_project_id = (
            normalize_uuid_string(project_id) if project_id else None
        )
        if normalized_project_id is None:
            if project_number is None:
                raise ValueError("project_id or project_number is required")
            normalized_project_id = self.find_project_by_number(
                tenant_id=normalized_tenant_id,
                project_number=project_number,
            )
        if normalized_project_id is None:
            return None
        with self._engine.connect() as connection:
            row = (
                connection.execute(
                    select(DOCUMENT_CAPTURE_ATTEMPTS_TABLE)
                    .where(
                        and_(
                            DOCUMENT_CAPTURE_ATTEMPTS_TABLE.c.tenant_id
                            == normalized_tenant_id,
                            DOCUMENT_CAPTURE_ATTEMPTS_TABLE.c.project_id
                            == normalized_project_id,
                        )
                    )
                    .order_by(
                        desc(DOCUMENT_CAPTURE_ATTEMPTS_TABLE.c.attempted_at),
                        desc(DOCUMENT_CAPTURE_ATTEMPTS_TABLE.c.created_at),
                        desc(DOCUMENT_CAPTURE_ATTEMPTS_TABLE.c.id),
                    )
                    .limit(1)
                )
                .mappings()
                .first()
            )
        return _attempt_from_mapping(row) if row is not None else None

    def list_due_backfill_candidates(
        self,
        *,
        now: datetime | str | None = None,
        max_attempts: int = 3,
        base_backoff_seconds: int = 3600,
        max_backoff_seconds: int = 86400,
        limit: int = 50,
    ) -> list[DocumentCaptureBackfillCandidate]:
        effective_now = _coerce_datetime(now)
        normalized_limit = max(1, int(limit))
        normalized_max_attempts = max(1, int(max_attempts))
        attempt_stats = (
            select(
                DOCUMENT_CAPTURE_ATTEMPTS_TABLE.c.tenant_id.label("tenant_id"),
                DOCUMENT_CAPTURE_ATTEMPTS_TABLE.c.project_id.label("project_id"),
                func.count().label("attempt_count"),
                func.max(DOCUMENT_CAPTURE_ATTEMPTS_TABLE.c.attempted_at).label(
                    "latest_attempted_at"
                ),
            )
            .group_by(
                DOCUMENT_CAPTURE_ATTEMPTS_TABLE.c.tenant_id,
                DOCUMENT_CAPTURE_ATTEMPTS_TABLE.c.project_id,
            )
            .subquery()
        )
        target_documents = (
            select(
                DOCUMENTS_TABLE.c.tenant_id.label("tenant_id"),
                DOCUMENTS_TABLE.c.project_id.label("project_id"),
                func.count().label("target_document_count"),
            )
            .where(
                DOCUMENTS_TABLE.c.document_type.in_(
                    [DocumentType.INVITATION.value, DocumentType.TOR.value]
                )
            )
            .group_by(DOCUMENTS_TABLE.c.tenant_id, DOCUMENTS_TABLE.c.project_id)
            .subquery()
        )
        profile_rank = (
            func.row_number()
            .over(
                partition_by=CRAWL_PROFILES_TABLE.c.tenant_id,
                order_by=(
                    CRAWL_PROFILES_TABLE.c.created_at,
                    CRAWL_PROFILES_TABLE.c.id,
                ),
            )
            .label("profile_rank")
        )
        active_profiles = (
            select(
                CRAWL_PROFILES_TABLE.c.tenant_id.label("tenant_id"),
                CRAWL_PROFILES_TABLE.c.id.label("profile_id"),
                CRAWL_PROFILES_TABLE.c.profile_type.label("profile_type"),
                profile_rank,
            )
            .where(CRAWL_PROFILES_TABLE.c.is_active.is_(True))
            .subquery()
        )
        open_states = [
            ProjectState.DISCOVERED.value,
            ProjectState.OPEN_INVITATION.value,
            ProjectState.OPEN_PUBLIC_HEARING.value,
            ProjectState.OPEN_CONSULTING.value,
        ]
        statement = (
            select(
                PROJECTS_TABLE.c.tenant_id,
                PROJECTS_TABLE.c.id.label("project_id"),
                PROJECTS_TABLE.c.project_number,
                PROJECTS_TABLE.c.project_state,
                PROJECTS_TABLE.c.proposal_submission_date,
                active_profiles.c.profile_id,
                active_profiles.c.profile_type,
                func.coalesce(attempt_stats.c.attempt_count, 0).label("attempt_count"),
                attempt_stats.c.latest_attempted_at,
                func.coalesce(target_documents.c.target_document_count, 0).label(
                    "target_document_count"
                ),
            )
            .join(
                active_profiles,
                and_(
                    active_profiles.c.tenant_id == PROJECTS_TABLE.c.tenant_id,
                    active_profiles.c.profile_rank == 1,
                ),
            )
            .outerjoin(
                attempt_stats,
                and_(
                    attempt_stats.c.tenant_id == PROJECTS_TABLE.c.tenant_id,
                    attempt_stats.c.project_id == PROJECTS_TABLE.c.id,
                ),
            )
            .outerjoin(
                target_documents,
                and_(
                    target_documents.c.tenant_id == PROJECTS_TABLE.c.tenant_id,
                    target_documents.c.project_id == PROJECTS_TABLE.c.id,
                ),
            )
            .where(
                PROJECTS_TABLE.c.project_state.in_(open_states),
                PROJECTS_TABLE.c.project_number.is_not(None),
                PROJECTS_TABLE.c.project_number != "",
                or_(
                    PROJECTS_TABLE.c.proposal_submission_date.is_(None),
                    PROJECTS_TABLE.c.proposal_submission_date >= effective_now.date(),
                ),
                func.coalesce(target_documents.c.target_document_count, 0) == 0,
                func.coalesce(attempt_stats.c.attempt_count, 0)
                < normalized_max_attempts,
            )
            .order_by(
                attempt_stats.c.latest_attempted_at.is_not(None),
                attempt_stats.c.latest_attempted_at,
                PROJECTS_TABLE.c.last_seen_at,
                PROJECTS_TABLE.c.id,
            )
            .limit(normalized_limit * 5)
        )
        with self._engine.connect() as connection:
            rows = connection.execute(statement).mappings().all()
        candidates: list[DocumentCaptureBackfillCandidate] = []
        for row in rows:
            latest_attempted_at = row["latest_attempted_at"]
            if latest_attempted_at is not None and latest_attempted_at.tzinfo is None:
                latest_attempted_at = latest_attempted_at.replace(tzinfo=UTC)
            if not _is_backoff_due(
                latest_attempted_at=latest_attempted_at,
                attempt_count=int(row["attempt_count"] or 0),
                now=effective_now,
                base_backoff_seconds=base_backoff_seconds,
                max_backoff_seconds=max_backoff_seconds,
            ):
                continue
            candidates.append(_candidate_from_mapping(row))
            if len(candidates) >= normalized_limit:
                break
        return candidates


def create_document_capture_attempt_repository(
    *,
    database_url: str | None = None,
    engine: Engine | None = None,
    bootstrap_schema: bool = True,
) -> SqlDocumentCaptureAttemptRepository:
    return SqlDocumentCaptureAttemptRepository(
        database_url=database_url,
        engine=engine,
        bootstrap_schema=bootstrap_schema,
    )
