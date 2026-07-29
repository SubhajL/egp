"""U8d acceptance tests: per-profile routing, the canary control and its rollback.

Until now nothing created `execution_backend='agent'` jobs, so the V1 agent
endpoints claimed nothing even when enabled. This is the switch.

Two properties dominate this file:

1. **Routing fails CLOSED.** `discovery_jobs.profile_id` has a plain FK to
   `crawl_profiles(id)` that is NOT composite with `tenant_id`. So tenant A quoting
   tenant B's profile satisfies both foreign keys independently — and a resolver
   that returned a default instead of raising would create a cross-tenant
   job/profile association. That is a tenant-isolation defect, not a nicety.
2. **A flip is not self-reversing.** Per-job backend is immutable and the in-flight
   dedupe is backend-agnostic, so setting a profile back to `legacy` strands the
   jobs already queued as `agent` AND blocks their replacements. The rollback has
   to reroute them explicitly.

Routing is resolved from the owning profile inside the insert transaction, so
every producer routes without naming `execution_backend` — which is what makes the
"no caller was forgotten" tests below meaningful.
"""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from psycopg import connect
from psycopg.errors import CheckViolation
import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
MIGRATIONS_DIR = REPO_ROOT / "packages/db/src/migrations"


@pytest.fixture(scope="module")
def migrated_database_url() -> str:
    from egp_db.dev_postgres import TempPostgresCluster, postgres_binaries_available

    if not postgres_binaries_available():
        pytest.skip("PostgreSQL binaries are required for the U8d routing tests")

    from egp_db.migration_runner import apply_migrations

    with TempPostgresCluster() as cluster:
        cluster.create_database("egp_u8d_routing")
        database_url = cluster.database_url("egp_u8d_routing")
        apply_migrations(database_url=database_url, migrations_dir=MIGRATIONS_DIR)
        yield database_url


@pytest.fixture(autouse=True)
def _isolate(migrated_database_url: str):
    with connect(migrated_database_url) as connection:
        with connection.cursor() as cursor:
            cursor.execute("DELETE FROM tenants")
        connection.commit()
    yield


@pytest.fixture
def repository(migrated_database_url: str):
    from egp_db.repositories.discovery_job_repo import create_discovery_job_repository

    return create_discovery_job_repository(database_url=migrated_database_url)


def _seed_profile(database_url: str, *, backend: str = "legacy") -> tuple[str, str]:
    tenant_id, profile_id = str(uuid4()), str(uuid4())
    with connect(database_url) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO tenants (id, name, slug) VALUES (%s, 'U8d', %s)",
                (tenant_id, f"t-{tenant_id[:8]}"),
            )
            cursor.execute(
                "INSERT INTO crawl_profiles (id, tenant_id, name, execution_backend) "
                "VALUES (%s, %s, 'p', %s)",
                (profile_id, tenant_id, backend),
            )
        connection.commit()
    return tenant_id, profile_id


def _backends(database_url: str, tenant_id: str) -> list[str]:
    with connect(database_url) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT execution_backend FROM discovery_jobs WHERE tenant_id = %s "
                "ORDER BY keyword",
                (tenant_id,),
            )
            return [row[0] for row in cursor.fetchall()]


# ----------------------------------------------------------------------
# migration 037
# ----------------------------------------------------------------------


def test_migration_037_defaults_profiles_to_legacy(migrated_database_url: str) -> None:
    """Adding the column must change nothing for existing profiles — every one of
    them keeps producing exactly the jobs it produces today."""

    tenant_id = str(uuid4())
    with connect(migrated_database_url) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO tenants (id, name, slug) VALUES (%s, 'U8d', %s)",
                (tenant_id, f"t-{tenant_id[:8]}"),
            )
            cursor.execute(
                "INSERT INTO crawl_profiles (id, tenant_id, name) VALUES (%s, %s, 'p')",
                (str(uuid4()), tenant_id),
            )
            cursor.execute("SELECT execution_backend FROM crawl_profiles")
            assert cursor.fetchone()[0] == "legacy"
        connection.commit()


