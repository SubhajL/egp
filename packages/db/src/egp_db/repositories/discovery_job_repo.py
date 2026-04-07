"""Durable outbox for immediate discovery dispatch."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Table,
    and_,
    insert,
    or_,
    select,
    update,
)
from sqlalchemy.engine import Engine, RowMapping

from egp_db.connection import DB_METADATA, create_shared_engine
from egp_db.db_utils import UUID_SQL_TYPE, normalize_database_url, normalize_uuid_string


METADATA = DB_METADATA

DISCOVERY_JOBS_TABLE = Table(
    "discovery_jobs",
    METADATA,
    Column("id", UUID_SQL_TYPE, primary_key=True),
    Column("tenant_id", UUID_SQL_TYPE, nullable=False),
    Column(
        "profile_id",
        UUID_SQL_TYPE,
        ForeignKey("crawl_profiles.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("profile_type", String, nullable=False),
    Column("keyword", String, nullable=False),
    Column("trigger_type", String, nullable=False, default="profile_created"),
    Column("live", Boolean, nullable=False, default=True),
    Column("job_status", String, nullable=False, default="pending"),
    Column("attempt_count", Integer, nullable=False, default=0),
    Column("last_error", String, nullable=True),
    Column("next_attempt_at", DateTime(timezone=True), nullable=False),
    Column("processing_started_at", DateTime(timezone=True), nullable=True),
    Column("dispatched_at", DateTime(timezone=True), nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
)

Index(
    "idx_discovery_jobs_pending_due",
    DISCOVERY_JOBS_TABLE.c.job_status,
    DISCOVERY_JOBS_TABLE.c.next_attempt_at,
    DISCOVERY_JOBS_TABLE.c.processing_started_at,
)


@dataclass(frozen=True, slots=True)
class DiscoveryJobRecord:
    id: str
    tenant_id: str
    profile_id: str
    profile_type: str
    keyword: str
    trigger_type: str
    live: bool
    job_status: str
    attempt_count: int
    last_error: str | None
    next_attempt_at: str
    processing_started_at: str | None
    dispatched_at: str | None
    created_at: str
    updated_at: str


def _now() -> datetime:
    return datetime.now(UTC)


def _to_iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.isoformat()


def _job_from_mapping(row: RowMapping) -> DiscoveryJobRecord:
    return DiscoveryJobRecord(
        id=str(row["id"]),
        tenant_id=str(row["tenant_id"]),
        profile_id=str(row["profile_id"]),
        profile_type=str(row["profile_type"]),
        keyword=str(row["keyword"]),
        trigger_type=str(row["trigger_type"]),
        live=bool(row["live"]),
        job_status=str(row["job_status"]),
        attempt_count=int(row["attempt_count"]),
        last_error=str(row["last_error"]) if row["last_error"] is not None else None,
        next_attempt_at=_to_iso(row["next_attempt_at"]) or "",
        processing_started_at=_to_iso(row["processing_started_at"]),
        dispatched_at=_to_iso(row["dispatched_at"]),
        created_at=_to_iso(row["created_at"]) or "",
        updated_at=_to_iso(row["updated_at"]) or "",
    )


def build_discovery_job_values(
    *,
    tenant_id: str,
    profile_id: str,
    profile_type: str,
    keyword: str,
    trigger_type: str = "profile_created",
    live: bool = True,
    now: datetime | None = None,
) -> dict[str, object]:
    created_at = now or _now()
    return {
        "id": str(uuid4()),
        "tenant_id": normalize_uuid_string(tenant_id),
        "profile_id": normalize_uuid_string(profile_id),
        "profile_type": str(profile_type).strip() or "custom",
        "keyword": str(keyword).strip(),
        "trigger_type": str(trigger_type).strip() or "profile_created",
        "live": bool(live),
        "job_status": "pending",
        "attempt_count": 0,
        "last_error": None,
        "next_attempt_at": created_at,
        "processing_started_at": None,
        "dispatched_at": None,
        "created_at": created_at,
        "updated_at": created_at,
    }


class SqlDiscoveryJobRepository:
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

    def create_discovery_job(
        self,
        *,
        tenant_id: str,
        profile_id: str,
        profile_type: str,
        keyword: str,
        trigger_type: str = "profile_created",
        live: bool = True,
    ) -> DiscoveryJobRecord:
        values = build_discovery_job_values(
            tenant_id=tenant_id,
            profile_id=profile_id,
            profile_type=profile_type,
            keyword=keyword,
            trigger_type=trigger_type,
            live=live,
        )
        with self._engine.begin() as connection:
            connection.execute(insert(DISCOVERY_JOBS_TABLE).values(**values))
        return self.get_discovery_job(tenant_id=tenant_id, job_id=str(values["id"]))

    def get_discovery_job(self, *, tenant_id: str, job_id: str) -> DiscoveryJobRecord:
        normalized_tenant_id = normalize_uuid_string(tenant_id)
        with self._engine.connect() as connection:
            row = (
                connection.execute(
                    select(DISCOVERY_JOBS_TABLE).where(
                        and_(
                            DISCOVERY_JOBS_TABLE.c.tenant_id == normalized_tenant_id,
                            DISCOVERY_JOBS_TABLE.c.id == normalize_uuid_string(job_id),
                        )
                    )
                )
                .mappings()
                .first()
            )
        if row is None:
            raise KeyError(job_id)
        return _job_from_mapping(row)

    def list_discovery_jobs(self, *, tenant_id: str) -> list[DiscoveryJobRecord]:
        normalized_tenant_id = normalize_uuid_string(tenant_id)
        with self._engine.connect() as connection:
            rows = (
                connection.execute(
                    select(DISCOVERY_JOBS_TABLE)
                    .where(DISCOVERY_JOBS_TABLE.c.tenant_id == normalized_tenant_id)
                    .order_by(
                        DISCOVERY_JOBS_TABLE.c.created_at, DISCOVERY_JOBS_TABLE.c.id
                    )
                )
                .mappings()
                .all()
            )
        return [_job_from_mapping(row) for row in rows]

    def claim_pending_discovery_jobs(
        self,
        *,
        limit: int = 10,
        stale_after_seconds: float = 60.0,
    ) -> list[DiscoveryJobRecord]:
        now = _now()
        stale_started_at = datetime.fromtimestamp(
            now.timestamp() - max(1.0, float(stale_after_seconds)), UTC
        )
        normalized_limit = max(1, int(limit))
        claimed_ids: list[str] = []
        with self._engine.begin() as connection:
            rows = (
                connection.execute(
                    select(DISCOVERY_JOBS_TABLE)
                    .where(
                        and_(
                            DISCOVERY_JOBS_TABLE.c.job_status == "pending",
                            DISCOVERY_JOBS_TABLE.c.next_attempt_at <= now,
                        )
                    )
                    .order_by(
                        DISCOVERY_JOBS_TABLE.c.next_attempt_at,
                        DISCOVERY_JOBS_TABLE.c.created_at,
                    )
                    .limit(normalized_limit)
                )
                .mappings()
                .all()
            )
            for row in rows:
                job_id = str(row["id"])
                started_at = row["processing_started_at"]
                if started_at is not None and started_at > stale_started_at:
                    continue
                updated = connection.execute(
                    update(DISCOVERY_JOBS_TABLE)
                    .where(
                        and_(
                            DISCOVERY_JOBS_TABLE.c.id == job_id,
                            DISCOVERY_JOBS_TABLE.c.job_status == "pending",
                            DISCOVERY_JOBS_TABLE.c.next_attempt_at <= now,
                            or_(
                                DISCOVERY_JOBS_TABLE.c.processing_started_at.is_(None),
                                DISCOVERY_JOBS_TABLE.c.processing_started_at
                                <= stale_started_at,
                            ),
                        )
                    )
                    .values(processing_started_at=now, updated_at=now)
                )
                if updated.rowcount:
                    claimed_ids.append(job_id)
            if not claimed_ids:
                return []
            claimed_rows = (
                connection.execute(
                    select(DISCOVERY_JOBS_TABLE).where(
                        DISCOVERY_JOBS_TABLE.c.id.in_(claimed_ids)
                    )
                )
                .mappings()
                .all()
            )
        claimed_by_id = {str(row["id"]): _job_from_mapping(row) for row in claimed_rows}
        return [
            claimed_by_id[job_id] for job_id in claimed_ids if job_id in claimed_by_id
        ]

    def record_discovery_job_attempt(
        self,
        *,
        tenant_id: str,
        job_id: str,
        job_status: str,
        last_error: str | None = None,
        next_attempt_at: datetime | None = None,
        processing_started_at: datetime | None = None,
        dispatched: bool = False,
    ) -> DiscoveryJobRecord:
        normalized_tenant_id = normalize_uuid_string(tenant_id)
        normalized_job_id = normalize_uuid_string(job_id)
        now = _now()
        with self._engine.begin() as connection:
            row = (
                connection.execute(
                    select(DISCOVERY_JOBS_TABLE).where(
                        and_(
                            DISCOVERY_JOBS_TABLE.c.tenant_id == normalized_tenant_id,
                            DISCOVERY_JOBS_TABLE.c.id == normalized_job_id,
                        )
                    )
                )
                .mappings()
                .first()
            )
            if row is None:
                raise KeyError(job_id)
            connection.execute(
                update(DISCOVERY_JOBS_TABLE)
                .where(DISCOVERY_JOBS_TABLE.c.id == normalized_job_id)
                .values(
                    job_status=str(job_status).strip(),
                    attempt_count=int(row["attempt_count"]) + 1,
                    last_error=(str(last_error).strip()[:1000] if last_error else None),
                    next_attempt_at=next_attempt_at or now,
                    processing_started_at=processing_started_at,
                    dispatched_at=now if dispatched else row["dispatched_at"],
                    updated_at=now,
                )
            )
            updated_row = (
                connection.execute(
                    select(DISCOVERY_JOBS_TABLE).where(
                        DISCOVERY_JOBS_TABLE.c.id == normalized_job_id
                    )
                )
                .mappings()
                .first()
            )
        if updated_row is None:
            raise KeyError(job_id)
        return _job_from_mapping(updated_row)


def create_discovery_job_repository(
    *,
    database_url: str | None = None,
    engine: Engine | None = None,
    bootstrap_schema: bool = True,
) -> SqlDiscoveryJobRepository:
    return SqlDiscoveryJobRepository(
        database_url=database_url,
        engine=engine,
        bootstrap_schema=bootstrap_schema,
    )
