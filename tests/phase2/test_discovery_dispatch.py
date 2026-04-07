from __future__ import annotations

from sqlalchemy import text

from egp_api.services.discovery_dispatch import DiscoveryDispatchProcessor
from egp_db.repositories.discovery_job_repo import SqlDiscoveryJobRepository

TENANT_ID = "11111111-1111-1111-1111-111111111111"
PROFILE_ID = "22222222-2222-2222-2222-222222222222"


def _seed_profile_row(repository: SqlDiscoveryJobRepository) -> None:
    now = "2026-04-07T00:00:00+00:00"
    with repository._engine.begin() as connection:  # test setup only
        connection.execute(
            text(
                """
                INSERT INTO tenants (id, name, slug, plan_code, is_active, created_at, updated_at)
                VALUES (:id, 'Acme', 'acme', 'monthly_membership', 1, :now, :now)
                """
            ),
            {"id": TENANT_ID, "now": now},
        )
        connection.execute(
            text(
                """
                INSERT INTO crawl_profiles (
                    id, tenant_id, name, profile_type, is_active,
                    max_pages_per_keyword, close_consulting_after_days,
                    close_stale_after_days, created_at, updated_at
                ) VALUES (
                    :id, :tenant_id, 'Watchlist', 'custom', 1,
                    15, 30, 45, :now, :now
                )
                """
            ),
            {"id": PROFILE_ID, "tenant_id": TENANT_ID, "now": now},
        )


def test_discovery_dispatch_processor_marks_job_dispatched(tmp_path) -> None:
    repo = SqlDiscoveryJobRepository(
        database_url=f"sqlite+pysqlite:///{tmp_path / 'dispatch.sqlite3'}",
        bootstrap_schema=True,
    )
    _seed_profile_row(repo)
    job = repo.create_discovery_job(
        tenant_id=TENANT_ID,
        profile_id=PROFILE_ID,
        profile_type="custom",
        keyword="analytics",
    )
    dispatched: list[dict[str, str]] = []

    def dispatcher(
        *, tenant_id: str, profile_id: str, profile_type: str, keyword: str
    ) -> None:
        dispatched.append(
            {
                "tenant_id": tenant_id,
                "profile_id": profile_id,
                "profile_type": profile_type,
                "keyword": keyword,
            }
        )

    processor = DiscoveryDispatchProcessor(repository=repo, dispatcher=dispatcher)

    assert processor.process_pending() == 1
    stored = repo.get_discovery_job(tenant_id=TENANT_ID, job_id=job.id)
    assert dispatched == [
        {
            "tenant_id": TENANT_ID,
            "profile_id": PROFILE_ID,
            "profile_type": "custom",
            "keyword": "analytics",
        }
    ]
    assert stored.job_status == "dispatched"
    assert stored.attempt_count == 1
    assert stored.dispatched_at is not None


def test_discovery_dispatch_processor_retries_and_then_fails(tmp_path) -> None:
    repo = SqlDiscoveryJobRepository(
        database_url=f"sqlite+pysqlite:///{tmp_path / 'dispatch-retry.sqlite3'}",
        bootstrap_schema=True,
    )
    _seed_profile_row(repo)
    job = repo.create_discovery_job(
        tenant_id=TENANT_ID,
        profile_id=PROFILE_ID,
        profile_type="custom",
        keyword="analytics",
    )
    attempts: list[str] = []

    def dispatcher(
        *, tenant_id: str, profile_id: str, profile_type: str, keyword: str
    ) -> None:
        attempts.append(keyword)
        raise RuntimeError("spawn failed")

    processor = DiscoveryDispatchProcessor(
        repository=repo,
        dispatcher=dispatcher,
        max_attempts=2,
        retry_delay_seconds=0.0,
    )

    assert processor.process_pending() == 1
    first = repo.get_discovery_job(tenant_id=TENANT_ID, job_id=job.id)
    assert first.job_status == "pending"
    assert first.attempt_count == 1
    assert first.last_error == "spawn failed"

    assert processor.process_pending() == 1
    second = repo.get_discovery_job(tenant_id=TENANT_ID, job_id=job.id)
    assert attempts == ["analytics", "analytics"]
    assert second.job_status == "failed"
    assert second.attempt_count == 2
    assert second.last_error == "spawn failed"