def test_migration_037_rejects_an_unknown_profile_backend(
    migrated_database_url: str,
) -> None:
    """Paired negative: without it the test above passes against a free-text column."""

    tenant_id, profile_id = _seed_profile(migrated_database_url)
    with connect(migrated_database_url) as connection:
        with connection.cursor() as cursor:
            with pytest.raises(CheckViolation):
                cursor.execute(
                    "UPDATE crawl_profiles SET execution_backend = 'quantum' "
                    "WHERE id = %s",
                    (profile_id,),
                )
    del tenant_id


# ----------------------------------------------------------------------
# fail-closed routing (tenant isolation)
# ----------------------------------------------------------------------


def test_routing_refuses_a_profile_belonging_to_another_tenant(
    migrated_database_url: str, repository
) -> None:
    """The tenant-isolation gate.

    The FK on `discovery_jobs.profile_id` is not composite with `tenant_id`, so
    tenant A + tenant B's profile satisfies both FKs independently. A resolver that
    fell back to a default instead of raising would happily create a cross-tenant
    job/profile association — silently.
    """

    from egp_db.repositories.discovery_job_repo import ProfileNotFoundForTenantError

    tenant_a, _profile_a = _seed_profile(migrated_database_url)
    _tenant_b, profile_b = _seed_profile(migrated_database_url)

    with pytest.raises(ProfileNotFoundForTenantError):
        repository.create_pending_discovery_job_if_absent(
            tenant_id=tenant_a,
            profile_id=profile_b,
            profile_type="custom",
            keyword="ครุภัณฑ์",
        )

    assert _backends(migrated_database_url, tenant_a) == []


def test_routing_refuses_a_profile_that_does_not_exist(
    migrated_database_url: str, repository
) -> None:
    from egp_db.repositories.discovery_job_repo import ProfileNotFoundForTenantError

    tenant_id, _profile_id = _seed_profile(migrated_database_url)
    with pytest.raises(ProfileNotFoundForTenantError):
        repository.create_discovery_job(
            tenant_id=tenant_id,
            profile_id=str(uuid4()),
            profile_type="custom",
            keyword="ครุภัณฑ์",
        )


# ----------------------------------------------------------------------
# every producer routes
# ----------------------------------------------------------------------


def test_pending_enqueue_routes_to_the_agent_backend(
    migrated_database_url: str, repository
) -> None:
    tenant_id, profile_id = _seed_profile(migrated_database_url, backend="agent")
    repository.create_pending_discovery_job_if_absent(
        tenant_id=tenant_id, profile_id=profile_id, profile_type="custom", keyword="ก"
    )
    assert _backends(migrated_database_url, tenant_id) == ["agent"]


def test_pending_enqueue_stays_legacy_for_a_legacy_profile(
    migrated_database_url: str, repository
) -> None:
    """Control: without it, a resolver that always returned 'agent' would pass the
    test above."""

    tenant_id, profile_id = _seed_profile(migrated_database_url, backend="legacy")
    repository.create_pending_discovery_job_if_absent(
        tenant_id=tenant_id, profile_id=profile_id, profile_type="custom", keyword="ก"
    )
    assert _backends(migrated_database_url, tenant_id) == ["legacy"]


def test_create_discovery_job_routes_from_the_profile(
    migrated_database_url: str, repository
) -> None:
    tenant_id, profile_id = _seed_profile(migrated_database_url, backend="agent")
    repository.create_discovery_job(
        tenant_id=tenant_id, profile_id=profile_id, profile_type="custom", keyword="ก"
    )
    assert _backends(migrated_database_url, tenant_id) == ["agent"]


