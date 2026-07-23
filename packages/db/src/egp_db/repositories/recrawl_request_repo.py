"""Durable request batches for manual keyword recrawls."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Table,
)
from sqlalchemy import and_, func, insert, select, update
from sqlalchemy.engine import Engine, RowMapping

from egp_db.connection import DB_METADATA, create_shared_engine
from egp_db.db_utils import UUID_SQL_TYPE, normalize_database_url, normalize_uuid_string


METADATA = DB_METADATA

RECRAWL_REQUESTS_TABLE = Table(
    "recrawl_requests",
    METADATA,
    Column("id", UUID_SQL_TYPE, primary_key=True),
    Column(
        "tenant_id",
        UUID_SQL_TYPE,
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column(
        "source",
        String,
        nullable=False,
        default="manual",
        server_default="manual",
    ),
    Column("idempotency_key", String, nullable=True),
    Column("requested_keyword_count", Integer, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
    CheckConstraint(
        "requested_keyword_count >= 0",
        name="recrawl_requests_keyword_count_check",
    ),
    CheckConstraint(
        "source IN ('manual', 'operator_recovery')",
        name="recrawl_requests_source_check",
    ),
)

Index(
    "idx_recrawl_requests_tenant_created",
    RECRAWL_REQUESTS_TABLE.c.tenant_id,
    RECRAWL_REQUESTS_TABLE.c.created_at,
)
Index(
    "idx_recrawl_requests_tenant_idempotency",
    RECRAWL_REQUESTS_TABLE.c.tenant_id,
    RECRAWL_REQUESTS_TABLE.c.idempotency_key,
    unique=True,
    sqlite_where=RECRAWL_REQUESTS_TABLE.c.idempotency_key.is_not(None),
    postgresql_where=RECRAWL_REQUESTS_TABLE.c.idempotency_key.is_not(None),
)


@dataclass(frozen=True, slots=True)
class RecrawlJobInput:
    profile_id: str
    profile_type: str
    keyword: str


@dataclass(frozen=True, slots=True)
class RecrawlRequestCreateResult:
    request_id: str
    queued_job_count: int
    queued_keywords: list[str]


@dataclass(frozen=True, slots=True)
class RecrawlRequestStatus:
    request_id: str
    requested_keyword_count: int
    queued_count: int
    running_count: int
    retrying_count: int
    succeeded_count: int
    zero_result_count: int
    partial_count: int
    failed_count: int
    failed_keywords: list[str]
    is_terminal: bool
    created_at: str
    updated_at: str


def _now() -> datetime:
    return datetime.now(UTC)


def _to_iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.isoformat()


def _summary_projects_seen(summary: object) -> int:
    if not isinstance(summary, dict):
        return 0
    try:
        return int(summary.get("projects_seen", 0))
    except (TypeError, ValueError):
        return 0


def _dedupe_jobs(jobs: list[RecrawlJobInput]) -> list[RecrawlJobInput]:
    unique: list[RecrawlJobInput] = []
    seen: set[tuple[str, str]] = set()
    for job in jobs:
        profile_id = normalize_uuid_string(job.profile_id)
        keyword = job.keyword.strip()
        key = (profile_id, keyword.casefold())
        if not keyword or key in seen:
            continue
        seen.add(key)
        unique.append(
            RecrawlJobInput(
                profile_id=profile_id,
                profile_type=job.profile_type.strip() or "custom",
                keyword=keyword,
            )
        )
    return unique


class SqlRecrawlRequestRepository:
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
            METADATA.create_all(self._engine)

    def create_request(
        self,
        *,
        tenant_id: str,
        jobs: list[RecrawlJobInput],
        source: str = "manual",
        idempotency_key: str | None = None,
        trigger_type: str = "manual",
        reject_existing_pending: bool = False,
    ) -> RecrawlRequestCreateResult:
        from egp_db.repositories.discovery_job_repo import (
            DISCOVERY_JOBS_TABLE,
            build_discovery_job_values,
        )

        normalized_tenant_id = normalize_uuid_string(tenant_id)
        desired_jobs = _dedupe_jobs(jobs)
        if not desired_jobs:
            raise ValueError("at least one active keyword is required")
        normalized_source = str(source).strip()
        if normalized_source not in {"manual", "operator_recovery"}:
            raise ValueError("invalid recrawl request source")
        normalized_trigger_type = str(trigger_type).strip()
        if normalized_trigger_type not in {"manual", "retry"}:
            raise ValueError("invalid recrawl trigger_type")
        normalized_idempotency_key = (
            str(idempotency_key).strip() if idempotency_key is not None else None
        )
        if normalized_idempotency_key == "":
            raise ValueError("idempotency_key cannot be empty")
        if normalized_source == "operator_recovery" and (
            normalized_trigger_type != "retry"
            or not normalized_idempotency_key
            or not reject_existing_pending
        ):
            raise ValueError(
                "operator recovery requires retry jobs, idempotency, and pending-job rejection"
            )

        now = _now()
        with self._engine.begin() as connection:
            if connection.dialect.name != "sqlite":
                tenants_table = METADATA.tables["tenants"]
                tenant_row = connection.execute(
                    select(tenants_table.c.id)
                    .where(tenants_table.c.id == normalized_tenant_id)
                    .with_for_update()
                ).scalar_one_or_none()
                if tenant_row is None:
                    raise KeyError(tenant_id)
            if normalized_idempotency_key is not None:
                existing_request_id = connection.execute(
                    select(RECRAWL_REQUESTS_TABLE.c.id).where(
                        and_(
                            RECRAWL_REQUESTS_TABLE.c.tenant_id
                            == normalized_tenant_id,
                            RECRAWL_REQUESTS_TABLE.c.idempotency_key
                            == normalized_idempotency_key,
                        )
                    )
                ).scalar_one_or_none()
                if existing_request_id is not None:
                    return RecrawlRequestCreateResult(
                        request_id=str(existing_request_id),
                        queued_job_count=0,
                        queued_keywords=[],
                    )
            existing_by_key: dict[tuple[str, str], RowMapping] = {}
            for desired in desired_jobs:
                row = (
                    connection.execute(
                        select(DISCOVERY_JOBS_TABLE)
                        .where(
                            and_(
                                DISCOVERY_JOBS_TABLE.c.tenant_id
                                == normalized_tenant_id,
                                DISCOVERY_JOBS_TABLE.c.profile_id == desired.profile_id,
                                DISCOVERY_JOBS_TABLE.c.keyword == desired.keyword,
                                DISCOVERY_JOBS_TABLE.c.live.is_(True),
                                DISCOVERY_JOBS_TABLE.c.job_status == "pending",
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
                if row is not None:
                    existing_by_key[(desired.profile_id, desired.keyword.casefold())] = row

            if reject_existing_pending and existing_by_key:
                pending_ids = sorted(str(row["id"]) for row in existing_by_key.values())
                raise ValueError(
                    "recovery targets already have pending discovery jobs: "
                    + ", ".join(pending_ids)
                )
            if reject_existing_pending:
                desired_keys = {
                    (desired.profile_id, desired.keyword.casefold())
                    for desired in desired_jobs
                }
                pending_rows = connection.execute(
                    select(DISCOVERY_JOBS_TABLE).where(
                        and_(
                            DISCOVERY_JOBS_TABLE.c.tenant_id
                            == normalized_tenant_id,
                            DISCOVERY_JOBS_TABLE.c.profile_id.in_(
                                {desired.profile_id for desired in desired_jobs}
                            ),
                            DISCOVERY_JOBS_TABLE.c.live.is_(True),
                            DISCOVERY_JOBS_TABLE.c.job_status == "pending",
                        )
                    )
                ).mappings().all()
                matching_pending_ids = sorted(
                    str(row["id"])
                    for row in pending_rows
                    if (
                        str(row["profile_id"]),
                        str(row["keyword"]).casefold(),
                    )
                    in desired_keys
                )
                if matching_pending_ids:
                    raise ValueError(
                        "recovery targets already have pending discovery jobs: "
                        + ", ".join(matching_pending_ids)
                    )

            existing_request_ids = {
                str(row["recrawl_request_id"])
                for row in existing_by_key.values()
                if row["recrawl_request_id"] is not None
            }
            if len(existing_request_ids) > 1:
                raise RuntimeError("multiple active recrawl requests overlap")
            request_id = (
                next(iter(existing_request_ids))
                if existing_request_ids
                else str(uuid4())
            )
            if existing_request_ids:
                request_job_rows = (
                    connection.execute(
                        select(DISCOVERY_JOBS_TABLE).where(
                            and_(
                                DISCOVERY_JOBS_TABLE.c.tenant_id
                                == normalized_tenant_id,
                                DISCOVERY_JOBS_TABLE.c.recrawl_request_id
                                == request_id,
                            )
                        )
                    )
                    .mappings()
                    .all()
                )
                request_jobs_by_key = {
                    (str(row["profile_id"]), str(row["keyword"]).casefold()): row
                    for row in request_job_rows
                }
                for desired in desired_jobs:
                    key = (desired.profile_id, desired.keyword.casefold())
                    if key not in existing_by_key and key in request_jobs_by_key:
                        existing_by_key[key] = request_jobs_by_key[key]
                if len(existing_by_key) == len(desired_jobs):
                    return RecrawlRequestCreateResult(
                        request_id=request_id,
                        queued_job_count=0,
                        queued_keywords=[],
                    )
            else:
                connection.execute(
                    insert(RECRAWL_REQUESTS_TABLE).values(
                        id=request_id,
                        tenant_id=normalized_tenant_id,
                        source=normalized_source,
                        idempotency_key=normalized_idempotency_key,
                        requested_keyword_count=len(desired_jobs),
                        created_at=now,
                        updated_at=now,
                    )
                )
            queued_keywords: list[str] = []
            for desired in desired_jobs:
                existing = existing_by_key.get(
                    (desired.profile_id, desired.keyword.casefold())
                )
                if existing is not None:
                    if existing["recrawl_request_id"] is None:
                        connection.execute(
                            update(DISCOVERY_JOBS_TABLE)
                            .where(DISCOVERY_JOBS_TABLE.c.id == existing["id"])
                            .values(recrawl_request_id=request_id, updated_at=now)
                        )
                    continue
                values = build_discovery_job_values(
                    tenant_id=normalized_tenant_id,
                    profile_id=desired.profile_id,
                    profile_type=desired.profile_type,
                    keyword=desired.keyword,
                    trigger_type=normalized_trigger_type,
                    live=True,
                    recrawl_request_id=request_id,
                    now=now,
                )
                connection.execute(insert(DISCOVERY_JOBS_TABLE).values(**values))
                queued_keywords.append(desired.keyword)

            correlated_job_count = connection.execute(
                select(func.count())
                .select_from(DISCOVERY_JOBS_TABLE)
                .where(
                    and_(
                        DISCOVERY_JOBS_TABLE.c.tenant_id == normalized_tenant_id,
                        DISCOVERY_JOBS_TABLE.c.recrawl_request_id == request_id,
                    )
                )
            ).scalar_one()
            connection.execute(
                update(RECRAWL_REQUESTS_TABLE)
                .where(
                    and_(
                        RECRAWL_REQUESTS_TABLE.c.tenant_id == normalized_tenant_id,
                        RECRAWL_REQUESTS_TABLE.c.id == request_id,
                    )
                )
                .values(
                    requested_keyword_count=int(correlated_job_count),
                    updated_at=now,
                )
            )

        return RecrawlRequestCreateResult(
            request_id=request_id,
            queued_job_count=len(queued_keywords),
            queued_keywords=queued_keywords,
        )

    def get_status(self, *, tenant_id: str, request_id: str) -> RecrawlRequestStatus:
        from egp_db.repositories.discovery_job_repo import DISCOVERY_JOBS_TABLE
        from egp_db.repositories.run_repo import CRAWL_RUNS_TABLE

        normalized_tenant_id = normalize_uuid_string(tenant_id)
        normalized_request_id = normalize_uuid_string(request_id)
        with self._engine.connect() as connection:
            request_row = (
                connection.execute(
                    select(RECRAWL_REQUESTS_TABLE).where(
                        and_(
                            RECRAWL_REQUESTS_TABLE.c.tenant_id
                            == normalized_tenant_id,
                            RECRAWL_REQUESTS_TABLE.c.id == normalized_request_id,
                        )
                    )
                )
                .mappings()
                .first()
            )
            if request_row is None:
                raise KeyError(request_id)
            job_rows = (
                connection.execute(
                    select(DISCOVERY_JOBS_TABLE)
                    .where(
                        and_(
                            DISCOVERY_JOBS_TABLE.c.tenant_id == normalized_tenant_id,
                            DISCOVERY_JOBS_TABLE.c.recrawl_request_id
                            == normalized_request_id,
                        )
                    )
                    .order_by(DISCOVERY_JOBS_TABLE.c.created_at, DISCOVERY_JOBS_TABLE.c.id)
                )
                .mappings()
                .all()
            )
            run_rows = (
                connection.execute(
                    select(CRAWL_RUNS_TABLE)
                    .where(
                        and_(
                            CRAWL_RUNS_TABLE.c.tenant_id == normalized_tenant_id,
                            CRAWL_RUNS_TABLE.c.recrawl_request_id
                            == normalized_request_id,
                        )
                    )
                    .order_by(CRAWL_RUNS_TABLE.c.created_at, CRAWL_RUNS_TABLE.c.id)
                )
                .mappings()
                .all()
            )

        latest_runs: dict[str, RowMapping] = {}
        for row in run_rows:
            job_id = row["discovery_job_id"]
            if job_id is not None:
                latest_runs[str(job_id)] = row

        counts = {
            "queued": 0,
            "running": 0,
            "retrying": 0,
            "succeeded": 0,
            "zero_result": 0,
            "partial": 0,
            "failed": 0,
        }
        failed_keywords: list[str] = []
        latest_timestamp = request_row["updated_at"]
        for job in job_rows:
            latest_timestamp = max(latest_timestamp, job["updated_at"])
            latest_run = latest_runs.get(str(job["id"]))
            if latest_run is not None:
                for timestamp_key in ("created_at", "started_at", "finished_at"):
                    timestamp = latest_run[timestamp_key]
                    if timestamp is not None:
                        latest_timestamp = max(latest_timestamp, timestamp)

            state = self._resolve_job_state(job=job, latest_run=latest_run)
            counts[state] += 1
            if state == "failed":
                failed_keywords.append(str(job["keyword"]))

        requested_count = int(request_row["requested_keyword_count"])
        terminal_count = (
            counts["succeeded"]
            + counts["zero_result"]
            + counts["partial"]
            + counts["failed"]
        )
        return RecrawlRequestStatus(
            request_id=str(request_row["id"]),
            requested_keyword_count=requested_count,
            queued_count=counts["queued"],
            running_count=counts["running"],
            retrying_count=counts["retrying"],
            succeeded_count=counts["succeeded"],
            zero_result_count=counts["zero_result"],
            partial_count=counts["partial"],
            failed_count=counts["failed"],
            failed_keywords=failed_keywords,
            is_terminal=terminal_count == requested_count,
            created_at=_to_iso(request_row["created_at"]) or "",
            updated_at=_to_iso(latest_timestamp) or "",
        )

    @staticmethod
    def _resolve_job_state(*, job: RowMapping, latest_run: RowMapping | None) -> str:
        job_status = str(job["job_status"])
        if job_status == "failed":
            return "failed"
        if latest_run is not None:
            run_status = str(latest_run["status"])
            if run_status == "succeeded":
                if _summary_projects_seen(latest_run["summary_json"]) == 0:
                    return "zero_result"
                return "succeeded"
            if run_status == "partial":
                return "partial"
            if run_status == "running":
                return "running"
            if run_status in {"failed", "cancelled"}:
                return "retrying" if job_status == "pending" else "failed"
        if job_status == "pending" and job["processing_started_at"] is not None:
            return "running"
        if job_status == "pending" and int(job["attempt_count"]) > 0:
            return "retrying"
        return "queued"


def create_recrawl_request_repository(
    *,
    database_url: str | None = None,
    engine: Engine | None = None,
    bootstrap_schema: bool = True,
) -> SqlRecrawlRequestRepository:
    return SqlRecrawlRequestRepository(
        database_url=database_url,
        engine=engine,
        bootstrap_schema=bootstrap_schema,
    )
