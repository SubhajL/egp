"""e-GP Intelligence Platform — Document Processor.

Handles document hashing (SHA-256), text extraction,
type/phase classification, and diff generation.
"""

from __future__ import annotations

import json
import sys

from egp_doc_processor.processor import build_document_processor


def _decode_optional_hex(value: object) -> bytes | None:
    if value in (None, ""):
        return None
    return bytes.fromhex(str(value))


def main(stdin_text: str | None = None) -> None:
    processor = build_document_processor()
    raw_input = stdin_text if stdin_text is not None else sys.stdin.read()
    if not raw_input.strip():
        print(
            json.dumps(
                {"service": "doc-processor", "processor": processor.__class__.__name__},
                sort_keys=True,
            )
        )
        return
    payload = json.loads(raw_input)
    result = processor.process_artifact(
        file_name=str(payload["file_name"]),
        file_bytes=bytes.fromhex(str(payload["file_bytes_hex"])),
        source_label=str(payload.get("source_label") or ""),
        source_status_text=str(payload.get("source_status_text") or ""),
        source_page_text=str(payload.get("source_page_text") or ""),
        project_state=payload.get("project_state"),
        old_file_name=(
            str(payload["old_file_name"])
            if payload.get("old_file_name") is not None
            else None
        ),
        old_file_bytes=_decode_optional_hex(payload.get("old_file_bytes_hex")),
        old_sha256=(
            str(payload["old_sha256"])
            if payload.get("old_sha256") is not None
            else None
        ),
        old_document_type=(
            str(payload["old_document_type"])
            if payload.get("old_document_type") is not None
            else None
        ),
        old_document_phase=(
            str(payload["old_document_phase"])
            if payload.get("old_document_phase") is not None
            else None
        ),
        comparison_scope=(
            str(payload["comparison_scope"])
            if payload.get("comparison_scope") is not None
            else None
        ),
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
