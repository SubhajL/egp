"""Service layer for document ingestion and retrieval."""

from __future__ import annotations

import base64
import binascii
from typing import TYPE_CHECKING

from egp_api.services.entitlement_service import TenantEntitlementService
from egp_db.repositories.document_repo import SqlDocumentRepository, StoreDocumentResult
from egp_shared_types.enums import DocumentType, NotificationType

if TYPE_CHECKING:
    from egp_db.repositories.project_repo import SqlProjectRepository
    from egp_notifications.dispatcher import NotificationDispatcher


class DocumentIngestService:
    def __init__(
        self,
        repository: SqlDocumentRepository,
        *,
        entitlement_service: TenantEntitlementService | None = None,
        project_repository: SqlProjectRepository | None = None,
        notification_dispatcher: NotificationDispatcher | None = None,
    ) -> None:
        self._repository = repository
        self._entitlement_service = entitlement_service
        self._project_repository = project_repository
        self._notification_dispatcher = notification_dispatcher

    def _resolve_project_context(
        self, *, tenant_id: str, project_id: str, source_status_text: str
    ) -> tuple[str, str | None]:
        if self._project_repository is None:
            return (source_status_text, None)
        project = self._project_repository.get_project(tenant_id=tenant_id, project_id=project_id)
        if project is None:
            return (source_status_text, None)
        resolved_status_text = source_status_text or (project.source_status_text or "")
        return (resolved_status_text, project.project_state.value)

    def ingest_document_bytes(
        self,
        *,
        tenant_id: str,
        project_id: str,
        file_name: str,
        file_bytes: bytes,
        source_label: str,
        source_status_text: str,
        source_page_text: str = "",
    ) -> StoreDocumentResult:
        resolved_status_text, project_state = self._resolve_project_context(
            tenant_id=tenant_id,
            project_id=project_id,
            source_status_text=source_status_text,
        )
        result = self._repository.store_document(
            tenant_id=tenant_id,
            project_id=project_id,
            file_name=file_name,
            file_bytes=file_bytes,
            source_label=source_label,
            source_status_text=resolved_status_text,
            source_page_text=source_page_text,
            project_state=project_state,
        )
        if (
            self._notification_dispatcher is not None
            and self._project_repository is not None
            and result.created
            and any(diff.diff_type == "changed" for diff in result.diff_records)
            and result.document.document_type is DocumentType.TOR
        ):
            project = self._project_repository.get_project(
                tenant_id=tenant_id, project_id=project_id
            )
            if project is not None:
                self._notification_dispatcher.dispatch(
                    tenant_id=tenant_id,
                    notification_type=NotificationType.TOR_CHANGED,
                    project_id=project_id,
                    template_vars={
                        "project_name": project.project_name,
                        "organization": project.organization_name or "",
                    },
                )
        return result

    def ingest_document(
        self,
        *,
        tenant_id: str,
        project_id: str,
        file_name: str,
        content_base64: str,
        source_label: str,
        source_status_text: str,
        source_page_text: str = "",
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
            source_page_text=source_page_text,
        )

    def list_documents(self, *, tenant_id: str, project_id: str):
        return self._repository.list_documents(tenant_id, project_id)

    def list_document_diffs(self, *, tenant_id: str, project_id: str):
        return self._repository.list_document_diffs(
            tenant_id=tenant_id,
            project_id=project_id,
        )

    def get_document_diff(
        self,
        *,
        tenant_id: str,
        document_id: str,
        other_document_id: str,
    ):
        return self._repository.get_document_diff(
            tenant_id=tenant_id,
            document_id=document_id,
            other_document_id=other_document_id,
        )

    def get_download_url(
        self,
        *,
        tenant_id: str,
        document_id: str,
        expires_in: int = 300,
    ) -> str:
        if self._entitlement_service is not None:
            self._entitlement_service.require_active_subscription(
                tenant_id=tenant_id,
                capability="document downloads",
            )
        return self._repository.get_download_url(
            tenant_id=tenant_id,
            document_id=document_id,
            expires_in=expires_in,
        )
