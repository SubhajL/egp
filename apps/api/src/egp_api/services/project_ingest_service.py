"""Compatibility exports for the shared project ingest domain service."""

from egp_domain.project_ingest import (
    DiscoverProjectIngestResult,
    ProjectIngestService,
    create_project_ingest_service,
)

__all__ = [
    "DiscoverProjectIngestResult",
    "ProjectIngestService",
    "create_project_ingest_service",
]
