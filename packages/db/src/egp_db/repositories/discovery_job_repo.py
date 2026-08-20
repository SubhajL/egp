"""Durable outbox for immediate discovery dispatch."""

from __future__ import annotations

from collections.abc import Collection
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Table,
    and_,
    case,
    func,
    insert,
    or_,
    select,
    text,
    update,
)
from sqlalchemy.engine import Engine, RowMapping

from egp_db.connection import DB_METADATA, create_shared_engine
from egp_db.db_utils import UUID_SQL_TYPE, normalize_database_url, normalize_uuid_string
from egp_db.repositories.recrawl_request_repo import RECRAWL_REQUESTS_TABLE
from egp_shared_types.enums import (
    IN_FLIGHT_DISCOVERY_JOB_STATUS_VALUES,
    DiscoveryFailureCode,
    ExecutionBackend,
)


METADATA = DB_METADATA
DISCOVERY_FAILURE_CODE_VALUES = tuple(code.value for code in DiscoveryFailureCode)
DISCOVERY_FAILURE_CODE_SQL = ", ".join(
    f"'{value}'" for value in DISCOVERY_FAILURE_CODE_VALUES
)
EXECUTION_BACKEND_VALUES = tuple(backend.value for backend in ExecutionBackend)
EXECUTION_BACKEND_SQL = ", ".join(f"'{value}'" for value in EXECUTION_BACKEND_VALUES)

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
    Column(
        "recrawl_request_id",
        UUID_SQL_TYPE,
        ForeignKey(RECRAWL_REQUESTS_TABLE.c.id, ondelete="SET NULL"),
        nullable=True,
    ),
    Column("job_status", String, nullable=False, default="pending"),
    Column(
        "execution_backend",
        String,
        nullable=False,
        default=ExecutionBackend.LEGACY.value,
        server_default=text(f"'{ExecutionBackend.LEGACY.value}'"),
    ),
    Column("attempt_count", Integer, nullable=False, default=0),
    Column("last_error", String, nullable=True),
    Column("last_error_code", String, nullable=True),
    Column("next_attempt_at", DateTime(timezone=True), nullable=False),
    Column("processing_started_at", DateTime(timezone=True), nullable=True),
    Column("claim_token", UUID_SQL_TYPE, nullable=True),
    Column("lease_expires_at", DateTime(timezone=True), nullable=True),
    Column("lease_heartbeat_at", DateTime(timezone=True), nullable=True),
    Column("dispatched_at", DateTime(timezone=True), nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
    CheckConstraint(
        f"last_error_code IS NULL OR last_error_code IN ({DISCOVERY_FAILURE_CODE_SQL})",
        name="discovery_jobs_last_error_code_check",
    ),
    # Mirrors migration 034. Without it the SQLite bootstrap used by tests would
    # accept a backend value PostgreSQL rejects, and such a row would be
    # invisible to every claimer.
    CheckConstraint(
        f"execution_backend IN ({EXECUTION_BACKEND_SQL})",
        name="discovery_jobs_execution_backend_check",
    ),
)


def _no_active_correlated_run_predicate():
    """Exclude jobs while a tenant-matched correlated run is still active."""
    from egp_db.repositories.run_repo import CRAWL_RUNS_TABLE

    return (
        ~select(CRAWL_RUNS_TABLE.c.id)
        .where(
            and_(
                CRAWL_RUNS_TABLE.c.tenant_id == DISCOVERY_JOBS_TABLE.c.tenant_id,
                CRAWL_RUNS_TABLE.c.discovery_job_id == DISCOVERY_JOBS_TABLE.c.id,
                CRAWL_RUNS_TABLE.c.status.in_(("queued", "running")),
            )
        )
        .exists()
    )


