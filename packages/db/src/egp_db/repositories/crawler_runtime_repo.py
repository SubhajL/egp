"""Sanitized global heartbeat state for crawler agents."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import CheckConstraint, Column, DateTime, Index, String, Table
from sqlalchemy import insert, select, update
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.engine import Engine, RowMapping

from egp_db.connection import DB_METADATA, create_shared_engine
from egp_db.db_utils import normalize_database_url
from egp_shared_types.enums import CrawlerBlockerCode


METADATA = DB_METADATA
CRAWLER_BLOCKER_VALUES = tuple(code.value for code in CrawlerBlockerCode)
CRAWLER_BLOCKER_SQL = ", ".join(f"'{value}'" for value in CRAWLER_BLOCKER_VALUES)

CRAWLER_RUNTIME_HEARTBEATS_TABLE = Table(
    "crawler_runtime_heartbeats",
    METADATA,
    Column("agent_id", String, primary_key=True),
    Column("runtime_mode", String, nullable=False),
    Column("watcher_status", String, nullable=False),
    Column("database_status", String, nullable=False),
    Column("blocker_code", String, nullable=True),
    Column("profile_status", String, nullable=False),
    Column("circuit_state", String, nullable=False),
    Column("circuit_reset_at", DateTime(timezone=True), nullable=True),
    Column("reported_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
    CheckConstraint(
        "runtime_mode IN ('embedded', 'external')",
        name="crawler_runtime_mode_check",
    ),
    CheckConstraint(
        "watcher_status IN ('running', 'stopping', 'error')",
        name="crawler_runtime_watcher_status_check",
    ),
    CheckConstraint(
        "database_status IN ('connected', 'unreachable', 'unknown')",
        name="crawler_runtime_database_status_check",
    ),
    CheckConstraint(
        f"blocker_code IS NULL OR blocker_code IN ({CRAWLER_BLOCKER_SQL})",
        name="crawler_runtime_blocker_code_check",
    ),
    CheckConstraint(
        "profile_status IN "
        "('ready', 'busy', 'warm_retry', 'operator_action_required', 'unknown')",
        name="crawler_runtime_profile_status_check",
    ),
    CheckConstraint(
        "circuit_state IN ('closed', 'open', 'half_open', 'unknown')",
        name="crawler_runtime_circuit_state_check",
    ),
)

Index(
    "idx_crawler_runtime_heartbeats_reported_at",
    CRAWLER_RUNTIME_HEARTBEATS_TABLE.c.reported_at,
)


@dataclass(frozen=True, slots=True)
class CrawlerRuntimeSnapshot:
    agent_id: str
    runtime_mode: str
    heartbeat_status: str
    watcher_status: str
    database_status: str
    blocker_code: str | None
    profile_status: str
    circuit_state: str
    circuit_reset_at: str | None
    reported_at: str | None
    heartbeat_age_seconds: int | None


def _now() -> datetime:
    return datetime.now(UTC)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _to_iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    return _as_utc(value).isoformat()


def _validated_choice(value: str, *, name: str, allowed: set[str]) -> str:
    normalized = str(value).strip().lower()
    if normalized not in allowed:
        raise ValueError(f"invalid crawler runtime {name}")
    return normalized


class SqlCrawlerRuntimeRepository:
    """Store only low-cardinality operational state from crawler agents."""

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

    def record_heartbeat(
        self,
        *,
        agent_id: str,
        runtime_mode: str,
        watcher_status: str,
        database_status: str,
        profile_status: str,
        circuit_state: str,
        blocker_code: CrawlerBlockerCode | str | None = None,
        circuit_reset_at: datetime | None = None,
        reported_at: datetime | None = None,
    ) -> CrawlerRuntimeSnapshot:
        normalized_agent_id = str(agent_id).strip()
        if not normalized_agent_id or len(normalized_agent_id) > 128:
            raise ValueError("invalid crawler runtime agent_id")
        normalized_mode = _validated_choice(
            runtime_mode,
            name="runtime_mode",
            allowed={"embedded", "external"},
        )
        normalized_watcher = _validated_choice(
            watcher_status,
            name="watcher_status",
            allowed={"running", "stopping", "error"},
        )
        normalized_database = _validated_choice(
            database_status,
            name="database_status",
            allowed={"connected", "unreachable", "unknown"},
        )
        normalized_profile = _validated_choice(
            profile_status,
            name="profile_status",
            allowed={
                "ready",
                "busy",
                "warm_retry",
                "operator_action_required",
                "unknown",
            },
        )
        normalized_circuit = _validated_choice(
            circuit_state,
            name="circuit_state",
            allowed={"closed", "open", "half_open", "unknown"},
        )
        normalized_blocker = (
            CrawlerBlockerCode(str(blocker_code)).value
            if blocker_code is not None
            else None
        )
        resolved_reported_at = _as_utc(reported_at or _now())
        resolved_reset_at = (
            _as_utc(circuit_reset_at) if circuit_reset_at is not None else None
        )
        values: dict[str, object] = {
            "runtime_mode": normalized_mode,
            "watcher_status": normalized_watcher,
            "database_status": normalized_database,
            "blocker_code": normalized_blocker,
            "profile_status": normalized_profile,
            "circuit_state": normalized_circuit,
            "circuit_reset_at": resolved_reset_at,
            "reported_at": resolved_reported_at,
            "updated_at": _now(),
        }
        with self._engine.begin() as connection:
            if connection.dialect.name == "postgresql":
                connection.execute(
                    postgresql_insert(CRAWLER_RUNTIME_HEARTBEATS_TABLE)
                    .values(agent_id=normalized_agent_id, **values)
                    .on_conflict_do_update(
                        index_elements=[CRAWLER_RUNTIME_HEARTBEATS_TABLE.c.agent_id],
                        set_=values,
                    )
                )
            elif connection.dialect.name == "sqlite":
                connection.execute(
                    sqlite_insert(CRAWLER_RUNTIME_HEARTBEATS_TABLE)
                    .values(agent_id=normalized_agent_id, **values)
                    .on_conflict_do_update(
                        index_elements=[CRAWLER_RUNTIME_HEARTBEATS_TABLE.c.agent_id],
                        set_=values,
                    )
                )
            else:
                result = connection.execute(
                    update(CRAWLER_RUNTIME_HEARTBEATS_TABLE)
                    .where(
                        CRAWLER_RUNTIME_HEARTBEATS_TABLE.c.agent_id
                        == normalized_agent_id
                    )
                    .values(**values)
                )
                if result.rowcount == 0:
                    connection.execute(
                        insert(CRAWLER_RUNTIME_HEARTBEATS_TABLE).values(
                            agent_id=normalized_agent_id,
                            **values,
                        )
                    )
        with self._engine.connect() as connection:
            stored = (
                connection.execute(
                    select(CRAWLER_RUNTIME_HEARTBEATS_TABLE).where(
                        CRAWLER_RUNTIME_HEARTBEATS_TABLE.c.agent_id
                        == normalized_agent_id
                    )
                )
                .mappings()
                .one()
            )
        return self._snapshot_from_row(
            stored,
            stale_after_seconds=2**31 - 1,
            now=resolved_reported_at,
        )

    def get_freshest_status(
        self,
        *,
        runtime_mode: str,
        stale_after_seconds: float,
        now: datetime | None = None,
    ) -> CrawlerRuntimeSnapshot:
        normalized_mode = _validated_choice(
            runtime_mode,
            name="runtime_mode",
            allowed={"embedded", "external"},
        )
        if stale_after_seconds <= 0:
            raise ValueError("stale_after_seconds must be positive")
        if normalized_mode == "embedded":
            return CrawlerRuntimeSnapshot(
                agent_id="embedded",
                runtime_mode="embedded",
                heartbeat_status="embedded_ready",
                watcher_status="running",
                database_status="connected",
                blocker_code=None,
                profile_status="ready",
                circuit_state="closed",
                circuit_reset_at=None,
                reported_at=None,
                heartbeat_age_seconds=None,
            )
        with self._engine.connect() as connection:
            row = (
                connection.execute(
                    select(CRAWLER_RUNTIME_HEARTBEATS_TABLE)
                    .where(CRAWLER_RUNTIME_HEARTBEATS_TABLE.c.runtime_mode == "external")
                    .order_by(
                        CRAWLER_RUNTIME_HEARTBEATS_TABLE.c.reported_at.desc(),
                        CRAWLER_RUNTIME_HEARTBEATS_TABLE.c.agent_id,
                    )
                    .limit(1)
                )
                .mappings()
                .first()
            )
        if row is None:
            return self._offline_snapshot(age_seconds=None)
        return self._snapshot_from_row(
            row,
            stale_after_seconds=float(stale_after_seconds),
            now=_as_utc(now or _now()),
        )

    @staticmethod
    def _offline_snapshot(*, age_seconds: int | None) -> CrawlerRuntimeSnapshot:
        return CrawlerRuntimeSnapshot(
            agent_id="unknown",
            runtime_mode="external",
            heartbeat_status="offline",
            watcher_status="error",
            database_status="unknown",
            blocker_code=CrawlerBlockerCode.AGENT_OFFLINE.value,
            profile_status="unknown",
            circuit_state="unknown",
            circuit_reset_at=None,
            reported_at=None,
            heartbeat_age_seconds=age_seconds,
        )

    @classmethod
    def _snapshot_from_row(
        cls,
        row: RowMapping,
        *,
        stale_after_seconds: float,
        now: datetime,
    ) -> CrawlerRuntimeSnapshot:
        reported_at = _as_utc(row["reported_at"])
        raw_age_seconds = max(0.0, (now - reported_at).total_seconds())
        age_seconds = int(raw_age_seconds)
        if raw_age_seconds > stale_after_seconds:
            stale = cls._offline_snapshot(age_seconds=age_seconds)
            return CrawlerRuntimeSnapshot(
                agent_id=str(row["agent_id"]),
                runtime_mode=stale.runtime_mode,
                heartbeat_status=stale.heartbeat_status,
                watcher_status=stale.watcher_status,
                database_status=stale.database_status,
                blocker_code=stale.blocker_code,
                profile_status=stale.profile_status,
                circuit_state=stale.circuit_state,
                circuit_reset_at=_to_iso(row["circuit_reset_at"]),
                reported_at=_to_iso(reported_at),
                heartbeat_age_seconds=age_seconds,
            )
        return CrawlerRuntimeSnapshot(
            agent_id=str(row["agent_id"]),
            runtime_mode=str(row["runtime_mode"]),
            heartbeat_status="online",
            watcher_status=str(row["watcher_status"]),
            database_status=str(row["database_status"]),
            blocker_code=(
                str(row["blocker_code"]) if row["blocker_code"] is not None else None
            ),
            profile_status=str(row["profile_status"]),
            circuit_state=str(row["circuit_state"]),
            circuit_reset_at=_to_iso(row["circuit_reset_at"]),
            reported_at=_to_iso(reported_at),
            heartbeat_age_seconds=age_seconds,
        )


def create_crawler_runtime_repository(
    *,
    database_url: str | None = None,
    engine: Engine | None = None,
    bootstrap_schema: bool = True,
) -> SqlCrawlerRuntimeRepository:
    return SqlCrawlerRuntimeRepository(
        database_url=database_url,
        engine=engine,
        bootstrap_schema=bootstrap_schema,
    )
