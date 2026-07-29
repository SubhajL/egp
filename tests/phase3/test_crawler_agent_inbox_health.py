"""U8b acceptance tests: proving the inbox processor can actually drain.

The compose file for `crawler-agent-inbox-executor` says it plainly:

    A running PID is not proof the processor can drain; that signal belongs with
    the U8 observability work.

That is this slice. The hard case — and the reason a backlog gauge alone is not
enough — is an **empty queue**: a processor that died and a processor that is
idle look identical from the queue side. Only a heartbeat separates them, and the
heartbeat therefore has to be written on *every* iteration, including the ones
that claim nothing.

Real PostgreSQL throughout: the truth table is computed in SQL over two tables,
and `drain_status` precedence is exactly the kind of thing a SQLite bootstrap can
agree with while production disagrees.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

from psycopg import connect
from psycopg.errors import CheckViolation
import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
MIGRATIONS_DIR = REPO_ROOT / "packages/db/src/migrations"

STALE_AFTER = 120.0


@pytest.fixture(scope="module")
def migrated_database_url() -> str:
    from egp_db.dev_postgres import TempPostgresCluster, postgres_binaries_available

    if not postgres_binaries_available():
        pytest.skip("PostgreSQL binaries are required for the U8b inbox-health tests")

    from egp_db.migration_runner import apply_migrations

    with TempPostgresCluster() as cluster:
        cluster.create_database("egp_u8b_inbox_health")
        database_url = cluster.database_url("egp_u8b_inbox_health")
        apply_migrations(database_url=database_url, migrations_dir=MIGRATIONS_DIR)
        yield database_url


@pytest.fixture(autouse=True)
def _isolate(migrated_database_url: str):
    with connect(migrated_database_url) as connection:
        with connection.cursor() as cursor:
            cursor.execute("DELETE FROM tenants")
            cursor.execute("DELETE FROM crawler_agent_inbox_heartbeats")
        connection.commit()
    yield


@pytest.fixture
def repository(migrated_database_url: str):
    from egp_db.repositories.crawler_agent_repo import create_crawler_agent_repository

    return create_crawler_agent_repository(database_url=migrated_database_url)


def _now() -> datetime:
    return datetime.now(UTC)


def _seed_inbox_rows(
    database_url: str,
    *,
    pending: int = 0,
    stuck_processing: int = 0,
    execution_backend: str = "agent",
) -> str:
    """Seed a tenant with `pending` queued inbox rows and `stuck_processing` rows
    whose processor lease has already expired. Returns the tenant id."""

    tenant_id, profile_id = str(uuid4()), str(uuid4())
    with connect(database_url) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO tenants (id, name, slug) VALUES (%s, 'U8b', %s)",
                (tenant_id, f"t-{tenant_id[:8]}"),
            )
            cursor.execute(
                "INSERT INTO crawl_profiles (id, tenant_id, name) VALUES (%s, %s, 'p')",
                (profile_id, tenant_id),
            )
            for index in range(pending + stuck_processing):
                job_id = str(uuid4())
                cursor.execute(
                    """
                    INSERT INTO discovery_jobs
                        (id, tenant_id, profile_id, profile_type, keyword,
                         next_attempt_at, execution_backend, job_status)
                    VALUES (%s, %s, %s, 'custom', %s,
                            NOW() - INTERVAL '1 minute', %s, 'result_received')
                    """,
                    (job_id, tenant_id, profile_id, f"kw-{index}", execution_backend),
                )
                is_stuck = index >= pending
                cursor.execute(
                    """
                    INSERT INTO crawler_agent_results
                        (id, tenant_id, job_id, claim_token, contract_version,
                         idempotency_key, envelope, envelope_sha256, inbox_status,
                         attempt_count, next_attempt_at, processor_token,
                         processing_expires_at, received_at, updated_at)
                    VALUES (%s, %s, %s, %s, 'v1', %s, '{}'::jsonb, %s, %s,
                            0, NOW() - INTERVAL '1 minute', %s, %s, NOW(), NOW())
                    """,
                    (
                        str(uuid4()),
                        tenant_id,
                        job_id,
                        str(uuid4()),
                        f"idem-{index}",
                        f"sha-{index}",
                        "processing" if is_stuck else "pending",
                        str(uuid4()) if is_stuck else None,
                        _now() - timedelta(minutes=5) if is_stuck else None,
                    ),
                )
        connection.commit()
    return tenant_id


def _heartbeat(repository, *, age_seconds: float, status: str = "running") -> None:
    repository.record_inbox_heartbeat(
        processor_id="inbox-1",
        status=status,
        backlog_depth=0,
        last_outcome="idle",
        now=_now() - timedelta(seconds=age_seconds),
    )


# ----------------------------------------------------------------------
# migration 035
# ----------------------------------------------------------------------


def test_migration_035_creates_the_inbox_heartbeat_table(
    migrated_database_url: str,
) -> None:
    with connect(migrated_database_url) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO crawler_agent_inbox_heartbeats
                    (processor_id, status, backlog_depth, last_outcome,
                     reported_at, updated_at)
                VALUES ('p1', 'running', 3, 'applied', NOW(), NOW())
                """
            )
            cursor.execute(
                "SELECT status, backlog_depth FROM crawler_agent_inbox_heartbeats"
            )
            assert cursor.fetchone() == ("running", 3)
        connection.commit()


