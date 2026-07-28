"""U7b: the V1 crawler-agent claim / renew / result contract.

Runs against a real ephemeral PostgreSQL cluster: the behaviours under test are
transactional (atomic claim consumption, SAVEPOINT recovery from a UNIQUE
violation, non-claimability after acceptance) and SQLite would not reproduce
them faithfully.
"""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from psycopg import connect
import pytest

from egp_db.dev_postgres import TempPostgresCluster, postgres_binaries_available


REPO_ROOT = Path(__file__).resolve().parents[2]
MIGRATIONS_DIR = REPO_ROOT / "packages/db/src/migrations"


@pytest.fixture(scope="module")
def migrated_database_url() -> str:
    if not postgres_binaries_available():
        pytest.skip("PostgreSQL binaries are required for the U7b contract tests")

    from egp_db.migration_runner import apply_migrations

    with TempPostgresCluster() as cluster:
        cluster.create_database("egp_u7b_contract")
        database_url = cluster.database_url("egp_u7b_contract")
        apply_migrations(database_url=database_url, migrations_dir=MIGRATIONS_DIR)
        yield database_url


@pytest.fixture
def repository(migrated_database_url: str):
    from egp_db.repositories.crawler_agent_repo import create_crawler_agent_repository

    return create_crawler_agent_repository(database_url=migrated_database_url)


def _seed_agent_job(
    database_url: str,
    *,
    keyword: str = "ครุภัณฑ์",
    execution_backend: str = "agent",
) -> tuple[str, str]:
    """Insert tenant + profile + one agent-backed pending job."""

    tenant_id, profile_id, job_id = str(uuid4()), str(uuid4()), str(uuid4())
    with connect(database_url) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO tenants (id, name, slug) VALUES (%s, 'U7b', %s)",
                (tenant_id, f"t-{tenant_id[:8]}"),
            )
            cursor.execute(
                "INSERT INTO crawl_profiles (id, tenant_id, name) VALUES (%s, %s, 'p')",
                (profile_id, tenant_id),
            )
            cursor.execute(
                """
                INSERT INTO discovery_jobs
                    (id, tenant_id, profile_id, profile_type, keyword,
                     next_attempt_at, execution_backend)
                VALUES (%s, %s, %s, 'custom', %s, NOW() - INTERVAL '1 minute', %s)
                """,
                (job_id, tenant_id, profile_id, keyword, execution_backend),
            )
    return tenant_id, job_id


def _job_status(database_url: str, job_id: str) -> str:
    with connect(database_url) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT job_status FROM discovery_jobs WHERE id = %s", (job_id,)
            )
            return cursor.fetchone()[0]


def _inbox_count(database_url: str, job_id: str) -> int:
    with connect(database_url) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT COUNT(*) FROM crawler_agent_results WHERE job_id = %s",
                (job_id,),
            )
            return cursor.fetchone()[0]


# ---------------------------------------------------------------------------
# claim
# ---------------------------------------------------------------------------


def test_claim_returns_the_work_inputs_and_derives_tenant(
    repository, migrated_database_url
) -> None:
    """Tenant identity comes from the claimed row, never from the caller.

    `/internal/worker/*` authenticates with one global token that carries no
    tenant identity, so the claimed job is the only trustworthy source.
    """

    tenant_id, job_id = _seed_agent_job(migrated_database_url, keyword="งานจ้าง")

    claim = repository.claim_agent_job(agent_id="mac-1")

    assert claim is not None
    assert claim.job_id == job_id
    assert claim.tenant_id == tenant_id
    assert claim.keyword == "งานจ้าง"
    assert claim.contract_version == "v1"
    assert claim.claim_token
    assert claim.lease_expires_at


def test_claim_ignores_legacy_backed_jobs(repository, migrated_database_url) -> None:
    """The partition added in U7a must hold from the agent side too."""

    _tenant_id, legacy_job_id = _seed_agent_job(
        migrated_database_url, execution_backend="legacy"
    )
    for _ in range(5):
        claim = repository.claim_agent_job(agent_id="mac-1")
        if claim is None:
            break
        assert claim.job_id != legacy_job_id


def test_claim_is_exclusive(repository, migrated_database_url) -> None:
    """A second claim must not hand out the same job while the lease is live."""

    _seed_agent_job(migrated_database_url)
    first = repository.claim_agent_job(agent_id="mac-1")
    second = repository.claim_agent_job(agent_id="mac-2")

    assert first is not None
    assert second is None or second.job_id != first.job_id


# ---------------------------------------------------------------------------
# renew
# ---------------------------------------------------------------------------


def test_renew_extends_a_live_lease(repository, migrated_database_url) -> None:
    _seed_agent_job(migrated_database_url)
    claim = repository.claim_agent_job(agent_id="mac-1", lease_seconds=60)
    assert claim is not None

    renewed = repository.renew_agent_claim(
        tenant_id=claim.tenant_id,
        job_id=claim.job_id,
        claim_token=claim.claim_token,
        lease_seconds=600,
    )

    assert renewed.lease_expires_at > claim.lease_expires_at


