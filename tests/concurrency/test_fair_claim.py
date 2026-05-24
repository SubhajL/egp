from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import insert, text

from egp_api.services.discovery_dispatch import (
    DiscoveryDispatchProcessor,
    DiscoveryDispatchRequest,
)
from egp_db.repositories.discovery_job_repo import (
    DISCOVERY_JOBS_TABLE,
    SqlDiscoveryJobRepository,
    build_discovery_job_values,
)


TENANT_A_ID = "11111111-1111-1111-1111-111111111111"
TENANT_B_ID = "22222222-2222-2222-2222-222222222222"
PROFILE_A_ID = "33333333-3333-3333-3333-333333333333"
PROFILE_B_ID = "44444444-4444-4444-4444-444444444444"


class RecordingDiscoveryDispatcher:
    def __init__(self) -> None:
        self.requests: list[DiscoveryDispatchRequest] = []

    def dispatch(self, request: DiscoveryDispatchRequest) -> None:
        self.requests.append(request)


def _seed_tenant_profile(
    repository: SqlDiscoveryJobRepository,
    *,
    tenant_id: str,
    profile_id: str,
    slug: str,
) -> None:
    now = "2026-05-24T00:00:00+00:00"
    with repository._engine.begin() as connection:  # test setup only
        connection.execute(
            text(
                """
                INSERT INTO tenants (id, name, slug, plan_code, is_active, created_at, updated_at)
                VALUES (:tenant_id, :name, :slug, 'monthly_membership', 1, :now, :now)
                """
            ),
            {
                "tenant_id": tenant_id,
                "name": slug.replace("-", " ").title(),
                "slug": slug,
                "now": now,
            },
        )
        connection.execute(
            text(
                """
                INSERT INTO crawl_profiles (
                    id, tenant_id, name, profile_type, is_active,
                    max_pages_per_keyword, close_consulting_after_days,
                    close_stale_after_days, created_at, updated_at
                ) VALUES (
                    :profile_id, :tenant_id, 'Watchlist', 'custom', 1,
                    15, 30, 45, :now, :now
                )
                """
            ),
            {
                "profile_id": profile_id,
                "tenant_id": tenant_id,
                "now": now,
            },
        )


def _seed_discovery_jobs(
    repository: SqlDiscoveryJobRepository,
    *,
    tenant_id: str,
    profile_id: str,
    keyword_prefix: str,
    count: int,
    first_due_at: datetime,
) -> None:
    rows = [
        build_discovery_job_values(
            tenant_id=tenant_id,
            profile_id=profile_id,
            profile_type="custom",
            keyword=f"{keyword_prefix}-{index:02d}",
            now=first_due_at + timedelta(milliseconds=index),
        )
        for index in range(count)
    ]
    with repository._engine.begin() as connection:  # test setup only
        connection.execute(insert(DISCOVERY_JOBS_TABLE), rows)


def test_fair_claim_reaches_later_tenant_within_worker_capacity_cycles(
    tmp_path,
) -> None:
    worker_count = 2
    repository = SqlDiscoveryJobRepository(
        database_url=f"sqlite+pysqlite:///{tmp_path / 'fair-claim.sqlite3'}",
        bootstrap_schema=True,
    )
    _seed_tenant_profile(
        repository,
        tenant_id=TENANT_A_ID,
        profile_id=PROFILE_A_ID,
        slug="tenant-a",
    )
    _seed_tenant_profile(
        repository,
        tenant_id=TENANT_B_ID,
        profile_id=PROFILE_B_ID,
        slug="tenant-b",
    )
    baseline_due_at = datetime.now(UTC) - timedelta(minutes=5)
    _seed_discovery_jobs(
        repository,
        tenant_id=TENANT_A_ID,
        profile_id=PROFILE_A_ID,
        keyword_prefix="tenant-a",
        count=50,
        first_due_at=baseline_due_at,
    )
    _seed_discovery_jobs(
        repository,
        tenant_id=TENANT_B_ID,
        profile_id=PROFILE_B_ID,
        keyword_prefix="tenant-b",
        count=1,
        first_due_at=baseline_due_at + timedelta(seconds=1),
    )
    dispatcher = RecordingDiscoveryDispatcher()
    processor = DiscoveryDispatchProcessor(
        repository=repository,
        dispatcher=dispatcher,
        worker_count=worker_count,
        claim_limit=worker_count * (worker_count + 1),
    )

    processed = processor.process_pending()

    assert processed == worker_count * (worker_count + 1)
    claimed_tenant_ids = [request.tenant_id for request in dispatcher.requests]
    assert TENANT_B_ID in claimed_tenant_ids
    assert claimed_tenant_ids.index(TENANT_B_ID) < worker_count * (worker_count + 1)
