"""Service layer for document ingestion and retrieval."""

from __future__ import annotations

import base64
import binascii
from dataclasses import dataclass
import logging
from typing import TYPE_CHECKING

from egp_api.services.entitlement_service import TenantEntitlementService
from egp_db.repositories.audit_repo import SqlAuditRepository
from egp_db.repositories.document_repo import (
    DocumentContentResult,
    DocumentContentStream,
    SqlDocumentRepository,
    StoreDocumentResult,
)
from egp_shared_types.enums import (
    DocumentReviewAction,
    DocumentReviewEventType,
    DocumentReviewStatus,
    DocumentType,
    NotificationType,
)

if TYPE_CHECKING:
    from egp_db.repositories.project_repo import SqlProjectRepository
    from egp_notifications.dispatcher import NotificationDispatcher

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DocumentDownloadLink:
    """Resolved download link for a document.

    ``url`` is set when the underlying artifact store can produce a
    browser-usable HTTP(S) URL (e.g. a Supabase signed URL). When the artifact
    store can only return a local filesystem path or otherwise non-HTTP value,
    ``url`` is ``None`` and callers should fall back to the proxied download
    endpoint.
    """

    url: str | None
    filename: str
    size_bytes: int
    sha256: str


class DocumentIngestService:
    def __init__(
        self,
        repository: SqlDocumentRepository,
        *,
        entitlement_service: TenantEntitlementService | None = None,
        project_repository: SqlProjectRepository | None = None,
        notification_dispatcher: NotificationDispatcher | None = None,
        audit_repository: SqlAuditRepository | None = None,
    ) -> None:
        self._repository = repository
        self._entitlement_service = entitlement_service
        self._project_repository = project_repository
        self._notification_dispatcher = notification_dispatcher
        self._audit_repository = audit_repository

    def _resolve_project_context(
        self,
        *,
        tenant_id: str,
        project_id: str,
        source_status_text: str,
        project_state: str | None = None,
    ) -> tuple[str, str | None]:
        if self._project_repository is None:
            return (source_status_text, project_state)
        project = self._project_repository.get_project(tenant_id=tenant_id, project_id=project_id)
        if project is None:
            return (source_status_text, project_state)
        resolved_status_text = source_status_text or (project.source_status_text or "")
        resolved_project_state = project_state or project.project_state.value
        return (resolved_status_text, resolved_project_state)

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
        project_state: str | None = None,
        actor_subject: str | None = None,
    ) -> StoreDocumentResult:
        resolved_actor_subject = actor_subject or "system:api"
        resolved_status_text, resolved_project_state = self._resolve_project_context(
            tenant_id=tenant_id,
            project_id=project_id,
            source_status_text=source_status_text,
            project_state=project_state,
        )
        logger.info(
            "Canonical document ingest started for %s",
            file_name,
            extra={
                "egp_event": "document_ingest_canonical_started",
                "tenant_id": tenant_id,
                "project_id": project_id,
                "file_name": file_name,
                "source_label": source_label,
                "source_status_present": bool(resolved_status_text),
                "source_page_text_present": bool(source_page_text),
                "project_state": resolved_project_state,
                "actor_subject": resolved_actor_subject,
            },
        )
        result = self._repository.store_document(
            tenant_id=tenant_id,
            project_id=project_id,
            file_name=file_name,
            file_bytes=file_bytes,
            source_label=source_label,
            source_status_text=resolved_status_text,
            source_page_text=source_page_text,
            project_state=resolved_project_state,
        )
        if self._audit_repository is not None and result.created:
            self._audit_repository.record_event(
                tenant_id=tenant_id,
                source="document",
                entity_type="document",
                entity_id=result.document.id,
                project_id=project_id,
                document_id=result.document.id,
                actor_subject=resolved_actor_subject,
                event_type="document.created",
                summary=f"Stored document {result.document.file_name}",
                metadata_json={
                    "document_type": result.document.document_type.value,
                    "document_phase": result.document.document_phase.value,
                    "file_name": result.document.file_name,
                },
            )
        logger.info(
            "Canonical document ingest succeeded for %s",
            file_name,
            extra={
                "egp_event": "document_ingest_canonical_succeeded",
                "tenant_id": tenant_id,
                "project_id": project_id,
                "file_name": file_name,
                "document_id": result.document.id,
                "document_sha256": result.document.sha256,
                "document_type": result.document.document_type.value,
                "document_phase": result.document.document_phase.value,
                "document_created": result.created,
                "diff_record_count": len(result.diff_records),
                "actor_subject": resolved_actor_subject,
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
        actor_subject: str | None = None,
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
            actor_subject=actor_subject,
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

    def list_document_reviews(
        self,
        *,
        tenant_id: str,
        project_id: str,
        status: DocumentReviewStatus | str | None = None,
        limit: int = 50,
        offset: int = 0,
    ):
        return self._repository.list_document_reviews(
            tenant_id=tenant_id,
            project_id=project_id,
            status=status,
            limit=limit,
            offset=offset,
        )

    def apply_document_review_action(
        self,
        *,
        tenant_id: str,
        review_id: str,
        action: DocumentReviewAction | str,
        actor_subject: str | None = None,
        note: str | None = None,
    ):
        detail = self._repository.apply_document_review_action(
            tenant_id=tenant_id,
            review_id=review_id,
            action=action,
            actor_subject=actor_subject,
            note=note,
        )
        approved_event_count = sum(
            1 for event in detail.events if event.event_type is DocumentReviewEventType.APPROVED
        )
        if (
            approved_event_count == 1
            and detail.status is DocumentReviewStatus.APPROVED
            and self._notification_dispatcher is not None
            and self._project_repository is not None
        ):
            new_document = self._repository.get_document(
                tenant_id=tenant_id,
                document_id=detail.diff.new_document_id,
            )
            if new_document is not None and new_document.document_type is DocumentType.TOR:
                project = self._project_repository.get_project(
                    tenant_id=tenant_id,
                    project_id=detail.project_id,
                )
                if project is not None:
                    self._notification_dispatcher.dispatch(
                        tenant_id=tenant_id,
                        notification_type=NotificationType.TOR_CHANGED,
                        project_id=detail.project_id,
                        template_vars={
                            "project_name": project.project_name,
                            "organization": project.organization_name or "",
                        },
                    )
        return detail

    def get_download_url(
        self,
        *,
        tenant_id: str,
        document_id: str,
        expires_in: int = 300,
    ) -> str:
        if self._entitlement_service is not None:
            self._entitlement_service.require_capability(
                tenant_id=tenant_id,
                capability="document_downloads",
            )
        return self._repository.get_download_url(
            tenant_id=tenant_id,
            document_id=document_id,
            expires_in=expires_in,
        )

    def download_document(
        self,
        *,
        tenant_id: str,
        document_id: str,
    ) -> DocumentContentResult:
        if self._entitlement_service is not None:
            self._entitlement_service.require_capability(
                tenant_id=tenant_id,
                capability="document_downloads",
            )
        return self._repository.get_document_content(
            tenant_id=tenant_id,
            document_id=document_id,
        )

    def iter_document_bytes(
        self,
        *,
        tenant_id: str,
        document_id: str,
        chunk_size: int | None = None,
    ) -> DocumentContentStream:
        """Streaming variant of :meth:`download_document`.

        Performs the entitlement check and returns a chunk iterator over the
        document bytes plus the metadata needed to set response headers.
        ``chunk_size`` defaults to the artifact store layer's default.
        """
        if self._entitlement_service is not None:
            self._entitlement_service.require_capability(
                tenant_id=tenant_id,
                capability="document_downloads",
            )
        if chunk_size is None:
            return self._repository.iter_document_bytes(
                tenant_id=tenant_id,
                document_id=document_id,
            )
        return self._repository.iter_document_bytes(
            tenant_id=tenant_id,
            document_id=document_id,
            chunk_size=chunk_size,
        )

    def get_document_metadata(
        self,
        *,
        tenant_id: str,
        document_id: str,
    ):
        """Return document metadata after the entitlement check.

        Used by the download route to short-circuit ``If-None-Match`` requests
        without ever fetching the artifact bytes.
        """
        if self._entitlement_service is not None:
            self._entitlement_service.require_capability(
                tenant_id=tenant_id,
                capability="document_downloads",
            )
        document = self._repository.get_document(tenant_id=tenant_id, document_id=document_id)
        if document is None:
            raise KeyError(document_id)
        return document

    def get_document_download_link(
        self,
        *,
        tenant_id: str,
        document_id: str,
        expires_in: int = 300,
    ) -> DocumentDownloadLink:
        """Resolve a browser-usable download link for ``document_id``.

        Performs the entitlement check, loads document metadata for the link
        payload, and attempts to obtain a signed URL from the resolved
        artifact store. When the store returns a value that is not an HTTP(S)
        URL (for example, the local filesystem store returns a filesystem
        path), the returned ``DocumentDownloadLink.url`` is ``None`` and the
        caller is expected to fall back to the proxied download endpoint.
        """
        if self._entitlement_service is not None:
            self._entitlement_service.require_capability(
                tenant_id=tenant_id,
                capability="document_downloads",
            )
        document = self._repository.get_document(tenant_id=tenant_id, document_id=document_id)
        if document is None:
            raise KeyError(document_id)

        signed_url: str | None
        try:
            candidate = self._repository.get_download_url(
                tenant_id=tenant_id,
                document_id=document_id,
                expires_in=expires_in,
            )
        except Exception:  # noqa: BLE001 - fall back to proxy on any resolver error
            signed_url = None
        else:
            signed_url = (
                candidate
                if isinstance(candidate, str)
                and (candidate.startswith("https://") or candidate.startswith("http://"))
                else None
            )

        return DocumentDownloadLink(
            url=signed_url,
            filename=document.file_name,
            size_bytes=document.size_bytes,
            sha256=document.sha256,
        )
