from __future__ import annotations

import threading

from sqlalchemy import text

from egp_api.services.discovery_dispatch import (
    DiscoveryDispatchRequest,
    DiscoveryDispatchProcessor,
    NonRetriableDiscoveryDispatchError,
)
from egp_db.repositories.discovery_job_repo import DiscoveryJobRecord, SqlDiscoveryJobRepository

TENANT_ID = "11111111-1111-1111-1111-111111111111"
PROFILE_ID = "22222222-2222-2222-2222-222222222222"


class RecordingDiscoveryDispatcher:
    def __init__(self) -> None:
        self.requests: list[DiscoveryDispatchRequest] = []

    def dispatch(self, request: DiscoveryDispatchRequest) -> None:
        self.requests.append(request)


class RaisingDiscoveryDispatcher:
    def __init__(self, exception: Exception) -> None:
        self.exception = exception

    def dispatch(self, request: DiscoveryDispatchRequest) -> None:
        del request
        raise self.exception


class RecordingClaimStore:
    def __init__(self, jobs: list[DiscoveryJobRecord]) -> None:
        self._jobs = list(jobs)
        self._jobs_by_id = {job.id: job for job in jobs}
        self.claim_limits: list[int] = []
        self.recorded_job_ids: list[str] = []

    def claim_pending_discovery_jobs(
        self,
        *,
        limit: int = 10,
        stale_after_seconds: float = 60.0,
        exclude_job_ids=None,
    ) -> list[DiscoveryJobRecord]:
        del stale_after_seconds
        excluded = set(exclude_job_ids or ())
        self.claim_limits.append(limit)
        claimable = [job for job in self._jobs if job.id not in excluded]
        claimed = claimable[:limit]
        claimed_ids = {job.id for job in claimed}
        self._jobs = [job for job in self._jobs if job.id not in claimed_ids]
        return claimed

    def record_discovery_job_attempt(
        self,
        *,
        tenant_id: str,
        job_id: str,
        job_status: str,
        last_error: str | None = None,
        next_attempt_at=None,
        processing_started_at=None,
        dispatched: bool = False,
    ) -> DiscoveryJobRecord:
        del tenant_id, job_status, last_error, next_attempt_at, processing_started_at, dispatched
        self.recorded_job_ids.append(job_id)
        return self._jobs_by_id[job_id]


def _job_record(job_id: str, *, keyword: str) -> DiscoveryJobRecord:
    return DiscoveryJobRecord(
        id=job_id,
        tenant_id=TENANT_ID,
        profile_id=PROFILE_ID,
        profile_type="custom",
        keyword=keyword,
        trigger_type="profile_created",
        live=True,
        job_status="pending",
        attempt_count=0,
        last_error=None,
        next_attempt_at="2026-04-07T00:00:00+00:00",
        processing_started_at=None,
        dispatched_at=None,
        created_at="2026-04-07T00:00:00+00:00",
        updated_at="2026-04-07T00:00:00+00:00",
    )


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
    dispatcher = RecordingDiscoveryDispatcher()

    processor = DiscoveryDispatchProcessor(repository=repo, dispatcher=dispatcher)

    assert processor.process_pending() == 1
    stored = repo.get_discovery_job(tenant_id=TENANT_ID, job_id=job.id)
    assert dispatcher.requests == [
        DiscoveryDispatchRequest(
            tenant_id=TENANT_ID,
            profile_id=PROFILE_ID,
            profile_type="custom",
            keyword="analytics",
        )
    ]
    assert stored.job_status == "dispatched"
    assert stored.attempt_count == 1
    assert stored.dispatched_at is not None


def test_discovery_dispatch_processor_runs_claimed_jobs_with_worker_pool(tmp_path) -> None:
    repo = SqlDiscoveryJobRepository(
        database_url=f"sqlite+pysqlite:///{tmp_path / 'dispatch-pool.sqlite3'}",
        bootstrap_schema=True,
    )
    _seed_profile_row(repo)
    for keyword in ("analytics", "procurement"):
        repo.create_discovery_job(
            tenant_id=TENANT_ID,
            profile_id=PROFILE_ID,
            profile_type="custom",
            keyword=keyword,
        )

    class BlockingDispatcher:
        def __init__(self) -> None:
            self._lock = threading.Lock()
            self._release = threading.Event()
            self._both_started = threading.Event()
            self.started_keywords: list[str] = []

        def dispatch(self, request: DiscoveryDispatchRequest) -> None:
            with self._lock:
                self.started_keywords.append(request.keyword)
                if len(self.started_keywords) == 2:
                    self._both_started.set()
            assert self._release.wait(timeout=2.0)

        def release(self) -> None:
            self._release.set()

        def wait_for_overlap(self) -> bool:
            return self._both_started.wait(timeout=0.5)

    dispatcher = BlockingDispatcher()
    processor = DiscoveryDispatchProcessor(
        repository=repo,
        dispatcher=dispatcher,
        worker_count=2,
    )
    processed: list[int] = []
    worker = threading.Thread(
        target=lambda: processed.append(processor.process_pending()),
        daemon=True,
    )

    worker.start()
    overlapped = dispatcher.wait_for_overlap()
    dispatcher.release()
    worker.join(timeout=2.0)

    assert overlapped is True
    assert processed == [2]
    assert worker.is_alive() is False
    stored = repo.list_discovery_jobs(tenant_id=TENANT_ID)
    assert {job.keyword: job.job_status for job in stored} == {
        "analytics": "dispatched",
        "procurement": "dispatched",
    }


