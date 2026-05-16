"""Document repository mapping and normalization helpers."""

from __future__ import annotations

from datetime import UTC, datetime
import mimetypes
import re
from uuid import uuid4

from sqlalchemy.engine import RowMapping

from egp_shared_types.enums import (
    DocumentPhase,
    DocumentReviewAction,
    DocumentReviewEventType,
    DocumentReviewStatus,
    DocumentType,
)

from .document_models import (
    DocumentDiffRecord,
    DocumentRecord,
    DocumentReviewEventRecord,
)


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _sanitize_file_name(file_name: str) -> str:
    sanitized = str(file_name or "").replace("\n", " ").replace("\r", " ").strip()
    sanitized = re.sub(r'[\\/*?:"<>|]+', "_", sanitized)
    sanitized = re.sub(r"\s+", " ", sanitized).strip().rstrip(".")
    return sanitized or "artifact.bin"


def _document_from_mapping(row: RowMapping) -> DocumentRecord:
    created_at = row["created_at"]
    return DocumentRecord(
        id=str(row["id"]),
        project_id=str(row["project_id"]),
        file_name=str(row["file_name"]),
        sha256=str(row["sha256"]),
        storage_key=str(row["storage_key"]),
        managed_backup_storage_key=(
            str(row["managed_backup_storage_key"])
            if "managed_backup_storage_key" in row
            and row["managed_backup_storage_key"] is not None
            else None
        ),
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


def _guess_content_type(file_name: str) -> str:
    guessed, _ = mimetypes.guess_type(file_name)
    return guessed or "application/octet-stream"


def _document_repo_facade():
    from egp_db.repositories import document_repo

    return document_repo


def build_document_record(
    *,
    project_id: str,
    file_name: str,
    file_bytes: bytes,
    source_label: str,
    source_status_text: str,
    storage_key: str,
    managed_backup_storage_key: str | None = None,
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
        else _document_repo_facade().classify_document(
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
        sha256=sha256 or _document_repo_facade().hash_file(file_bytes),
        storage_key=storage_key,
        managed_backup_storage_key=managed_backup_storage_key,
        document_type=resolved_document_type,
        document_phase=resolved_document_phase,
        source_label=source_label,
        source_status_text=source_status_text,
        size_bytes=len(file_bytes),
        is_current=is_current,
        supersedes_document_id=supersedes_document_id,
        created_at=created_at or _now_iso(),
    )
