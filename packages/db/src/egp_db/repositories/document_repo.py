"""Repository-level document record builders and relational persistence."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import mimetypes
from pathlib import Path
import re
from uuid import uuid4

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Index,
    Integer,
    String,
    Table,
    UniqueConstraint,
    and_,
    desc,
    func,
    or_,
)
from sqlalchemy import Column, insert, select, update
from sqlalchemy.engine import Engine, RowMapping

from egp_crawler_core.document_hasher import hash_file
from egp_db.artifact_store import (
    ArtifactStore,
    LocalArtifactStore,
    S3ArtifactStore,
    SupabaseArtifactStore,
)
from egp_db.connection import DB_METADATA, create_shared_engine
from egp_db.db_utils import (
    UUID_SQL_TYPE,
    is_sqlite_url,
    normalize_database_url,
    normalize_uuid_string,
)
from egp_document_classifier.classifier import classify_document, derive_artifact_bucket
from egp_document_classifier.diff_engine import ComparisonScope, build_document_diff
from egp_shared_types.enums import (
    ArtifactBucket,
    DocumentPhase,
    DocumentReviewAction,
    DocumentReviewEventType,
    DocumentReviewStatus,
    DocumentType,
)


@dataclass(frozen=True, slots=True)
class DocumentRecord:
    id: str
    project_id: str
    file_name: str
    sha256: str
    storage_key: str
    document_type: DocumentType
    document_phase: DocumentPhase
    source_label: str
    source_status_text: str
    size_bytes: int
    is_current: bool
    supersedes_document_id: str | None
    created_at: str


@dataclass(frozen=True, slots=True)
class DocumentDiffRecord:
    id: str
    project_id: str
    old_document_id: str
    new_document_id: str
    diff_type: str
    summary_json: dict[str, object] | None
    created_at: str


@dataclass(frozen=True, slots=True)
class StoreDocumentResult:
    created: bool
    document: DocumentRecord
    diff_records: list[DocumentDiffRecord]


@dataclass(frozen=True, slots=True)
class DocumentReviewEventRecord:
    id: str
    review_id: str
    document_diff_id: str
    event_type: DocumentReviewEventType
    actor_subject: str | None
    note: str | None
    from_status: DocumentReviewStatus | None
    to_status: DocumentReviewStatus | None
    created_at: str


@dataclass(frozen=True, slots=True)
class DocumentReviewDetail:
    id: str
    project_id: str
    document_diff_id: str
    status: DocumentReviewStatus
    resolved_at: str | None
    created_at: str
    updated_at: str
    diff: DocumentDiffRecord
    events: list[DocumentReviewEventRecord]


@dataclass(frozen=True, slots=True)
class DocumentReviewPage:
    reviews: list[DocumentReviewDetail]
    total: int
    limit: int
    offset: int


METADATA = DB_METADATA

DOCUMENTS_TABLE = Table(
    "documents",
    METADATA,
    Column("id", UUID_SQL_TYPE, primary_key=True),
    Column("tenant_id", UUID_SQL_TYPE, nullable=False),
    Column("project_id", UUID_SQL_TYPE, nullable=False),
    Column("file_name", String, nullable=False),
    Column("sha256", String, nullable=False),
    Column("storage_key", String, nullable=False),
    Column("document_type", String, nullable=False),
    Column("document_phase", String, nullable=False),
    Column("source_label", String, nullable=False, default=""),
    Column("source_status_text", String, nullable=False, default=""),
    Column("size_bytes", Integer, nullable=False),
    Column("is_current", Boolean, nullable=False, default=True),
    Column("supersedes_document_id", UUID_SQL_TYPE, nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False),
    UniqueConstraint(
        "tenant_id",
        "project_id",
        "sha256",
        "document_type",
        "document_phase",
        name="documents_project_hash_class_phase_uq",
    ),
)

DOCUMENT_DIFFS_TABLE = Table(
    "document_diffs",
    METADATA,
    Column("id", UUID_SQL_TYPE, primary_key=True),
    Column("tenant_id", UUID_SQL_TYPE, nullable=False),
    Column("project_id", UUID_SQL_TYPE, nullable=False),
    Column("old_document_id", UUID_SQL_TYPE, nullable=False),
    Column("new_document_id", UUID_SQL_TYPE, nullable=False),
    Column("diff_type", String, nullable=False),
    Column("summary_json", JSON, nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False),
)

DOCUMENT_DIFF_REVIEWS_TABLE = Table(
    "document_diff_reviews",
    METADATA,
    Column("id", UUID_SQL_TYPE, primary_key=True),
    Column("tenant_id", UUID_SQL_TYPE, nullable=False),
    Column("project_id", UUID_SQL_TYPE, nullable=False),
    Column("document_diff_id", UUID_SQL_TYPE, nullable=False),
    Column("status", String, nullable=False),
    Column("resolved_at", DateTime(timezone=True), nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
    UniqueConstraint(
        "document_diff_id",
        name="document_diff_reviews_document_diff_unique",
    ),
)

DOCUMENT_REVIEW_EVENTS_TABLE = Table(
    "document_review_events",
    METADATA,
    Column("id", UUID_SQL_TYPE, primary_key=True),
    Column("tenant_id", UUID_SQL_TYPE, nullable=False),
    Column("project_id", UUID_SQL_TYPE, nullable=False),
    Column("review_id", UUID_SQL_TYPE, nullable=False),
    Column("document_diff_id", UUID_SQL_TYPE, nullable=False),
    Column("event_type", String, nullable=False),
    Column("actor_subject", String, nullable=True),
    Column("note", String, nullable=True),
    Column("from_status", String, nullable=True),
    Column("to_status", String, nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False),
)

Index(
    "idx_documents_project",
    DOCUMENTS_TABLE.c.tenant_id,
    DOCUMENTS_TABLE.c.project_id,
    DOCUMENTS_TABLE.c.is_current,
    DOCUMENTS_TABLE.c.created_at,
)
Index(
    "idx_documents_type",
    DOCUMENTS_TABLE.c.tenant_id,
    DOCUMENTS_TABLE.c.project_id,
    DOCUMENTS_TABLE.c.document_type,
    DOCUMENTS_TABLE.c.document_phase,
    DOCUMENTS_TABLE.c.created_at,
)
Index(
    "idx_diffs_project",
    DOCUMENT_DIFFS_TABLE.c.tenant_id,
    DOCUMENT_DIFFS_TABLE.c.project_id,
    DOCUMENT_DIFFS_TABLE.c.created_at,
)
Index(
    "idx_document_diff_reviews_project_created",
    DOCUMENT_DIFF_REVIEWS_TABLE.c.tenant_id,
    DOCUMENT_DIFF_REVIEWS_TABLE.c.project_id,
    DOCUMENT_DIFF_REVIEWS_TABLE.c.created_at,
)
Index(
    "idx_document_diff_reviews_status_created",
    DOCUMENT_DIFF_REVIEWS_TABLE.c.tenant_id,
    DOCUMENT_DIFF_REVIEWS_TABLE.c.status,
    DOCUMENT_DIFF_REVIEWS_TABLE.c.created_at,
)
Index(
    "idx_document_review_events_review_created",
    DOCUMENT_REVIEW_EVENTS_TABLE.c.review_id,
    DOCUMENT_REVIEW_EVENTS_TABLE.c.created_at,
)
Index(
    "idx_document_review_events_diff_created",
    DOCUMENT_REVIEW_EVENTS_TABLE.c.document_diff_id,
    DOCUMENT_REVIEW_EVENTS_TABLE.c.created_at,
)


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _sanitize_file_name(file_name: str) -> str:
    sanitized = re.sub(r"[^A-Za-z0-9._-]+", "_", file_name.strip())
    return sanitized or "artifact.bin"


def _document_from_mapping(row: RowMapping) -> DocumentRecord:
    created_at = row["created_at"]
    return DocumentRecord(
        id=str(row["id"]),
        project_id=str(row["project_id"]),
        file_name=str(row["file_name"]),
        sha256=str(row["sha256"]),
        storage_key=str(row["storage_key"]),
        document_type=DocumentType(str(row["document_type"])),
        document_phase=DocumentPhase(str(row["document_phase"])),
        source_label=str(row["source_label"] or ""),
        source_status_text=str(row["source_status_text"] or ""),
        size_bytes=int(row["size_bytes"]),
        is_current=bool(row["is_current"]),
        supersedes_document_id=(
            str(row["supersedes_document_id"])
            if row["supersedes_document_id"] is not None
            else None
        ),
        created_at=created_at.isoformat()
        if isinstance(created_at, datetime)
        else str(created_at),
    )


def _diff_from_mapping(row: RowMapping) -> DocumentDiffRecord:
    created_at = row["created_at"]
    return DocumentDiffRecord(
        id=str(row["id"]),
        project_id=str(row["project_id"]),
        old_document_id=str(row["old_document_id"]),
        new_document_id=str(row["new_document_id"]),
        diff_type=str(row["diff_type"]),
        summary_json=row["summary_json"],
        created_at=created_at.isoformat()
        if isinstance(created_at, datetime)
        else str(created_at),
    )


def _review_event_from_mapping(row: RowMapping) -> DocumentReviewEventRecord:
    created_at = row["created_at"]
    from_status = row["from_status"]
    to_status = row["to_status"]
    return DocumentReviewEventRecord(
        id=str(row["id"]),
        review_id=str(row["review_id"]),
        document_diff_id=str(row["document_diff_id"]),
        event_type=DocumentReviewEventType(str(row["event_type"])),
        actor_subject=str(row["actor_subject"])
        if row["actor_subject"] is not None
        else None,
        note=str(row["note"]) if row["note"] is not None else None,
        from_status=DocumentReviewStatus(str(from_status))
        if from_status is not None
        else None,
        to_status=DocumentReviewStatus(str(to_status))
        if to_status is not None
        else None,
        created_at=created_at.isoformat()
        if isinstance(created_at, datetime)
        else str(created_at),
    )


def _to_db_timestamp(value: str) -> datetime:
    return datetime.fromisoformat(value)


def _normalize_limit_offset(*, limit: int, offset: int) -> tuple[int, int]:
    normalized_limit = int(limit)
    normalized_offset = int(offset)
    if normalized_limit < 1 or normalized_limit > 200:
        raise ValueError("limit must be between 1 and 200")
    if normalized_offset < 0:
        raise ValueError("offset must be greater than or equal to 0")
    return (normalized_limit, normalized_offset)


def _normalize_review_status(
    value: DocumentReviewStatus | str | None,
) -> DocumentReviewStatus | None:
    if value is None:
        return None
    return (
        value
        if isinstance(value, DocumentReviewStatus)
        else DocumentReviewStatus(str(value))
    )


def _normalize_review_action(value: DocumentReviewAction | str) -> DocumentReviewAction:
    return (
        value
        if isinstance(value, DocumentReviewAction)
        else DocumentReviewAction(str(value))
    )


def build_document_record(
    *,
    project_id: str,
    file_name: str,
    file_bytes: bytes,
    source_label: str,
    source_status_text: str,
    storage_key: str,
    source_page_text: str = "",
    project_state: str | None = None,
    document_id: str | None = None,
    is_current: bool = True,
    supersedes_document_id: str | None = None,
    created_at: str | None = None,
    sha256: str | None = None,
    document_type: DocumentType | None = None,
    document_phase: DocumentPhase | None = None,
) -> DocumentRecord:
    resolved_document_type, resolved_document_phase = (
        (document_type, document_phase)
        if document_type is not None and document_phase is not None
        else classify_document(
            label=source_label,
            source_status_text=source_status_text,
            source_page_text=source_page_text,
            project_state=project_state,
            file_name=file_name,
        )
    )
    return DocumentRecord(
        id=document_id or str(uuid4()),
        project_id=project_id,
        file_name=file_name,
        sha256=sha256 or hash_file(file_bytes),
        storage_key=storage_key,
        document_type=resolved_document_type,
        document_phase=resolved_document_phase,
        source_label=source_label,
        source_status_text=source_status_text,
        size_bytes=len(file_bytes),
        is_current=is_current,
        supersedes_document_id=supersedes_document_id,
        created_at=created_at or _now_iso(),
    )


class SqlDocumentRepository:
    """Relational document metadata repository with pluggable blob storage."""

    def __init__(
        self,
        *,
        database_url: str | None = None,
        artifact_store: ArtifactStore,
        engine: Engine | None = None,
        bootstrap_schema: bool = False,
    ) -> None:
        if engine is None and database_url is None:
            raise ValueError("database_url or engine is required")
        normalized_url = (
            normalize_database_url(database_url) if database_url is not None else None
        )
        self._database_url = normalized_url
        self._artifact_store = artifact_store
        self._engine = engine or create_shared_engine(normalized_url or "")
        if bootstrap_schema:
            self._ensure_schema()

    def _ensure_schema(self) -> None:
        METADATA.create_all(self._engine)

    def _append_review_event(
        self,
        connection,
        *,
        tenant_id: str,
        project_id: str,
        review_id: str,
        document_diff_id: str,
        event_type: DocumentReviewEventType,
        actor_subject: str | None,
        note: str | None,
        from_status: DocumentReviewStatus | None,
        to_status: DocumentReviewStatus | None,
        created_at: datetime,
    ) -> None:
        connection.execute(
            insert(DOCUMENT_REVIEW_EVENTS_TABLE).values(
                id=str(uuid4()),
                tenant_id=tenant_id,
                project_id=project_id,
                review_id=review_id,
                document_diff_id=document_diff_id,
                event_type=event_type.value,
                actor_subject=str(actor_subject).strip() if actor_subject else None,
                note=str(note).strip() if note else None,
                from_status=from_status.value if from_status is not None else None,
                to_status=to_status.value if to_status is not None else None,
                created_at=created_at,
            )
        )

    def _create_review_for_changed_diff(
        self,
        connection,
        *,
        tenant_id: str,
        project_id: str,
        diff_record: DocumentDiffRecord,
    ) -> None:
        existing = (
            connection.execute(
                select(DOCUMENT_DIFF_REVIEWS_TABLE.c.id).where(
                    and_(
                        DOCUMENT_DIFF_REVIEWS_TABLE.c.tenant_id == tenant_id,
                        DOCUMENT_DIFF_REVIEWS_TABLE.c.document_diff_id
                        == diff_record.id,
                    )
                )
            )
            .mappings()
            .first()
        )
        if existing is not None:
            return
        now = _to_db_timestamp(diff_record.created_at)
        review_id = str(uuid4())
        connection.execute(
            insert(DOCUMENT_DIFF_REVIEWS_TABLE).values(
                id=review_id,
                tenant_id=tenant_id,
                project_id=project_id,
                document_diff_id=diff_record.id,
                status=DocumentReviewStatus.PENDING.value,
                resolved_at=None,
                created_at=now,
                updated_at=now,
            )
        )
        self._append_review_event(
            connection,
            tenant_id=tenant_id,
            project_id=project_id,
            review_id=review_id,
            document_diff_id=diff_record.id,
            event_type=DocumentReviewEventType.CREATED,
            actor_subject=None,
            note=None,
            from_status=None,
            to_status=DocumentReviewStatus.PENDING,
            created_at=now,
        )

    def _load_review_events(
        self,
        connection,
        *,
        review_ids: list[str],
    ) -> dict[str, list[DocumentReviewEventRecord]]:
        if not review_ids:
            return {}
        rows = (
            connection.execute(
                select(DOCUMENT_REVIEW_EVENTS_TABLE)
                .where(DOCUMENT_REVIEW_EVENTS_TABLE.c.review_id.in_(review_ids))
                .order_by(DOCUMENT_REVIEW_EVENTS_TABLE.c.created_at.asc())
            )
            .mappings()
            .all()
        )
        grouped: dict[str, list[DocumentReviewEventRecord]] = {}
        for row in rows:
            event = _review_event_from_mapping(row)
            grouped.setdefault(event.review_id, []).append(event)
        return grouped

    def _load_diffs_by_id(
        self,
        connection,
        *,
        diff_ids: list[str],
    ) -> dict[str, DocumentDiffRecord]:
        if not diff_ids:
            return {}
        rows = (
            connection.execute(
                select(DOCUMENT_DIFFS_TABLE).where(
                    DOCUMENT_DIFFS_TABLE.c.id.in_(diff_ids)
                )
            )
            .mappings()
            .all()
        )
        return {str(row["id"]): _diff_from_mapping(row) for row in rows}

    def _build_review_detail(
        self,
        *,
        row: RowMapping,
        diff: DocumentDiffRecord,
        events: list[DocumentReviewEventRecord],
    ) -> DocumentReviewDetail:
        resolved_at = row["resolved_at"]
        created_at = row["created_at"]
        updated_at = row["updated_at"]
        return DocumentReviewDetail(
            id=str(row["id"]),
            project_id=str(row["project_id"]),
            document_diff_id=str(row["document_diff_id"]),
            status=DocumentReviewStatus(str(row["status"])),
            resolved_at=resolved_at.isoformat()
            if isinstance(resolved_at, datetime)
            else (str(resolved_at) if resolved_at is not None else None),
            created_at=created_at.isoformat()
            if isinstance(created_at, datetime)
            else str(created_at),
            updated_at=updated_at.isoformat()
            if isinstance(updated_at, datetime)
            else str(updated_at),
            diff=diff,
            events=events,
        )

    def _find_existing_document(
        self,
        *,
        connection,
        tenant_id: str,
        project_id: str,
        sha256: str,
        document_type: DocumentType,
        document_phase: DocumentPhase,
    ) -> DocumentRecord | None:
        row = (
            connection.execute(
                select(DOCUMENTS_TABLE)
                .where(
                    and_(
                        DOCUMENTS_TABLE.c.tenant_id == tenant_id,
                        DOCUMENTS_TABLE.c.project_id == project_id,
                        DOCUMENTS_TABLE.c.sha256 == sha256,
                        DOCUMENTS_TABLE.c.document_type == document_type.value,
                        DOCUMENTS_TABLE.c.document_phase == document_phase.value,
                    )
                )
                .limit(1)
            )
            .mappings()
            .first()
        )
        return _document_from_mapping(row) if row is not None else None

    def _find_current_same_class(
        self,
        *,
        connection,
        tenant_id: str,
        project_id: str,
        document_type: DocumentType,
        document_phase: DocumentPhase,
    ) -> DocumentRecord | None:
        row = (
            connection.execute(
                select(DOCUMENTS_TABLE)
                .where(
                    and_(
                        DOCUMENTS_TABLE.c.tenant_id == tenant_id,
                        DOCUMENTS_TABLE.c.project_id == project_id,
                        DOCUMENTS_TABLE.c.document_type == document_type.value,
                        DOCUMENTS_TABLE.c.document_phase == document_phase.value,
                        DOCUMENTS_TABLE.c.is_current.is_(True),
                    )
                )
                .order_by(desc(DOCUMENTS_TABLE.c.created_at))
                .limit(1)
            )
            .mappings()
            .first()
        )
        return _document_from_mapping(row) if row is not None else None

    def _find_phase_transition_target(
        self,
        *,
        connection,
        tenant_id: str,
        project_id: str,
        document_type: DocumentType,
        document_phase: DocumentPhase,
    ) -> DocumentRecord | None:
        if document_type is not DocumentType.TOR:
            return None
        if document_phase is DocumentPhase.PUBLIC_HEARING:
            other_phase = DocumentPhase.FINAL
        elif document_phase is DocumentPhase.FINAL:
            other_phase = DocumentPhase.PUBLIC_HEARING
        else:
            return None
        return self._find_current_same_class(
            connection=connection,
            tenant_id=tenant_id,
            project_id=project_id,
            document_type=document_type,
            document_phase=other_phase,
        )

    def _build_diff_record(
        self,
        *,
        tenant_id: str,
        project_id: str,
        comparison_target: DocumentRecord,
        stored_document: DocumentRecord,
        new_file_bytes: bytes,
        comparison_scope: ComparisonScope,
    ) -> DocumentDiffRecord:
        old_file_bytes = self._artifact_store.get_bytes(comparison_target.storage_key)
        diff_result = build_document_diff(
            old_document_type=comparison_target.document_type,
            old_document_phase=comparison_target.document_phase,
            old_file_name=comparison_target.file_name,
            old_sha256=comparison_target.sha256,
            old_bytes=old_file_bytes,
            new_document_type=stored_document.document_type,
            new_document_phase=stored_document.document_phase,
            new_file_name=stored_document.file_name,
            new_sha256=stored_document.sha256,
            new_bytes=new_file_bytes,
            comparison_scope=comparison_scope,
        )
        return DocumentDiffRecord(
            id=str(uuid4()),
            project_id=project_id,
            old_document_id=comparison_target.id,
            new_document_id=stored_document.id,
            diff_type=diff_result.diff_type,
            summary_json=diff_result.summary_json,
            created_at=_now_iso(),
        )

    def store_document(
        self,
        *,
        tenant_id: str,
        project_id: str,
        file_name: str,
        file_bytes: bytes,
        source_label: str,
        source_status_text: str,
        source_page_text: str = "",
        project_state: str | None = None,
    ) -> StoreDocumentResult:
        tenant_id = normalize_uuid_string(tenant_id)
        project_id = normalize_uuid_string(project_id)
        document_sha256 = hash_file(file_bytes)
        document_type, document_phase = classify_document(
            label=source_label,
            source_status_text=source_status_text,
            source_page_text=source_page_text,
            project_state=project_state,
            file_name=file_name,
        )
        draft_document = build_document_record(
            project_id=project_id,
            file_name=file_name,
            file_bytes=file_bytes,
            source_label=source_label,
            source_status_text=source_status_text,
            storage_key="",
            source_page_text=source_page_text,
            project_state=project_state,
            sha256=document_sha256,
            document_type=document_type,
            document_phase=document_phase,
        )
        safe_name = _sanitize_file_name(file_name)
        blob_key = f"tenants/{tenant_id}/projects/{project_id}/artifacts/{draft_document.sha256}/{safe_name}"
        content_type = mimetypes.guess_type(file_name)[0]

        stored_key: str | None = None
        try:
            with self._engine.begin() as connection:
                existing = self._find_existing_document(
                    connection=connection,
                    tenant_id=tenant_id,
                    project_id=project_id,
                    sha256=draft_document.sha256,
                    document_type=draft_document.document_type,
                    document_phase=draft_document.document_phase,
                )
                if existing is not None:
                    return StoreDocumentResult(
                        created=False,
                        document=existing,
                        diff_records=[],
                    )

                current_same_class = self._find_current_same_class(
                    connection=connection,
                    tenant_id=tenant_id,
                    project_id=project_id,
                    document_type=draft_document.document_type,
                    document_phase=draft_document.document_phase,
                )
                comparison_target = current_same_class
                comparison_scope: ComparisonScope | None = (
                    "same_phase_version" if current_same_class is not None else None
                )
                if comparison_target is None:
                    comparison_target = self._find_phase_transition_target(
                        connection=connection,
                        tenant_id=tenant_id,
                        project_id=project_id,
                        document_type=draft_document.document_type,
                        document_phase=draft_document.document_phase,
                    )
                    if comparison_target is not None:
                        comparison_scope = "phase_transition"

                stored_key = self._artifact_store.put_bytes(
                    key=blob_key,
                    data=file_bytes,
                    content_type=content_type,
                )
                stored_document = build_document_record(
                    project_id=project_id,
                    file_name=file_name,
                    file_bytes=file_bytes,
                    source_label=source_label,
                    source_status_text=source_status_text,
                    storage_key=stored_key,
                    source_page_text=source_page_text,
                    project_state=project_state,
                    supersedes_document_id=(
                        current_same_class.id
                        if current_same_class is not None
                        else None
                    ),
                    sha256=document_sha256,
                    document_type=document_type,
                    document_phase=document_phase,
                )

                if current_same_class is not None:
                    connection.execute(
                        update(DOCUMENTS_TABLE)
                        .where(
                            and_(
                                DOCUMENTS_TABLE.c.tenant_id == tenant_id,
                                DOCUMENTS_TABLE.c.id == current_same_class.id,
                            )
                        )
                        .values(is_current=False)
                    )

                connection.execute(
                    insert(DOCUMENTS_TABLE).values(
                        id=stored_document.id,
                        tenant_id=tenant_id,
                        project_id=stored_document.project_id,
                        file_name=stored_document.file_name,
                        sha256=stored_document.sha256,
                        storage_key=stored_document.storage_key,
                        document_type=stored_document.document_type.value,
                        document_phase=stored_document.document_phase.value,
                        source_label=stored_document.source_label,
                        source_status_text=stored_document.source_status_text,
                        size_bytes=stored_document.size_bytes,
                        is_current=stored_document.is_current,
                        supersedes_document_id=stored_document.supersedes_document_id,
                        created_at=_to_db_timestamp(stored_document.created_at),
                    )
                )

                new_diff_records: list[DocumentDiffRecord] = []
                if comparison_target is not None and comparison_scope is not None:
                    diff_record = self._build_diff_record(
                        tenant_id=tenant_id,
                        project_id=project_id,
                        comparison_target=comparison_target,
                        stored_document=stored_document,
                        new_file_bytes=file_bytes,
                        comparison_scope=comparison_scope,
                    )
                    connection.execute(
                        insert(DOCUMENT_DIFFS_TABLE).values(
                            id=diff_record.id,
                            tenant_id=tenant_id,
                            project_id=diff_record.project_id,
                            old_document_id=diff_record.old_document_id,
                            new_document_id=diff_record.new_document_id,
                            diff_type=diff_record.diff_type,
                            summary_json=diff_record.summary_json,
                            created_at=_to_db_timestamp(diff_record.created_at),
                        )
                    )
                    new_diff_records.append(diff_record)
                    if diff_record.diff_type == "changed":
                        self._create_review_for_changed_diff(
                            connection,
                            tenant_id=tenant_id,
                            project_id=project_id,
                            diff_record=diff_record,
                        )

                return StoreDocumentResult(
                    created=True,
                    document=stored_document,
                    diff_records=new_diff_records,
                )
        except Exception:
            if stored_key is not None:
                self._artifact_store.delete(stored_key)
            raise

    def list_documents(self, tenant_id: str, project_id: str) -> list[DocumentRecord]:
        tenant_id = normalize_uuid_string(tenant_id)
        project_id = normalize_uuid_string(project_id)
        with self._engine.connect() as connection:
            rows = (
                connection.execute(
                    select(DOCUMENTS_TABLE)
                    .where(
                        and_(
                            DOCUMENTS_TABLE.c.tenant_id == tenant_id,
                            DOCUMENTS_TABLE.c.project_id == project_id,
                        )
                    )
                    .order_by(desc(DOCUMENTS_TABLE.c.created_at))
                )
                .mappings()
                .all()
            )
        return [_document_from_mapping(row) for row in rows]

    def get_artifact_bucket(self, tenant_id: str, project_id: str) -> ArtifactBucket:
        documents = self.list_documents(tenant_id, project_id)
        return derive_artifact_bucket(
            documents=[
                {
                    "document_type": document.document_type.value,
                    "document_phase": document.document_phase.value,
                }
                for document in documents
                if document.is_current
            ]
        )

    def get_document(
        self, *, tenant_id: str, document_id: str
    ) -> DocumentRecord | None:
        tenant_id = normalize_uuid_string(tenant_id)
        document_id = normalize_uuid_string(document_id)
        with self._engine.connect() as connection:
            row = (
                connection.execute(
                    select(DOCUMENTS_TABLE)
                    .where(
                        and_(
                            DOCUMENTS_TABLE.c.tenant_id == tenant_id,
                            DOCUMENTS_TABLE.c.id == document_id,
                        )
                    )
                    .limit(1)
                )
                .mappings()
                .first()
            )
        return _document_from_mapping(row) if row is not None else None

    def list_document_diffs(
        self, *, tenant_id: str, project_id: str
    ) -> list[DocumentDiffRecord]:
        normalized_tenant_id = normalize_uuid_string(tenant_id)
        normalized_project_id = normalize_uuid_string(project_id)
        with self._engine.connect() as connection:
            rows = (
                connection.execute(
                    select(DOCUMENT_DIFFS_TABLE)
                    .where(
                        and_(
                            DOCUMENT_DIFFS_TABLE.c.tenant_id == normalized_tenant_id,
                            DOCUMENT_DIFFS_TABLE.c.project_id == normalized_project_id,
                        )
                    )
                    .order_by(desc(DOCUMENT_DIFFS_TABLE.c.created_at))
                )
                .mappings()
                .all()
            )
        return [_diff_from_mapping(row) for row in rows]

    def get_document_diff(
        self,
        *,
        tenant_id: str,
        document_id: str,
        other_document_id: str,
    ) -> DocumentDiffRecord | None:
        normalized_tenant_id = normalize_uuid_string(tenant_id)
        normalized_document_id = normalize_uuid_string(document_id)
        normalized_other_document_id = normalize_uuid_string(other_document_id)
        with self._engine.connect() as connection:
            row = (
                connection.execute(
                    select(DOCUMENT_DIFFS_TABLE)
                    .where(
                        and_(
                            DOCUMENT_DIFFS_TABLE.c.tenant_id == normalized_tenant_id,
                            or_(
                                and_(
                                    DOCUMENT_DIFFS_TABLE.c.old_document_id
                                    == normalized_other_document_id,
                                    DOCUMENT_DIFFS_TABLE.c.new_document_id
                                    == normalized_document_id,
                                ),
                                and_(
                                    DOCUMENT_DIFFS_TABLE.c.old_document_id
                                    == normalized_document_id,
                                    DOCUMENT_DIFFS_TABLE.c.new_document_id
                                    == normalized_other_document_id,
                                ),
                            ),
                        )
                    )
                    .order_by(desc(DOCUMENT_DIFFS_TABLE.c.created_at))
                    .limit(1)
                )
                .mappings()
                .first()
            )
        return _diff_from_mapping(row) if row is not None else None

    def list_document_reviews(
        self,
        *,
        tenant_id: str,
        project_id: str,
        status: DocumentReviewStatus | str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> DocumentReviewPage:
        normalized_tenant_id = normalize_uuid_string(tenant_id)
        normalized_project_id = normalize_uuid_string(project_id)
        normalized_status = _normalize_review_status(status)
        normalized_limit, normalized_offset = _normalize_limit_offset(
            limit=limit,
            offset=offset,
        )
        criteria = [
            DOCUMENT_DIFF_REVIEWS_TABLE.c.tenant_id == normalized_tenant_id,
            DOCUMENT_DIFF_REVIEWS_TABLE.c.project_id == normalized_project_id,
        ]
        if normalized_status is not None:
            criteria.append(
                DOCUMENT_DIFF_REVIEWS_TABLE.c.status == normalized_status.value
            )
        with self._engine.connect() as connection:
            total = int(
                connection.execute(
                    select(func.count())
                    .select_from(DOCUMENT_DIFF_REVIEWS_TABLE)
                    .where(and_(*criteria))
                ).scalar_one()
            )
            rows = (
                connection.execute(
                    select(DOCUMENT_DIFF_REVIEWS_TABLE)
                    .where(and_(*criteria))
                    .order_by(desc(DOCUMENT_DIFF_REVIEWS_TABLE.c.created_at))
                    .limit(normalized_limit)
                    .offset(normalized_offset)
                )
                .mappings()
                .all()
            )
            review_ids = [str(row["id"]) for row in rows]
            diff_ids = [str(row["document_diff_id"]) for row in rows]
            event_map = self._load_review_events(connection, review_ids=review_ids)
            diff_map = self._load_diffs_by_id(connection, diff_ids=diff_ids)
        reviews = [
            self._build_review_detail(
                row=row,
                diff=diff_map[str(row["document_diff_id"])],
                events=event_map.get(str(row["id"]), []),
            )
            for row in rows
        ]
        return DocumentReviewPage(
            reviews=reviews,
            total=total,
            limit=normalized_limit,
            offset=normalized_offset,
        )

    def get_document_review(
        self,
        *,
        tenant_id: str,
        review_id: str,
    ) -> DocumentReviewDetail | None:
        normalized_tenant_id = normalize_uuid_string(tenant_id)
        normalized_review_id = normalize_uuid_string(review_id)
        with self._engine.connect() as connection:
            row = (
                connection.execute(
                    select(DOCUMENT_DIFF_REVIEWS_TABLE)
                    .where(
                        and_(
                            DOCUMENT_DIFF_REVIEWS_TABLE.c.tenant_id
                            == normalized_tenant_id,
                            DOCUMENT_DIFF_REVIEWS_TABLE.c.id == normalized_review_id,
                        )
                    )
                    .limit(1)
                )
                .mappings()
                .first()
            )
            if row is None:
                return None
            event_map = self._load_review_events(
                connection, review_ids=[normalized_review_id]
            )
            diff_map = self._load_diffs_by_id(
                connection,
                diff_ids=[str(row["document_diff_id"])],
            )
        return self._build_review_detail(
            row=row,
            diff=diff_map[str(row["document_diff_id"])],
            events=event_map.get(normalized_review_id, []),
        )

    def apply_document_review_action(
        self,
        *,
        tenant_id: str,
        review_id: str,
        action: DocumentReviewAction | str,
        actor_subject: str | None = None,
        note: str | None = None,
    ) -> DocumentReviewDetail:
        normalized_tenant_id = normalize_uuid_string(tenant_id)
        normalized_review_id = normalize_uuid_string(review_id)
        normalized_action = _normalize_review_action(action)
        now = datetime.now(UTC)
        with self._engine.begin() as connection:
            row = (
                connection.execute(
                    select(DOCUMENT_DIFF_REVIEWS_TABLE)
                    .where(
                        and_(
                            DOCUMENT_DIFF_REVIEWS_TABLE.c.tenant_id
                            == normalized_tenant_id,
                            DOCUMENT_DIFF_REVIEWS_TABLE.c.id == normalized_review_id,
                        )
                    )
                    .limit(1)
                )
                .mappings()
                .first()
            )
            if row is None:
                raise KeyError(normalized_review_id)
            current_status = DocumentReviewStatus(str(row["status"]))
            if normalized_action is DocumentReviewAction.APPROVE:
                if current_status is not DocumentReviewStatus.PENDING:
                    raise ValueError("approve action requires pending review status")
                next_status = DocumentReviewStatus.APPROVED
                event_type = DocumentReviewEventType.APPROVED
                resolved_at = now
            elif normalized_action is DocumentReviewAction.REJECT:
                if current_status is not DocumentReviewStatus.PENDING:
                    raise ValueError("reject action requires pending review status")
                next_status = DocumentReviewStatus.REJECTED
                event_type = DocumentReviewEventType.REJECTED
                resolved_at = now
            else:
                if current_status is DocumentReviewStatus.PENDING:
                    raise ValueError(
                        "reopen action requires approved or rejected review status"
                    )
                next_status = DocumentReviewStatus.PENDING
                event_type = DocumentReviewEventType.REOPENED
                resolved_at = None
            connection.execute(
                update(DOCUMENT_DIFF_REVIEWS_TABLE)
                .where(
                    and_(
                        DOCUMENT_DIFF_REVIEWS_TABLE.c.tenant_id == normalized_tenant_id,
                        DOCUMENT_DIFF_REVIEWS_TABLE.c.id == normalized_review_id,
                    )
                )
                .values(
                    status=next_status.value,
                    resolved_at=resolved_at,
                    updated_at=now,
                )
            )
            self._append_review_event(
                connection,
                tenant_id=normalized_tenant_id,
                project_id=str(row["project_id"]),
                review_id=normalized_review_id,
                document_diff_id=str(row["document_diff_id"]),
                event_type=event_type,
                actor_subject=actor_subject,
                note=note,
                from_status=current_status,
                to_status=next_status,
                created_at=now,
            )
        detail = self.get_document_review(
            tenant_id=normalized_tenant_id,
            review_id=normalized_review_id,
        )
        if detail is None:
            raise KeyError(normalized_review_id)
        return detail

    def get_download_url(
        self, *, tenant_id: str, document_id: str, expires_in: int = 300
    ) -> str:
        document = self.get_document(tenant_id=tenant_id, document_id=document_id)
        if document is None:
            raise KeyError(document_id)
        return self._artifact_store.download_url(
            document.storage_key, expires_in=expires_in
        )


class FilesystemDocumentRepository(SqlDocumentRepository):
    """Compatibility wrapper for local filesystem blob storage plus SQLite metadata."""

    def __init__(self, base_dir: Path | str) -> None:
        root = Path(base_dir)
        super().__init__(
            database_url=f"sqlite+pysqlite:///{root / 'document_metadata.sqlite3'}",
            artifact_store=LocalArtifactStore(root),
            bootstrap_schema=True,
        )


def create_document_repository(
    *,
    database_url: str,
    engine: Engine | None = None,
    storage_backend: str = "local",
    artifact_root: Path | str | None = None,
    s3_bucket: str | None = None,
    s3_prefix: str = "",
    s3_client=None,
    supabase_url: str | None = None,
    supabase_service_role_key: str | None = None,
    supabase_client=None,
) -> SqlDocumentRepository:
    normalized_backend = storage_backend.strip().lower()
    if normalized_backend == "local":
        if artifact_root is None:
            raise ValueError("artifact_root is required for local artifact storage")
        artifact_store: ArtifactStore = LocalArtifactStore(artifact_root)
    elif normalized_backend == "s3":
        if not s3_bucket:
            raise ValueError("s3_bucket is required for s3 artifact storage")
        artifact_store = S3ArtifactStore(
            bucket=s3_bucket,
            prefix=s3_prefix,
            client=s3_client,
        )
    elif normalized_backend == "supabase":
        if not supabase_url:
            raise ValueError("supabase_url is required for supabase artifact storage")
        if not supabase_service_role_key:
            raise ValueError(
                "supabase_service_role_key is required for supabase artifact storage"
            )
        if not s3_bucket:
            raise ValueError(
                "artifact_bucket is required for supabase artifact storage"
            )
        artifact_store = SupabaseArtifactStore(
            project_url=supabase_url,
            service_role_key=supabase_service_role_key,
            bucket=s3_bucket,
            prefix=s3_prefix,
            client=supabase_client,
        )
    else:
        raise ValueError(f"Unsupported storage backend: {storage_backend}")

    return SqlDocumentRepository(
        database_url=database_url,
        artifact_store=artifact_store,
        engine=engine,
        bootstrap_schema=is_sqlite_url(database_url),
    )
