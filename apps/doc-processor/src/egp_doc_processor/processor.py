"""Thin document processor facade."""

from __future__ import annotations

from dataclasses import dataclass

from egp_crawler_core.document_hasher import hash_file
from egp_document_classifier.diff_engine import build_document_diff

from egp_doc_processor.classification import classify_artifact
from egp_document_classifier.classifier import DocumentClassification
from egp_shared_types.enums import ProjectState


@dataclass(slots=True)
class DocumentProcessor:
    def classify_artifact(
        self,
        *,
        file_name: str,
        source_label: str,
        source_status_text: str = "",
        source_page_text: str = "",
        project_state: ProjectState | str | None = None,
    ) -> DocumentClassification:
        return classify_artifact(
            file_name=file_name,
            source_label=source_label,
            source_status_text=source_status_text,
            source_page_text=source_page_text,
            project_state=project_state,
        )

    def process_artifact(
        self,
        *,
        file_name: str,
        file_bytes: bytes,
        source_label: str,
        source_status_text: str = "",
        source_page_text: str = "",
        project_state: ProjectState | str | None = None,
        old_file_name: str | None = None,
        old_file_bytes: bytes | None = None,
        old_sha256: str | None = None,
        old_document_type: str | None = None,
        old_document_phase: str | None = None,
        comparison_scope: str | None = None,
    ) -> dict[str, object]:
        classification = self.classify_artifact(
            file_name=file_name,
            source_label=source_label,
            source_status_text=source_status_text,
            source_page_text=source_page_text,
            project_state=project_state,
        )
        artifact_sha256 = hash_file(file_bytes)
        result: dict[str, object] = {
            "sha256": artifact_sha256,
            "classification": {
                "document_type": classification.document_type.value,
                "document_phase": classification.document_phase.value,
                "matched_markers": list(classification.matched_markers),
            },
        }
        if (
            old_file_bytes is not None
            and old_sha256 is not None
            and old_document_type is not None
            and old_document_phase is not None
            and comparison_scope is not None
        ):
            diff = build_document_diff(
                old_document_type=classification.document_type.__class__(
                    old_document_type
                ),
                old_document_phase=classification.document_phase.__class__(
                    old_document_phase
                ),
                old_file_name=old_file_name or "previous-document",
                old_sha256=old_sha256,
                old_bytes=old_file_bytes,
                new_document_type=classification.document_type,
                new_document_phase=classification.document_phase,
                new_file_name=file_name,
                new_sha256=artifact_sha256,
                new_bytes=file_bytes,
                comparison_scope=comparison_scope,
            )
            result["diff"] = {
                "diff_type": diff.diff_type,
                "summary_json": diff.summary_json,
            }
        return result


def build_document_processor() -> DocumentProcessor:
    return DocumentProcessor()
