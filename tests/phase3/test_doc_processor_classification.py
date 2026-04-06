from __future__ import annotations

import importlib
from hashlib import sha256
from pathlib import Path
import sys

DOC_PROCESSOR_SRC = (
    Path(__file__).resolve().parents[2] / "apps" / "doc-processor" / "src"
)
if str(DOC_PROCESSOR_SRC) not in sys.path:
    sys.path.insert(0, str(DOC_PROCESSOR_SRC))


def test_doc_processor_classify_artifact_uses_page_context() -> None:
    from egp_shared_types.enums import DocumentPhase, DocumentType

    classify_artifact = importlib.import_module(
        "egp_doc_processor.classification"
    ).classify_artifact
    result = classify_artifact(
        file_name="tor.pdf",
        source_label="เอกสารประกวดราคา",
        source_status_text="",
        source_page_text="หน้าเอกสารนี้ใช้สำหรับรับฟังความคิดเห็นและประชาพิจารณ์",
    )

    assert result.document_type is DocumentType.TOR
    assert result.document_phase is DocumentPhase.PUBLIC_HEARING
    assert "ประชาพิจารณ์" in result.matched_markers


def test_doc_processor_process_artifact_returns_hash_and_diff() -> None:
    from egp_shared_types.enums import DocumentPhase, DocumentType

    processor_module = importlib.import_module("egp_doc_processor.processor")
    processor = processor_module.build_document_processor()

    result = processor.process_artifact(
        file_name="tor-final.pdf",
        file_bytes=b"updated tor text",
        source_label="เอกสารประกวดราคา",
        source_status_text="ประกาศเชิญชวน",
        old_file_name="tor-hearing.pdf",
        old_file_bytes=b"original tor text",
        old_sha256=sha256(b"original tor text").hexdigest(),
        old_document_type=DocumentType.TOR.value,
        old_document_phase=DocumentPhase.PUBLIC_HEARING.value,
        comparison_scope="phase_transition",
    )

    assert result["sha256"] == sha256(b"updated tor text").hexdigest()
    assert result["classification"]["document_type"] == "tor"
    assert result["classification"]["document_phase"] == "final"
    assert result["diff"]["diff_type"] == "changed"
    assert result["diff"]["summary_json"]["comparison_scope"] == "phase_transition"
