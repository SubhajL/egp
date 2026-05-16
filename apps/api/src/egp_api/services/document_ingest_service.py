"""Compatibility exports for the shared document ingest domain service."""

from egp_domain.document_ingest import (
    CapabilityEntitlementService,
    DocumentDownloadLink,
    DocumentIngestService,
)

__all__ = [
    "CapabilityEntitlementService",
    "DocumentDownloadLink",
    "DocumentIngestService",
]
