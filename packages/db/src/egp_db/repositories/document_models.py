"""Document repository record types and errors."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass

from egp_shared_types.enums import (
    DocumentPhase,
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
    managed_backup_storage_key: str | None
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
class DocumentContentResult:
    document: DocumentRecord
    file_bytes: bytes
    content_type: str


@dataclass(frozen=True, slots=True)
class DocumentContentStream:
    """Streaming counterpart of :class:`DocumentContentResult`.

    ``chunks`` is an iterator that yields the document bytes in chunks; the
    iterator must be fully consumed (or closed) by the caller. ``content_type``
    and ``document`` mirror :class:`DocumentContentResult` so callers can build
    response headers (Content-Type, Content-Length, ETag) without re-fetching
    metadata.
    """

    document: DocumentRecord
    chunks: "Iterator[bytes]"
    content_type: str


class DocumentArtifactReadError(RuntimeError):
    def __init__(
        self,
        *,
        document_id: str,
        storage_key: str,
        managed_backup_storage_key: str | None,
        provider: str,
        cause: Exception,
    ) -> None:
        self.document_id = document_id
        self.storage_key = storage_key
        self.managed_backup_storage_key = managed_backup_storage_key
        self.provider = provider
        self.cause = cause
        super().__init__(
            f"failed to read document artifact {document_id} from {provider}: {cause}"
        )


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
