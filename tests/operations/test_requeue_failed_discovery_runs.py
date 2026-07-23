"""Fail-closed coverage for the bounded incident recovery command."""

from __future__ import annotations

import json
from pathlib import Path
import sys

import pytest
from sqlalchemy import text

from egp_api.main import create_app
from egp_db.dev_postgres import TempPostgresCluster, postgres_binaries_available
from egp_db.migration_runner import apply_migrations


REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import requeue_failed_discovery_runs as recovery  # noqa: E402


TENANT_ID = "11111111-1111-1111-1111-111111111111"
OTHER_TENANT_ID = "22222222-2222-2222-2222-222222222222"


def _make_app(tmp_path: Path):
    database_url = f"sqlite+pysqlite:///{tmp_path / 'recovery.sqlite3'}"
    app = create_app(
        artifact_root=tmp_path,
        database_url=database_url,
        auth_required=False,
    )
    return app, database_url


def _create_profile(app, *, tenant_id: str = TENANT_ID, keyword: str = "analytics"):
    return app.state.profile_repository.create_profile(
        tenant_id=tenant_id,
        name=f"Recovery {tenant_id[-4:]} {keyword}",
        profile_type="custom",
        max_pages_per_keyword=15,
        close_consulting_after_days=30,
        close_stale_after_days=45,
        keywords=[keyword],
        enabled_by_user=True,
    ).profile


def _create_source_run(
    app,
    *,
    tenant_id: str = TENANT_ID,
    profile_id: str,
    keyword: str = "analytics",
    trigger_type: str = "manual",
    status: str = "failed",
) -> str:
    run = app.state.run_repository.create_run(
        tenant_id=tenant_id,
        profile_id=profile_id,
        trigger_type=trigger_type,
    )
    app.state.run_repository.create_task(
        run_id=run.id,
        task_type="discover",
        keyword=keyword,
    )
    app.state.run_repository.mark_run_started(run.id)
    app.state.run_repository.mark_run_finished(
        run.id,
        status=status,
        error_count=1 if status == "failed" else 0,
    )
    return run.id


def test_recovery_defaults_to_dry_run(tmp_path, capsys) -> None:
    app, database_url = _make_app(tmp_path)
    profile = _create_profile(app)
    run_id = _create_source_run(app, profile_id=profile.id)

    exit_code = recovery.main(
        [
            "--database-url",
            database_url,
            "--tenant-id",
            TENANT_ID,
            "--run-id",
            run_id,
            "--expected-count",
            "1",
        ]
    )

    assert exit_code == 0
    output = json.loads(capsys.readouterr().out)
    assert output["mode"] == "dry_run"
    assert output["is_executable"] is True
    assert output["source_run_count"] == 1
    assert output["recovery_job_count"] == 1
    with app.state.db_engine.connect() as connection:
        assert connection.execute(text("SELECT COUNT(*) FROM recrawl_requests")).scalar_one() == 0
        assert connection.execute(text("SELECT COUNT(*) FROM discovery_jobs")).scalar_one() == 0


@pytest.mark.parametrize(
    ("trigger_type", "status"),
    [("schedule", "failed"), ("manual", "succeeded")],
)
def test_recovery_rejects_nonfailed_or_nonmanual_run(
    tmp_path,
    trigger_type: str,
    status: str,
) -> None:
    app, database_url = _make_app(tmp_path)
    profile = _create_profile(app)
    run_id = _create_source_run(
        app,
        profile_id=profile.id,
        trigger_type=trigger_type,
        status=status,
    )

    with pytest.raises(recovery.RecoveryValidationError):
        recovery.build_recovery_plan(
            database_url=database_url,
            tenant_id=TENANT_ID,
            run_ids=[run_id],
            expected_count=1,
        )


def test_recovery_rejects_cross_tenant_run_ids(tmp_path) -> None:
    app, database_url = _make_app(tmp_path)
    profile = _create_profile(app, tenant_id=OTHER_TENANT_ID)
    run_id = _create_source_run(
        app,
        tenant_id=OTHER_TENANT_ID,
        profile_id=profile.id,
    )

    with pytest.raises(recovery.RecoveryValidationError, match="tenant"):
        recovery.build_recovery_plan(
            database_url=database_url,
            tenant_id=TENANT_ID,
            run_ids=[run_id],
            expected_count=1,
        )


