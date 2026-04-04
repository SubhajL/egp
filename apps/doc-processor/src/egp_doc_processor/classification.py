"""Document-processor classification helpers."""

from __future__ import annotations

from egp_document_classifier.classifier import (
    DocumentClassification,
    classify_document_details,
)
from egp_shared_types.enums import ProjectState


def classify_artifact(
    *,
    file_name: str,
    source_label: str,
    source_status_text: str = "",
    source_page_text: str = "",
    project_state: ProjectState | str | None = None,
) -> DocumentClassification:
    return classify_document_details(
        label=source_label,
        source_status_text=source_status_text,
        source_page_text=source_page_text,
        project_state=project_state,
        file_name=file_name,
    )
