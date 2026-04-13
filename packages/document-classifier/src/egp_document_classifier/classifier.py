"""Document classification helpers for e-GP artifacts."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import re

from egp_shared_types.enums import (
    ArtifactBucket,
    DocumentPhase,
    DocumentType,
    ProjectState,
)


_PUBLIC_HEARING_MARKERS = (
    "ประชาพิจารณ์",
    "รับฟังคำวิจารณ์",
    "รับฟังความคิดเห็น",
    "hearing",
)
_DRAFT_TOR_MARKERS = (
    "ร่างเอกสารประกวดราคา",
    "ร่างขอบเขตของงาน",
    "ร่างทีโออาร์",
    "draft tor",
    "draft terms of reference",
)
_TOR_MARKERS = (
    "เอกสารประกวดราคา",
    "ขอบเขตของงาน",
    "เอกสารจ้างที่ปรึกษา",
    "terms of reference",
)
_INVITATION_MARKERS = ("ประกาศเชิญชวน", "หนังสือเชิญชวน")
_MID_PRICE_MARKERS = ("ประกาศราคากลาง", "ราคากลาง")
_TOR_TOKEN_PATTERN = re.compile(r"(?<![a-z0-9])tor(?![a-z0-9])", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class DocumentClassification:
    document_type: DocumentType
    document_phase: DocumentPhase
    matched_markers: tuple[str, ...] = ()


def _normalize_text(value: str | None) -> str:
    return str(value or "").strip().casefold()


def _find_text_markers(text: str, markers: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(marker for marker in markers if marker.casefold() in text)


def _contains_tor_marker(text: str) -> tuple[str, ...]:
    matched_text_markers = _find_text_markers(text, _TOR_MARKERS + _DRAFT_TOR_MARKERS)
    matched_token_markers = ("tor",) if _TOR_TOKEN_PATTERN.search(text) else ()
    return matched_text_markers + matched_token_markers


def _normalize_project_state(project_state: ProjectState | str | None) -> str:
    if project_state is None:
        return ""
    if isinstance(project_state, ProjectState):
        return project_state.value
    return str(project_state).strip().casefold()


def classify_document_details(
    *,
    label: str,
    source_status_text: str = "",
    source_page_text: str = "",
    project_state: ProjectState | str | None = None,
    file_name: str = "",
) -> DocumentClassification:
    normalized_label = _normalize_text(label)
    normalized_status = _normalize_text(source_status_text)
    normalized_page = _normalize_text(source_page_text)
    normalized_file_name = _normalize_text(file_name)
    normalized_project_state = _normalize_project_state(project_state)
    combined_text = " ".join(
        part
        for part in (
            normalized_label,
            normalized_status,
            normalized_page,
            normalized_file_name,
        )
        if part
    )

    tor_markers = _contains_tor_marker(combined_text)
    if tor_markers:
        matched_markers = list(tor_markers)
        if normalized_project_state == ProjectState.OPEN_PUBLIC_HEARING.value:
            matched_markers.append("project_state:open_public_hearing")
            return DocumentClassification(
                document_type=DocumentType.TOR,
                document_phase=DocumentPhase.PUBLIC_HEARING,
                matched_markers=tuple(matched_markers),
            )

        hearing_markers = _find_text_markers(combined_text, _PUBLIC_HEARING_MARKERS)
        draft_markers = _find_text_markers(combined_text, _DRAFT_TOR_MARKERS)
        if hearing_markers or draft_markers:
            return DocumentClassification(
                document_type=DocumentType.TOR,
                document_phase=DocumentPhase.PUBLIC_HEARING,
                matched_markers=tuple(
                    matched_markers + list(hearing_markers) + list(draft_markers)
                ),
            )

        return DocumentClassification(
            document_type=DocumentType.TOR,
            document_phase=DocumentPhase.FINAL,
            matched_markers=tuple(matched_markers),
        )

    invitation_markers = _find_text_markers(combined_text, _INVITATION_MARKERS)
    if invitation_markers:
        return DocumentClassification(
            document_type=DocumentType.INVITATION,
            document_phase=DocumentPhase.UNKNOWN,
            matched_markers=invitation_markers,
        )

    mid_price_markers = _find_text_markers(combined_text, _MID_PRICE_MARKERS)
    if mid_price_markers:
        return DocumentClassification(
            document_type=DocumentType.MID_PRICE,
            document_phase=DocumentPhase.UNKNOWN,
            matched_markers=mid_price_markers,
        )

    return DocumentClassification(
        document_type=DocumentType.OTHER,
        document_phase=DocumentPhase.UNKNOWN,
        matched_markers=(),
    )


def classify_document(
    *,
    label: str,
    source_status_text: str = "",
    source_page_text: str = "",
    project_state: ProjectState | str | None = None,
    file_name: str = "",
) -> tuple[DocumentType, DocumentPhase]:
    result = classify_document_details(
        label=label,
        source_status_text=source_status_text,
        source_page_text=source_page_text,
        project_state=project_state,
        file_name=file_name,
    )
    return (result.document_type, result.document_phase)


def derive_artifact_bucket(
    *,
    labels: Sequence[str] = (),
    documents: Sequence[Mapping[str, object]] = (),
) -> ArtifactBucket:
    """Collapse observed document evidence into one export/reporting bucket.

    The buckets are intentionally coarse because the legacy script and worker
    surfaces need one comparable value even when evidence came from filenames,
    source labels, or already-classified DB rows.
    """

    has_mid_price = False
    has_invitation = False
    has_draft_tor = False
    has_final_tor = False

    for document in documents:
        try:
            document_type = DocumentType(str(document.get("document_type") or "").strip())
        except ValueError:
            document_type = None
        try:
            document_phase = DocumentPhase(str(document.get("document_phase") or "").strip())
        except ValueError:
            document_phase = None

        if document_type is DocumentType.MID_PRICE:
            has_mid_price = True
            continue
        if document_type is DocumentType.INVITATION:
            has_invitation = True
            continue
        if document_type is DocumentType.TOR and document_phase is DocumentPhase.PUBLIC_HEARING:
            has_draft_tor = True
            continue
        if document_type is DocumentType.TOR and document_phase is DocumentPhase.FINAL:
            has_final_tor = True
            continue

    for label in labels:
        document_type, document_phase = classify_document(label=label)
        if document_type is DocumentType.MID_PRICE:
            has_mid_price = True
        elif document_type is DocumentType.INVITATION:
            has_invitation = True
        elif document_type is DocumentType.TOR and document_phase is DocumentPhase.PUBLIC_HEARING:
            has_draft_tor = True
        elif document_type is DocumentType.TOR and document_phase is DocumentPhase.FINAL:
            has_final_tor = True

    if has_final_tor:
        return ArtifactBucket.FINAL_TOR_DOWNLOADED
    if has_draft_tor:
        return ArtifactBucket.DRAFT_PLUS_PRICING
    if has_invitation and has_mid_price:
        return ArtifactBucket.INVITATION_PLUS_PRICING
    if has_mid_price:
        return ArtifactBucket.PRICING_ONLY
    return ArtifactBucket.NO_ARTIFACT_EVIDENCE
