"""Tenant-scoped crawl run and task persistence."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Table,
    and_,
    desc,
    func,
)
from sqlalchemy import Column, insert, select, update
from sqlalchemy.engine import Engine, RowMapping

from egp_db.connection import DB_METADATA, create_shared_engine
from egp_db.db_utils import UUID_SQL_TYPE, normalize_database_url, normalize_uuid_string
from egp_shared_types.enums import CrawlRunStatus, CrawlTaskType


@dataclass(frozen=True, slots=True)
class CrawlRunRecord:
    id: str
    tenant_id: str
    trigger_type: str
    status: CrawlRunStatus
    profile_id: str | None
    started_at: str | None
    finished_at: str | None
    summary_json: dict[str, object] | None
    error_count: int
    created_at: str


@dataclass(frozen=True, slots=True)
class CrawlTaskRecord:
    id: str
    run_id: str
    task_type: str
    project_id: str | None
    keyword: str | None
    status: str
    attempts: int
    started_at: str | None
    finished_at: str | None
    payload: dict[str, object] | None
    result_json: dict[str, object] | None
    created_at: str


@dataclass(frozen=True, slots=True)
class CrawlRunDetail:
    run: CrawlRunRecord
    tasks: list[CrawlTaskRecord]


@dataclass(frozen=True, slots=True)
class CrawlRunPage:
    items: list[CrawlRunRecord]
    total: int
    limit: int
    offset: int


@dataclass(frozen=True, slots=True)
class ProjectCrawlEvidenceRecord:
    task_id: str
    run_id: str
    trigger_type: str
    run_status: CrawlRunStatus
    task_type: str
    task_status: str
    attempts: int
    keyword: str | None
    started_at: str | None
    finished_at: str | None
    created_at: str
    payload: dict[str, object] | None
    result_json: dict[str, object] | None
    run_summary_json: dict[str, object] | None
    run_error_count: int


@dataclass(frozen=True, slots=True)
class ProjectCrawlEvidencePage:
    items: list[ProjectCrawlEvidenceRecord]
    total: int
    limit: int
    offset: int


METADATA = DB_METADATA

CRAWL_RUNS_TABLE = Table(
    "crawl_runs",
    METADATA,
    Column("id", UUID_SQL_TYPE, primary_key=True),
    Column("tenant_id", UUID_SQL_TYPE, nullable=False),
    Column("profile_id", UUID_SQL_TYPE, nullable=True),
    Column("trigger_type", String, nullable=False),
    Column("status", String, nullable=False),
    Column("started_at", DateTime(timezone=True), nullable=True),
    Column("finished_at", DateTime(timezone=True), nullable=True),
    Column("summary_json", JSON, nullable=True),
    Column("error_count", Integer, nullable=False, default=0),
    Column("created_at", DateTime(timezone=True), nullable=False),
    CheckConstraint(
        "trigger_type IN ('schedule', 'manual', 'retry', 'backfill')",
        name="runs_trigger_check",
    ),
    CheckConstraint(
        "status IN ('queued', 'running', 'succeeded', 'partial', 'failed', 'cancelled')",
        name="runs_status_check",
    ),
)

CRAWL_TASKS_TABLE = Table(
    "crawl_tasks",
    METADATA,
    Column("id", UUID_SQL_TYPE, primary_key=True),
    Column(
        "run_id",
        UUID_SQL_TYPE,
        ForeignKey("crawl_runs.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("task_type", String, nullable=False),
    Column("project_id", UUID_SQL_TYPE, nullable=True),
    Column("keyword", String, nullable=True),
    Column("status", String, nullable=False),
    Column("attempts", Integer, nullable=False, default=0),
    Column("started_at", DateTime(timezone=True), nullable=True),
    Column("finished_at", DateTime(timezone=True), nullable=True),
    Column("payload", JSON, nullable=True),
    Column("result_json", JSON, nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False),
    CheckConstraint(
        "task_type IN ('discover', 'update', 'close_check', 'download')",
        name="tasks_type_check",
    ),
    CheckConstraint(
        "status IN ('queued', 'running', 'succeeded', 'failed', 'skipped')",
        name="tasks_status_check",
    ),
)


def _now() -> datetime:
    return datetime.now(UTC)


def _dt_to_iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.isoformat()


_VALID_RUN_TRIGGER_TYPES = {"schedule", "manual", "retry", "backfill"}
_VALID_TASK_STATUSES = {"queued", "running", "succeeded", "failed", "skipped"}


def _validate_run_trigger_type(value: str) -> str:
    normalized = str(value).strip()
    if normalized not in _VALID_RUN_TRIGGER_TYPES:
        raise ValueError("invalid crawl run trigger_type")
    return normalized


def _validate_run_status(value: CrawlRunStatus | str) -> str:
    normalized = (
        value.value if isinstance(value, CrawlRunStatus) else str(value).strip()
    )
    try:
        return CrawlRunStatus(normalized).value
    except ValueError as exc:
        raise ValueError("invalid crawl run status") from exc


def _validate_task_type(value: str) -> str:
    normalized = str(value).strip()
    try:
        return CrawlTaskType(normalized).value
    except ValueError as exc:
        raise ValueError("invalid crawl task_type") from exc


def _validate_task_status(value: str) -> str:
    normalized = str(value).strip()
    if normalized not in _VALID_TASK_STATUSES:
        raise ValueError("invalid crawl task status")
    return normalized


def _run_from_mapping(row: RowMapping) -> CrawlRunRecord:
    return CrawlRunRecord(
        id=str(row["id"]),
        tenant_id=str(row["tenant_id"]),
        trigger_type=str(row["trigger_type"]),
        status=CrawlRunStatus(str(row["status"])),
        profile_id=str(row["profile_id"]) if row["profile_id"] is not None else None,
        started_at=_dt_to_iso(row["started_at"]),
        finished_at=_dt_to_iso(row["finished_at"]),
        summary_json=row["summary_json"],
        error_count=int(row["error_count"]),
        created_at=_dt_to_iso(row["created_at"]) or "",
    )


def _task_from_mapping(row: RowMapping) -> CrawlTaskRecord:
    return CrawlTaskRecord(
        id=str(row["id"]),
        run_id=str(row["run_id"]),
        task_type=str(row["task_type"]),
        project_id=str(row["project_id"]) if row["project_id"] is not None else None,
        keyword=str(row["keyword"]) if row["keyword"] is not None else None,
        status=str(row["status"]),
        attempts=int(row["attempts"]),
        started_at=_dt_to_iso(row["started_at"]),
        finished_at=_dt_to_iso(row["finished_at"]),
        payload=row["payload"],
        result_json=row["result_json"],
        created_at=_dt_to_iso(row["created_at"]) or "",
    )


def _project_crawl_evidence_from_mapping(row: RowMapping) -> ProjectCrawlEvidenceRecord:
    return ProjectCrawlEvidenceRecord(
        task_id=str(row["task_id"]),
        run_id=str(row["run_id"]),
        trigger_type=str(row["trigger_type"]),
        run_status=CrawlRunStatus(str(row["run_status"])),
        task_type=str(row["task_type"]),
        task_status=str(row["task_status"]),
        attempts=int(row["attempts"]),
        keyword=str(row["keyword"]) if row["keyword"] is not None else None,
        started_at=_dt_to_iso(row["started_at"]),
        finished_at=_dt_to_iso(row["finished_at"]),
        created_at=_dt_to_iso(row["created_at"]) or "",
        payload=row["payload"],
        result_json=row["result_json"],
        run_summary_json=row["run_summary_json"],
        run_error_count=int(row["run_error_count"]),
    )


class SqlRunRepository:
    """Relational crawl run repository."""

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

    def create_run(
        self,
        *,
        tenant_id: str,
        trigger_type: str,
        profile_id: str | None = None,
        summary_json: dict[str, object] | None = None,
    ) -> CrawlRunRecord:
        now = _now()
        run_id = str(uuid4())
        normalized_profile_id = (
            normalize_uuid_string(profile_id) if profile_id else None
        )
        normalized_trigger_type = _validate_run_trigger_type(trigger_type)
        with self._engine.begin() as connection:
            connection.execute(
                insert(CRAWL_RUNS_TABLE).values(
                    id=run_id,
                    tenant_id=normalize_uuid_string(tenant_id),
                    profile_id=normalized_profile_id,
                    trigger_type=normalized_trigger_type,
                    status=CrawlRunStatus.QUEUED.value,
                    started_at=None,
                    finished_at=None,
                    summary_json=summary_json,
                    error_count=0,
                    created_at=now,
                )
            )
            row = (
                connection.execute(
                    select(CRAWL_RUNS_TABLE)
                    .where(CRAWL_RUNS_TABLE.c.id == run_id)
                    .limit(1)
                )
                .mappings()
                .one()
            )
        return _run_from_mapping(row)

    def mark_run_started(self, run_id: str) -> CrawlRunRecord:
        now = _now()
        normalized_run_id = normalize_uuid_string(run_id)
        with self._engine.begin() as connection:
            connection.execute(
                update(CRAWL_RUNS_TABLE)
                .where(CRAWL_RUNS_TABLE.c.id == normalized_run_id)
                .values(status=CrawlRunStatus.RUNNING.value, started_at=now)
            )
            row = (
                connection.execute(
                    select(CRAWL_RUNS_TABLE)
                    .where(CRAWL_RUNS_TABLE.c.id == normalized_run_id)
                    .limit(1)
                )
                .mappings()
                .one()
            )
        return _run_from_mapping(row)

    def mark_run_finished(
        self,
        run_id: str,
        *,
        status: CrawlRunStatus | str,
        summary_json: dict[str, object] | None = None,
        error_count: int = 0,
    ) -> CrawlRunRecord:
        now = _now()
        normalized_run_id = normalize_uuid_string(run_id)
        normalized_status = _validate_run_status(status)
        with self._engine.begin() as connection:
            connection.execute(
                update(CRAWL_RUNS_TABLE)
                .where(CRAWL_RUNS_TABLE.c.id == normalized_run_id)
                .values(
                    status=normalized_status,
                    finished_at=now,
                    summary_json=summary_json,
                    error_count=error_count,
                )
            )
            row = (
                connection.execute(
                    select(CRAWL_RUNS_TABLE)
                    .where(CRAWL_RUNS_TABLE.c.id == normalized_run_id)
                    .limit(1)
                )
                .mappings()
                .one()
            )
        return _run_from_mapping(row)

    def create_task(
        self,
        *,
        run_id: str,
        task_type: str,
        project_id: str | None = None,
        keyword: str | None = None,
        payload: dict[str, object] | None = None,
    ) -> CrawlTaskRecord:
        now = _now()
        task_id = str(uuid4())
        normalized_task_type = _validate_task_type(task_type)
        with self._engine.begin() as connection:
            connection.execute(
                insert(CRAWL_TASKS_TABLE).values(
                    id=task_id,
                    run_id=normalize_uuid_string(run_id),
                    task_type=normalized_task_type,
                    project_id=normalize_uuid_string(project_id)
                    if project_id
                    else None,
                    keyword=keyword,
                    status="queued",
                    attempts=0,
                    started_at=None,
                    finished_at=None,
                    payload=payload,
                    result_json=None,
                    created_at=now,
                )
            )
            row = (
                connection.execute(
                    select(CRAWL_TASKS_TABLE)
                    .where(CRAWL_TASKS_TABLE.c.id == task_id)
                    .limit(1)
                )
                .mappings()
                .one()
            )
        return _task_from_mapping(row)

    def mark_task_started(self, task_id: str) -> CrawlTaskRecord:
        now = _now()
        normalized_task_id = normalize_uuid_string(task_id)
        with self._engine.begin() as connection:
            connection.execute(
                update(CRAWL_TASKS_TABLE)
                .where(CRAWL_TASKS_TABLE.c.id == normalized_task_id)
                .values(
                    status="running",
                    started_at=now,
                    attempts=CRAWL_TASKS_TABLE.c.attempts + 1,
                )
            )
            row = (
                connection.execute(
                    select(CRAWL_TASKS_TABLE)
                    .where(CRAWL_TASKS_TABLE.c.id == normalized_task_id)
                    .limit(1)
                )
                .mappings()
                .one()
            )
        return _task_from_mapping(row)

    def mark_task_finished(
        self,
        task_id: str,
        *,
        status: str,
        result_json: dict[str, object] | None = None,
    ) -> CrawlTaskRecord:
        now = _now()
        normalized_task_id = normalize_uuid_string(task_id)
        normalized_status = _validate_task_status(status)
        with self._engine.begin() as connection:
            current = (
                connection.execute(
                    select(CRAWL_TASKS_TABLE)
                    .where(CRAWL_TASKS_TABLE.c.id == normalized_task_id)
                    .limit(1)
                )
                .mappings()
                .one()
            )
            attempts = int(current["attempts"])
            started_at = current["started_at"] or now
            connection.execute(
                update(CRAWL_TASKS_TABLE)
                .where(CRAWL_TASKS_TABLE.c.id == normalized_task_id)
                .values(
                    status=normalized_status,
                    attempts=attempts or 1,
                    started_at=started_at,
                    finished_at=now,
                    result_json=result_json,
                )
            )
            row = (
                connection.execute(
                    select(CRAWL_TASKS_TABLE)
                    .where(CRAWL_TASKS_TABLE.c.id == normalized_task_id)
                    .limit(1)
                )
                .mappings()
                .one()
            )
        return _task_from_mapping(row)

    def list_runs(
        self, *, tenant_id: str, limit: int = 50, offset: int = 0
    ) -> CrawlRunPage:
        normalized_limit = max(1, min(int(limit), 200))
        normalized_offset = max(0, int(offset))
        normalized_tenant_id = normalize_uuid_string(tenant_id)
        with self._engine.connect() as connection:
            total = int(
                connection.execute(
                    select(func.count())
                    .select_from(CRAWL_RUNS_TABLE)
                    .where(CRAWL_RUNS_TABLE.c.tenant_id == normalized_tenant_id)
                ).scalar_one()
            )
            rows = (
                connection.execute(
                    select(CRAWL_RUNS_TABLE)
                    .where(CRAWL_RUNS_TABLE.c.tenant_id == normalized_tenant_id)
                    .order_by(desc(CRAWL_RUNS_TABLE.c.created_at))
                    .limit(normalized_limit)
                    .offset(normalized_offset)
                )
                .mappings()
                .all()
            )
        return CrawlRunPage(
            items=[_run_from_mapping(row) for row in rows],
            total=total,
            limit=normalized_limit,
            offset=normalized_offset,
        )

    def find_run_by_id(self, run_id: str) -> CrawlRunRecord | None:
        normalized_run_id = normalize_uuid_string(run_id)
        with self._engine.connect() as connection:
            row = (
                connection.execute(
                    select(CRAWL_RUNS_TABLE)
                    .where(CRAWL_RUNS_TABLE.c.id == normalized_run_id)
                    .limit(1)
                )
                .mappings()
                .first()
            )
        return _run_from_mapping(row) if row is not None else None

    def find_task_by_id(self, task_id: str) -> CrawlTaskRecord | None:
        normalized_task_id = normalize_uuid_string(task_id)
        with self._engine.connect() as connection:
            row = (
                connection.execute(
                    select(CRAWL_TASKS_TABLE)
                    .where(CRAWL_TASKS_TABLE.c.id == normalized_task_id)
                    .limit(1)
                )
                .mappings()
                .first()
            )
        return _task_from_mapping(row) if row is not None else None

    def get_run_detail(self, *, tenant_id: str, run_id: str) -> CrawlRunDetail | None:
        normalized_tenant_id = normalize_uuid_string(tenant_id)
        normalized_run_id = normalize_uuid_string(run_id)
        with self._engine.connect() as connection:
            run_row = (
                connection.execute(
                    select(CRAWL_RUNS_TABLE)
                    .where(
                        and_(
                            CRAWL_RUNS_TABLE.c.tenant_id == normalized_tenant_id,
                            CRAWL_RUNS_TABLE.c.id == normalized_run_id,
                        )
                    )
                    .limit(1)
                )
                .mappings()
                .first()
            )
            if run_row is None:
                return None
            task_rows = (
                connection.execute(
                    select(CRAWL_TASKS_TABLE)
                    .where(CRAWL_TASKS_TABLE.c.run_id == normalized_run_id)
                    .order_by(CRAWL_TASKS_TABLE.c.created_at)
                )
                .mappings()
                .all()
            )
        return CrawlRunDetail(
            run=_run_from_mapping(run_row),
            tasks=[_task_from_mapping(row) for row in task_rows],
        )

    def list_project_crawl_evidence(
        self,
        *,
        tenant_id: str,
        project_id: str,
        limit: int = 20,
        offset: int = 0,
    ) -> ProjectCrawlEvidencePage:
        normalized_tenant_id = normalize_uuid_string(tenant_id)
        normalized_project_id = normalize_uuid_string(project_id)
        normalized_limit = max(1, min(int(limit), 100))
        normalized_offset = max(0, int(offset))
        joined_tables = CRAWL_TASKS_TABLE.join(
            CRAWL_RUNS_TABLE,
            CRAWL_RUNS_TABLE.c.id == CRAWL_TASKS_TABLE.c.run_id,
        )
        filters = and_(
            CRAWL_RUNS_TABLE.c.tenant_id == normalized_tenant_id,
            CRAWL_TASKS_TABLE.c.project_id == normalized_project_id,
        )
        with self._engine.connect() as connection:
            total = int(
                connection.execute(
                    select(func.count()).select_from(joined_tables).where(filters)
                ).scalar_one()
            )
            rows = (
                connection.execute(
                    select(
                        CRAWL_TASKS_TABLE.c.id.label("task_id"),
                        CRAWL_TASKS_TABLE.c.run_id,
                        CRAWL_RUNS_TABLE.c.trigger_type,
                        CRAWL_RUNS_TABLE.c.status.label("run_status"),
                        CRAWL_TASKS_TABLE.c.task_type,
                        CRAWL_TASKS_TABLE.c.status.label("task_status"),
                        CRAWL_TASKS_TABLE.c.attempts,
                        CRAWL_TASKS_TABLE.c.keyword,
                        CRAWL_TASKS_TABLE.c.started_at,
                        CRAWL_TASKS_TABLE.c.finished_at,
                        CRAWL_TASKS_TABLE.c.created_at,
                        CRAWL_TASKS_TABLE.c.payload,
                        CRAWL_TASKS_TABLE.c.result_json,
                        CRAWL_RUNS_TABLE.c.summary_json.label("run_summary_json"),
                        CRAWL_RUNS_TABLE.c.error_count.label("run_error_count"),
                    )
                    .select_from(joined_tables)
                    .where(filters)
                    .order_by(
                        desc(CRAWL_TASKS_TABLE.c.finished_at),
                        desc(CRAWL_TASKS_TABLE.c.started_at),
                        desc(CRAWL_TASKS_TABLE.c.created_at),
                    )
                    .limit(normalized_limit)
                    .offset(normalized_offset)
                )
                .mappings()
                .all()
            )
        return ProjectCrawlEvidencePage(
            items=[_project_crawl_evidence_from_mapping(row) for row in rows],
            total=total,
            limit=normalized_limit,
            offset=normalized_offset,
        )


def create_run_repository(
    *,
    database_url: str | None = None,
    engine: Engine | None = None,
    bootstrap_schema: bool = True,
) -> SqlRunRepository:
    return SqlRunRepository(
        database_url=database_url, engine=engine, bootstrap_schema=bootstrap_schema
    )