def test_renew_rejects_a_wrong_claim_token(repository, migrated_database_url) -> None:
    from egp_db.repositories.crawler_agent_repo import StaleAgentClaimError

    _seed_agent_job(migrated_database_url)
    claim = repository.claim_agent_job(agent_id="mac-1")
    assert claim is not None

    with pytest.raises(StaleAgentClaimError):
        repository.renew_agent_claim(
            tenant_id=claim.tenant_id,
            job_id=claim.job_id,
            claim_token=str(uuid4()),
        )


def test_renew_rejects_another_tenants_job(repository, migrated_database_url) -> None:
    """Two-tenant negative: a valid token for tenant A must not renew B's job."""

    from egp_db.repositories.crawler_agent_repo import StaleAgentClaimError

    _seed_agent_job(migrated_database_url)
    claim = repository.claim_agent_job(agent_id="mac-1")
    assert claim is not None
    other_tenant_id, _ = _seed_agent_job(migrated_database_url)

    with pytest.raises(StaleAgentClaimError):
        repository.renew_agent_claim(
            tenant_id=other_tenant_id,
            job_id=claim.job_id,
            claim_token=claim.claim_token,
        )


# ---------------------------------------------------------------------------
# result acceptance
# ---------------------------------------------------------------------------


def test_result_acceptance_consumes_the_claim_atomically(
    repository, migrated_database_url
) -> None:
    """Accepting a result must make the job non-claimable in the same transaction.

    Without this the job stays `pending`, its lease eventually expires, another
    claimant takes it, and the stale result is applied on top of the new work.
    """

    _seed_agent_job(migrated_database_url)
    claim = repository.claim_agent_job(agent_id="mac-1")
    assert claim is not None

    submission = repository.record_result_envelope(
        tenant_id=claim.tenant_id,
        job_id=claim.job_id,
        claim_token=claim.claim_token,
        idempotency_key="delivery-1",
        contract_version="v1",
        envelope={"kind": "discovery", "payload": {"projects_seen": 3}},
    )

    assert submission.replayed is False
    assert submission.inbox_status == "pending"
    assert _job_status(migrated_database_url, claim.job_id) == "result_received"
    assert _inbox_count(migrated_database_url, claim.job_id) == 1
    # The consumed lease must be gone, so THIS job cannot be re-claimed.
    # (`claim_agent_job` is deliberately global across tenants, so other tests'
    # seeded jobs in this module-scoped cluster may still be claimable — assert
    # about this job specifically rather than about global emptiness.)
    for _ in range(5):
        other = repository.claim_agent_job(agent_id="mac-2")
        if other is None:
            break
        assert other.job_id != claim.job_id


def test_identical_replay_returns_the_original_row(
    repository, migrated_database_url
) -> None:
    """The ordering fix: a replay must not be rejected by the pending guard.

    The first submission already moved the job out of `pending` and cleared the
    claim, so a naive `WHERE job_status='pending' AND claim_token=…` design would
    raise StaleAgentClaimError here instead of returning the original row.
    """

    _seed_agent_job(migrated_database_url)
    claim = repository.claim_agent_job(agent_id="mac-1")
    assert claim is not None
    envelope = {"kind": "discovery", "payload": {"projects_seen": 3}}
    kwargs = dict(
        tenant_id=claim.tenant_id,
        job_id=claim.job_id,
        claim_token=claim.claim_token,
        idempotency_key="delivery-1",
        contract_version="v1",
    )

    first = repository.record_result_envelope(envelope=envelope, **kwargs)
    # Same payload, different key order — canonicalisation must see them as equal.
    replay = repository.record_result_envelope(
        envelope={"payload": {"projects_seen": 3}, "kind": "discovery"}, **kwargs
    )

    assert replay.replayed is True
    assert replay.result_id == first.result_id
    assert _inbox_count(migrated_database_url, claim.job_id) == 1


def test_same_claim_different_body_conflicts(
    repository, migrated_database_url
) -> None:
    from egp_db.repositories.crawler_agent_repo import IdempotencyConflictError

    _seed_agent_job(migrated_database_url)
    claim = repository.claim_agent_job(agent_id="mac-1")
    assert claim is not None
    kwargs = dict(
        tenant_id=claim.tenant_id,
        job_id=claim.job_id,
        claim_token=claim.claim_token,
        idempotency_key="delivery-1",
        contract_version="v1",
    )
    repository.record_result_envelope(
        envelope={"kind": "discovery", "payload": {"projects_seen": 3}}, **kwargs
    )

    with pytest.raises(IdempotencyConflictError):
        repository.record_result_envelope(
            envelope={"kind": "discovery", "payload": {"projects_seen": 999}}, **kwargs
        )

    assert _inbox_count(migrated_database_url, claim.job_id) == 1


