"""Database and migration readiness assessment."""

from __future__ import annotations

from dataclasses import dataclass
from math import ceil
from pathlib import Path
from typing import Literal

from psycopg import connect
from sqlalchemy import text

from egp_db.connection import create_shared_engine
from egp_db.db_utils import is_sqlite_url, normalize_database_url
from egp_db.migration_runner import list_migration_files

ReadinessStatus = Literal["ready", "not_ready"]
CheckStatus = Literal["ok", "error", "unknown"]


class DatabaseUnavailableError(RuntimeError):
    """Raised when the readiness probe cannot reach the configured database."""


class MigrationLedgerUnavailableError(RuntimeError):
    """Raised when the database is reachable but its migration ledger is not."""


@dataclass(frozen=True, slots=True)
class ReadinessSnapshot:
    status: ReadinessStatus
    reason: str | None
    database_status: CheckStatus
    migration_status: CheckStatus
    pending_count: int | None
    unexpected_count: int | None

    @property
    def is_ready(self) -> bool:
        return self.status == "ready"

    def to_payload(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "status": self.status,
            "checks": {
                "database": {"status": self.database_status},
                "migrations": {
                    "status": self.migration_status,
                    "pending_count": self.pending_count,
                    "unexpected_count": self.unexpected_count,
                },
            },
        }
        if self.reason is not None:
            payload["reason"] = self.reason
        return payload


class ReadinessService:
    """Build a bounded readiness snapshot without changing database state."""

    def __init__(
        self,
        *,
        database_url: str,
        migrations_dir: Path | None = None,
        timeout_seconds: float = 2.0,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        self._database_url = database_url
        self._migrations_dir = migrations_dir or _default_migrations_dir()
        self._timeout_seconds = timeout_seconds

    def build_readiness_snapshot(self) -> ReadinessSnapshot:
        try:
            expected_versions = {path.name for path in list_migration_files(self._migrations_dir)}
        except OSError:
            expected_versions = set()
        if not expected_versions:
            return ReadinessSnapshot(
                status="not_ready",
                reason="migration_manifest_unavailable",
                database_status="unknown",
                migration_status="error",
                pending_count=None,
                unexpected_count=None,
            )

        try:
            applied_versions = self._read_applied_versions()
        except DatabaseUnavailableError:
            return ReadinessSnapshot(
                status="not_ready",
                reason="database_unreachable",
                database_status="error",
                migration_status="unknown",
                pending_count=None,
                unexpected_count=None,
            )
        except MigrationLedgerUnavailableError:
            return ReadinessSnapshot(
                status="not_ready",
                reason="migration_ledger_unavailable",
                database_status="ok",
                migration_status="error",
                pending_count=None,
                unexpected_count=None,
            )

        pending_versions = expected_versions - applied_versions
        unexpected_versions = applied_versions - expected_versions
        if pending_versions:
            return ReadinessSnapshot(
                status="not_ready",
                reason="migrations_pending",
                database_status="ok",
                migration_status="error",
                pending_count=len(pending_versions),
                unexpected_count=len(unexpected_versions),
            )
        if unexpected_versions:
            return ReadinessSnapshot(
                status="not_ready",
                reason="migration_history_mismatch",
                database_status="ok",
                migration_status="error",
                pending_count=0,
                unexpected_count=len(unexpected_versions),
            )
        return ReadinessSnapshot(
            status="ready",
            reason=None,
            database_status="ok",
            migration_status="ok",
            pending_count=0,
            unexpected_count=0,
        )

    def _read_applied_versions(self) -> set[str]:
        if is_sqlite_url(self._database_url):
            return self._read_sqlite_applied_versions()
        return self._read_postgres_applied_versions()

    def _read_sqlite_applied_versions(self) -> set[str]:
        engine = create_shared_engine(self._database_url)
        try:
            with engine.connect() as connection:
                connection.execute(text("SELECT 1"))
                try:
                    rows = connection.execute(
                        text("SELECT version FROM schema_migrations")
                    ).fetchall()
                except Exception as exc:
                    raise MigrationLedgerUnavailableError from exc
        except MigrationLedgerUnavailableError:
            raise
        except Exception as exc:
            raise DatabaseUnavailableError from exc
        return {str(row[0]) for row in rows}

    def _read_postgres_applied_versions(self) -> set[str]:
        database_url = normalize_database_url(self._database_url).replace(
            "postgresql+psycopg://",
            "postgresql://",
            1,
        )
        timeout_milliseconds = max(1, int(self._timeout_seconds * 1_000))
        try:
            connection_context = connect(
                database_url,
                connect_timeout=max(1, ceil(self._timeout_seconds)),
                options=f"-c statement_timeout={timeout_milliseconds}",
            )
        except Exception as exc:
            raise DatabaseUnavailableError from exc

        with connection_context as connection:
            try:
                with connection.cursor() as cursor:
                    cursor.execute("SELECT 1")
            except Exception as exc:
                raise DatabaseUnavailableError from exc
            try:
                with connection.cursor() as cursor:
                    cursor.execute("SELECT version FROM schema_migrations")
                    rows = cursor.fetchall()
            except Exception as exc:
                raise MigrationLedgerUnavailableError from exc
        return {str(row[0]) for row in rows}


def _default_migrations_dir() -> Path:
    return Path(__file__).resolve().parents[5] / "packages/db/src/migrations"
