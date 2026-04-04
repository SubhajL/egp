from __future__ import annotations

from egp_document_classifier.diff_engine import build_document_diff
from egp_shared_types.enums import DocumentPhase, DocumentType


def test_build_document_diff_marks_identical_phase_transition() -> None:
    result = build_document_diff(
        old_document_type=DocumentType.TOR,
        old_document_phase=DocumentPhase.PUBLIC_HEARING,
        old_file_name="tor-hearing.pdf",
        old_sha256="sha-one",
        old_bytes=b"same-tor-bytes",
        new_document_type=DocumentType.TOR,
        new_document_phase=DocumentPhase.FINAL,
        new_file_name="tor-final.pdf",
        new_sha256="sha-one",
        new_bytes=b"same-tor-bytes",
        comparison_scope="phase_transition",
    )

    assert result.diff_type == "identical"
    assert result.summary_json["comparison_scope"] == "phase_transition"
    assert result.summary_json["similarity_ratio"] == 1.0
    assert result.summary_json["changed_line_count"] == 0


def test_build_document_diff_handles_missing_text_extraction() -> None:
    result = build_document_diff(
        old_document_type=DocumentType.TOR,
        old_document_phase=DocumentPhase.FINAL,
        old_file_name="tor-v1.pdf",
        old_sha256="sha-one",
        old_bytes=b"\xff\x00\xfe\x01",
        new_document_type=DocumentType.TOR,
        new_document_phase=DocumentPhase.FINAL,
        new_file_name="tor-v2.pdf",
        new_sha256="sha-two",
        new_bytes=b"\xff\x00\xfe\x02",
        comparison_scope="same_phase_version",
    )

    assert result.diff_type == "changed"
    assert result.summary_json["text_extraction_status"] == "unavailable"
    assert result.summary_json["text_diff_available"] is False
    assert result.summary_json["comparison_scope"] == "same_phase_version"
