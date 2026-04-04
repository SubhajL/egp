"""Document classification exports."""

from .classifier import (
    DocumentClassification,
    classify_document,
    classify_document_details,
)

__all__ = ["DocumentClassification", "classify_document", "classify_document_details"]