def test_rules_service_profile_created_jobs_route_from_the_profile(
    migrated_database_url: str, repository
) -> None:
    """One of the two `rules_service` producers the plan review flagged as
    uncovered. It never mentions `execution_backend`, so it can only route via the
    shared in-transaction resolver — which is exactly what makes this meaningful."""

    tenant_id, profile_id = _seed_profile(migrated_database_url, backend="agent")

    # Drive the repository call the rules service makes, with its arguments.
    repository.create_pending_discovery_job_if_absent(
        tenant_id=tenant_id,
        profile_id=profile_id,
        profile_type="custom",
        keyword="ก",
        trigger_type="profile_created",
        live=True,
    )
    assert _backends(migrated_database_url, tenant_id) == ["agent"]


def test_scheduled_enqueue_executor_routes_from_the_profile(
    migrated_database_url: str, repository
) -> None:
    """Drives the executor function, not the repository, so a caller that forgot
    to route would fail here even though the repository is correct."""

    from egp_api.executors.scheduled_discovery_enqueue import (
        enqueue_scheduled_discovery_jobs,
    )

    tenant_id, profile_id = _seed_profile(migrated_database_url, backend="agent")

    def _scheduler(*, database_url, job_runner, now=None):
        job_runner(
            {
                "tenant_id": tenant_id,
                "profile_id": profile_id,
                "profile": "custom",
                "keyword": "ก",
                "live": True,
            }
        )
        return {"due_job_count": 1}

    enqueue_scheduled_discovery_jobs(
        database_url=migrated_database_url,
        discovery_job_repository=repository,
        scheduler=_scheduler,
    )
    assert _backends(migrated_database_url, tenant_id) == ["agent"]


def test_an_agent_routed_job_is_claimable_only_by_the_agent_claimer(
    migrated_database_url: str, repository
) -> None:
    """The requirement that actually matters: routing has to change who executes."""

    from egp_db.repositories.crawler_agent_repo import create_crawler_agent_repository

    agent_tenant, agent_profile = _seed_profile(migrated_database_url, backend="agent")
    legacy_tenant, legacy_profile = _seed_profile(
        migrated_database_url, backend="legacy"
    )
    repository.create_pending_discovery_job_if_absent(
        tenant_id=agent_tenant,
        profile_id=agent_profile,
        profile_type="custom",
        keyword="agent-work",
    )
    repository.create_pending_discovery_job_if_absent(
        tenant_id=legacy_tenant,
        profile_id=legacy_profile,
        profile_type="custom",
        keyword="legacy-work",
    )

    legacy_claimed = repository.claim_pending_discovery_jobs(limit=10)
    assert [job.keyword for job in legacy_claimed] == ["legacy-work"]

    agent_repository = create_crawler_agent_repository(
        database_url=migrated_database_url
    )
    claim = agent_repository.claim_agent_job(agent_id="canary")
    assert claim is not None and claim.keyword == "agent-work"


# ----------------------------------------------------------------------
# the canary control and its rollback
# ----------------------------------------------------------------------


def _run_cli(argv: list[str]) -> int:
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "set_profile_execution_backend",
        REPO_ROOT / "scripts/set_profile_execution_backend.py",
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.main(argv)


def test_the_cli_refuses_to_change_routing_without_confirmation(
    migrated_database_url: str,
) -> None:
    tenant_id, profile_id = _seed_profile(migrated_database_url)
    assert (
        _run_cli(
            [
                "--database-url", migrated_database_url,
                "--tenant-id", tenant_id,
                "--profile-id", profile_id,
                "--backend", "agent",
            ]
        )
        == 2
    )
    with connect(migrated_database_url) as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT execution_backend FROM crawl_profiles")
            assert cursor.fetchone()[0] == "legacy"


def test_the_cli_dry_run_never_writes(migrated_database_url: str) -> None:
    tenant_id, profile_id = _seed_profile(migrated_database_url)
    assert (
        _run_cli(
            [
                "--database-url", migrated_database_url,
                "--tenant-id", tenant_id,
                "--profile-id", profile_id,
                "--backend", "agent",
                "--dry-run",
            ]
        )
        == 0
    )
    with connect(migrated_database_url) as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT execution_backend FROM crawl_profiles")
            assert cursor.fetchone()[0] == "legacy"