Index(
    "idx_discovery_jobs_pending_due",
    DISCOVERY_JOBS_TABLE.c.job_status,
    DISCOVERY_JOBS_TABLE.c.next_attempt_at,
    DISCOVERY_JOBS_TABLE.c.lease_expires_at,
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
    last_error_code: str | None
    next_attempt_at: str
    processing_started_at: str | None
    claim_token: str | None
    lease_expires_at: str | None
    lease_heartbeat_at: str | None
    dispatched_at: str | None
    created_at: str
    updated_at: str
    recrawl_request_id: str | None = None


@dataclass(frozen=True, slots=True)
class DiscoveryJobEnqueueResult:
    job: DiscoveryJobRecord
    created: bool


@dataclass(frozen=True, slots=True)
class DiscoveryQueueSnapshot:
    pending_count: int
    claimable_count: int
    leased_count: int
    retry_scheduled_count: int

    @classmethod
    def empty(cls) -> DiscoveryQueueSnapshot:
        return cls(
            pending_count=0,
            claimable_count=0,
            leased_count=0,
            retry_scheduled_count=0,
        )


class StaleDiscoveryJobClaimError(RuntimeError):
    """Raised when an expired or superseded owner tries to mutate a job."""


def _now() -> datetime:
    return datetime.now(UTC)


def _to_iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.isoformat()


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _job_from_mapping(row: RowMapping) -> DiscoveryJobRecord:
    return DiscoveryJobRecord(
        id=str(row["id"]),
        tenant_id=str(row["tenant_id"]),
        profile_id=str(row["profile_id"]),
        profile_type=str(row["profile_type"]),
        keyword=str(row["keyword"]),
        trigger_type=str(row["trigger_type"]),
        live=bool(row["live"]),
        recrawl_request_id=(
            str(row["recrawl_request_id"])
            if row["recrawl_request_id"] is not None
            else None
        ),
        job_status=str(row["job_status"]),
        attempt_count=int(row["attempt_count"]),
        last_error=str(row["last_error"]) if row["last_error"] is not None else None,
        last_error_code=(
            str(row["last_error_code"]) if row["last_error_code"] is not None else None
        ),
        next_attempt_at=_to_iso(row["next_attempt_at"]) or "",
        processing_started_at=_to_iso(row["processing_started_at"]),
        claim_token=(
            str(row["claim_token"]) if row["claim_token"] is not None else None
        ),
        lease_expires_at=_to_iso(row["lease_expires_at"]),
        lease_heartbeat_at=_to_iso(row["lease_heartbeat_at"]),
        dispatched_at=_to_iso(row["dispatched_at"]),
        created_at=_to_iso(row["created_at"]) or "",
        updated_at=_to_iso(row["updated_at"]) or "",
    )


class ProfileNotFoundForTenantError(ValueError):
    """The owning profile is absent, or belongs to a different tenant."""


def resolve_profile_execution_backend(
    connection,
    *,
    tenant_id: str,
    profile_id: str,
) -> str:
    """Derive a job's execution backend from its owning profile. FAILS CLOSED.

    Must run on the CALLER'S connection, inside the same transaction as the
    insert, so routing cannot be decided against a profile that changes before the
    row lands.

    Failing closed is a tenant-isolation requirement, not caution.
    ``discovery_jobs.profile_id`` has a plain FK to ``crawl_profiles(id)`` that is
    NOT composite with ``tenant_id`` (015). So for tenant A and a profile owned by
    tenant B, a tenant-scoped lookup finds nothing — and if that returned a default
    instead of raising, the insert would still satisfy both foreign keys
    independently and create a **cross-tenant job/profile association**.
    """

    from egp_db.repositories.profile_repo import CRAWL_PROFILES_TABLE

    row = (
        connection.execute(
            select(CRAWL_PROFILES_TABLE.c.execution_backend).where(
                and_(
                    CRAWL_PROFILES_TABLE.c.tenant_id
                    == normalize_uuid_string(tenant_id),
                    CRAWL_PROFILES_TABLE.c.id == normalize_uuid_string(profile_id),
                )
            )
        )
        .scalars()
        .first()
    )
    if row is None:
        raise ProfileNotFoundForTenantError(
            f"profile {profile_id} does not exist for tenant {tenant_id}; "
            "refusing to create a discovery job"
        )
    return str(row)


def build_discovery_job_values(
    *,
    tenant_id: str,
    profile_id: str,
    profile_type: str,
    keyword: str,
    trigger_type: str = "profile_created",
    live: bool = True,
    recrawl_request_id: str | None = None,
    execution_backend: str = ExecutionBackend.LEGACY.value,
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
        "recrawl_request_id": (
            normalize_uuid_string(recrawl_request_id) if recrawl_request_id else None
        ),
        "job_status": "pending",
        "execution_backend": str(execution_backend),
        "attempt_count": 0,
        "last_error": None,
        "last_error_code": None,
        "next_attempt_at": created_at,
        "processing_started_at": None,
        "claim_token": None,
        "lease_expires_at": None,
        "lease_heartbeat_at": None,
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
        recrawl_request_id: str | None = None,
    ) -> DiscoveryJobRecord:
        with self._engine.begin() as connection:
            # Resolution and construction both inside the transaction: routing must
            # not be decided against a profile that can change before the row lands.
            values = build_discovery_job_values(
                tenant_id=tenant_id,
                profile_id=profile_id,
                profile_type=profile_type,
                keyword=keyword,
                trigger_type=trigger_type,
                live=live,
                recrawl_request_id=recrawl_request_id,
                execution_backend=resolve_profile_execution_backend(
                    connection, tenant_id=tenant_id, profile_id=profile_id
                ),
            )
            connection.execute(insert(DISCOVERY_JOBS_TABLE).values(**values))
        return self.get_discovery_job(tenant_id=tenant_id, job_id=str(values["id"]))

    def create_pending_discovery_job_if_absent(
        self,
        *,
        tenant_id: str,
        profile_id: str,
        profile_type: str,
        keyword: str,
        trigger_type: str = "profile_created",
        live: bool = True,
        recrawl_request_id: str | None = None,
    ) -> DiscoveryJobEnqueueResult:
        with self._engine.begin() as connection:
            values = build_discovery_job_values(
                tenant_id=tenant_id,
                profile_id=profile_id,
                profile_type=profile_type,
                keyword=keyword,
                trigger_type=trigger_type,
                live=live,
                recrawl_request_id=recrawl_request_id,
                execution_backend=resolve_profile_execution_backend(
                    connection, tenant_id=tenant_id, profile_id=profile_id
                ),
            )
            existing = (
                connection.execute(
                    select(DISCOVERY_JOBS_TABLE)
                    .where(
                        and_(
                            DISCOVERY_JOBS_TABLE.c.tenant_id == values["tenant_id"],
                            DISCOVERY_JOBS_TABLE.c.profile_id == values["profile_id"],
                            DISCOVERY_JOBS_TABLE.c.keyword == values["keyword"],
                            DISCOVERY_JOBS_TABLE.c.trigger_type
                            == values["trigger_type"],
                            DISCOVERY_JOBS_TABLE.c.live == values["live"],
                            # In-flight, not merely pending: a job whose result is
                            # awaiting application already covers this
                            # (profile, keyword). Checking only `pending` would
                            # read it as absent and enqueue a duplicate.
                            DISCOVERY_JOBS_TABLE.c.job_status.in_(
                                IN_FLIGHT_DISCOVERY_JOB_STATUS_VALUES
                            ),
                        )
                    )
                    .order_by(
                        DISCOVERY_JOBS_TABLE.c.created_at.desc(),
                        DISCOVERY_JOBS_TABLE.c.id.desc(),
                    )
                    .limit(1)
                )
                .mappings()
                .first()
            )
            if existing is not None:
                return DiscoveryJobEnqueueResult(
                    job=_job_from_mapping(existing), created=False
                )
            connection.execute(insert(DISCOVERY_JOBS_TABLE).values(**values))
        return DiscoveryJobEnqueueResult(
            job=self.get_discovery_job(tenant_id=tenant_id, job_id=str(values["id"])),
            created=True,
        )

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

    def count_pending_discovery_jobs(self, *, tenant_id: str) -> int:
        normalized_tenant_id = normalize_uuid_string(tenant_id)
        with self._engine.connect() as connection:
            return int(
                connection.execute(
                    select(func.count())
                    .select_from(DISCOVERY_JOBS_TABLE)
                    .where(
                        and_(
                            DISCOVERY_JOBS_TABLE.c.tenant_id == normalized_tenant_id,
                            # Deliberately PENDING-only, not the in-flight set.
                            # This feeds entitlement_service's `queued_keyword_count`,
                            # which is compared against `max_queued_keywords` — a
                            # QUEUE-DEPTH cap, not a concurrency cap (concurrency is
                            # `inflight_run_count >= max_concurrent_runs`, counted
                            # separately from runs). A `result_received` job has
                            # already executed, so it is no longer queued; counting it
                            # here would silently tighten a customer-facing quota.
                            DISCOVERY_JOBS_TABLE.c.job_status == "pending",
                        )
                    )
                ).scalar_one()
            )

    def get_discovery_queue_snapshot(
        self,
        *,
        now: datetime | None = None,
        exclude_trigger_types: Collection[str] | None = None,
    ) -> DiscoveryQueueSnapshot:
        """Return legacy-queue operational counts without tenant or keyword payloads.

        Scoped to ``execution_backend='legacy'`` because every consumer of this
        snapshot is the legacy dispatcher: ``build_discovery_one_shot_summary``
        derives ``exit_reason`` from these counts (``pending_count == 0`` means
        ``queue_drained``), and ``discovery_doctor`` reports them as operator
        diagnostics. Counting agent-owned rows here would make a bounded one-shot
        crawl report ``work_remains`` forever, and a caller looping until
        ``queue_drained`` would never terminate, because the legacy consumer
        correctly refuses to claim those rows. An agent-queue snapshot is separate
        work (U7b+).
        """

        resolved_now = _as_utc(now or _now())
        pending_conditions = [
            DISCOVERY_JOBS_TABLE.c.job_status == "pending",
            DISCOVERY_JOBS_TABLE.c.execution_backend == ExecutionBackend.LEGACY.value,
        ]
        if exclude_trigger_types:
            pending_conditions.append(
                DISCOVERY_JOBS_TABLE.c.trigger_type.not_in(tuple(exclude_trigger_types))
            )
        pending = and_(*pending_conditions)
        claimable = and_(
            pending,
            DISCOVERY_JOBS_TABLE.c.next_attempt_at <= resolved_now,
            _no_active_correlated_run_predicate(),
            or_(
                DISCOVERY_JOBS_TABLE.c.claim_token.is_(None),
                DISCOVERY_JOBS_TABLE.c.lease_expires_at.is_(None),
                DISCOVERY_JOBS_TABLE.c.lease_expires_at <= resolved_now,
            ),
        )
        leased = and_(
            pending,
            DISCOVERY_JOBS_TABLE.c.claim_token.is_not(None),
            DISCOVERY_JOBS_TABLE.c.lease_expires_at > resolved_now,
        )
        retry_scheduled = and_(
            pending,
            DISCOVERY_JOBS_TABLE.c.next_attempt_at > resolved_now,
        )
        with self._engine.connect() as connection:
            row = (
                connection.execute(
                    select(
                        func.sum(case((pending, 1), else_=0)).label("pending_count"),
                        func.sum(case((claimable, 1), else_=0)).label(
                            "claimable_count"
                        ),
                        func.sum(case((leased, 1), else_=0)).label("leased_count"),
                        func.sum(case((retry_scheduled, 1), else_=0)).label(
                            "retry_scheduled_count"
                        ),
                    ).select_from(DISCOVERY_JOBS_TABLE)
                )
                .mappings()
                .one()
            )
        return DiscoveryQueueSnapshot(
            pending_count=int(row["pending_count"] or 0),
            claimable_count=int(row["claimable_count"] or 0),
            leased_count=int(row["leased_count"] or 0),
            retry_scheduled_count=int(row["retry_scheduled_count"] or 0),
        )

    def has_claimable_discovery_jobs(
        self,
        *,
        exclude_job_ids: Collection[str] | None = None,
        only_job_id: str | None = None,
        only_tenant_id: str | None = None,
        only_live: bool | None = None,
        only_trigger_type: str | None = None,
        exclude_trigger_types: Collection[str] | None = None,
    ) -> bool:
        now = _now()
        excluded_job_ids = {
            normalize_uuid_string(job_id) for job_id in (exclude_job_ids or ())
        }
        claimable_conditions = [
            DISCOVERY_JOBS_TABLE.c.job_status == "pending",
            # U7: the legacy consumer owns only legacy-backed rows. Without this
            # predicate the legacy executor and a crawler agent race for the
            # same jobs.
            DISCOVERY_JOBS_TABLE.c.execution_backend == ExecutionBackend.LEGACY.value,
            DISCOVERY_JOBS_TABLE.c.next_attempt_at <= now,
            _no_active_correlated_run_predicate(),
            or_(
                DISCOVERY_JOBS_TABLE.c.claim_token.is_(None),
                DISCOVERY_JOBS_TABLE.c.lease_expires_at.is_(None),
                DISCOVERY_JOBS_TABLE.c.lease_expires_at <= now,
            ),
        ]
        if excluded_job_ids:
            claimable_conditions.append(
                DISCOVERY_JOBS_TABLE.c.id.not_in(excluded_job_ids)
            )
        if only_job_id is not None:
            claimable_conditions.append(
                DISCOVERY_JOBS_TABLE.c.id == normalize_uuid_string(only_job_id)
            )
        if only_tenant_id is not None:
            claimable_conditions.append(
                DISCOVERY_JOBS_TABLE.c.tenant_id
                == normalize_uuid_string(only_tenant_id)
            )
        if only_live is not None:
            claimable_conditions.append(DISCOVERY_JOBS_TABLE.c.live.is_(only_live))
        if only_trigger_type is not None:
            claimable_conditions.append(
                DISCOVERY_JOBS_TABLE.c.trigger_type == only_trigger_type
            )
        if exclude_trigger_types:
            claimable_conditions.append(
                DISCOVERY_JOBS_TABLE.c.trigger_type.not_in(tuple(exclude_trigger_types))
            )
        with self._engine.connect() as connection:
            row = (
                connection.execute(
                    select(DISCOVERY_JOBS_TABLE.c.id)
                    .where(and_(*claimable_conditions))
                    .limit(1)
                )
                .mappings()
                .first()
            )
        return row is not None

    def claim_pending_discovery_jobs(
        self,
        *,
        limit: int = 10,
        lease_seconds: float = 60.0,
        exclude_job_ids: Collection[str] | None = None,
        only_job_id: str | None = None,
        only_tenant_id: str | None = None,
        only_live: bool | None = None,
        only_trigger_type: str | None = None,
        exclude_trigger_types: Collection[str] | None = None,
    ) -> list[DiscoveryJobRecord]:
        now = _now()
        normalized_lease_seconds = max(0.01, float(lease_seconds))
        normalized_limit = max(1, int(limit))
        excluded_job_ids = {
            normalize_uuid_string(job_id) for job_id in (exclude_job_ids or ())
        }
        pending_conditions = [
            DISCOVERY_JOBS_TABLE.c.job_status == "pending",
            # U7: see has_claimable_discovery_jobs — the legacy consumer must not
            # claim agent-owned rows.
            DISCOVERY_JOBS_TABLE.c.execution_backend == ExecutionBackend.LEGACY.value,
            DISCOVERY_JOBS_TABLE.c.next_attempt_at <= now,
            _no_active_correlated_run_predicate(),
        ]
        if excluded_job_ids:
            pending_conditions.append(
                DISCOVERY_JOBS_TABLE.c.id.not_in(excluded_job_ids)
            )
        if only_job_id is not None:
            pending_conditions.append(
                DISCOVERY_JOBS_TABLE.c.id == normalize_uuid_string(only_job_id)
            )
        if only_tenant_id is not None:
            pending_conditions.append(
                DISCOVERY_JOBS_TABLE.c.tenant_id
                == normalize_uuid_string(only_tenant_id)
            )
        if only_live is not None:
            pending_conditions.append(DISCOVERY_JOBS_TABLE.c.live.is_(only_live))
        if only_trigger_type is not None:
            pending_conditions.append(
                DISCOVERY_JOBS_TABLE.c.trigger_type == only_trigger_type
            )
        if exclude_trigger_types:
            pending_conditions.append(
                DISCOVERY_JOBS_TABLE.c.trigger_type.not_in(tuple(exclude_trigger_types))
            )
        claimable_conditions = [
            *pending_conditions,
            or_(
                DISCOVERY_JOBS_TABLE.c.claim_token.is_(None),
                DISCOVERY_JOBS_TABLE.c.lease_expires_at.is_(None),
                DISCOVERY_JOBS_TABLE.c.lease_expires_at <= now,
            ),
        ]
        tenant_rank = (
            func.row_number()
            .over(
                partition_by=DISCOVERY_JOBS_TABLE.c.tenant_id,
                order_by=(
                    DISCOVERY_JOBS_TABLE.c.next_attempt_at,
                    DISCOVERY_JOBS_TABLE.c.created_at,
                    DISCOVERY_JOBS_TABLE.c.id,
                ),
            )
            .label("tenant_claim_rank")
        )
        ranked_jobs = (
            select(DISCOVERY_JOBS_TABLE, tenant_rank)
            .where(and_(*claimable_conditions))
            .subquery()
        )
        claimed_ids: list[str] = []
        with self._engine.begin() as connection:
            rows = (
                connection.execute(
                    select(ranked_jobs)
                    .order_by(
                        ranked_jobs.c.tenant_claim_rank,
                        ranked_jobs.c.next_attempt_at,
                        ranked_jobs.c.created_at,
                        ranked_jobs.c.id,
                    )
                    .limit(normalized_limit)
                )
                .mappings()
                .all()
            )
            for row in rows:
                job_id = str(row["id"])
                # Serialize with run reservation, which locks this same job
                # row.  The UPDATE below is then a separate statement with a
                # fresh READ COMMITTED snapshot of the active-run barrier.
                locked_job_id = connection.execute(
                    select(DISCOVERY_JOBS_TABLE.c.id)
                    .where(DISCOVERY_JOBS_TABLE.c.id == job_id)
                    .with_for_update()
                ).scalar_one_or_none()
                if locked_job_id is None:
                    continue
                claim_now = _now()
                claim_lease_expires_at = claim_now + timedelta(
                    seconds=normalized_lease_seconds
                )
                claim_token = str(uuid4())
                updated = connection.execute(
                    update(DISCOVERY_JOBS_TABLE)
                    .where(
                        and_(
                            DISCOVERY_JOBS_TABLE.c.id == job_id,
                            DISCOVERY_JOBS_TABLE.c.job_status == "pending",
                            # Repeated from the candidate query on purpose: this is
                            # the compare-and-swap. Without it, a row rerouted to
                            # the agent backend between selection and update would
                            # still be leased by the legacy executor.
                            DISCOVERY_JOBS_TABLE.c.execution_backend
                            == ExecutionBackend.LEGACY.value,
                            DISCOVERY_JOBS_TABLE.c.next_attempt_at <= claim_now,
                            _no_active_correlated_run_predicate(),
                            or_(
                                DISCOVERY_JOBS_TABLE.c.claim_token.is_(None),
                                DISCOVERY_JOBS_TABLE.c.lease_expires_at.is_(None),
                                DISCOVERY_JOBS_TABLE.c.lease_expires_at <= claim_now,
                            ),
                        )
                    )
                    .values(
                        processing_started_at=claim_now,
                        claim_token=claim_token,
                        lease_expires_at=claim_lease_expires_at,
                        lease_heartbeat_at=claim_now,
                        updated_at=claim_now,
                    )
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

    def recover_completed_discovery_job(
        self,
        *,
        tenant_id: str,
        job_id: str,
    ) -> DiscoveryJobRecord | None:
        """Atomically dispatch a job whose correlated run already completed."""

        from egp_db.repositories.run_repo import CRAWL_RUNS_TABLE

        normalized_tenant_id = normalize_uuid_string(tenant_id)
        normalized_job_id = normalize_uuid_string(job_id)
        now = _now()
        with self._engine.begin() as connection:
            locked = connection.execute(
                select(DISCOVERY_JOBS_TABLE.c.id)
                .where(
                    and_(
                        DISCOVERY_JOBS_TABLE.c.tenant_id == normalized_tenant_id,
                        DISCOVERY_JOBS_TABLE.c.id == normalized_job_id,
                    )
                )
                .with_for_update()
            ).scalar_one_or_none()
            if locked is None:
                return None
            completed_run = connection.execute(
                select(CRAWL_RUNS_TABLE.c.id)
                .where(
                    and_(
                        CRAWL_RUNS_TABLE.c.tenant_id == normalized_tenant_id,
                        CRAWL_RUNS_TABLE.c.discovery_job_id == normalized_job_id,
                        CRAWL_RUNS_TABLE.c.status.in_(("succeeded", "partial")),
                    )
                )
                .limit(1)
            ).scalar_one_or_none()
            if completed_run is None:
                return None
            connection.execute(
                update(DISCOVERY_JOBS_TABLE)
                .where(
                    and_(
                        DISCOVERY_JOBS_TABLE.c.tenant_id == normalized_tenant_id,
                        DISCOVERY_JOBS_TABLE.c.id == normalized_job_id,
                    )
                )
                .values(
                    job_status="dispatched",
                    attempt_count=DISCOVERY_JOBS_TABLE.c.attempt_count + 1,
                    last_error=None,
                    last_error_code=None,
                    next_attempt_at=now,
                    processing_started_at=None,
                    claim_token=None,
                    lease_expires_at=None,
                    lease_heartbeat_at=None,
                    dispatched_at=now,
                    updated_at=now,
                )
            )
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
                .one()
            )
        return _job_from_mapping(row)

    def renew_discovery_job_lease(
        self,
        *,
        tenant_id: str,
        job_id: str,
        claim_token: str,
        lease_seconds: float = 60.0,
    ) -> DiscoveryJobRecord:
        normalized_tenant_id = normalize_uuid_string(tenant_id)
        normalized_job_id = normalize_uuid_string(job_id)
        normalized_claim_token = normalize_uuid_string(claim_token)
        now = _now()
        lease_expires_at = now + timedelta(seconds=max(0.01, float(lease_seconds)))
        with self._engine.begin() as connection:
            renewed = connection.execute(
                update(DISCOVERY_JOBS_TABLE)
                .where(
                    and_(
                        DISCOVERY_JOBS_TABLE.c.tenant_id == normalized_tenant_id,
                        DISCOVERY_JOBS_TABLE.c.id == normalized_job_id,
                        DISCOVERY_JOBS_TABLE.c.job_status == "pending",
                        DISCOVERY_JOBS_TABLE.c.claim_token == normalized_claim_token,
                        DISCOVERY_JOBS_TABLE.c.lease_expires_at.is_not(None),
                        DISCOVERY_JOBS_TABLE.c.lease_expires_at > now,
                    )
                )
                .values(
                    lease_expires_at=lease_expires_at,
                    lease_heartbeat_at=now,
                    updated_at=now,
                )
            )
            if not renewed.rowcount:
                raise StaleDiscoveryJobClaimError(
                    f"discovery job lease is stale for job {job_id}"
                )
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
                .one()
            )
        return _job_from_mapping(row)

    def record_discovery_job_attempt(
        self,
        *,
        tenant_id: str,
        job_id: str,
        claim_token: str | None = None,
        job_status: str,
        last_error: str | None = None,
        last_error_code: DiscoveryFailureCode | str | None = None,
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
            current_claim_token = (
                str(row["claim_token"]) if row["claim_token"] is not None else None
            )
            normalized_claim_token = (
                normalize_uuid_string(claim_token) if claim_token else None
            )
            lease_expires_at = row["lease_expires_at"]
            if current_claim_token is not None and (
                normalized_claim_token != current_claim_token
                or lease_expires_at is None
                or _as_utc(lease_expires_at) <= _as_utc(now)
            ):
                raise StaleDiscoveryJobClaimError(
                    f"discovery job lease is stale for job {job_id}"
                )
            if current_claim_token is None and normalized_claim_token is not None:
                raise StaleDiscoveryJobClaimError(
                    f"discovery job claim token was superseded for job {job_id}"
                )
            normalized_error_code: str | None = None
            if last_error_code:
                try:
                    normalized_error_code = DiscoveryFailureCode(
                        str(last_error_code).strip()
                    ).value
                except ValueError as exc:
                    raise ValueError(
                        f"unknown discovery failure code: {last_error_code!r}"
                    ) from exc
            attempt_filters = [
                DISCOVERY_JOBS_TABLE.c.tenant_id == normalized_tenant_id,
                DISCOVERY_JOBS_TABLE.c.id == normalized_job_id,
            ]
            if current_claim_token is not None:
                attempt_filters.extend(
                    [
                        DISCOVERY_JOBS_TABLE.c.claim_token == normalized_claim_token,
                        DISCOVERY_JOBS_TABLE.c.lease_expires_at > now,
                    ]
                )
            updated = connection.execute(
                update(DISCOVERY_JOBS_TABLE)
                .where(and_(*attempt_filters))
                .values(
                    job_status=str(job_status).strip(),
                    attempt_count=int(row["attempt_count"]) + 1,
                    last_error=(str(last_error).strip()[:1000] if last_error else None),
                    last_error_code=normalized_error_code,
                    next_attempt_at=next_attempt_at or now,
                    processing_started_at=processing_started_at,
                    claim_token=None,
                    lease_expires_at=None,
                    lease_heartbeat_at=None,
                    dispatched_at=now if dispatched else row["dispatched_at"],
                    updated_at=now,
                )
            )
            if not updated.rowcount:
                raise StaleDiscoveryJobClaimError(
                    f"discovery job lease changed while finishing job {job_id}"
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
    bootstrap_schema: bool = False,
) -> SqlDiscoveryJobRepository:
    return SqlDiscoveryJobRepository(
        database_url=database_url,
        engine=engine,
        bootstrap_schema=bootstrap_schema,
    )
