"""U7a: the legacy discovery claimer must never claim agent-owned jobs.

Before U7 the external discovery executor claimed every due pending job with no
execution-backend predicate, so an agent consumer added later would race it for
the same rows. These tests pin the partition: the legacy claimer sees only
``execution_backend='legacy'``.

Kept at the repository level (SQLite) because the predicate is repository SQL;
the database-side constraints are covered by ``test_crawler_agent_schema.py``.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from sqlalchemy import event, insert, text

from egp_db.repositories.discovery_job_repo import (
    DISCOVERY_JOBS_TABLE,
    SqlDiscoveryJobRepository,
    build_discovery_job_values,
)
from egp_shared_types.enums import ExecutionBackend


TENANT_ID = "11111111-1111-1111-1111-111111111111"
PROFILE_ID = "33333333-3333-3333-3333-333333333333"


def _seed_tenant_profile(repository: SqlDiscoveryJobRepository) -> None:
    now = "2026-07-28T00:00:00+00:00"
    with repository._engine.begin() as connection:  # test setup only
        connection.execute(
            text(
                """
                INSERT INTO tenants
                    (id, name, slug, plan_code, is_active, created_at, updated_at)
                VALUES (:tenant_id, 'U7 tenant', 'u7-tenant',
                        'monthly_membership', 1, :now, :now)
                """
            ),
            {"tenant_id": TENANT_ID, "now": now},
        )
        connection.execute(
            text(
                """
                INSERT INTO crawl_profiles
                    (id, tenant_id, name, profile_type, is_active,
                     max_pages_per_keyword, close_consulting_after_days,
                     close_stale_after_days, created_at, updated_at)
                VALUES (:profile_id, :tenant_id, 'U7 profile', 'custom', 1,
                        15, 30, 45, :now, :now)
                """
            ),
            {"profile_id": PROFILE_ID, "tenant_id": TENANT_ID, "now": now},
        )


def _seed_job(
    repository: SqlDiscoveryJobRepository,
    *,
    keyword: str,
    execution_backend: str | None,
    due_at: datetime,
) -> None:
    values = build_discovery_job_values(
        tenant_id=TENANT_ID,
        profile_id=PROFILE_ID,
        profile_type="custom",
        keyword=keyword,
        now=due_at,
    )
    if execution_backend is not None:
        values["execution_backend"] = execution_backend
    with repository._engine.begin() as connection:  # test setup only
        connection.execute(insert(DISCOVERY_JOBS_TABLE), [values])


def _repository(tmp_path) -> SqlDiscoveryJobRepository:
    repository = SqlDiscoveryJobRepository(
        database_url=f"sqlite+pysqlite:///{tmp_path / 'u7-routing.sqlite3'}",
        bootstrap_schema=True,
    )
    _seed_tenant_profile(repository)
    return repository


def test_legacy_claimer_ignores_agent_owned_jobs(tmp_path) -> None:
    repository = _repository(tmp_path)
    due_at = datetime.now(UTC) - timedelta(minutes=5)
    _seed_job(
        repository,
        keyword="legacy-work",
        execution_backend=ExecutionBackend.LEGACY.value,
        due_at=due_at,
    )
    _seed_job(
        repository,
        keyword="agent-work",
        execution_backend=ExecutionBackend.AGENT.value,
        due_at=due_at,
    )

    claimed = repository.claim_pending_discovery_jobs(limit=10)

    assert [job.keyword for job in claimed] == ["legacy-work"]


def test_legacy_claimer_still_claims_rows_written_before_u7(tmp_path) -> None:
    """Rows inserted without an explicit backend must stay legacy-owned."""

    repository = _repository(tmp_path)
    due_at = datetime.now(UTC) - timedelta(minutes=5)
    _seed_job(
        repository, keyword="pre-u7-work", execution_backend=None, due_at=due_at
    )

    claimed = repository.claim_pending_discovery_jobs(limit=10)

    assert [job.keyword for job in claimed] == ["pre-u7-work"]


def test_has_claimable_discovery_jobs_ignores_agent_owned_jobs(tmp_path) -> None:
    """The dispatch wake-up probe must not be woken by agent-owned work."""

    repository = _repository(tmp_path)
    due_at = datetime.now(UTC) - timedelta(minutes=5)
    _seed_job(
        repository,
        keyword="agent-only",
        execution_backend=ExecutionBackend.AGENT.value,
        due_at=due_at,
    )

    assert repository.has_claimable_discovery_jobs() is False

    # Positive control: the probe must still fire for legacy work, otherwise the
    # assertion above would pass on a method that always returned False.
    _seed_job(
        repository,
        keyword="legacy-too",
        execution_backend=ExecutionBackend.LEGACY.value,
        due_at=due_at,
    )
    assert repository.has_claimable_discovery_jobs() is True


def test_queue_snapshot_counts_only_legacy_owned_jobs(tmp_path) -> None:
    """The queue snapshot describes the LEGACY dispatch queue.

    ``build_discovery_one_shot_summary`` derives ``exit_reason`` from these counts:
    ``pending_count == 0`` means ``queue_drained`` and ``claimable_count == 0``
    means ``waiting_retry_or_lease``. If agent-owned jobs inflated these counts, a
    bounded one-shot crawl would report ``work_remains`` forever and a caller
    looping until ``queue_drained`` would never terminate, even though the legacy
    consumer correctly refuses to claim those rows.
    """

    repository = _repository(tmp_path)
    due_at = datetime.now(UTC) - timedelta(minutes=5)
    _seed_job(
        repository,
        keyword="legacy-work",
        execution_backend=ExecutionBackend.LEGACY.value,
        due_at=due_at,
    )
    _seed_job(
        repository,
        keyword="agent-work",
        execution_backend=ExecutionBackend.AGENT.value,
        due_at=due_at,
    )

    snapshot = repository.get_discovery_queue_snapshot()

    assert snapshot.pending_count == 1
    assert snapshot.claimable_count == 1


def test_queue_snapshot_reports_drained_when_only_agent_work_remains(
    tmp_path,
) -> None:
    """A legacy queue holding nothing but agent rows must read as drained."""

    repository = _repository(tmp_path)
    due_at = datetime.now(UTC) - timedelta(minutes=5)
    _seed_job(
        repository,
        keyword="agent-only",
        execution_backend=ExecutionBackend.AGENT.value,
        due_at=due_at,
    )

    snapshot = repository.get_discovery_queue_snapshot()

    assert snapshot.pending_count == 0
    assert snapshot.claimable_count == 0


def test_claim_update_rechecks_backend_after_selection(tmp_path) -> None:
    """The compare-and-swap must re-assert ownership, not trust the candidate query.

    Flips the row to agent ownership *between* the candidate SELECT and the
    claiming UPDATE, using an engine-level hook. Without the backend predicate
    repeated in the UPDATE, every other condition in its WHERE clause still holds
    after the flip, so the legacy executor would lease a job it no longer owns.
    """

    repository = _repository(tmp_path)
    due_at = datetime.now(UTC) - timedelta(minutes=5)
    _seed_job(
        repository,
        keyword="reroute-me",
        execution_backend=ExecutionBackend.LEGACY.value,
        due_at=due_at,
    )

    state = {"flipped": False}

    def _flip_before_claim_update(
        conn, cursor, statement, parameters, context, executemany
    ):
        # Fire immediately before the claiming UPDATE, i.e. after the candidate
        # SELECT has already decided this row is legacy-owned. Reuses the same
        # connection (same transaction) so SQLite raises no lock conflict, and the
        # flag prevents the nested statement from re-entering this hook.
        if state["flipped"]:
            return
        normalized = " ".join(statement.split()).upper()
        if normalized.startswith("UPDATE DISCOVERY_JOBS"):
            state["flipped"] = True
            conn.exec_driver_sql(
                "UPDATE discovery_jobs SET execution_backend = 'agent' "
                "WHERE keyword = 'reroute-me'"
            )

    event.listen(
        repository._engine, "before_cursor_execute", _flip_before_claim_update
    )
    try:
        claimed = repository.claim_pending_discovery_jobs(limit=10)
    finally:
        event.remove(
            repository._engine, "before_cursor_execute", _flip_before_claim_update
        )

    assert state["flipped"] is True, "hook never fired; test would be vacuous"
    assert claimed == []


def test_sqlite_bootstrap_rejects_an_unknown_execution_backend(tmp_path) -> None:
    """Metadata parity: SQLite must reject what PostgreSQL rejects.

    Without the CheckConstraint mirrored onto DISCOVERY_JOBS_TABLE, tests could
    store a backend value production forbids, and such a row would be invisible to
    every claimer.
    """

    import sqlalchemy.exc

    repository = _repository(tmp_path)
    due_at = datetime.now(UTC) - timedelta(minutes=5)
    with pytest.raises(sqlalchemy.exc.IntegrityError):
        _seed_job(
            repository, keyword="bogus", execution_backend="quantum", due_at=due_at
        )
