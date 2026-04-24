"""Structured document diff helpers."""

from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Literal

from egp_shared_types.enums import DocumentPhase, DocumentType

ComparisonScope = Literal["same_phase_version", "phase_transition"]

_TEXT_PREVIEW_LIMIT = 500
_VALID_COMPARISON_SCOPES = {"same_phase_version", "phase_transition"}


@dataclass(frozen=True, slots=True)
class DocumentDiffResult:
    diff_type: str
    summary_json: dict[str, object]


def _decode_inline_text(file_bytes: bytes) -> str | None:
    try:
        decoded = file_bytes.decode("utf-8")
    except UnicodeDecodeError:
        return None
    return decoded.replace("\r\n", "\n").replace("\r", "\n").rstrip()


def _build_text_preview(text: str | None) -> str | None:
    if text is None:
        return None
    if len(text) <= _TEXT_PREVIEW_LIMIT:
        return text
    return f"{text[:_TEXT_PREVIEW_LIMIT].rstrip()}..."


def _count_line_changes(old_text: str, new_text: str) -> tuple[int, int, int]:
    old_lines = old_text.splitlines()
    new_lines = new_text.splitlines()
    matcher = SequenceMatcher(a=old_lines, b=new_lines)
    added_line_count = 0
    removed_line_count = 0

    for opcode, old_start, old_end, new_start, new_end in matcher.get_opcodes():
        if opcode == "insert":
            added_line_count += new_end - new_start
        elif opcode == "delete":
            removed_line_count += old_end - old_start
        elif opcode == "replace":
            removed_line_count += old_end - old_start
            added_line_count += new_end - new_start

    return (
        added_line_count,
        removed_line_count,
        added_line_count + removed_line_count,
    )


def _calculate_similarity_ratio(
    *,
    old_bytes: bytes,
    new_bytes: bytes,
    old_text: str | None,
    new_text: str | None,
) -> tuple[float | None, bool]:
    if old_bytes == new_bytes:
        return 1.0, False
    if old_text is None or new_text is None:
        return None, True
    return round(SequenceMatcher(a=old_text, b=new_text).ratio(), 4), False


def build_document_diff(
    *,
    old_document_type: DocumentType,
    old_document_phase: DocumentPhase,
    old_file_name: str,
    old_sha256: str,
    old_bytes: bytes,
    new_document_type: DocumentType,
    new_document_phase: DocumentPhase,
    new_file_name: str,
    new_sha256: str,
    new_bytes: bytes,
    comparison_scope: ComparisonScope | str,
) -> DocumentDiffResult:
    normalized_scope = str(comparison_scope).strip()
    if normalized_scope not in _VALID_COMPARISON_SCOPES:
        raise ValueError(f"Unsupported comparison_scope: {comparison_scope}")

    old_text = _decode_inline_text(old_bytes)
    new_text = _decode_inline_text(new_bytes)
    text_diff_available = old_text is not None and new_text is not None
    text_extraction_status = "inline_text" if text_diff_available else "unavailable"
    added_line_count = 0
    removed_line_count = 0
    changed_line_count = 0
    if text_diff_available:
        (
            added_line_count,
            removed_line_count,
            changed_line_count,
        ) = _count_line_changes(old_text, new_text)

    diff_type = "identical" if old_bytes == new_bytes else "changed"
    similarity_ratio, binary_similarity_skipped = _calculate_similarity_ratio(
        old_bytes=old_bytes,
        new_bytes=new_bytes,
        old_text=old_text,
        new_text=new_text,
    )
    summary_json: dict[str, object] = {
        "summary_version": 1,
        "comparison_scope": normalized_scope,
        "text_extraction_status": text_extraction_status,
        "text_diff_available": text_diff_available,
        "similarity_ratio": similarity_ratio,
        "old_document_phase": old_document_phase.value,
        "new_document_phase": new_document_phase.value,
        "old_sha256": old_sha256,
        "new_sha256": new_sha256,
        "old_size_bytes": len(old_bytes),
        "new_size_bytes": len(new_bytes),
        "size_delta_bytes": len(new_bytes) - len(old_bytes),
        "old_file_name": old_file_name,
        "new_file_name": new_file_name,
        "added_line_count": added_line_count,
        "removed_line_count": removed_line_count,
        "changed_line_count": changed_line_count,
        "old_text_preview": _build_text_preview(old_text),
        "new_text_preview": _build_text_preview(new_text),
    }
    if binary_similarity_skipped:
        summary_json["binary_similarity_skipped"] = True
    return DocumentDiffResult(diff_type=diff_type, summary_json=summary_json)