def test_discovery_dispatch_processor_preserves_serial_mode_with_one_worker(tmp_path) -> None:
    repo = SqlDiscoveryJobRepository(
        database_url=f"sqlite+pysqlite:///{tmp_path / 'dispatch-serial.sqlite3'}",
        bootstrap_schema=True,
    )
    _seed_profile_row(repo)
    for keyword in ("analytics", "procurement"):
        repo.create_discovery_job(
            tenant_id=TENANT_ID,
            profile_id=PROFILE_ID,
            profile_type="custom",
            keyword=keyword,
        )
    dispatcher = RecordingDiscoveryDispatcher()

    processor = DiscoveryDispatchProcessor(
        repository=repo,
        dispatcher=dispatcher,
        worker_count=1,
    )

    assert processor.process_pending() == 2
    assert [request.keyword for request in dispatcher.requests] == [
        "analytics",
        "procurement",
    ]


def test_discovery_dispatch_processor_claims_only_worker_capacity_per_batch() -> None:
    store = RecordingClaimStore(
        [
            _job_record("11111111-1111-1111-1111-111111111111", keyword="one"),
            _job_record("22222222-2222-2222-2222-222222222222", keyword="two"),
            _job_record("33333333-3333-3333-3333-333333333333", keyword="three"),
            _job_record("44444444-4444-4444-4444-444444444444", keyword="four"),
            _job_record("55555555-5555-5555-5555-555555555555", keyword="five"),
        ]
    )
    dispatcher = RecordingDiscoveryDispatcher()
    processor = DiscoveryDispatchProcessor(
        repository=store,
        dispatcher=dispatcher,
        claim_limit=5,
        worker_count=2,
    )

    assert processor.process_pending() == 5
    assert store.claim_limits == [2, 2, 1]
    assert {request.keyword for request in dispatcher.requests} == {
        "one",
        "two",
        "three",
        "four",
        "five",
    }


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

    class FailingDispatcher:
        def dispatch(self, request: DiscoveryDispatchRequest) -> None:
            attempts.append(request.keyword)
            raise RuntimeError("spawn failed")

    processor = DiscoveryDispatchProcessor(
        repository=repo,
        dispatcher=FailingDispatcher(),
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


def test_discovery_dispatch_processor_retries_when_worker_exits_non_zero(
    tmp_path,
) -> None:
    repo = SqlDiscoveryJobRepository(
        database_url=f"sqlite+pysqlite:///{tmp_path / 'dispatch-worker-exit.sqlite3'}",
        bootstrap_schema=True,
    )
    _seed_profile_row(repo)
    job = repo.create_discovery_job(
        tenant_id=TENANT_ID,
        profile_id=PROFILE_ID,
        profile_type="custom",
        keyword="analytics",
    )

    processor = DiscoveryDispatchProcessor(
        repository=repo,
        dispatcher=RaisingDiscoveryDispatcher(RuntimeError("worker exited non-zero")),
        max_attempts=2,
        retry_delay_seconds=0.0,
    )

    assert processor.process_pending() == 1
    first = repo.get_discovery_job(tenant_id=TENANT_ID, job_id=job.id)
    assert first.job_status == "pending"
    assert first.attempt_count == 1
    assert first.last_error == "worker exited non-zero"

    assert processor.process_pending() == 1
    second = repo.get_discovery_job(tenant_id=TENANT_ID, job_id=job.id)
    assert second.job_status == "failed"
    assert second.attempt_count == 2
    assert second.last_error == "worker exited non-zero"


def test_discovery_dispatch_processor_fails_immediately_on_non_retriable_error(
    tmp_path,
) -> None:
    repo = SqlDiscoveryJobRepository(
        database_url=f"sqlite+pysqlite:///{tmp_path / 'dispatch-terminal.sqlite3'}",
        bootstrap_schema=True,
    )
    _seed_profile_row(repo)
    job = repo.create_discovery_job(
        tenant_id=TENANT_ID,
        profile_id=PROFILE_ID,
        profile_type="custom",
        keyword="analytics",
    )

    processor = DiscoveryDispatchProcessor(
        repository=repo,
        dispatcher=RaisingDiscoveryDispatcher(
            NonRetriableDiscoveryDispatchError("active subscription required for runs")
        ),
        max_attempts=3,
        retry_delay_seconds=0.0,
    )

    assert processor.process_pending() == 1
    stored = repo.get_discovery_job(tenant_id=TENANT_ID, job_id=job.id)
    assert stored.job_status == "failed"
    assert stored.attempt_count == 1
    assert stored.last_error == "active subscription required for runs"
