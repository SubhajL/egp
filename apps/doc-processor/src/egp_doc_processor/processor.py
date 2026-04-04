"""Thin document processor facade."""

from __future__ import annotations

from dataclasses import dataclass

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


def build_document_processor() -> DocumentProcessor:
    return DocumentProcessor()
