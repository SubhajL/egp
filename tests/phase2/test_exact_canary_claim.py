from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import importlib
from pathlib import Path
from threading import Event
from time import monotonic, sleep
from uuid import uuid4

import pytest
from psycopg import connect
from sqlalchemy import text

from egp_db.dev_postgres import TempPostgresCluster, postgres_binaries_available
from egp_db.migration_runner import apply_migrations
from egp_db.repositories.discovery_job_repo import SqlDiscoveryJobRepository


TENANT_ID = "11111111-1111-4111-8111-111111111111"
PROFILE_ID = "22222222-2222-4222-8222-222222222222"
KEYWORD = "ประกวดราคาจ้างวิเคราะห์ข้อมูล"


def _target(**overrides: object):
    target_type = importlib.import_module(
        "egp_shared_types.exact_canary"
    ).ExactIngestionCanaryTarget
    payload = {
        "contract_version": 1,
        "kind": "exact_ingestion_canary",
        "tenant_id": TENANT_ID,
        "job_id": overrides.pop("job_id"),
        "profile_id": PROFILE_ID,
        "keyword": KEYWORD,
        "live": True,
        "execution_backend": "legacy",
        "browser_required": True,
        "max_pages_per_keyword": 15,
        **overrides,
    }
    return target_type.from_mapping(payload)


def _repo(tmp_path: Path, name: str) -> SqlDiscoveryJobRepository:
    repo = SqlDiscoveryJobRepository(
        database_url=f"sqlite+pysqlite:///{tmp_path / f'{name}.sqlite3'}",
        bootstrap_schema=True,
    )
    now = "2026-08-24T00:00:00+00:00"
    with repo._engine.begin() as connection:  # test setup only
        connection.execute(
            text(
                """
                INSERT INTO tenants (id, name, slug, plan_code, is_active, created_at, updated_at)
                VALUES (:id, 'Canary', :slug, 'monthly_membership', 1, :now, :now)
                """
            ),
            {"id": TENANT_ID, "slug": f"canary-{name}", "now": now},
        )
        connection.execute(
            text(
                """
                INSERT INTO crawl_profiles (
                    id, tenant_id, name, profile_type, is_active,
                    max_pages_per_keyword, close_consulting_after_days,
                    close_stale_after_days, execution_backend, created_at, updated_at
                ) VALUES (
                    :id, :tenant_id, 'Canary', 'custom', 1,
                    15, 30, 45, 'legacy', :now, :now
                )
                """
            ),
            {"id": PROFILE_ID, "tenant_id": TENANT_ID, "now": now},
        )
        connection.execute(
            text(
                """
                INSERT INTO crawl_profile_keywords (id, profile_id, keyword, position, created_at)
                VALUES (:id, :profile_id, :keyword, 1, :now)
                """
            ),
            {
                "id": str(uuid4()),
                "profile_id": PROFILE_ID,
                "keyword": KEYWORD,
                "now": now,
            },
        )
    return repo


def _job(repo: SqlDiscoveryJobRepository, *, live: bool = True):
    return repo.create_discovery_job(
        tenant_id=TENANT_ID,
        profile_id=PROFILE_ID,
        profile_type="custom",
        keyword=KEYWORD,
        live=live,
    )


def test_exact_canary_claim_requires_every_pinned_field(tmp_path: Path) -> None:
    repo = _repo(tmp_path, "exact-match")
    job = _job(repo)
    target = _target(job_id=job.id)

    assert repo.has_claimable_discovery_jobs(exact_canary_target=target) is True
    claimed = repo.claim_pending_discovery_jobs(
        limit=1,
        exact_canary_target=target,
    )

    assert [record.id for record in claimed] == [job.id]
    assert claimed[0].live is True
    assert claimed[0].execution_backend == "legacy"


@pytest.mark.parametrize(
    "mismatch",
    [
        "tenant_id",
        "job_id",
        "profile_id",
        "keyword",
        "job_live",
        "profile_backend",
        "profile_cap",
        "profile_keyword",
    ],
)
def test_exact_canary_claim_mismatch_does_not_mutate_job(
    tmp_path: Path,
    mismatch: str,
) -> None:
    repo = _repo(tmp_path, mismatch)
    job = _job(repo, live=mismatch != "job_live")
    overrides: dict[str, object] = {"job_id": job.id}
    if mismatch == "tenant_id":
        overrides["tenant_id"] = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
    elif mismatch == "job_id":
        overrides["job_id"] = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
    elif mismatch == "profile_id":
        overrides["profile_id"] = "cccccccc-cccc-4ccc-8ccc-cccccccccccc"
    elif mismatch == "keyword":
        overrides["keyword"] = "คำค้นอื่น"

    with repo._engine.begin() as connection:  # test setup only
        if mismatch == "profile_backend":
            connection.execute(
                text(
                    "UPDATE crawl_profiles SET execution_backend = 'agent' WHERE id = :id"
                ),
                {"id": PROFILE_ID},
            )
        elif mismatch == "profile_cap":
            connection.execute(
                text(
                    "UPDATE crawl_profiles SET max_pages_per_keyword = 7 WHERE id = :id"
                ),
                {"id": PROFILE_ID},
            )
        elif mismatch == "profile_keyword":
            connection.execute(
                text(
                    "UPDATE crawl_profile_keywords SET keyword = 'คำค้นอื่น' WHERE profile_id = :id"
                ),
                {"id": PROFILE_ID},
            )

    target = _target(**overrides)
    assert repo.has_claimable_discovery_jobs(exact_canary_target=target) is False
    assert (
        repo.claim_pending_discovery_jobs(
            limit=1,
            exact_canary_target=target,
        )
        == []
    )

    stored = repo.get_discovery_job(tenant_id=TENANT_ID, job_id=job.id)
    assert stored.job_status == "pending"
    assert stored.claim_token is None
    assert stored.processing_started_at is None


