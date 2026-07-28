"""U7b prerequisite: `result_received` must count as IN-FLIGHT work everywhere.

Migration 034 added the `result_received` discovery-job status but nothing produces
it yet. U7b introduces the producer, so before that lands every place that reasons
about "is there outstanding work for this profile/keyword/tenant" has to learn the
new status. Each site below is a real defect once a producer exists:

* reporting — a job awaiting inbox processing must not read as ``queued``, which
  means "not started";
* admission/backpressure — it must still occupy the tenant's concurrency budget;
* the three dedupe/conflict paths — otherwise a second identical job is enqueued
  while the first one's result is sitting in the inbox.

The whole point is a single shared definition, so a future status cannot be added
to some sites and forgotten at others.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import insert, text

from egp_db.repositories.discovery_job_repo import (
    DISCOVERY_JOBS_TABLE,
    SqlDiscoveryJobRepository,
    build_discovery_job_values,
)
from egp_db.repositories.recrawl_request_repo import SqlRecrawlRequestRepository
from egp_shared_types.enums import (
    IN_FLIGHT_DISCOVERY_JOB_STATUSES,
    DiscoveryJobStatus,
)


TENANT_ID = "11111111-1111-1111-1111-111111111111"
PROFILE_ID = "33333333-3333-3333-3333-333333333333"


def _seed_tenant_profile(repository) -> None:
    now = "2026-07-28T00:00:00+00:00"
    with repository._engine.begin() as connection:  # test setup only
        connection.execute(
            text(
                """
                INSERT INTO tenants
                    (id, name, slug, plan_code, is_active, created_at, updated_at)
                VALUES (:tenant_id, 'U7b tenant', 'u7b-tenant',
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
                VALUES (:profile_id, :tenant_id, 'U7b profile', 'custom', 1,
                        15, 30, 45, :now, :now)
                """
            ),
            {"profile_id": PROFILE_ID, "tenant_id": TENANT_ID, "now": now},
        )


def _repository(tmp_path) -> SqlDiscoveryJobRepository:
    repository = SqlDiscoveryJobRepository(
        database_url=f"sqlite+pysqlite:///{tmp_path / 'u7b-inflight.sqlite3'}",
        bootstrap_schema=True,
    )
    _seed_tenant_profile(repository)
    return repository


def _seed_job(repository, *, keyword: str, job_status: str) -> str:
    values = build_discovery_job_values(
        tenant_id=TENANT_ID,
        profile_id=PROFILE_ID,
        profile_type="custom",
        keyword=keyword,
        now=datetime.now(UTC) - timedelta(minutes=5),
    )
    values["job_status"] = job_status
    with repository._engine.begin() as connection:  # test setup only
        connection.execute(insert(DISCOVERY_JOBS_TABLE), [values])
    return str(values["id"])


# --------------------------------------------------------------------------
# The shared definition
# --------------------------------------------------------------------------


def test_in_flight_statuses_are_pending_and_result_received() -> None:
    """One definition, reused by every site below."""

    assert IN_FLIGHT_DISCOVERY_JOB_STATUSES == frozenset(
        {DiscoveryJobStatus.PENDING, DiscoveryJobStatus.RESULT_RECEIVED}
    )


def test_in_flight_statuses_exclude_terminal_states() -> None:
    assert DiscoveryJobStatus.DISPATCHED not in IN_FLIGHT_DISCOVERY_JOB_STATUSES
    assert DiscoveryJobStatus.FAILED not in IN_FLIGHT_DISCOVERY_JOB_STATUSES


# --------------------------------------------------------------------------
# Admission quota — deliberately NOT widened
# --------------------------------------------------------------------------


def test_pending_count_stays_queue_depth_only(tmp_path) -> None:
    """`count_pending_discovery_jobs` must NOT be widened to the in-flight set.

    It feeds `entitlement_service`'s `queued_keyword_count`, which is compared
    against `max_queued_keywords` — a queue-DEPTH cap. Concurrency is a separate
    check (`inflight_run_count >= max_concurrent_runs`). A `result_received` job
    has already executed, so counting it here would silently tighten a
    customer-facing quota and could deny admission incorrectly.

    Admission semantics for in-flight-but-unapplied work is a deliberate U8
    decision, made when jobs can actually reach that state.
    """

    repository = _repository(tmp_path)
    _seed_job(repository, keyword="still-pending", job_status="pending")
    _seed_job(repository, keyword="awaiting-apply", job_status="result_received")
    _seed_job(repository, keyword="already-done", job_status="dispatched")

    assert repository.count_pending_discovery_jobs(tenant_id=TENANT_ID) == 1


# --------------------------------------------------------------------------
# Site 1 — reporting
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("job_status", "expected_state"),
    [
        ("pending", "queued"),
        ("result_received", "running"),
    ],
)
def test_resolve_job_state_does_not_report_result_received_as_queued(
    job_status: str, expected_state: str
) -> None:
    """`queued` means "not started". A submitted result is the opposite of that.

    Mapped to `running` rather than a new vocabulary value on purpose: these
    strings are published through OpenAPI and the frontend filters on them
    (`apps/web/src/app/(app)/projects/page.tsx`), so a new value would be a
    contract + UI change. From the requester's side the crawl genuinely is still
    in progress until its result has been applied.
    """

    job = {
        "job_status": job_status,
        "processing_started_at": None,
        "attempt_count": 0,
    }

    assert (
        SqlRecrawlRequestRepository._resolve_job_state(job=job, latest_run=None)
        == expected_state
    )


def test_resolve_job_state_keeps_failed_terminal() -> None:
    """Regression guard: widening must not disturb the existing branches."""

    job = {"job_status": "failed", "processing_started_at": None, "attempt_count": 0}
    assert (
        SqlRecrawlRequestRepository._resolve_job_state(job=job, latest_run=None)
        == "failed"
    )


# --------------------------------------------------------------------------
# Site 8 — enqueue dedupe (found by enumerating every job_status filter)
# --------------------------------------------------------------------------


def test_enqueue_if_absent_treats_result_received_as_present(tmp_path) -> None:
    """`create_pending_discovery_job_if_absent` must not duplicate in-flight work.

    With a `pending`-only existence check, a job whose result is sitting in the
    inbox reads as absent, so the scheduled enqueuer / profile reconciliation
    would create a second job for the same (profile, keyword) while the first is
    still being applied.
    """

    repository = _repository(tmp_path)
    first = repository.create_pending_discovery_job_if_absent(
        tenant_id=TENANT_ID,
        profile_id=PROFILE_ID,
        profile_type="custom",
        keyword="dedupe-me",
    )
    assert first.created is True

    with repository._engine.begin() as connection:  # simulate the agent submitting
        connection.execute(
            text(
                "UPDATE discovery_jobs SET job_status = 'result_received' "
                "WHERE id = :job_id"
            ),
            {"job_id": first.job.id},
        )

    second = repository.create_pending_discovery_job_if_absent(
        tenant_id=TENANT_ID,
        profile_id=PROFILE_ID,
        profile_type="custom",
        keyword="dedupe-me",
    )

    assert second.created is False, "a duplicate job was enqueued for in-flight work"
    assert second.job.id == first.job.id


def test_enqueue_if_absent_still_creates_after_terminal_status(tmp_path) -> None:
    """Positive control: a finished job must NOT block a fresh enqueue."""

    repository = _repository(tmp_path)
    first = repository.create_pending_discovery_job_if_absent(
        tenant_id=TENANT_ID,
        profile_id=PROFILE_ID,
        profile_type="custom",
        keyword="finished",
    )
    with repository._engine.begin() as connection:
        connection.execute(
            text("UPDATE discovery_jobs SET job_status = 'dispatched' WHERE id = :j"),
            {"j": first.job.id},
        )

    second = repository.create_pending_discovery_job_if_absent(
        tenant_id=TENANT_ID,
        profile_id=PROFILE_ID,
        profile_type="custom",
        keyword="finished",
    )
    assert second.created is True
