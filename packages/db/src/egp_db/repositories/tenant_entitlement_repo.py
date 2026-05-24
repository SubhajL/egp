"""Tenant-level operational entitlement caps."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import CheckConstraint, Column, DateTime, ForeignKey, Integer, Table, insert, select
from sqlalchemy.engine import Engine, RowMapping

from egp_db.connection import DB_METADATA, create_shared_engine
from egp_db.db_utils import UUID_SQL_TYPE, normalize_database_url, normalize_uuid_string
from egp_db.repositories.admin_repo import TENANTS_TABLE


METADATA = DB_METADATA
DEFAULT_MAX_CONCURRENT_RUNS = 1
DEFAULT_MAX_QUEUED_KEYWORDS = 20

TENANT_ENTITLEMENTS_TABLE = Table(
    "tenant_entitlements",
    METADATA,
    Column(
        "tenant_id",
        UUID_SQL_TYPE,
        ForeignKey(TENANTS_TABLE.c.id, ondelete="CASCADE"),
        primary_key=True,
    ),
    Column("max_concurrent_runs", Integer, nullable=False, default=DEFAULT_MAX_CONCURRENT_RUNS),
    Column("max_queued_keywords", Integer, nullable=False, default=DEFAULT_MAX_QUEUED_KEYWORDS),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
    CheckConstraint(
        "max_concurrent_runs > 0",
        name="tenant_entitlements_max_concurrent_runs_check",
    ),
    CheckConstraint(
        "max_queued_keywords > 0",
        name="tenant_entitlements_max_queued_keywords_check",
    ),
)


@dataclass(frozen=True, slots=True)
class TenantRunAdmissionCaps:
    max_concurrent_runs: int
    max_queued_keywords: int


def _now() -> datetime:
    return datetime.now(UTC)


def _caps_from_mapping(row: RowMapping | None) -> TenantRunAdmissionCaps:
    if row is None:
        return TenantRunAdmissionCaps(
            max_concurrent_runs=DEFAULT_MAX_CONCURRENT_RUNS,
            max_queued_keywords=DEFAULT_MAX_QUEUED_KEYWORDS,
        )
    return TenantRunAdmissionCaps(
        max_concurrent_runs=max(1, int(row["max_concurrent_runs"])),
        max_queued_keywords=max(1, int(row["max_queued_keywords"])),
    )


class SqlTenantEntitlementRepository:
    """Repository for tenant-specific runtime admission caps."""

    def __init__(
        self,
        *,
        database_url: str | None = None,
        engine: Engine | None = None,
        bootstrap_schema: bool = False,
    ) -> None:
        if engine is None and database_url is None:
            raise ValueError("database_url or engine is required")
        self._database_url = (
            normalize_database_url(database_url) if database_url is not None else None
        )
        self._engine = engine or create_shared_engine(self._database_url or "")
        if bootstrap_schema:
            self._ensure_schema()

    def _ensure_schema(self) -> None:
        METADATA.create_all(self._engine)

    def get_run_admission_caps(self, *, tenant_id: str) -> TenantRunAdmissionCaps:
        normalized_tenant_id = normalize_uuid_string(tenant_id)
        with self._engine.connect() as connection:
            row = (
                connection.execute(
                    select(TENANT_ENTITLEMENTS_TABLE)
                    .where(TENANT_ENTITLEMENTS_TABLE.c.tenant_id == normalized_tenant_id)
                    .limit(1)
                )
                .mappings()
                .one_or_none()
            )
        return _caps_from_mapping(row)

    def upsert_run_admission_caps(
        self,
        *,
        tenant_id: str,
        max_concurrent_runs: int = DEFAULT_MAX_CONCURRENT_RUNS,
        max_queued_keywords: int = DEFAULT_MAX_QUEUED_KEYWORDS,
    ) -> TenantRunAdmissionCaps:
        normalized_tenant_id = normalize_uuid_string(tenant_id)
        now = _now()
        values = {
            "tenant_id": normalized_tenant_id,
            "max_concurrent_runs": max(1, int(max_concurrent_runs)),
            "max_queued_keywords": max(1, int(max_queued_keywords)),
            "created_at": now,
            "updated_at": now,
        }
        with self._engine.begin() as connection:
            existing = (
                connection.execute(
                    select(TENANT_ENTITLEMENTS_TABLE.c.tenant_id)
                    .where(TENANT_ENTITLEMENTS_TABLE.c.tenant_id == normalized_tenant_id)
                    .limit(1)
                )
                .mappings()
                .one_or_none()
            )
            if existing is None:
                connection.execute(insert(TENANT_ENTITLEMENTS_TABLE).values(**values))
            else:
                connection.execute(
                    TENANT_ENTITLEMENTS_TABLE.update()
                    .where(TENANT_ENTITLEMENTS_TABLE.c.tenant_id == normalized_tenant_id)
                    .values(
                        max_concurrent_runs=values["max_concurrent_runs"],
                        max_queued_keywords=values["max_queued_keywords"],
                        updated_at=now,
                    )
                )
        return self.get_run_admission_caps(tenant_id=tenant_id)


def create_tenant_entitlement_repository(
    *,
    database_url: str | None = None,
    engine: Engine | None = None,
    bootstrap_schema: bool = True,
) -> SqlTenantEntitlementRepository:
    return SqlTenantEntitlementRepository(
        database_url=database_url,
        engine=engine,
        bootstrap_schema=bootstrap_schema,
    )