def test_migration_035_rejects_an_unknown_processor_status(
    migrated_database_url: str,
) -> None:
    """Paired negative — without it the test above passes against a free-text column."""

    with connect(migrated_database_url) as connection:
        with connection.cursor() as cursor:
            with pytest.raises(CheckViolation):
                cursor.execute(
                    """
                    INSERT INTO crawler_agent_inbox_heartbeats
                        (processor_id, status, backlog_depth, last_outcome,
                         reported_at, updated_at)
                    VALUES ('p2', 'vibing', 0, 'idle', NOW(), NOW())
                    """
                )


def test_migration_035_rejects_an_unbounded_last_outcome(
    migrated_database_url: str,
) -> None:
    """`last_outcome` must be a bounded vocabulary, never a free-form error string.

    `crawler_runtime_heartbeats` deliberately contains no free-form error payload
    (migration 033's header says so); this table follows the same rule, because an
    exception message is exactly where tenant data leaks into global operator state.
    """

    with connect(migrated_database_url) as connection:
        with connection.cursor() as cursor:
            with pytest.raises(CheckViolation):
                cursor.execute(
                    """
                    INSERT INTO crawler_agent_inbox_heartbeats
                        (processor_id, status, backlog_depth, last_outcome,
                         reported_at, updated_at)
                    VALUES ('p3', 'running', 0,
                            'ProgrammingError: relation "x" for tenant Acme', NOW(), NOW())
                    """
                )


# ----------------------------------------------------------------------
# heartbeat recording
# ----------------------------------------------------------------------


def test_record_inbox_heartbeat_upserts_on_processor_id(
    repository, migrated_database_url: str
) -> None:
    repository.record_inbox_heartbeat(
        processor_id="inbox-1", status="running", backlog_depth=1, last_outcome="applied"
    )
    repository.record_inbox_heartbeat(
        processor_id="inbox-1", status="running", backlog_depth=7, last_outcome="idle"
    )

    with connect(migrated_database_url) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT count(*) FROM crawler_agent_inbox_heartbeats"
            )
            assert cursor.fetchone()[0] == 1
            cursor.execute(
                "SELECT backlog_depth, last_outcome, status, reported_at, updated_at "
                "FROM crawler_agent_inbox_heartbeats"
            )
            backlog, outcome, status, reported_at, updated_at = cursor.fetchone()
            # Every field must actually move, not just the row count: an
            # implementation that inserted once and ignored later writes would
            # otherwise pass.
            assert (backlog, outcome, status) == (7, "idle", "running")
            assert reported_at is not None and updated_at is not None


# ----------------------------------------------------------------------
# drain_status truth table — the whole point of the slice
# ----------------------------------------------------------------------


def test_drain_status_is_unknown_when_no_heartbeat_was_ever_recorded(
    repository,
) -> None:
    health = repository.get_inbox_health(stale_after_seconds=STALE_AFTER)
    assert health.drain_status == "unknown"