def test_exact_canary_postgres_claim_rechecks_live_after_concurrent_mutation() -> None:
    if not postgres_binaries_available():
        pytest.skip("PostgreSQL binaries are required for exact-canary claim race")

    repo_root = Path(__file__).resolve().parents[2]
    with TempPostgresCluster() as cluster:
        cluster.create_database("egp_exact_canary_claim")
        database_url = cluster.database_url("egp_exact_canary_claim")
        apply_migrations(
            database_url=database_url,
            migrations_dir=repo_root / "packages/db/src/migrations",
        )
        with connect(database_url) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO tenants (id, name, slug, plan_code)
                    VALUES (%s, 'Canary', 'exact-canary-claim', 'monthly_membership')
                    """,
                    (TENANT_ID,),
                )
                cursor.execute(
                    """
                    INSERT INTO crawl_profiles (
                        id, tenant_id, name, profile_type,
                        max_pages_per_keyword, execution_backend
                    ) VALUES (%s, %s, 'Canary', 'custom', 15, 'legacy')
                    """,
                    (PROFILE_ID, TENANT_ID),
                )
                cursor.execute(
                    """
                    INSERT INTO crawl_profile_keywords (profile_id, keyword, position)
                    VALUES (%s, %s, 1)
                    """,
                    (PROFILE_ID, KEYWORD),
                )
            connection.commit()

        repository = SqlDiscoveryJobRepository(
            database_url=database_url,
            bootstrap_schema=False,
        )
        job = _job(repository)
        target = _target(job_id=job.id)
        claim_started = Event()
        worker_application_name = "exact_canary_claim_racer"

        def claim_exact_target():
            claim_started.set()
            worker_repository = SqlDiscoveryJobRepository(
                database_url=(
                    f"{database_url}?application_name={worker_application_name}"
                ),
                bootstrap_schema=False,
            )
            return worker_repository.claim_pending_discovery_jobs(
                limit=1,
                exact_canary_target=target,
            )

        with connect(database_url) as mutation_connection:
            with mutation_connection.cursor() as cursor:
                cursor.execute(
                    "SELECT id FROM crawl_profiles WHERE id = %s FOR UPDATE",
                    (PROFILE_ID,),
                )
                with ThreadPoolExecutor(max_workers=1) as executor:
                    future = executor.submit(claim_exact_target)
                    assert claim_started.wait(timeout=2)
                    deadline = monotonic() + 2
                    worker_is_blocked_on_profile_lock = False
                    with connect(database_url, autocommit=True) as monitor_connection:
                        with monitor_connection.cursor() as monitor_cursor:
                            while monotonic() < deadline:
                                monitor_cursor.execute(
                                    """
                                    SELECT EXISTS (
                                        SELECT 1
                                        FROM pg_stat_activity
                                        WHERE application_name = %s
                                          AND state = 'active'
                                          AND wait_event_type = 'Lock'
                                          AND query ILIKE '%%crawl_profiles%%'
                                          AND query ILIKE '%%FOR UPDATE%%'
                                    )
                                    """,
                                    (worker_application_name,),
                                )
                                worker_is_blocked_on_profile_lock = bool(
                                    monitor_cursor.fetchone()[0]
                                )
                                if worker_is_blocked_on_profile_lock:
                                    break
                                sleep(0.01)
                    if not worker_is_blocked_on_profile_lock:
                        mutation_connection.rollback()
                        future.result(timeout=5)
                        pytest.fail(
                            "claim worker did not block on the exact profile lock"
                        )
                    cursor.execute(
                        "UPDATE discovery_jobs SET live = FALSE WHERE id = %s",
                        (job.id,),
                    )
                    mutation_connection.commit()
                    claimed = future.result(timeout=5)

        assert claimed == []
        stored = repository.get_discovery_job(tenant_id=TENANT_ID, job_id=job.id)
        assert stored.live is False
        assert stored.job_status == "pending"
        assert stored.claim_token is None
        assert stored.processing_started_at is None
