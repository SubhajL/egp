"""Compatibility facade for document repository persistence."""

from __future__ import annotations

from pathlib import Path

from sqlalchemy.engine import Engine

from egp_crawler_core.document_hasher import hash_file
from egp_db.artifact_store import (
    ArtifactStore,
    LocalArtifactStore,
    S3ArtifactStore,
    SupabaseArtifactStore,
)
from egp_db.connection import create_shared_engine
from egp_db.db_utils import is_sqlite_url, normalize_database_url
from egp_db.tenant_storage_resolver import TenantArtifactStoreResolver
from egp_document_classifier.classifier import classify_document

from .document_delivery import DocumentDeliveryMixin
from .document_diffs import DocumentDiffMixin
from .document_models import (
    DocumentArtifactReadError,
    DocumentContentResult,
    DocumentContentStream,
    DocumentDiffRecord,
    DocumentRecord,
    DocumentReviewDetail,
    DocumentReviewEventRecord,
    DocumentReviewPage,
    StoreDocumentResult,
)
from .document_persistence import DocumentPersistenceMixin
from .document_reviews import DocumentReviewMixin
from .document_schema import (
    DOCUMENTS_TABLE,
    DOCUMENT_DIFFS_TABLE,
    DOCUMENT_DIFF_REVIEWS_TABLE,
    DOCUMENT_REVIEW_EVENTS_TABLE,
    METADATA,
)
from .document_utils import build_document_record


__all__ = [
    "DOCUMENTS_TABLE",
    "DOCUMENT_DIFFS_TABLE",
    "DOCUMENT_DIFF_REVIEWS_TABLE",
    "DOCUMENT_REVIEW_EVENTS_TABLE",
    "METADATA",
    "DocumentArtifactReadError",
    "DocumentContentResult",
    "DocumentContentStream",
    "DocumentDiffRecord",
    "DocumentRecord",
    "DocumentReviewDetail",
    "DocumentReviewEventRecord",
    "DocumentReviewPage",
    "FilesystemDocumentRepository",
    "SqlDocumentRepository",
    "StoreDocumentResult",
    "build_document_record",
    "classify_document",
    "create_artifact_store",
    "create_document_repository",
    "hash_file",
]


class SqlDocumentRepository(
    DocumentPersistenceMixin,
    DocumentDiffMixin,
    DocumentReviewMixin,
    DocumentDeliveryMixin,
):
    """Relational document metadata repository with pluggable blob storage."""

    def __init__(
        self,
        *,
        database_url: str | None = None,
        artifact_store: ArtifactStore,
        artifact_store_resolver: TenantArtifactStoreResolver | None = None,
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
        self._artifact_store_resolver = artifact_store_resolver
        self._engine = engine or create_shared_engine(normalized_url or "")
        if bootstrap_schema:
            self._ensure_schema()


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
    artifact_store_resolver: TenantArtifactStoreResolver | None = None,
) -> SqlDocumentRepository:
    artifact_store = create_artifact_store(
        storage_backend=storage_backend,
        artifact_root=artifact_root,
        s3_bucket=s3_bucket,
        s3_prefix=s3_prefix,
        s3_client=s3_client,
        supabase_url=supabase_url,
        supabase_service_role_key=supabase_service_role_key,
        supabase_client=supabase_client,
    )
    return SqlDocumentRepository(
        database_url=database_url,
        artifact_store=artifact_store,
        artifact_store_resolver=artifact_store_resolver,
        engine=engine,
        bootstrap_schema=is_sqlite_url(database_url),
    )


def create_artifact_store(
    *,
    storage_backend: str = "local",
    artifact_root: Path | str | None = None,
    s3_bucket: str | None = None,
    s3_prefix: str = "",
    s3_client=None,
    supabase_url: str | None = None,
    supabase_service_role_key: str | None = None,
    supabase_client=None,
) -> ArtifactStore:
    normalized_backend = storage_backend.strip().lower()
    if normalized_backend == "local":
        if artifact_root is None:
            raise ValueError("artifact_root is required for local artifact storage")
        return LocalArtifactStore(artifact_root)
    elif normalized_backend == "s3":
        if not s3_bucket:
            raise ValueError("s3_bucket is required for s3 artifact storage")
        return S3ArtifactStore(
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
        return SupabaseArtifactStore(
            project_url=supabase_url,
            service_role_key=supabase_service_role_key,
            bucket=s3_bucket,
            prefix=s3_prefix,
            client=supabase_client,
        )
    else:
        raise ValueError(f"Unsupported storage backend: {storage_backend}")