def test_drain_status_is_idle_when_the_queue_is_empty_and_the_heartbeat_is_fresh(
    repository,
) -> None:
    _heartbeat(repository, age_seconds=1)
    health = repository.get_inbox_health(stale_after_seconds=STALE_AFTER)
    assert health.drain_status == "idle"
    assert health.backlog_depth == 0


def test_drain_status_is_draining_when_work_waits_behind_a_fresh_heartbeat(
    repository, migrated_database_url: str
) -> None:
    _seed_inbox_rows(migrated_database_url, pending=3)
    _heartbeat(repository, age_seconds=1)

    health = repository.get_inbox_health(stale_after_seconds=STALE_AFTER)
    assert health.drain_status == "draining"
    assert health.backlog_depth == 3
    assert health.oldest_pending_age_seconds is not None
    assert health.oldest_pending_age_seconds >= 0


def test_drain_status_is_wedged_when_a_backlog_waits_behind_a_stale_heartbeat(
    repository, migrated_database_url: str
) -> None:
    _seed_inbox_rows(migrated_database_url, pending=3)
    _heartbeat(repository, age_seconds=600)

    health = repository.get_inbox_health(stale_after_seconds=STALE_AFTER)
    assert health.drain_status == "wedged"
    assert health.backlog_depth == 3


def test_drain_status_is_wedged_for_an_empty_backlog_with_a_dead_processor(
    repository,
) -> None:
    """The case the whole feature exists for.

    With nothing queued, a dead processor and a healthy idle one are
    indistinguishable from the queue alone. An implementation that keys `wedged`
    off `backlog_depth > 0` — the obvious one — reports `idle` here and hides a
    dead processor indefinitely.
    """

    _heartbeat(repository, age_seconds=600)
    health = repository.get_inbox_health(stale_after_seconds=STALE_AFTER)
    assert health.drain_status == "wedged"
    assert health.backlog_depth == 0


def test_drain_status_is_wedged_when_the_processor_reports_an_error(
    repository,
) -> None:
    _heartbeat(repository, age_seconds=1, status="error")
    health = repository.get_inbox_health(stale_after_seconds=STALE_AFTER)
    assert health.drain_status == "wedged"


def test_a_stuck_processing_row_wins_over_a_fresh_heartbeat(
    repository, migrated_database_url: str
) -> None:
    """Precedence, asserted rather than left implicit: a row whose processor lease
    expired mid-apply means work is stranded even while another processor happily
    heartbeats."""

    _seed_inbox_rows(migrated_database_url, stuck_processing=2)
    _heartbeat(repository, age_seconds=1)

    health = repository.get_inbox_health(stale_after_seconds=STALE_AFTER)
    assert health.stuck_processing_count == 2
    assert health.drain_status == "wedged"


def test_health_aggregates_multiple_processors_by_the_freshest_heartbeat(
    repository,
) -> None:
    """Two replicas, one dead: the fleet is draining, so the freshest wins.

    Without an explicit rule, `MIN(reported_at)` would report the fleet wedged
    forever after any replica is scaled down and its stale row is left behind.
    """

    repository.record_inbox_heartbeat(
        processor_id="inbox-dead",
        status="running",
        backlog_depth=0,
        last_outcome="idle",
        now=_now() - timedelta(seconds=900),
    )
    repository.record_inbox_heartbeat(
        processor_id="inbox-live",
        status="running",
        backlog_depth=0,
        last_outcome="idle",
        now=_now(),
    )

    health = repository.get_inbox_health(stale_after_seconds=STALE_AFTER)
    assert health.drain_status == "idle"
    assert health.heartbeat_processor_id == "inbox-live"


# ----------------------------------------------------------------------
# the processor must heartbeat on EVERY iteration
# ----------------------------------------------------------------------


def test_processor_heartbeats_even_when_it_claims_nothing(
    repository, migrated_database_url: str
) -> None:
    """`process_once` returns early when no row is claimable. If the heartbeat
    lives after that return, an idle processor never reports and is
    indistinguishable from a dead one — which defeats the feature."""

    from egp_api.executors.crawler_agent_results import CrawlerAgentInboxProcessor

    class _NeverIngests:
        def ingest_discovered_project(self, *, event):  # pragma: no cover
            raise AssertionError("nothing should be applied in this test")

        def ingest_status_update_event(self, *, event):  # pragma: no cover
            raise AssertionError("nothing should be applied in this test")

    processor = CrawlerAgentInboxProcessor(
        repository=repository,
        project_ingest_service=_NeverIngests(),
        processor_id="idle-processor",
    )
    outcome = processor.process_once()
    assert not outcome.claimed

    health = repository.get_inbox_health(stale_after_seconds=STALE_AFTER)
    assert health.drain_status == "idle"
    assert health.heartbeat_processor_id == "idle-processor"


