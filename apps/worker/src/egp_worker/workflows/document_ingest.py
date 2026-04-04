"""Worker-side document ingestion helpers."""

from __future__ import annotations

from pathlib import Path

from egp_db.repositories.document_repo import (
    SqlDocumentRepository,
    StoreDocumentResult,
    create_document_repository,
)


def ingest_document_artifact(
    *,
    artifact_root: Path | str,
    database_url: str | None = None,
    artifact_storage_backend: str = "local",
    artifact_bucket: str | None = None,
    artifact_prefix: str = "",
    s3_client=None,
    supabase_url: str | None = None,
    supabase_service_role_key: str | None = None,
    supabase_client=None,
    repository: SqlDocumentRepository | None = None,
    tenant_id: str,
    project_id: str,
    file_name: str,
    file_bytes: bytes,
    source_label: str,
    source_status_text: str,
) -> StoreDocumentResult:
    resolved_artifact_root = Path(artifact_root)
    if repository is None:
        repository = create_document_repository(
            database_url=database_url
            or f"sqlite+pysqlite:///{resolved_artifact_root / 'document_metadata.sqlite3'}",
            storage_backend=artifact_storage_backend,
            artifact_root=resolved_artifact_root,
            s3_bucket=artifact_bucket,
            s3_prefix=artifact_prefix,
            s3_client=s3_client,
            supabase_url=supabase_url,
            supabase_service_role_key=supabase_service_role_key,
            supabase_client=supabase_client,
        )
    return repository.store_document(
        tenant_id=tenant_id,
        project_id=project_id,
        file_name=file_name,
        file_bytes=file_bytes,
        source_label=source_label,
        source_status_text=source_status_text,
    )
