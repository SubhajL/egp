"""Real-PostgreSQL contracts for F7 durable terminalization and cleanup."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import suppress
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
from uuid import uuid4

import pytest
from psycopg import connect
from sqlalchemy import event

from egp_api.services.discovery_dispatch import DiscoveryDispatchProcessor
from egp_api.services.discovery_worker_dispatcher import SubprocessDiscoveryDispatcher
from egp_api.services.run_service import RunService
from egp_db.dev_postgres import TempPostgresCluster, postgres_binaries_available
from egp_db.migration_runner import apply_migrations
from egp_db.repositories.candidate_attempt_repo import SqlCandidateAttemptRepository
from egp_db.repositories.discovery_job_repo import (
    SqlDiscoveryJobRepository,
    StaleDiscoveryJobClaimError,
)
from egp_db.repositories.run_repo import SqlRunRepository
from egp_shared_types.enums import CrawlRunStatus, DiscoveryFailureCode


REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def postgres_cluster() -> Iterator[TempPostgresCluster]:
    if not postgres_binaries_available():
        pytest.skip("PostgreSQL binaries not available")
    with TempPostgresCluster() as cluster:
        yield cluster


@pytest.fixture
def database_url(postgres_cluster: TempPostgresCluster) -> Iterator[str]:
    database_name = f"f7_terminal_{uuid4().hex[:12]}"
    postgres_cluster.create_database(database_name)
    url = postgres_cluster.database_url(database_name)
    apply_migrations(
        database_url=url,
        migrations_dir=REPO_ROOT / "packages/db/src/migrations",
    )
    try:
        yield url
    finally:
        postgres_cluster.drop_database(database_name)


@pytest.fixture
def ci_database_url() -> str:
    url = os.environ.get("DATABASE_URL")
    if os.environ.get("EGP_CI_POSTGRES_CONTRACT") != "1" or not url:
        pytest.skip("required CI PostgreSQL contract not enabled")
    return url


def _seed_job(database_url: str, *, keyword: str) -> tuple[str, str, str]:
    tenant_id = str(uuid4())
    profile_id = str(uuid4())
    with connect(database_url) as connection, connection.cursor() as cursor:
        cursor.execute(
            "INSERT INTO tenants (id,name,slug,plan_code,is_active) "
            "VALUES (%s,%s,%s,'free',TRUE)",
            (tenant_id, "F7 Tenant", f"f7-{tenant_id[:8]}"),
        )
        cursor.execute(
            "INSERT INTO crawl_profiles "
            "(id,tenant_id,name,profile_type,is_active,max_pages_per_keyword,"
            "close_consulting_after_days,close_stale_after_days) "
            "VALUES (%s,%s,%s,'custom',TRUE,1,30,45)",
            (profile_id, tenant_id, "F7 Profile"),
        )
        connection.commit()
    repository = SqlDiscoveryJobRepository(database_url=database_url)
    job = repository.create_discovery_job(
        tenant_id=tenant_id,
        profile_id=profile_id,
        profile_type="custom",
        keyword=keyword,
        live=False,
    )
    return tenant_id, profile_id, job.id


def _processor(
    database_url: str,
    *,
    tenant_id: str,
    job_id: str,
    artifact_root: Path,
    fault_mode: str | None,
) -> tuple[DiscoveryDispatchProcessor, SqlDiscoveryJobRepository, SqlRunRepository]:
    job_repository = SqlDiscoveryJobRepository(database_url=database_url)
    run_repository = SqlRunRepository(database_url=database_url)
    dispatcher = SubprocessDiscoveryDispatcher(
        database_url,
        artifact_root=artifact_root,
        run_repository=run_repository,
        fault_mode=fault_mode,
        fault_injection_authorized=True,
    )
    return (
        DiscoveryDispatchProcessor(
            repository=job_repository,
            dispatcher=dispatcher,
            max_attempts=1,
            retry_delay_seconds=0.0,
            target_job_id=job_id,
            target_tenant_id=tenant_id,
            force_terminal_failures=True,
        ),
        job_repository,
        run_repository,
    )


def _job_runs(database_url: str, *, tenant_id: str, job_id: str) -> list[dict]:
    with connect(database_url) as connection, connection.cursor() as cursor:
        cursor.execute(
            "SELECT id,status,summary_json FROM crawl_runs "
            "WHERE tenant_id=%s AND discovery_job_id=%s ORDER BY created_at,id",
            (tenant_id, job_id),
        )
        return [
            {"id": str(row[0]), "status": str(row[1]), "summary_json": row[2] or {}}
            for row in cursor.fetchall()
        ]


def _install_terminalization_failure_trigger(database_url: str) -> tuple[str, str]:
    suffix = uuid4().hex[:12]
    function_name = f"f7_fail_terminalization_{suffix}"
    trigger_name = f"f7_fail_terminalization_trigger_{suffix}"
    with connect(database_url) as connection, connection.cursor() as cursor:
        cursor.execute(
            f"""
            CREATE FUNCTION {function_name}() RETURNS trigger AS $$
            BEGIN
                IF NEW.status = 'failed' AND OLD.status IN ('queued', 'running') THEN
                    RAISE EXCEPTION 'injected F7 terminalization write failure';
                END IF;
                RETURN NEW;
            END;
            $$ LANGUAGE plpgsql
            """
        )
        cursor.execute(
            f"""
            CREATE TRIGGER {trigger_name}
            BEFORE UPDATE OF status ON crawl_runs
            FOR EACH ROW EXECUTE FUNCTION {function_name}()
            """
        )
        connection.commit()
    return trigger_name, function_name


def _drop_terminalization_failure_trigger(
    database_url: str,
    *,
    trigger_name: str,
    function_name: str,
) -> None:
    with connect(database_url) as connection, connection.cursor() as cursor:
        cursor.execute(f"DROP TRIGGER IF EXISTS {trigger_name} ON crawl_runs")
        cursor.execute(f"DROP FUNCTION IF EXISTS {function_name}()")
        connection.commit()


def _install_spawned_summary_failure_trigger(database_url: str) -> tuple[str, str]:
    suffix = uuid4().hex[:12]
    function_name = f"f7_fail_spawned_summary_{suffix}"
    trigger_name = f"f7_fail_spawned_summary_trigger_{suffix}"
    with connect(database_url) as connection, connection.cursor() as cursor:
        cursor.execute(
            f"""
            CREATE FUNCTION {function_name}() RETURNS trigger AS $$
            BEGIN
                IF NEW.summary_json->>'worker_dispatch_phase' = 'spawned' THEN
                    RAISE EXCEPTION 'injected F7 spawned-summary write failure';
                END IF;
                RETURN NEW;
            END;
            $$ LANGUAGE plpgsql
            """
        )
        cursor.execute(
            f"""
            CREATE TRIGGER {trigger_name}
            BEFORE UPDATE OF summary_json ON crawl_runs
            FOR EACH ROW EXECUTE FUNCTION {function_name}()
            """
        )
        connection.commit()
    return trigger_name, function_name


def _drop_spawned_summary_failure_trigger(
    database_url: str,
    *,
    trigger_name: str,
    function_name: str,
) -> None:
    with connect(database_url) as connection, connection.cursor() as cursor:
        cursor.execute(f"DROP TRIGGER IF EXISTS {trigger_name} ON crawl_runs")
        cursor.execute(f"DROP FUNCTION IF EXISTS {function_name}()")
        connection.commit()


def _assert_terminalization_write_failure_recovers(
    database_url: str,
    *,
    artifact_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id, _profile_id, job_id = _seed_job(
        database_url,
        keyword="f7 terminalization outage",
    )
    processor, job_repository, run_repository = _processor(
        database_url,
        tenant_id=tenant_id,
        job_id=job_id,
        artifact_root=artifact_root,
        fault_mode="nonzero_exit",
    )
    trigger_name, function_name = _install_terminalization_failure_trigger(database_url)
    try:

        def fail_pre_spawn(*args: object, **kwargs: object) -> None:
            del args, kwargs
            raise RuntimeError("injected pre-spawn setup failure")

        def unexpected_spawn(*args: object, **kwargs: object) -> None:
            pytest.fail(f"pre-spawn contract launched a process: {args!r} {kwargs!r}")

        with monkeypatch.context() as pre_spawn_context:
            pre_spawn_context.setattr(
                "egp_api.services.discovery_worker_dispatcher.tempfile.SpooledTemporaryFile",
                fail_pre_spawn,
            )
            pre_spawn_context.setattr(
                "egp_api.services.discovery_worker_dispatcher.subprocess.Popen",
                unexpected_spawn,
            )
            first_result = processor.process_pending(limit=1)
        assert first_result.dispositions[0].outcome == "retrying"
        stored_job = job_repository.get_discovery_job(
            tenant_id=tenant_id,
            job_id=job_id,
        )
        assert stored_job.job_status == "pending"
        assert stored_job.attempt_count == 1
        runs = _job_runs(database_url, tenant_id=tenant_id, job_id=job_id)
        assert len(runs) == 1
        assert runs[0]["status"] == CrawlRunStatus.QUEUED.value
        assert runs[0]["summary_json"]["worker_owner_pid"] == os.getpid()
        assert runs[0]["summary_json"]["worker_dispatch_phase"] == "reserved"
        assert "worker_pid" not in runs[0]["summary_json"]
        assert (
            job_repository.has_claimable_discovery_jobs(
                only_job_id=job_id,
                only_tenant_id=tenant_id,
            )
            is False
        )
        assert (
            job_repository.claim_pending_discovery_jobs(
                only_job_id=job_id,
                only_tenant_id=tenant_id,
            )
            == []
        )
    finally:
        _drop_terminalization_failure_trigger(
            database_url,
            trigger_name=trigger_name,
            function_name=function_name,
        )

    first_run_id = runs[0]["id"]
    candidates = SqlCandidateAttemptRepository(database_url=database_url)
    candidates.record_accepted(
        tenant_id=tenant_id,
        run_id=first_run_id,
        candidate_key="f7-terminalization-candidate",
        keyword="f7",
    )
    reconciled = RunService(
        run_repository,
        database_url=database_url,
    ).reconcile_missing_workers(owner_pid=os.getpid())
    assert [run.id for run in reconciled] == [first_run_id]
    assert candidates.get_run_candidate_summary(tenant_id, first_run_id).unknown == 1
    assert (
        job_repository.has_claimable_discovery_jobs(
            only_job_id=job_id,
            only_tenant_id=tenant_id,
        )
        is True
    )

    second_result = processor.process_pending(limit=1)
    assert second_result.dispositions[0].outcome == "fault_verified"
    final_job = job_repository.get_discovery_job(tenant_id=tenant_id, job_id=job_id)
    assert final_job.job_status == "failed"
    assert final_job.attempt_count == 2
    final_runs = _job_runs(database_url, tenant_id=tenant_id, job_id=job_id)
    assert len(final_runs) == 2
    assert all(run["status"] == CrawlRunStatus.FAILED.value for run in final_runs)


def _assert_active_run_failure_cas(database_url: str) -> None:
    tenant_id, profile_id, job_id = _seed_job(
        database_url,
        keyword="f7 terminalization cas",
    )
    repository = SqlRunRepository(database_url=database_url)
    run = repository.create_run(
        tenant_id=tenant_id,
        profile_id=profile_id,
        discovery_job_id=job_id,
        trigger_type="manual",
    )
    interleaved = False

    def complete_before_failure_update(
        conn,
        cursor,
        statement: str,
        parameters,
        context,
        executemany: bool,
    ) -> None:
        del conn, cursor, parameters, context, executemany
        nonlocal interleaved
        if (
            interleaved
            or "FROM crawl_runs" not in statement
            or "FOR UPDATE" not in statement
        ):
            return
        interleaved = True
        with connect(database_url) as connection, connection.cursor() as db_cursor:
            db_cursor.execute(
                "UPDATE crawl_runs SET status='succeeded', finished_at=NOW() "
                "WHERE tenant_id=%s AND id=%s",
                (tenant_id, run.id),
            )
            connection.commit()

    event.listen(
        repository._engine, "before_cursor_execute", complete_before_failure_update
    )
    try:
        failed = repository.fail_run_if_active(
            tenant_id=tenant_id,
            run_id=run.id,
            error="late failure",
            failure_reason="worker_lost",
        )
    finally:
        event.remove(
            repository._engine,
            "before_cursor_execute",
            complete_before_failure_update,
        )

    assert interleaved is True
    assert failed is None
    stored = repository.find_run_by_id_for_tenant(
        tenant_id=tenant_id,
        run_id=run.id,
    )
    assert stored is not None
    assert stored.status is CrawlRunStatus.SUCCEEDED


def _assert_stale_claim_cannot_reserve_run(database_url: str) -> None:
    tenant_id, profile_id, job_id = _seed_job(
        database_url,
        keyword="f7 stale reservation claim",
    )
    jobs = SqlDiscoveryJobRepository(database_url=database_url)
    stale_claim = jobs.claim_pending_discovery_jobs(
        only_job_id=job_id,
        only_tenant_id=tenant_id,
        lease_seconds=0.01,
    )[0]
    time.sleep(0.03)
    replacement_claim = jobs.claim_pending_discovery_jobs(
        only_job_id=job_id,
        only_tenant_id=tenant_id,
        lease_seconds=60.0,
    )[0]
    assert replacement_claim.claim_token != stale_claim.claim_token

    runs = SqlRunRepository(database_url=database_url)
    with pytest.raises(StaleDiscoveryJobClaimError):
        runs.create_run(
            tenant_id=tenant_id,
            profile_id=profile_id,
            discovery_job_id=job_id,
            discovery_job_claim_token=stale_claim.claim_token,
            trigger_type="manual",
        )

    assert _job_runs(database_url, tenant_id=tenant_id, job_id=job_id) == []


def _assert_claim_expiry_while_reservation_waits_is_rejected(database_url: str) -> None:
    tenant_id, profile_id, job_id = _seed_job(
        database_url,
        keyword="f7 claim expires during reservation",
    )
    jobs = SqlDiscoveryJobRepository(database_url=database_url)
    claim = jobs.claim_pending_discovery_jobs(
        only_job_id=job_id,
        only_tenant_id=tenant_id,
        lease_seconds=0.02,
    )[0]
    runs = SqlRunRepository(database_url=database_url)
    delayed = False

    def delay_claim_lock(
        _conn: object,
        _cursor: object,
        statement: str,
        _parameters: object,
        _context: object,
        _executemany: object,
    ) -> None:
        nonlocal delayed
        if not delayed and "FROM discovery_jobs" in statement:
            delayed = True
            time.sleep(0.05)

    event.listen(runs._engine, "before_cursor_execute", delay_claim_lock)
    try:
        with pytest.raises(StaleDiscoveryJobClaimError):
            runs.create_run(
                tenant_id=tenant_id,
                profile_id=profile_id,
                discovery_job_id=job_id,
                discovery_job_claim_token=claim.claim_token,
                trigger_type="manual",
            )
    finally:
        event.remove(runs._engine, "before_cursor_execute", delay_claim_lock)

    assert delayed is True
    assert _job_runs(database_url, tenant_id=tenant_id, job_id=job_id) == []


def _assert_normal_pre_spawn_failure_recovers(
    database_url: str,
    *,
    artifact_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id, _profile_id, job_id = _seed_job(
        database_url,
        keyword="f7 normal pre-spawn outage",
    )
    processor, jobs, runs = _processor(
        database_url,
        tenant_id=tenant_id,
        job_id=job_id,
        artifact_root=artifact_root,
        fault_mode=None,
    )
    trigger_name, function_name = _install_terminalization_failure_trigger(database_url)
    try:

        def fail_spool(*args: object, **kwargs: object) -> None:
            del args, kwargs
            raise RuntimeError("injected normal pre-spawn setup failure")

        with monkeypatch.context() as pre_spawn_context:
            pre_spawn_context.setattr(
                "egp_api.services.discovery_worker_dispatcher.tempfile.SpooledTemporaryFile",
                fail_spool,
            )
            result = processor.process_pending(limit=1)
        assert result.dispositions[0].outcome == "retrying"
        persisted = _job_runs(database_url, tenant_id=tenant_id, job_id=job_id)
        assert len(persisted) == 1
        assert persisted[0]["status"] == CrawlRunStatus.QUEUED.value
        assert persisted[0]["summary_json"]["worker_dispatch_phase"] == "reserved"
        assert "worker_pid" not in persisted[0]["summary_json"]
    finally:
        _drop_terminalization_failure_trigger(
            database_url,
            trigger_name=trigger_name,
            function_name=function_name,
        )

    reconciled = RunService(runs, database_url=database_url).reconcile_missing_workers(
        owner_pid=os.getpid()
    )
    assert [run.id for run in reconciled] == [persisted[0]["id"]]
    assert (
        jobs.has_claimable_discovery_jobs(
            only_job_id=job_id,
            only_tenant_id=tenant_id,
        )
        is True
    )


def _assert_stale_legacy_reservation_recovers(database_url: str) -> None:
    tenant_id, profile_id, job_id = _seed_job(
        database_url,
        keyword="f7 stale legacy reservation",
    )
    jobs = SqlDiscoveryJobRepository(database_url=database_url)
    runs = SqlRunRepository(database_url=database_url)
    legacy = runs.create_run(
        tenant_id=tenant_id,
        profile_id=profile_id,
        discovery_job_id=job_id,
        trigger_type="manual",
    )
    with connect(database_url) as connection, connection.cursor() as cursor:
        cursor.execute(
            "UPDATE crawl_runs SET last_activity_at=NOW() - INTERVAL '10 minutes' "
            "WHERE tenant_id=%s AND id=%s",
            (tenant_id, legacy.id),
        )
        connection.commit()

    assert (
        jobs.has_claimable_discovery_jobs(
            only_job_id=job_id,
            only_tenant_id=tenant_id,
        )
        is False
    )
    failed = runs.fail_runs_with_missing_workers(owner_pid=os.getpid())
    assert [run.id for run in failed] == [legacy.id]
    assert (
        jobs.has_claimable_discovery_jobs(
            only_job_id=job_id,
            only_tenant_id=tenant_id,
        )
        is True
    )


def _assert_spawned_summary_failure_reaps_child(
    database_url: str,
    *,
    artifact_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id, _profile_id, job_id = _seed_job(
        database_url,
        keyword="f7 spawned summary outage",
    )
    sentinel = artifact_root / "payload-received"
    artifact_root.mkdir(parents=True, exist_ok=True)
    child_script = (
        "import pathlib, sys; sys.stdin.buffer.read(); "
        "pathlib.Path(sys.argv[1]).write_text('received')"
    )
    real_popen = subprocess.Popen
    children: list[subprocess.Popen[bytes]] = []

    def tracking_popen(*args: object, **kwargs: object):
        del args
        child = real_popen(
            [sys.executable, "-c", child_script, str(sentinel)],
            **kwargs,
        )
        children.append(child)
        return child

    monkeypatch.setattr(
        "egp_api.services.discovery_worker_dispatcher.subprocess.Popen",
        tracking_popen,
    )
    processor, _jobs, _runs = _processor(
        database_url,
        tenant_id=tenant_id,
        job_id=job_id,
        artifact_root=artifact_root,
        fault_mode="nonzero_exit",
    )
    trigger_name, function_name = _install_spawned_summary_failure_trigger(database_url)
    try:
        processor.process_pending(limit=1)
    finally:
        _drop_spawned_summary_failure_trigger(
            database_url,
            trigger_name=trigger_name,
            function_name=function_name,
        )
        for child in children:
            if child.poll() is None:
                with suppress(ProcessLookupError):
                    os.killpg(child.pid, signal.SIGKILL)
                child.wait(timeout=2)

    assert len(children) == 1
    assert children[0].poll() is not None
    assert sentinel.exists() is False


def _assert_legacy_divergence_recovery(database_url: str) -> None:
    tenant_id, profile_id, job_id = _seed_job(
        database_url,
        keyword="f7 legacy divergence",
    )
    jobs = SqlDiscoveryJobRepository(database_url=database_url)
    claimed = jobs.claim_pending_discovery_jobs(
        only_job_id=job_id,
        only_tenant_id=tenant_id,
    )[0]
    jobs.record_discovery_job_attempt(
        tenant_id=tenant_id,
        job_id=job_id,
        claim_token=claimed.claim_token,
        job_status="failed",
        last_error="legacy terminalization failed",
        last_error_code=DiscoveryFailureCode.DISPATCH_EXCEPTION,
    )
    runs = SqlRunRepository(database_url=database_url)
    legacy = runs.create_run(
        tenant_id=tenant_id,
        profile_id=profile_id,
        discovery_job_id=job_id,
        trigger_type="manual",
    )
    sibling_tenant = str(uuid4())
    sibling_run_id = str(uuid4())
    with connect(database_url) as connection, connection.cursor() as cursor:
        cursor.execute(
            "INSERT INTO tenants (id,name,slug,plan_code,is_active) "
            "VALUES (%s,%s,%s,'free',TRUE)",
            (sibling_tenant, "F7 Sibling", f"f7-sibling-{sibling_tenant[:8]}"),
        )
        cursor.execute(
            "INSERT INTO crawl_runs "
            "(id,tenant_id,discovery_job_id,trigger_type,status,last_activity_at,"
            "error_count,created_at) VALUES (%s,%s,%s,'manual','queued',NOW(),0,NOW())",
            (sibling_run_id, sibling_tenant, job_id),
        )
        connection.commit()

    failed = runs.fail_runs_with_missing_workers(owner_pid=os.getpid())

    assert [run.id for run in failed] == [legacy.id]
    matching = runs.find_run_by_id_for_tenant(tenant_id=tenant_id, run_id=legacy.id)
    assert matching is not None
    assert matching.status is CrawlRunStatus.FAILED
    untouched = runs.find_run_by_id_for_tenant(
        tenant_id=sibling_tenant,
        run_id=sibling_run_id,
    )
    assert untouched is not None
    assert untouched.status is CrawlRunStatus.QUEUED


def _assert_signal_crash_reaps_descendant(
    database_url: str,
    *,
    artifact_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id, _profile_id, job_id = _seed_job(
        database_url,
        keyword="f7 signal crash",
    )
    descendant_pid_path = artifact_root / "signal-descendant.pid"
    artifact_root.mkdir(parents=True, exist_ok=True)
    descendant_script = "import time; time.sleep(60)"
    leader_script = (
        "import os, pathlib, signal, subprocess, sys; "
        "descendant = subprocess.Popen([sys.executable, '-c', sys.argv[2]], "
        "stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL); "
        "pathlib.Path(sys.argv[1]).write_text(str(descendant.pid)); "
        "os.kill(os.getpid(), signal.SIGTERM)"
    )
    monkeypatch.setattr(
        "egp_api.services.discovery_worker_dispatcher._fault_worker_command",
        lambda mode: [
            sys.executable,
            "-c",
            leader_script,
            str(descendant_pid_path),
            descendant_script,
        ],
    )
    processor, jobs, _runs = _processor(
        database_url,
        tenant_id=tenant_id,
        job_id=job_id,
        artifact_root=artifact_root,
        fault_mode="worker_crash",
    )

    descendant_pid: int | None = None
    try:
        result = processor.process_pending(limit=1)

        assert result.dispositions[0].outcome == "fault_verified"
        assert (
            jobs.get_discovery_job(tenant_id=tenant_id, job_id=job_id).job_status
            == "failed"
        )
        persisted_runs = _job_runs(database_url, tenant_id=tenant_id, job_id=job_id)
        assert len(persisted_runs) == 1
        assert persisted_runs[0]["status"] == CrawlRunStatus.FAILED.value
        assert (
            persisted_runs[0]["summary_json"]["failure_reason"]
            == DiscoveryFailureCode.WORKER_TERMINATED.value
        )
        assert descendant_pid_path.exists()
        descendant_pid = int(descendant_pid_path.read_text())
        deadline = time.monotonic() + 3.0
        descendant_exists = True
        while descendant_exists and time.monotonic() < deadline:
            try:
                os.kill(descendant_pid, 0)
            except ProcessLookupError:
                descendant_exists = False
            else:
                time.sleep(0.02)
        assert descendant_exists is False
    finally:
        if descendant_pid is None and descendant_pid_path.exists():
            descendant_pid = int(descendant_pid_path.read_text())
        if descendant_pid is not None:
            with suppress(ProcessLookupError):
                os.kill(descendant_pid, signal.SIGKILL)


def test_f7_postgres_terminalization_write_failure_recovers(
    database_url: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _assert_terminalization_write_failure_recovers(
        database_url,
        artifact_root=tmp_path / "terminalization-artifacts",
        monkeypatch=monkeypatch,
    )


def test_f7_postgres_active_run_failure_is_compare_and_swap(
    database_url: str,
) -> None:
    _assert_active_run_failure_cas(database_url)


def test_f7_postgres_stale_claim_cannot_reserve_run(database_url: str) -> None:
    _assert_stale_claim_cannot_reserve_run(database_url)


def test_f7_postgres_claim_expiry_during_reservation_is_rejected(
    database_url: str,
) -> None:
    _assert_claim_expiry_while_reservation_waits_is_rejected(database_url)


def test_f7_postgres_normal_pre_spawn_failure_recovers(
    database_url: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _assert_normal_pre_spawn_failure_recovers(
        database_url,
        artifact_root=tmp_path / "normal-pre-spawn-artifacts",
        monkeypatch=monkeypatch,
    )


def test_f7_postgres_stale_legacy_reservation_recovers(database_url: str) -> None:
    _assert_stale_legacy_reservation_recovers(database_url)


def test_f7_postgres_spawned_summary_failure_reaps_child(
    database_url: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _assert_spawned_summary_failure_reaps_child(
        database_url,
        artifact_root=tmp_path / "spawned-summary-artifacts",
        monkeypatch=monkeypatch,
    )


def test_f7_postgres_repairs_legacy_divergent_run_tenant_safely(
    database_url: str,
) -> None:
    _assert_legacy_divergence_recovery(database_url)


def test_f7_postgres_signal_crash_reaps_descendant_group(
    database_url: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _assert_signal_crash_reaps_descendant(
        database_url,
        artifact_root=tmp_path / "signal-artifacts",
        monkeypatch=monkeypatch,
    )


def test_f7_ci_postgres_contract(
    ci_database_url: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _assert_terminalization_write_failure_recovers(
        ci_database_url,
        artifact_root=tmp_path / "ci-terminalization-artifacts",
        monkeypatch=monkeypatch,
    )
    _assert_active_run_failure_cas(ci_database_url)
    _assert_stale_claim_cannot_reserve_run(ci_database_url)
    _assert_claim_expiry_while_reservation_waits_is_rejected(ci_database_url)
    with monkeypatch.context() as pre_spawn_context:
        _assert_normal_pre_spawn_failure_recovers(
            ci_database_url,
            artifact_root=tmp_path / "ci-normal-pre-spawn-artifacts",
            monkeypatch=pre_spawn_context,
        )
    _assert_stale_legacy_reservation_recovers(ci_database_url)
    with monkeypatch.context() as summary_context:
        _assert_spawned_summary_failure_reaps_child(
            ci_database_url,
            artifact_root=tmp_path / "ci-spawned-summary-artifacts",
            monkeypatch=summary_context,
        )
    _assert_legacy_divergence_recovery(ci_database_url)
    with monkeypatch.context() as signal_context:
        _assert_signal_crash_reaps_descendant(
            ci_database_url,
            artifact_root=tmp_path / "ci-signal-artifacts",
            monkeypatch=signal_context,
        )
