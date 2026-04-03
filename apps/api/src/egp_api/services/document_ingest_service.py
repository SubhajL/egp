"""Service layer for document ingestion and retrieval."""

from __future__ import annotations

import base64
import binascii

from egp_db.repositories.document_repo import SqlDocumentRepository, StoreDocumentResult


class DocumentIngestService:
    def __init__(self, repository: SqlDocumentRepository) -> None:
        self._repository = repository

    def ingest_document_bytes(
        self,
        *,
        tenant_id: str,
        project_id: str,
        file_name: str,
        file_bytes: bytes,
        source_label: str,
        source_status_text: str,
    ) -> StoreDocumentResult:
        return self._repository.store_document(
            tenant_id=tenant_id,
            project_id=project_id,
            file_name=file_name,
            file_bytes=file_bytes,
            source_label=source_label,
            source_status_text=source_status_text,
        )

    def ingest_document(
        self,
        *,
        tenant_id: str,
        project_id: str,
        file_name: str,
        content_base64: str,
        source_label: str,
        source_status_text: str,
    ) -> StoreDocumentResult:
        try:
            file_bytes = base64.b64decode(content_base64, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise ValueError("content_base64 must be valid base64") from exc

        return self.ingest_document_bytes(
            tenant_id=tenant_id,
            project_id=project_id,
            file_name=file_name,
            file_bytes=file_bytes,
            source_label=source_label,
            source_status_text=source_status_text,
        )

    def list_documents(self, *, tenant_id: str, project_id: str):
        return self._repository.list_documents(tenant_id, project_id)

    def get_download_url(
        self,
        *,
        tenant_id: str,
        document_id: str,
        expires_in: int = 300,
    ) -> str:
        return self._repository.get_download_url(
            tenant_id=tenant_id,
            document_id=document_id,
            expires_in=expires_in,
        )