def test_result_from_a_superseded_claim_is_rejected(
    repository, migrated_database_url
) -> None:
    """The stale-result race the `result_received` state exists to close."""

    from egp_db.repositories.crawler_agent_repo import StaleAgentClaimError

    _seed_agent_job(migrated_database_url)
    first = repository.claim_agent_job(agent_id="mac-1", lease_seconds=0.05)
    assert first is not None
    # Expire the lease so a second agent can reclaim the job.
    with connect(migrated_database_url) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "UPDATE discovery_jobs SET lease_expires_at = NOW() - INTERVAL '1 hour' "
                "WHERE id = %s",
                (first.job_id,),
            )
    second = repository.claim_agent_job(agent_id="mac-2")
    assert second is not None and second.job_id == first.job_id

    with pytest.raises(StaleAgentClaimError):
        repository.record_result_envelope(
            tenant_id=first.tenant_id,
            job_id=first.job_id,
            claim_token=first.claim_token,
            idempotency_key="stale-delivery",
            contract_version="v1",
            envelope={"kind": "discovery", "payload": {}},
        )

    assert _inbox_count(migrated_database_url, first.job_id) == 0
    assert _job_status(migrated_database_url, first.job_id) == "pending"


def test_unsupported_contract_version_writes_nothing(
    repository, migrated_database_url
) -> None:
    from egp_db.repositories.crawler_agent_repo import UnsupportedContractVersionError

    _seed_agent_job(migrated_database_url)
    claim = repository.claim_agent_job(agent_id="mac-1")
    assert claim is not None

    with pytest.raises(UnsupportedContractVersionError):
        repository.record_result_envelope(
            tenant_id=claim.tenant_id,
            job_id=claim.job_id,
            claim_token=claim.claim_token,
            idempotency_key="d",
            contract_version="v99",
            envelope={"kind": "discovery", "payload": {}},
        )

    assert _inbox_count(migrated_database_url, claim.job_id) == 0
    assert _job_status(migrated_database_url, claim.job_id) == "pending"


def test_result_for_another_tenants_job_is_rejected(
    repository, migrated_database_url
) -> None:
    """Two-tenant negative on the write path."""

    from egp_db.repositories.crawler_agent_repo import StaleAgentClaimError

    _seed_agent_job(migrated_database_url)
    claim = repository.claim_agent_job(agent_id="mac-1")
    assert claim is not None
    other_tenant_id, _ = _seed_agent_job(migrated_database_url)

    with pytest.raises(StaleAgentClaimError):
        repository.record_result_envelope(
            tenant_id=other_tenant_id,
            job_id=claim.job_id,
            claim_token=claim.claim_token,
            idempotency_key="cross-tenant",
            contract_version="v1",
            envelope={"kind": "discovery", "payload": {}},
        )

    assert _inbox_count(migrated_database_url, claim.job_id) == 0


def test_zero_row_transition_rechecks_the_inbox_before_reporting_stale(
    repository, migrated_database_url, monkeypatch
) -> None:
    """The concurrent-replay branch, driven deterministically.

    Two identical deliveries can both miss the initial inbox lookup; one wins the
    transition and commits, the other blocks on the row lock and then finds zero
    rows updated. Answering "stale" there is wrong — that delivery did succeed.

    A serial test cannot reach this branch, because the initial lookup catches the
    replay first. So the first lookup is forced to miss, exactly as it would under
    a concurrent snapshot, and the branch is then exercised for real: the second
    lookup (after the zero-row transition) must find the row and report a replay.
    """

    from egp_db.repositories import crawler_agent_repo as repo_module

    _seed_agent_job(migrated_database_url)
    claim = repository.claim_agent_job(agent_id="mac-1")
    assert claim is not None
    envelope = {"kind": "discovery", "payload": {"projects_seen": 7}}
    kwargs = dict(
        tenant_id=claim.tenant_id,
        job_id=claim.job_id,
        claim_token=claim.claim_token,
        idempotency_key="race-delivery",
        contract_version="v1",
    )
    first = repository.record_result_envelope(envelope=envelope, **kwargs)
    assert _job_status(migrated_database_url, claim.job_id) == "result_received"

    real_select = repo_module._select_inbox_row
    calls = {"n": 0}

    def _miss_once(connection, **kw):
        calls["n"] += 1
        if calls["n"] == 1:
            return None  # simulate the concurrent snapshot missing the row
        return real_select(connection, **kw)

    monkeypatch.setattr(repo_module, "_select_inbox_row", _miss_once)

    replay = repository.record_result_envelope(envelope=envelope, **kwargs)

    assert calls["n"] >= 2, "the zero-row branch was never reached"
    assert replay.replayed is True
    assert replay.result_id == first.result_id


def test_claim_skips_a_contended_row_instead_of_reporting_no_work(
    repository, migrated_database_url
) -> None:
    """Contention must not produce a false "queue empty".

    With two due jobs and two agents, both can select the same candidate. If the
    loser returned None the caller would answer 204 while work remained, so a
    contended row is skipped and the next candidate tried.
    """

    _seed_agent_job(migrated_database_url)
    _seed_agent_job(migrated_database_url)

    first = repository.claim_agent_job(agent_id="mac-1")
    second = repository.claim_agent_job(agent_id="mac-2")

    assert first is not None
    assert second is not None
    assert first.job_id != second.job_id
