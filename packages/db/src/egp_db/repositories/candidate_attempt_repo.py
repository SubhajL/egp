"""Discovery candidate attempt accounting repository.

Records every candidate accepted from the e-GP results table during a
discovery crawl run and tracks its terminal state (persisted / dropped /
failed / unknown).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    Index,
    Integer,
    String,
    Table,
    UniqueConstraint,
    and_,
    func,
    insert,
    select,
    update,
)
from sqlalchemy.engine import Engine, RowMapping

from egp_shared_types.enums import CandidateTerminalReason

from egp_db.connection import DB_METADATA, create_shared_engine
from egp_db.db_utils import UUID_SQL_TYPE, normalize_database_url, normalize_uuid_string


METADATA = DB_METADATA

# The typed vocabulary is defined once (shared-types); the mirror CHECK below is
# built from it, and migration 039's SQL lists are drift-tested against it.
_TERMINAL_REASON_VALUES = tuple(member.value for member in CandidateTerminalReason)
_TERMINAL_REASON_SQL_LIST = ", ".join(f"'{value}'" for value in _TERMINAL_REASON_VALUES)

DISCOVERY_CANDIDATE_ATTEMPTS_TABLE = Table(
    "discovery_candidate_attempts",
    METADATA,
    Column("id", UUID_SQL_TYPE, primary_key=True),
    Column("tenant_id", UUID_SQL_TYPE, nullable=False),
    Column("run_id", UUID_SQL_TYPE, nullable=False),
    Column("candidate_key", String, nullable=False),
    Column("keyword", String, nullable=False),
    Column("page_number", Integer, nullable=True),
    Column("row_ordinal", Integer, nullable=True),
    Column("candidate_status", String, nullable=False, default="accepted"),
    Column("terminal_reason", String, nullable=True),
    Column("terminal_detail", String, nullable=True),
    Column("project_id", UUID_SQL_TYPE, nullable=True),
    Column("project_number", String, nullable=True),
    Column("row_marker", String, nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
    CheckConstraint(
        "candidate_status IN ('accepted', 'persisted', 'dropped', 'failed', 'unknown')",
        name="discovery_candidate_attempts_status_check",
    ),
    # Migration 039 mirrors (SQLite enforces CHECKs, so the unit suite gets a
    # real constraint oracle; the composite FKs are PostgreSQL-only by the 034
    # precedent — the real-Postgres suite is the referential-integrity oracle).
    CheckConstraint(
        f"terminal_reason IS NULL OR terminal_reason IN ({_TERMINAL_REASON_SQL_LIST})",
        name="dca_terminal_reason_vocab_check",
    ),
    CheckConstraint(
        "(candidate_status = 'accepted'"
        " AND terminal_reason IS NULL AND project_id IS NULL)"
        " OR (candidate_status = 'persisted'"
        " AND terminal_reason IS NULL AND project_id IS NOT NULL)"
        " OR (candidate_status IN ('dropped', 'failed', 'unknown')"
        " AND terminal_reason IS NOT NULL AND project_id IS NULL)",
        name="dca_status_shape_check",
    ),
    UniqueConstraint(
        "tenant_id",
        "run_id",
        "candidate_key",
        name="discovery_candidate_attempts_tenant_run_key",
    ),
    extend_existing=True,
)

Index(
    "idx_dca_tenant_run",
    DISCOVERY_CANDIDATE_ATTEMPTS_TABLE.c.tenant_id,
    DISCOVERY_CANDIDATE_ATTEMPTS_TABLE.c.run_id,
)
Index(
    "idx_dca_open_accepted",
    DISCOVERY_CANDIDATE_ATTEMPTS_TABLE.c.run_id,
    DISCOVERY_CANDIDATE_ATTEMPTS_TABLE.c.candidate_status,
    postgresql_where=(
        DISCOVERY_CANDIDATE_ATTEMPTS_TABLE.c.candidate_status == "accepted"
    ),
)


# ---------------------------------------------------------------------------
# Dataclasses / errors
# ---------------------------------------------------------------------------

TERMINAL_STATUSES = frozenset({"persisted", "dropped", "failed", "unknown"})


class CandidateTerminalConflictError(RuntimeError):
    """A terminal candidate row was asked to become a DIFFERENT terminal state.

    Raised by ``_finalize`` when the row is already terminal and the request
    diverges in status, terminal_reason, or (normalized) project_id. An
    identical replay is idempotent and returns the existing record instead.
    """

    def __init__(
        self,
        *,
        tenant_id: str,
        run_id: str,
        candidate_key: str,
        existing_status: str,
        existing_reason: str | None,
        existing_project_id: str | None,
        requested_status: str,
        requested_reason: str | None,
        requested_project_id: str | None,
    ) -> None:
        self.tenant_id = tenant_id
        self.run_id = run_id
        self.candidate_key = candidate_key
        self.existing_status = existing_status
        self.existing_reason = existing_reason
        self.existing_project_id = existing_project_id
        self.requested_status = requested_status
        self.requested_reason = requested_reason
        self.requested_project_id = requested_project_id
        super().__init__(
            f"candidate {candidate_key} is already terminal as "
            f"({existing_status}, {existing_reason}, {existing_project_id}); "
            f"refusing rewrite to "
            f"({requested_status}, {requested_reason}, {requested_project_id})"
        )


@dataclass(frozen=True, slots=True)
class CandidateAttemptRecord:
    id: str
    tenant_id: str
    run_id: str
    candidate_key: str
    keyword: str
    page_number: int | None
    row_ordinal: int | None
    candidate_status: str
    terminal_reason: str | None
    terminal_detail: str | None
    project_id: str | None
    project_number: str | None
    row_marker: str | None
    created_at: str
    updated_at: str


@dataclass(frozen=True, slots=True)
class CandidateRunSummary:
    accepted: int
    persisted: int
    dropped: int
    failed: int
    unknown: int
    total: int


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now() -> datetime:
    return datetime.now(UTC)


def _dt_to_iso(value: datetime | None) -> str:
    if value is None:
        return ""
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.isoformat()


def _record_from_mapping(row: RowMapping) -> CandidateAttemptRecord:
    return CandidateAttemptRecord(
        id=str(row["id"]),
        tenant_id=str(row["tenant_id"]),
        run_id=str(row["run_id"]),
        candidate_key=str(row["candidate_key"]),
        keyword=str(row["keyword"]),
        page_number=int(row["page_number"]) if row["page_number"] is not None else None,
        row_ordinal=int(row["row_ordinal"]) if row["row_ordinal"] is not None else None,
        candidate_status=str(row["candidate_status"]),
        terminal_reason=str(row["terminal_reason"]) if row["terminal_reason"] is not None else None,
        terminal_detail=str(row["terminal_detail"]) if row["terminal_detail"] is not None else None,
        project_id=str(row["project_id"]) if row["project_id"] is not None else None,
        project_number=str(row["project_number"]) if row["project_number"] is not None else None,
        row_marker=str(row["row_marker"]) if row["row_marker"] is not None else None,
        created_at=_dt_to_iso(row["created_at"]),
        updated_at=_dt_to_iso(row["updated_at"]),
    )


def _require_vocabulary_reason(terminal_reason: str | None) -> None:
    """Reject any reason outside CandidateTerminalReason BEFORE touching SQL.

    Keeps the vocabulary self-enforcing at the Python layer: new failure
    classes must extend the enum (and ship a migration) instead of silently
    collapsing into free text or ``unclassified``.
    """
    if terminal_reason is None:
        return
    if terminal_reason not in _TERMINAL_REASON_VALUES:
        raise ValueError(
            f"terminal_reason {terminal_reason!r} is not in the "
            f"CandidateTerminalReason vocabulary"
        )


def _dialect_insert(table, connection):
    """Return a dialect-specific INSERT that supports on_conflict_do_nothing.

    Mirrors ``project_aliases.py``; both PostgreSQL and SQLite implement the
    ``on_conflict_do_nothing`` extension, so idempotent inserts work on the
    production database and the SQLite test/bootstrap path alike.
    """
    if connection.dialect.name == "postgresql":
        from sqlalchemy.dialects.postgresql import insert as postgresql_insert

        return postgresql_insert(table)
    if connection.dialect.name == "sqlite":
        from sqlalchemy.dialects.sqlite import insert as sqlite_insert

        return sqlite_insert(table)
    return insert(table)


# ---------------------------------------------------------------------------
# Repository
# ---------------------------------------------------------------------------

class SqlCandidateAttemptRepository:
    """Durable accounting for discovery candidate rows."""

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

    # -- write: accept ---------------------------------------------------

    def record_accepted(
        self,
        tenant_id: str,
        run_id: str,
        candidate_key: str,
        keyword: str,
        page_number: int | None = None,
        row_ordinal: int | None = None,
        project_number: str | None = None,
        row_marker: str | None = None,
    ) -> CandidateAttemptRecord:
        """Record a newly accepted candidate.  Idempotent via ON CONFLICT DO NOTHING."""
        now = _now()
        normalized_tenant = normalize_uuid_string(tenant_id)
        normalized_run = normalize_uuid_string(run_id)
        row_id = str(uuid4())
        values = {
            "id": row_id,
            "tenant_id": normalized_tenant,
            "run_id": normalized_run,
            "candidate_key": candidate_key,
            "keyword": keyword,
            "page_number": page_number,
            "row_ordinal": row_ordinal,
            "candidate_status": "accepted",
            "terminal_reason": None,
            "terminal_detail": None,
            "project_id": None,
            "project_number": project_number,
            "row_marker": row_marker,
            "created_at": now,
            "updated_at": now,
        }
        t = DISCOVERY_CANDIDATE_ATTEMPTS_TABLE
        with self._engine.begin() as conn:
            # Idempotent insert on the (tenant_id, run_id, candidate_key) unique
            # constraint. Both PostgreSQL (production) and SQLite (tests) implement
            # on_conflict_do_nothing; the generic fallback degrades to a plain
            # insert. `prefix_with("OR IGNORE")` was SQLite-only and produced
            # invalid `INSERT OR IGNORE` SQL on PostgreSQL.
            stmt = _dialect_insert(t, conn).values(**values)
            if hasattr(stmt, "on_conflict_do_nothing"):
                stmt = stmt.on_conflict_do_nothing(
                    index_elements=[t.c.tenant_id, t.c.run_id, t.c.candidate_key]
                )
            conn.execute(stmt)
            row = (
                conn.execute(
                    select(t).where(
                        and_(
                            t.c.tenant_id == normalized_tenant,
                            t.c.run_id == normalized_run,
                            t.c.candidate_key == candidate_key,
                        )
                    ).limit(1)
                )
                .mappings()
                .one()
            )
        return _record_from_mapping(row)

    # -- write: finalize -------------------------------------------------

    def _finalize(
        self,
        tenant_id: str,
        run_id: str,
        candidate_key: str,
        new_status: str,
        terminal_reason: str | None = None,
        project_id: str | None = None,
        terminal_detail: str | None = None,
    ) -> CandidateAttemptRecord | None:
        """Transition from 'accepted' to a terminal state.

        Outcomes on an already-terminal row (F6/R6): an identical request —
        same status, same reason, same normalized project — returns the
        existing record (idempotent replay; ``terminal_detail`` is diagnostics
        only and excluded from the comparison, so the first detail wins); any
        divergence raises :class:`CandidateTerminalConflictError`. A missing
        row still returns ``None``.
        """
        _require_vocabulary_reason(terminal_reason)
        normalized_tenant = normalize_uuid_string(tenant_id)
        normalized_run = normalize_uuid_string(run_id)
        normalized_project = (
            normalize_uuid_string(project_id) if project_id is not None else None
        )
        t = DISCOVERY_CANDIDATE_ATTEMPTS_TABLE
        set_values: dict[str, object] = {
            "candidate_status": new_status,
            "terminal_reason": terminal_reason,
            "terminal_detail": terminal_detail,
            "updated_at": _now(),
        }
        if normalized_project is not None:
            set_values["project_id"] = normalized_project
        with self._engine.begin() as conn:
            result = conn.execute(
                update(t)
                .where(
                    and_(
                        t.c.tenant_id == normalized_tenant,
                        t.c.run_id == normalized_run,
                        t.c.candidate_key == candidate_key,
                        t.c.candidate_status == "accepted",
                    )
                )
                .values(**set_values)
            )
            row = (
                conn.execute(
                    select(t).where(
                        and_(
                            t.c.tenant_id == normalized_tenant,
                            t.c.run_id == normalized_run,
                            t.c.candidate_key == candidate_key,
                        )
                    ).limit(1)
                )
                .mappings()
                .one_or_none()
            )
            if result.rowcount == 0:
                if row is None:
                    return None
                existing_project = (
                    str(row["project_id"]) if row["project_id"] is not None else None
                )
                existing_reason = (
                    str(row["terminal_reason"])
                    if row["terminal_reason"] is not None
                    else None
                )
                identical = (
                    str(row["candidate_status"]) == new_status
                    and existing_reason == terminal_reason
                    and existing_project == normalized_project
                )
                if not identical:
                    raise CandidateTerminalConflictError(
                        tenant_id=normalized_tenant,
                        run_id=normalized_run,
                        candidate_key=candidate_key,
                        existing_status=str(row["candidate_status"]),
                        existing_reason=existing_reason,
                        existing_project_id=existing_project,
                        requested_status=new_status,
                        requested_reason=terminal_reason,
                        requested_project_id=normalized_project,
                    )
        if row is None:  # pragma: no cover - rowcount>0 guarantees the row exists
            return None
        return _record_from_mapping(row)

    def finalize_persisted(
        self,
        tenant_id: str,
        run_id: str,
        candidate_key: str,
        project_id: str,
    ) -> CandidateAttemptRecord | None:
        return self._finalize(
            tenant_id, run_id, candidate_key,
            new_status="persisted",
            project_id=project_id,
        )

    def finalize_failed(
        self,
        tenant_id: str,
        run_id: str,
        candidate_key: str,
        terminal_reason: str,
        terminal_detail: str | None = None,
    ) -> CandidateAttemptRecord | None:
        return self._finalize(
            tenant_id, run_id, candidate_key,
            new_status="failed",
            terminal_reason=terminal_reason,
            terminal_detail=terminal_detail,
        )

    def finalize_dropped(
        self,
        tenant_id: str,
        run_id: str,
        candidate_key: str,
        terminal_reason: str,
        terminal_detail: str | None = None,
    ) -> CandidateAttemptRecord | None:
        return self._finalize(
            tenant_id, run_id, candidate_key,
            new_status="dropped",
            terminal_reason=terminal_reason,
            terminal_detail=terminal_detail,
        )

    # -- write: reconcile ------------------------------------------------

    def reconcile_open_candidates(
        self,
        *,
        tenant_id: str,
        run_id: str,
        terminal_reason: str = CandidateTerminalReason.WORKER_LOST.value,
    ) -> int:
        """Mark one tenant/run's still-accepted candidates as ``unknown``."""
        _require_vocabulary_reason(terminal_reason)
        normalized_tenant = normalize_uuid_string(tenant_id)
        normalized_run = normalize_uuid_string(run_id)
        t = DISCOVERY_CANDIDATE_ATTEMPTS_TABLE
        with self._engine.begin() as conn:
            result = conn.execute(
                update(t)
                .where(
                    and_(
                        t.c.tenant_id == normalized_tenant,
                        t.c.run_id == normalized_run,
                        t.c.candidate_status == "accepted",
                    )
                )
                .values(
                    candidate_status="unknown",
                    terminal_reason=terminal_reason,
                    updated_at=_now(),
                )
            )
        return result.rowcount

    # -- read: summary ---------------------------------------------------

    def get_run_candidate_summary(
        self,
        tenant_id: str,
        run_id: str,
    ) -> CandidateRunSummary:
        normalized_tenant = normalize_uuid_string(tenant_id)
        normalized_run = normalize_uuid_string(run_id)
        t = DISCOVERY_CANDIDATE_ATTEMPTS_TABLE
        with self._engine.connect() as conn:
            rows = (
                conn.execute(
                    select(
                        t.c.candidate_status,
                        func.count().label("cnt"),
                    )
                    .where(
                        and_(
                            t.c.tenant_id == normalized_tenant,
                            t.c.run_id == normalized_run,
                        )
                    )
                    .group_by(t.c.candidate_status)
                )
                .mappings()
                .all()
            )
        counts: dict[str, int] = {str(r["candidate_status"]): int(r["cnt"]) for r in rows}
        return CandidateRunSummary(
            accepted=counts.get("accepted", 0),
            persisted=counts.get("persisted", 0),
            dropped=counts.get("dropped", 0),
            failed=counts.get("failed", 0),
            unknown=counts.get("unknown", 0),
            total=sum(counts.values()),
        )


def create_candidate_attempt_repository(
    *,
    database_url: str | None = None,
    engine: Engine | None = None,
    bootstrap_schema: bool = False,
) -> SqlCandidateAttemptRepository:
    return SqlCandidateAttemptRepository(
        database_url=database_url,
        engine=engine,
        bootstrap_schema=bootstrap_schema,
    )