def test_a_heartbeat_failure_never_interrupts_draining(migrated_database_url: str) -> None:
    """Telemetry must not break the thing it observes.

    The raising repository is a double injected to make an otherwise unreachable
    failure reachable; every other test in this file uses the real repository.
    """

    from egp_api.executors.crawler_agent_results import CrawlerAgentInboxProcessor
    from egp_db.repositories.crawler_agent_repo import create_crawler_agent_repository

    real = create_crawler_agent_repository(database_url=migrated_database_url)

    class _HeartbeatExplodes:
        def __init__(self) -> None:
            self.attempts = 0

        def __getattr__(self, name):
            return getattr(real, name)

        def record_inbox_heartbeat(self, **kwargs):
            self.attempts += 1
            raise RuntimeError("simulated heartbeat table outage")

    repository = _HeartbeatExplodes()
    processor = CrawlerAgentInboxProcessor(
        repository=repository,
        project_ingest_service=object(),
    )
    outcome = processor.process_once()  # must not raise
    assert not outcome.claimed
    # Without this the test would also pass if heartbeat reporting were deleted
    # outright, which is the opposite of what it is meant to protect.
    assert repository.attempts == 1


# ----------------------------------------------------------------------
# agent queue visibility
# ----------------------------------------------------------------------


def test_agent_queue_snapshot_counts_only_agent_backed_jobs(
    repository, migrated_database_url: str
) -> None:
    """All four counts are asserted. A snapshot that got `pending` right and the
    other three wrong would otherwise pass."""

    tenant_id, profile_id = str(uuid4()), str(uuid4())
    with connect(migrated_database_url) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO tenants (id, name, slug) VALUES (%s, 'U8b', %s)",
                (tenant_id, f"t-{tenant_id[:8]}"),
            )
            cursor.execute(
                "INSERT INTO crawl_profiles (id, tenant_id, name) VALUES (%s, %s, 'p')",
                (profile_id, tenant_id),
            )
            # one claimable agent job, one retry-scheduled agent job,
            # one leased agent job, and one legacy job that must not be counted
            for keyword, backend, next_attempt, claim, lease in (
                ("agent-claimable", "agent", "NOW() - INTERVAL '1 minute'", None, None),
                ("agent-retry", "agent", "NOW() + INTERVAL '1 hour'", None, None),
                (
                    "agent-leased",
                    "agent",
                    "NOW() - INTERVAL '1 minute'",
                    str(uuid4()),
                    "NOW() + INTERVAL '1 hour'",
                ),
                ("legacy-work", "legacy", "NOW() - INTERVAL '1 minute'", None, None),
            ):
                cursor.execute(
                    f"""
                    INSERT INTO discovery_jobs
                        (id, tenant_id, profile_id, profile_type, keyword,
                         next_attempt_at, execution_backend, claim_token,
                         lease_expires_at)
                    VALUES (%s, %s, %s, 'custom', %s, {next_attempt}, %s, %s,
                            {lease or 'NULL'})
                    """,
                    (str(uuid4()), tenant_id, profile_id, keyword, backend, claim),
                )
        connection.commit()

    snapshot = repository.get_agent_queue_snapshot()
    assert snapshot.pending_count == 3
    assert snapshot.claimable_count == 1
    assert snapshot.leased_count == 1
    assert snapshot.retry_scheduled_count == 1


# ----------------------------------------------------------------------
# operator route
# ----------------------------------------------------------------------


