from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import insert, text

from egp_db.repositories import discovery_job_repo as discovery_job_repo_module
from egp_api.services.discovery_dispatch import (
    DiscoveryDispatchProcessor,
    DiscoveryDispatchRequest,
)
from egp_db.repositories.discovery_job_repo import (
    DISCOVERY_JOBS_TABLE,
    SqlDiscoveryJobRepository,
    StaleDiscoveryJobClaimError,
    build_discovery_job_values,
)
from egp_shared_types.enums import DiscoveryFailureCode


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

    assert processed.processed_count == worker_count * (worker_count + 1)
    claimed_tenant_ids = [request.tenant_id for request in dispatcher.requests]
    assert TENANT_B_ID in claimed_tenant_ids
    assert claimed_tenant_ids.index(TENANT_B_ID) < worker_count * (worker_count + 1)


def test_renewed_lease_cannot_be_reclaimed(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    clock = {"now": datetime(2026, 7, 23, 1, 0, tzinfo=UTC)}
    monkeypatch.setattr(discovery_job_repo_module, "_now", lambda: clock["now"])
    repository = SqlDiscoveryJobRepository(
        database_url=f"sqlite+pysqlite:///{tmp_path / 'renewed-lease.sqlite3'}",
        bootstrap_schema=True,
    )
    _seed_tenant_profile(
        repository,
        tenant_id=TENANT_A_ID,
        profile_id=PROFILE_A_ID,
        slug="tenant-a",
    )
    job = repository.create_discovery_job(
        tenant_id=TENANT_A_ID,
        profile_id=PROFILE_A_ID,
        profile_type="custom",
        keyword="renew-me",
    )

    claimed = repository.claim_pending_discovery_jobs(limit=1, lease_seconds=60.0)
    clock["now"] += timedelta(seconds=50)
    renewed = repository.renew_discovery_job_lease(
        tenant_id=TENANT_A_ID,
        job_id=job.id,
        claim_token=claimed[0].claim_token or "",
        lease_seconds=60.0,
    )
    clock["now"] += timedelta(seconds=20)

    assert claimed[0].claim_token is not None
    assert renewed.claim_token == claimed[0].claim_token
    assert renewed.lease_heartbeat_at is not None
    assert repository.claim_pending_discovery_jobs(limit=1, lease_seconds=60.0) == []


def test_expired_lease_can_be_reclaimed(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    clock = {"now": datetime(2026, 7, 23, 2, 0, tzinfo=UTC)}
    monkeypatch.setattr(discovery_job_repo_module, "_now", lambda: clock["now"])
    repository = SqlDiscoveryJobRepository(
        database_url=f"sqlite+pysqlite:///{tmp_path / 'expired-lease.sqlite3'}",
        bootstrap_schema=True,
    )
    _seed_tenant_profile(
        repository,
        tenant_id=TENANT_A_ID,
        profile_id=PROFILE_A_ID,
        slug="tenant-a",
    )
    repository.create_discovery_job(
        tenant_id=TENANT_A_ID,
        profile_id=PROFILE_A_ID,
        profile_type="custom",
        keyword="reclaim-me",
    )

    first_claim = repository.claim_pending_discovery_jobs(limit=1, lease_seconds=60.0)[0]
    clock["now"] += timedelta(seconds=61)
    second_claim = repository.claim_pending_discovery_jobs(limit=1, lease_seconds=60.0)[0]

    assert first_claim.id == second_claim.id
    assert first_claim.claim_token is not None
    assert second_claim.claim_token is not None
    assert first_claim.claim_token != second_claim.claim_token


def test_stale_claim_token_cannot_finish_job(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    clock = {"now": datetime(2026, 7, 23, 3, 0, tzinfo=UTC)}
    monkeypatch.setattr(discovery_job_repo_module, "_now", lambda: clock["now"])
    repository = SqlDiscoveryJobRepository(
        database_url=f"sqlite+pysqlite:///{tmp_path / 'stale-token.sqlite3'}",
        bootstrap_schema=True,
    )
    _seed_tenant_profile(
        repository,
        tenant_id=TENANT_A_ID,
        profile_id=PROFILE_A_ID,
        slug="tenant-a",
    )
    repository.create_discovery_job(
        tenant_id=TENANT_A_ID,
        profile_id=PROFILE_A_ID,
        profile_type="custom",
        keyword="owned-job",
    )
    first_claim = repository.claim_pending_discovery_jobs(limit=1, lease_seconds=60.0)[0]
    clock["now"] += timedelta(seconds=61)
    second_claim = repository.claim_pending_discovery_jobs(limit=1, lease_seconds=60.0)[0]

    with pytest.raises(StaleDiscoveryJobClaimError):
        repository.record_discovery_job_attempt(
            tenant_id=TENANT_A_ID,
            job_id=first_claim.id,
            claim_token=first_claim.claim_token,
            job_status="dispatched",
            last_error=None,
            last_error_code=None,
            dispatched=True,
        )

    completed = repository.record_discovery_job_attempt(
        tenant_id=TENANT_A_ID,
        job_id=second_claim.id,
        claim_token=second_claim.claim_token,
        job_status="failed",
        last_error="worker exited",
        last_error_code=DiscoveryFailureCode.WORKER_EXIT_NONZERO,
    )

    assert completed.job_status == "failed"
    assert completed.last_error_code == DiscoveryFailureCode.WORKER_EXIT_NONZERO
    assert completed.claim_token is None
    assert completed.lease_expires_at is None


def test_discovery_job_repository_rejects_unknown_failure_code(tmp_path) -> None:
    repository = SqlDiscoveryJobRepository(
        database_url=f"sqlite+pysqlite:///{tmp_path / 'invalid-code.sqlite3'}",
        bootstrap_schema=True,
    )
    _seed_tenant_profile(
        repository,
        tenant_id=TENANT_A_ID,
        profile_id=PROFILE_A_ID,
        slug="tenant-a",
    )
    job = repository.create_discovery_job(
        tenant_id=TENANT_A_ID,
        profile_id=PROFILE_A_ID,
        profile_type="custom",
        keyword="invalid-code",
    )

    with pytest.raises(ValueError, match="unknown discovery failure code"):
        repository.record_discovery_job_attempt(
            tenant_id=TENANT_A_ID,
            job_id=job.id,
            job_status="failed",
            last_error="bad code",
            last_error_code="not-a-real-code",
        )
