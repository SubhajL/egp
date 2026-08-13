"""PR-CANARY-03 F1: record_accepted must emit valid PostgreSQL SQL.

These tests are the regression guard for the shipped defect where
``record_accepted`` emitted SQLite-only ``INSERT OR IGNORE``, which aborts
every crawl on PostgreSQL (the production database).

T1 is a deterministic root-cause guard (no server): it captures the EXACT
statement the production method executes and compiles it on the engine's own
(SQLite) dialect, asserting the ``OR IGNORE`` prefix is gone. The shipped bug
compiled to ``INSERT OR IGNORE`` on every dialect, so this catches a regression
at its source. T2 is the authoritative PostgreSQL oracle: it runs the real
method against a real PostgreSQL cluster with the real migration set applied.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import event
from sqlalchemy.dialects import sqlite as sqlite_dialect

from egp_db.dev_postgres import postgres_binaries_available
from egp_db.repositories.candidate_attempt_repo import (
    DISCOVERY_CANDIDATE_ATTEMPTS_TABLE,
    SqlCandidateAttemptRepository,
)


TENANT_ID = "11111111-1111-1111-1111-111111111111"
RUN_ID = "22222222-2222-2222-2222-222222222222"
PROJECT_ID = "33333333-3333-3333-3333-333333333333"


# ---------------------------------------------------------------------------
# T1: record_accepted's real INSERT uses ON CONFLICT, never the OR IGNORE prefix
# ---------------------------------------------------------------------------
def test_record_accepted_uses_on_conflict_not_or_ignore(tmp_path) -> None:
    """Capture the real INSERT record_accepted runs; assert no OR IGNORE prefix.

    Deterministic root-cause guard (no server needed). Captures via a
    before_execute listener so the test tracks the production statement builder
    (a hand-rebuilt statement would be vacuous). The shipped bug used
    ``prefix_with("OR IGNORE")``, which compiled to ``INSERT OR IGNORE`` on
    EVERY dialect — including SQLite — so compiling the captured statement on
    the engine's own (SQLite) dialect catches the regression at its source.
    The authoritative PostgreSQL proof is T2.
    """
    database_url = f"sqlite+pysqlite:///{tmp_path / 'f1-probe.sqlite3'}"
    repo = SqlCandidateAttemptRepository(
        database_url=database_url,
        bootstrap_schema=True,
    )

    captured: list[object] = []

    def _capture(conn, clauseelement, multiparams, params, execution_options):  # noqa: ANN001
        table_name = getattr(getattr(clauseelement, "table", None), "name", "")
        if table_name == DISCOVERY_CANDIDATE_ATTEMPTS_TABLE.name:
            captured.append(clauseelement)

    event.listen(repo._engine, "before_execute", _capture)
    try:
        repo.record_accepted(
            tenant_id=TENANT_ID,
            run_id=RUN_ID,
            candidate_key="abc123",
            keyword="analytics",
            page_number=1,
            row_ordinal=3,
        )
    finally:
        event.remove(repo._engine, "before_execute", _capture)

    insert_statements = [c for c in captured if type(c).__name__ == "Insert"]
    assert insert_statements, "record_accepted must issue an INSERT statement"

    compiled_sql = str(
        insert_statements[0].compile(dialect=sqlite_dialect.dialect())
    )
    assert "OR IGNORE" not in compiled_sql, (
        f"record_accepted still uses the SQLite-only OR IGNORE prefix "
        f"(invalid on PostgreSQL): {compiled_sql}"
    )
    assert "ON CONFLICT" in compiled_sql, (
        f"record_accepted must use ON CONFLICT DO NOTHING for idempotency: "
        f"{compiled_sql}"
    )


# ---------------------------------------------------------------------------
# T2: real PostgreSQL round-trip through the real migrations (authoritative)
# ---------------------------------------------------------------------------
def test_record_accepted_round_trips_on_real_postgres() -> None:
    """Run the real method against real PostgreSQL with the real migration set.

    This is the oracle F1 needed originally: SQLite tests hid the dialect bug.
    """
    if not postgres_binaries_available():
        pytest.skip("PostgreSQL binaries (initdb/pg_ctl/psql) not on PATH")

    from psycopg import connect

    from egp_db.dev_postgres import TempPostgresCluster
    from egp_db.migration_runner import apply_migrations

    repo_root = Path(__file__).resolve().parents[2]
    migrations_dir = repo_root / "packages/db/src/migrations"
    database_name = "egp_f1_candidate_smoke"

    with TempPostgresCluster() as cluster:
        cluster.create_database(database_name)
        database_url = cluster.database_url(database_name)
        apply_migrations(database_url=database_url, migrations_dir=migrations_dir)

        with connect(database_url) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO tenants (name, slug, plan_code)
                    VALUES (%s, %s, %s)
                    RETURNING id
                    """,
                    ("F1 Tenant", "f1-tenant", "dev"),
                )
                tenant_id = str(cursor.fetchone()[0])
                # Migration 039 added composite tenant FKs, so the run and
                # project referenced below must really exist for this tenant.
                cursor.execute(
                    "INSERT INTO crawl_runs (tenant_id, trigger_type)"
                    " VALUES (%s, 'manual') RETURNING id",
                    (tenant_id,),
                )
                run_id = str(cursor.fetchone()[0])
                cursor.execute(
                    "INSERT INTO projects"
                    " (tenant_id, canonical_project_id, project_name)"
                    " VALUES (%s, %s, %s) RETURNING id",
                    (tenant_id, "canon-f1-dialect", "F1 Dialect Project"),
                )
                project_id = str(cursor.fetchone()[0])
            connection.commit()

        repo = SqlCandidateAttemptRepository(
            database_url=database_url,
            bootstrap_schema=False,
        )
        candidate_key = "pg-candidate-key"

        first = repo.record_accepted(
            tenant_id=tenant_id,
            run_id=run_id,
            candidate_key=candidate_key,
            keyword="analytics",
            page_number=1,
            row_ordinal=3,
        )
        # Idempotent replay must not raise and must not duplicate.
        second = repo.record_accepted(
            tenant_id=tenant_id,
            run_id=run_id,
            candidate_key=candidate_key,
            keyword="analytics",
            page_number=1,
            row_ordinal=3,
        )
        assert first.id == second.id, "idempotent replay must return the same row"

        summary = repo.get_run_candidate_summary(
            tenant_id=tenant_id, run_id=run_id
        )
        assert summary.total == 1, "duplicate insert must not create a second row"
        assert summary.accepted == 1

        finalized = repo.finalize_persisted(
            tenant_id=tenant_id,
            run_id=run_id,
            candidate_key=candidate_key,
            project_id=project_id,
        )
        assert finalized is not None
        assert finalized.candidate_status == "persisted"
