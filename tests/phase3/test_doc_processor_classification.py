from __future__ import annotations

import importlib
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