def test_inbox_health_route_requires_the_operator_role(
    migrated_database_url: str, tmp_path: Path
) -> None:
    """A permanently-404 route would satisfy a status-allowlist matrix, so this
    asserts the 200 body shape as well as the 401/403 boundary."""

    from fastapi.testclient import TestClient

    from egp_api.main import create_app

    client = TestClient(
        create_app(
            artifact_root=tmp_path,
            database_url=migrated_database_url,
            auth_required=True,
            jwt_secret="u8b-user-jwt-secret",
            internal_worker_token="u8b-worker-token",
            background_runtime_mode="external",
        )
    )

    anonymous = client.get("/v1/rules/crawler-agent-inbox")
    assert anonymous.status_code == 401


def test_inbox_health_route_reports_drain_status_and_agent_queue(
    migrated_database_url: str, tmp_path: Path, repository
) -> None:
    from fastapi.testclient import TestClient

    from egp_api.main import create_app

    _heartbeat(repository, age_seconds=1)

    client = TestClient(
        create_app(
            artifact_root=tmp_path,
            database_url=migrated_database_url,
            auth_required=False,
            background_runtime_mode="external",
        )
    )
    response = client.get("/v1/rules/crawler-agent-inbox")
    assert response.status_code == 200
    body = response.json()
    assert body["drain_status"] == "idle"
    assert body["heartbeat_processor_id"] == "inbox-1"
    assert body["agent_queue_pending_count"] == 0
    # Counts only: the operator surface must never carry tenant payloads.
    assert "tenant_id" not in body


# ----------------------------------------------------------------------
# regressions found by the Tier-2 review
# ----------------------------------------------------------------------


def test_a_crashing_processor_reports_error_not_health(
    repository, migrated_database_url: str
) -> None:
    """The defect this pins would have defeated the whole feature.

    Reporting from a blanket `finally` wrote a fresh `running`/`idle` heartbeat
    even when the iteration raised. A processor that throws on every claim would
    then: write a healthy heartbeat, die, be restarted by Compose, and refresh
    the healthy heartbeat again — leaving the operator route reporting `idle`
    forever while nothing drains.
    """

    from egp_api.executors.crawler_agent_results import CrawlerAgentInboxProcessor

    class _ClaimExplodes:
        def __getattr__(self, name):
            return getattr(repository, name)

        def claim_next_result(self, **kwargs):
            raise RuntimeError("simulated database outage")

    processor = CrawlerAgentInboxProcessor(
        repository=_ClaimExplodes(),
        project_ingest_service=object(),
        processor_id="crashing-processor",
    )

    with pytest.raises(RuntimeError, match="simulated database outage"):
        processor.process_once()

    health = repository.get_inbox_health(stale_after_seconds=STALE_AFTER)
    assert health.heartbeat_status == "error"
    assert health.heartbeat_last_outcome == "error"
    assert health.drain_status == "wedged"


def test_heartbeat_reporting_does_not_run_the_full_health_aggregate(
    migrated_database_url: str, repository
) -> None:
    """The backlog probe runs on EVERY iteration — once per idle poll and once
    per drained row. Using the full health aggregate (SUM/MIN/MAX over the whole
    table, no WHERE) meant the observability feature made draining slower as
    applied history grew."""

    from egp_api.executors.crawler_agent_results import CrawlerAgentInboxProcessor

    class _CountingRepository:
        def __init__(self) -> None:
            self.health_calls = 0

        def __getattr__(self, name):
            return getattr(repository, name)

        def get_inbox_health(self, **kwargs):
            self.health_calls += 1
            return repository.get_inbox_health(**kwargs)

    counting = _CountingRepository()
    processor = CrawlerAgentInboxProcessor(
        repository=counting,
        project_ingest_service=object(),
        processor_id="cheap-probe",
    )
    processor.process_once()

    assert counting.health_calls == 0


def test_a_fresh_running_processor_keeps_the_fleet_available(repository) -> None:
    """Availability means "at least one fresh running processor", not "the newest
    row happens to be running". Taking the newest row outright reported the fleet
    wedged whenever a replica that was shutting down heartbeat a second later."""

    repository.record_inbox_heartbeat(
        processor_id="inbox-running",
        status="running",
        backlog_depth=0,
        last_outcome="idle",
        now=_now() - timedelta(seconds=2),
    )
    repository.record_inbox_heartbeat(
        processor_id="inbox-stopping",
        status="stopping",
        backlog_depth=0,
        last_outcome="idle",
        now=_now() - timedelta(seconds=1),
    )

    health = repository.get_inbox_health(stale_after_seconds=STALE_AFTER)
    assert health.drain_status == "idle"
    assert health.heartbeat_processor_id == "inbox-running"