def test_recovery_rejects_ambiguous_source_task_and_paused_profile(tmp_path) -> None:
    app, database_url = _make_app(tmp_path)
    profile = _create_profile(app)
    run_id = _create_source_run(app, profile_id=profile.id)
    app.state.run_repository.create_task(
        run_id=run_id,
        task_type="discover",
        keyword="second keyword",
    )

    with pytest.raises(recovery.RecoveryValidationError, match="exactly one"):
        recovery.build_recovery_plan(
            database_url=database_url,
            tenant_id=TENANT_ID,
            run_ids=[run_id],
            expected_count=1,
        )

    with app.state.db_engine.begin() as connection:
        connection.execute(
            text("UPDATE crawl_profiles SET enabled_by_user = FALSE, is_active = FALSE")
        )
        connection.execute(
            text("DELETE FROM crawl_tasks WHERE keyword = 'second keyword'")
        )
    with pytest.raises(recovery.RecoveryValidationError, match="paused"):
        recovery.build_recovery_plan(
            database_url=database_url,
            tenant_id=TENANT_ID,
            run_ids=[run_id],
            expected_count=1,
        )


def test_recovery_deduplicates_profile_keyword_pairs(tmp_path) -> None:
    app, database_url = _make_app(tmp_path)
    profile = _create_profile(app)
    first_run_id = _create_source_run(app, profile_id=profile.id)
    second_run_id = _create_source_run(app, profile_id=profile.id)

    plan = recovery.build_recovery_plan(
        database_url=database_url,
        tenant_id=TENANT_ID,
        run_ids=[first_run_id, second_run_id],
        expected_count=None,
    )

    assert len(plan.sources) == 2
    assert len(plan.jobs) == 1
    assert plan.jobs[0].source_run_ids == (first_run_id, second_run_id)


def test_recovery_rejects_count_mismatch_and_existing_pending_job(tmp_path) -> None:
    app, database_url = _make_app(tmp_path)
    profile = _create_profile(app)
    run_id = _create_source_run(app, profile_id=profile.id)

    with pytest.raises(recovery.RecoveryValidationError, match="expected 10"):
        recovery.build_recovery_plan(
            database_url=database_url,
            tenant_id=TENANT_ID,
            run_ids=[run_id],
            expected_count=10,
        )

    app.state.discovery_job_repository.create_discovery_job(
        tenant_id=TENANT_ID,
        profile_id=profile.id,
        profile_type=profile.profile_type,
        keyword="analytics",
        trigger_type="manual",
    )
    plan = recovery.build_recovery_plan(
        database_url=database_url,
        tenant_id=TENANT_ID,
        run_ids=[run_id],
        expected_count=1,
    )
    assert plan.is_executable is False
    assert len(plan.conflicts) == 1
    with pytest.raises(recovery.RecoveryValidationError, match="pending"):
        recovery.execute_recovery_plan(database_url=database_url, plan=plan)


def test_recovery_execute_creates_one_correlated_request_and_is_idempotent(
    tmp_path,
) -> None:
    app, database_url = _make_app(tmp_path)
    profile = _create_profile(app)
    run_id = _create_source_run(app, profile_id=profile.id)
    plan = recovery.build_recovery_plan(
        database_url=database_url,
        tenant_id=TENANT_ID,
        run_ids=[run_id],
        expected_count=1,
    )

    first = recovery.execute_recovery_plan(database_url=database_url, plan=plan)
    second = recovery.execute_recovery_plan(database_url=database_url, plan=plan)

    assert first.request_id == second.request_id
    assert first.queued_job_count == 1
    assert second.queued_job_count == 0
    with app.state.db_engine.connect() as connection:
        request_rows = connection.execute(
            text(
                "SELECT id, source, idempotency_key, requested_keyword_count "
                "FROM recrawl_requests"
            )
        ).mappings().all()
        job_rows = connection.execute(
            text(
                "SELECT trigger_type, recrawl_request_id, keyword, job_status "
                "FROM discovery_jobs"
            )
        ).mappings().all()
    assert request_rows == [
        {
            "id": first.request_id,
            "source": "operator_recovery",
            "idempotency_key": plan.idempotency_key,
            "requested_keyword_count": 1,
        }
    ]
    assert job_rows == [
        {
            "trigger_type": "retry",
            "recrawl_request_id": first.request_id,
            "keyword": "analytics",
            "job_status": "pending",
        }
    ]


