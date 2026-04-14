"""Service wrapper for tenant-scoped audit log access."""

from __future__ import annotations

from egp_db.repositories.audit_repo import AuditLogPage, SqlAuditRepository


VALID_AUDIT_SOURCES = {"admin", "document", "project", "billing", "review"}
VALID_AUDIT_ENTITY_TYPES = {
    "project",
    "billing_record",
    "document_review",
    "document",
    "user",
    "tenant_settings",
    "tenant_storage_settings",
    "webhook",
}


class AuditService:
    def __init__(self, repository: SqlAuditRepository) -> None:
        self._repository = repository

    def list_events(
        self,
        *,
        tenant_id: str,
        source: str | None = None,
        entity_type: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> AuditLogPage:
        normalized_source = str(source).strip() if source is not None else None
        normalized_entity_type = str(entity_type).strip() if entity_type is not None else None
        if normalized_source is not None and normalized_source not in VALID_AUDIT_SOURCES:
            raise ValueError(f"unsupported audit source: {normalized_source}")
        if (
            normalized_entity_type is not None
            and normalized_entity_type not in VALID_AUDIT_ENTITY_TYPES
        ):
            raise ValueError(f"unsupported audit entity_type: {normalized_entity_type}")
        return self._repository.list_events(
            tenant_id=tenant_id,
            source=normalized_source,
            entity_type=normalized_entity_type,
            limit=limit,
            offset=offset,
        )
