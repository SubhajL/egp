"""Repository-level document record builders and relational persistence."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import mimetypes
from pathlib import Path
import re
from uuid import uuid4

from sqlalchemy import (
    Boolean,
    DateTime,
    Index,
    Integer,
    String,
    Table,
    UniqueConstraint,
    and_,
    desc,
)
from sqlalchemy import Column, insert, select, update
from sqlalchemy.engine import Engine, RowMapping

from egp_crawler_core.document_hasher import hash_file
from egp_db.artifact_store import ArtifactStore, LocalArtifactStore, S3ArtifactStore, SupabaseArtifactStore
from egp_db.connection import DB_METADATA, create_shared_engine
from egp_db.db_utils import UUID_SQL_TYPE, is_sqlite_url, normalize_database_url, normalize_uuid_string
from egp_document_classifier.classifier import classify_document
from egp_shared_types.enums import DocumentPhase, DocumentType


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
    created_at: str


@dataclass(frozen=True, slots=True)
class StoreDocumentResult:
    created: bool
    document: DocumentRecord
    diff_records: list[DocumentDiffRecord]


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
        created_at=created_at.isoformat() if isinstance(created_at, datetime) else str(created_at),
    )


def _diff_from_mapping(row: RowMapping) -> DocumentDiffRecord:
    created_at = row["created_at"]
    return DocumentDiffRecord(
        id=str(row["id"]),
        project_id=str(row["project_id"]),
        old_document_id=str(row["old_document_id"]),
        new_document_id=str(row["new_document_id"]),
        diff_type=str(row["diff_type"]),
        created_at=created_at.isoformat() if isinstance(created_at, datetime) else str(created_at),
    )


def _to_db_timestamp(value: str) -> datetime:
    return datetime.fromisoformat(value)


def build_document_record(
    *,
    project_id: str,
    file_name: str,
    file_bytes: bytes,
    source_label: str,
    source_status_text: str,
    storage_key: str,
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
        normalized_url = normalize_database_url(database_url) if database_url is not None else None
        self._database_url = normalized_url
        self._artifact_store = artifact_store
        self._engine = engine or create_shared_engine(normalized_url or "")
        if bootstrap_schema:
            self._ensure_schema()

    def _ensure_schema(self) -> None:
        METADATA.create_all(self._engine)

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
        row = connection.execute(
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
        ).mappings().first()
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
        row = connection.execute(
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
        ).mappings().first()
        return _document_from_mapping(row) if row is not None else None

    def store_document(
        self,
        *,
        tenant_id: str,
        project_id: str,
        file_name: str,
        file_bytes: bytes,
        source_label: str,
        source_status_text: str,
    ) -> StoreDocumentResult:
        tenant_id = normalize_uuid_string(tenant_id)
        project_id = normalize_uuid_string(project_id)
        document_sha256 = hash_file(file_bytes)
        document_type, document_phase = classify_document(
            label=source_label,
            source_status_text=source_status_text,
        )
        draft_document = build_document_record(
            project_id=project_id,
            file_name=file_name,
            file_bytes=file_bytes,
            source_label=source_label,
            source_status_text=source_status_text,
            storage_key="",
            sha256=document_sha256,
            document_type=document_type,
            document_phase=document_phase,
        )
        safe_name = _sanitize_file_name(file_name)
        blob_key = (
            f"tenants/{tenant_id}/projects/{project_id}/artifacts/{draft_document.sha256}/{safe_name}"
        )
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
                    supersedes_document_id=(
                        current_same_class.id if current_same_class is not None else None
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
                if current_same_class is not None:
                    diff_record = DocumentDiffRecord(
                        id=str(uuid4()),
                        project_id=project_id,
                        old_document_id=current_same_class.id,
                        new_document_id=stored_document.id,
                        diff_type="changed",
                        created_at=_now_iso(),
                    )
                    connection.execute(
                        insert(DOCUMENT_DIFFS_TABLE).values(
                            id=diff_record.id,
                            tenant_id=tenant_id,
                            project_id=diff_record.project_id,
                            old_document_id=diff_record.old_document_id,
                            new_document_id=diff_record.new_document_id,
                            diff_type=diff_record.diff_type,
                            created_at=_to_db_timestamp(diff_record.created_at),
                        )
                    )
                    new_diff_records.append(diff_record)

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
            rows = connection.execute(
                select(DOCUMENTS_TABLE)
                .where(
                    and_(
                        DOCUMENTS_TABLE.c.tenant_id == tenant_id,
                        DOCUMENTS_TABLE.c.project_id == project_id,
                    )
                )
                .order_by(desc(DOCUMENTS_TABLE.c.created_at))
            ).mappings().all()
        return [_document_from_mapping(row) for row in rows]

    def get_document(self, *, tenant_id: str, document_id: str) -> DocumentRecord | None:
        tenant_id = normalize_uuid_string(tenant_id)
        document_id = normalize_uuid_string(document_id)
        with self._engine.connect() as connection:
            row = connection.execute(
                select(DOCUMENTS_TABLE)
                .where(
                    and_(
                        DOCUMENTS_TABLE.c.tenant_id == tenant_id,
                        DOCUMENTS_TABLE.c.id == document_id,
                    )
                )
                .limit(1)
            ).mappings().first()
        return _document_from_mapping(row) if row is not None else None

    def get_download_url(self, *, tenant_id: str, document_id: str, expires_in: int = 300) -> str:
        document = self.get_document(tenant_id=tenant_id, document_id=document_id)
        if document is None:
            raise KeyError(document_id)
        return self._artifact_store.download_url(document.storage_key, expires_in=expires_in)


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
            raise ValueError("supabase_service_role_key is required for supabase artifact storage")
        if not s3_bucket:
            raise ValueError("artifact_bucket is required for supabase artifact storage")
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