def test_recovery_execute_revalidates_source_profile(tmp_path) -> None:
    app, database_url = _make_app(tmp_path)
    profile = _create_profile(app)
    run_id = _create_source_run(app, profile_id=profile.id)
    plan = recovery.build_recovery_plan(
        database_url=database_url,
        tenant_id=TENANT_ID,
        run_ids=[run_id],
        expected_count=1,
    )
    with app.state.db_engine.begin() as connection:
        connection.execute(
            text("UPDATE crawl_profiles SET enabled_by_user = FALSE, is_active = FALSE")
        )

    with pytest.raises(recovery.RecoveryValidationError, match="paused"):
        recovery.execute_recovery_plan(database_url=database_url, plan=plan)
    with app.state.db_engine.connect() as connection:
        assert connection.execute(text("SELECT COUNT(*) FROM recrawl_requests")).scalar_one() == 0
        assert connection.execute(text("SELECT COUNT(*) FROM discovery_jobs")).scalar_one() == 0


def test_recovery_executes_idempotently_on_migrated_postgres() -> None:
    if not postgres_binaries_available():
        pytest.skip("PostgreSQL binaries not available")

    profile_id = "33333333-3333-3333-3333-333333333333"
    run_id = "44444444-4444-4444-4444-444444444444"
    with TempPostgresCluster() as cluster:
        cluster.create_database("egp_failed_run_recovery_test")
        database_url = cluster.database_url("egp_failed_run_recovery_test")
        apply_migrations(
            database_url=database_url,
            migrations_dir=REPO_ROOT / "packages/db/src/migrations",
        )
        from psycopg import connect

        with connect(database_url) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO tenants (id, name, slug)
                    VALUES (%s, 'Recovery tenant', 'recovery-tenant')
                    """,
                    (TENANT_ID,),
                )
                cursor.execute(
                    """
                    INSERT INTO crawl_profiles (
                        id, tenant_id, name, profile_type,
                        enabled_by_user, is_active
                    ) VALUES (%s, %s, 'Recovery profile', 'custom', TRUE, TRUE)
                    """,
                    (profile_id, TENANT_ID),
                )
                cursor.execute(
                    """
                    INSERT INTO crawl_runs (
                        id, tenant_id, profile_id, trigger_type, status
                    ) VALUES (%s, %s, %s, 'manual', 'failed')
                    """,
                    (run_id, TENANT_ID, profile_id),
                )
                cursor.execute(
                    """
                    INSERT INTO crawl_tasks (
                        id, run_id, task_type, keyword, status
                    ) VALUES (
                        '55555555-5555-5555-5555-555555555555',
                        %s, 'discover', 'analytics', 'failed'
                    )
                    """,
                    (run_id,),
                )
            connection.commit()

        plan = recovery.build_recovery_plan(
            database_url=database_url,
            tenant_id=TENANT_ID,
            run_ids=[run_id],
            expected_count=1,
        )
        first = recovery.execute_recovery_plan(database_url=database_url, plan=plan)
        second = recovery.execute_recovery_plan(database_url=database_url, plan=plan)

        assert first.request_id == second.request_id
        assert (first.queued_job_count, second.queued_job_count) == (1, 0)
        with connect(database_url) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT r.source, r.idempotency_key, j.trigger_type, j.keyword
                    FROM recrawl_requests AS r
                    JOIN discovery_jobs AS j ON j.recrawl_request_id = r.id
                    """
                )
                assert cursor.fetchone() == (
                    "operator_recovery",
                    plan.idempotency_key,
                    "retry",
                    "analytics",
                )