def test_the_cli_fails_loudly_on_an_unknown_profile(
    migrated_database_url: str,
) -> None:
    """A typo'd id during a rollback must not look like success."""

    tenant_id, _profile_id = _seed_profile(migrated_database_url)
    assert (
        _run_cli(
            [
                "--database-url", migrated_database_url,
                "--tenant-id", tenant_id,
                "--profile-id", str(uuid4()),
                "--backend", "legacy",
                "--confirm",
            ]
        )
        == 1
    )


def test_rolling_back_without_reroute_strands_already_queued_agent_jobs(
    migrated_database_url: str, repository
) -> None:
    """Pins the trap. Flipping the profile back is NOT enough on its own: the job
    already queued as `agent` keeps its backend, and — being in-flight — also
    blocks the dedupe from creating a legacy replacement. The keyword goes quiet."""

    tenant_id, profile_id = _seed_profile(migrated_database_url, backend="agent")
    repository.create_pending_discovery_job_if_absent(
        tenant_id=tenant_id, profile_id=profile_id, profile_type="custom", keyword="ก"
    )

    assert (
        _run_cli(
            [
                "--database-url", migrated_database_url,
                "--tenant-id", tenant_id,
                "--profile-id", profile_id,
                "--backend", "legacy",
                "--confirm",
            ]
        )
        == 0
    )

    # The queued job is still agent-owned...
    assert _backends(migrated_database_url, tenant_id) == ["agent"]
    # ...and the dedupe refuses to create a legacy replacement for it.
    result = repository.create_pending_discovery_job_if_absent(
        tenant_id=tenant_id, profile_id=profile_id, profile_type="custom", keyword="ก"
    )
    assert not result.created
    assert _backends(migrated_database_url, tenant_id) == ["agent"]


def test_rolling_back_with_reroute_recovers_the_queued_jobs(
    migrated_database_url: str, repository
) -> None:
    """The working rollback — the reason `--reroute-pending` exists."""

    tenant_id, profile_id = _seed_profile(migrated_database_url, backend="agent")
    repository.create_pending_discovery_job_if_absent(
        tenant_id=tenant_id, profile_id=profile_id, profile_type="custom", keyword="ก"
    )

    assert (
        _run_cli(
            [
                "--database-url", migrated_database_url,
                "--tenant-id", tenant_id,
                "--profile-id", profile_id,
                "--backend", "legacy",
                "--reroute-pending",
                "--confirm",
            ]
        )
        == 0
    )

    assert _backends(migrated_database_url, tenant_id) == ["legacy"]
    # And the legacy claimer can now see it again.
    assert [job.keyword for job in repository.claim_pending_discovery_jobs(limit=10)] == [
        "ก"
    ]


def test_the_reroute_leaves_a_claimed_job_alone(
    migrated_database_url: str, repository
) -> None:
    """Rewriting the backend of a job someone is already executing would strand its
    claimant, so mid-flight rows are reported rather than rewritten."""

    tenant_id, profile_id = _seed_profile(migrated_database_url, backend="agent")
    repository.create_pending_discovery_job_if_absent(
        tenant_id=tenant_id, profile_id=profile_id, profile_type="custom", keyword="ก"
    )
    with connect(migrated_database_url) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "UPDATE discovery_jobs SET claim_token = %s, "
                "lease_expires_at = NOW() + INTERVAL '10 minutes'",
                (str(uuid4()),),
            )
        connection.commit()

    assert (
        _run_cli(
            [
                "--database-url", migrated_database_url,
                "--tenant-id", tenant_id,
                "--profile-id", profile_id,
                "--backend", "legacy",
                "--reroute-pending",
                "--confirm",
            ]
        )
        == 0
    )
    assert _backends(migrated_database_url, tenant_id) == ["agent"]
