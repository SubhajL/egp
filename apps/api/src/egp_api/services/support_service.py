"""Internal support tooling service."""

from __future__ import annotations

from egp_db.repositories.support_repo import (
    SqlSupportRepository,
    SupportSummary,
    SupportTenantRecord,
)


class SupportService:
    def __init__(self, repository: SqlSupportRepository) -> None:
        self._repository = repository

    def search_tenants(self, *, query: str, limit: int = 20) -> list[SupportTenantRecord]:
        normalized_query = str(query).strip()
        if not normalized_query:
            return []
        return self._repository.search_tenants(query=normalized_query, limit=limit)

    def get_summary(self, *, tenant_id: str, window_days: int = 30) -> SupportSummary:
        return self._repository.get_support_summary(
            tenant_id=tenant_id,
            window_days=window_days,
        )
