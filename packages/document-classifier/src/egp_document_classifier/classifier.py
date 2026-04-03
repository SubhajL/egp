"""Document classification helpers for e-GP artifacts."""

from __future__ import annotations

from egp_shared_types.enums import DocumentPhase, DocumentType


_PUBLIC_HEARING_MARKERS = (
    "ประชาพิจารณ์",
    "รับฟังคำวิจารณ์",
    "รับฟังความคิดเห็น",
)
_TOR_MARKERS = (
    "ร่างเอกสารประกวดราคา",
    "เอกสารประกวดราคา",
    "ร่างขอบเขตของงาน",
    "ขอบเขตของงาน",
    "เอกสารจ้างที่ปรึกษา",
    "terms of reference",
    "tor",
)
_INVITATION_MARKERS = ("ประกาศเชิญชวน", "หนังสือเชิญชวน")
_MID_PRICE_MARKERS = ("ประกาศราคากลาง", "ราคากลาง")


def classify_document(
    *,
    label: str,
    source_status_text: str = "",
) -> tuple[DocumentType, DocumentPhase]:
    normalized_label = label.strip().casefold()
    normalized_status = source_status_text.strip().casefold()
    combined_text = f"{normalized_label} {normalized_status}".strip()

    if any(marker.casefold() in combined_text for marker in _TOR_MARKERS):
        phase = DocumentPhase.FINAL
        if any(marker.casefold() in combined_text for marker in _PUBLIC_HEARING_MARKERS):
            phase = DocumentPhase.PUBLIC_HEARING
        return (DocumentType.TOR, phase)

    if any(marker.casefold() in combined_text for marker in _INVITATION_MARKERS):
        return (DocumentType.INVITATION, DocumentPhase.UNKNOWN)

    if any(marker.casefold() in combined_text for marker in _MID_PRICE_MARKERS):
        return (DocumentType.MID_PRICE, DocumentPhase.UNKNOWN)

    return (DocumentType.OTHER, DocumentPhase.UNKNOWN)