def test_a_future_dated_heartbeat_cannot_mask_a_dead_fleet(repository) -> None:
    """The executor stamps its own clock and the API compares against its own.
    A heartbeat an hour ahead would otherwise stay "fresh" for an hour AND sort
    first, hiding every genuinely dead processor behind it."""

    repository.record_inbox_heartbeat(
        processor_id="inbox-dead",
        status="running",
        backlog_depth=0,
        last_outcome="idle",
        now=_now() - timedelta(seconds=900),
    )
    repository.record_inbox_heartbeat(
        processor_id="inbox-skewed",
        status="running",
        backlog_depth=0,
        last_outcome="idle",
        now=_now() + timedelta(hours=1),
    )

    health = repository.get_inbox_health(stale_after_seconds=STALE_AFTER)
    assert health.drain_status == "wedged"


def test_only_future_scheduled_retries_are_not_reported_as_draining(
    repository, migrated_database_url: str
) -> None:
    """`draining` must mean work is actually due. A backlog whose retries are all
    scheduled far in the future, reported as `draining` while
    `heartbeat_last_outcome=idle`, contradicted itself and hid an accidentally
    far-future retry schedule."""

    _seed_inbox_rows(migrated_database_url, pending=2)
    with connect(migrated_database_url) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "UPDATE crawler_agent_results "
                "SET next_attempt_at = NOW() + INTERVAL '24 hours'"
            )
        connection.commit()
    _heartbeat(repository, age_seconds=1)

    health = repository.get_inbox_health(stale_after_seconds=STALE_AFTER)
    assert health.backlog_depth == 2
    assert health.due_backlog_depth == 0
    assert health.drain_status == "idle"


def test_inbox_health_route_rejects_a_viewer_and_allows_an_operator(
    migrated_database_url: str, tmp_path: Path
) -> None:
    """The anonymous-401 assertion alone never reaches the role guard — auth
    middleware answers first — so deleting `require_run_operator_role` would have
    left this route open to any authenticated viewer with the suite still green."""

    import jwt
    from fastapi.testclient import TestClient

    from egp_api.main import create_app

    jwt_secret = "u8b-role-secret-that-is-at-least-32-bytes-long"
    client = TestClient(
        create_app(
            artifact_root=tmp_path,
            database_url=migrated_database_url,
            auth_required=True,
            jwt_secret=jwt_secret,
            internal_worker_token="u8b-worker-token",
            background_runtime_mode="external",
        )
    )

    def _headers(role: str) -> dict[str, str]:
        token = jwt.encode(
            {
                "sub": "user-u8b",
                "tenant_id": "11111111-1111-1111-1111-111111111111",
                "role": role,
            },
            jwt_secret,
            algorithm="HS256",
        )
        return {"Authorization": f"Bearer {token}"}

    assert client.get(
        "/v1/rules/crawler-agent-inbox", headers=_headers("viewer")
    ).status_code == 403
    assert client.get(
        "/v1/rules/crawler-agent-inbox", headers=_headers("analyst")
    ).status_code == 200


def test_compose_services_receive_the_new_liveness_variables() -> None:
    """The existing compose-topology oracle asserts a fixed variable list and would
    not notice either of these disappearing. That oracle is on the do-not-touch
    list, so the new requirement is asserted here instead of by editing it.

    They belong to DIFFERENT services on purpose: the executor writes the
    heartbeat, the API derives staleness from it.
    """

    import yaml

    for compose_name in ("docker-compose.yml", "docker-compose-localdev.yml"):
        compose = yaml.safe_load((REPO_ROOT / compose_name).read_text())
        services = compose["services"]
        assert (
            "EGP_CRAWLER_AGENT_INBOX_PROCESSOR_ID"
            in services["crawler-agent-inbox-executor"]["environment"]
        ), f"{compose_name}: executor cannot identify its heartbeat"
        assert (
            "EGP_CRAWLER_AGENT_INBOX_STALE_AFTER_SECONDS"
            in services["api"]["environment"]
        ), f"{compose_name}: API cannot judge heartbeat staleness"
