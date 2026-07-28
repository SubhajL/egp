"""U7b endpoints: the dark gate AND proof the enabled path actually works.

The existing auth matrix in `tests/phase1/test_internal_worker_auth.py` accepts any
allow-listed status, and it already treats 404 as a valid authenticated result. So
a permanently-404 endpoint would satisfy both the matrix and the route inventory
while doing nothing. This module is the compensating evidence: it turns the
protocol on and drives claim → renew → result → replay → conflict end to end.
"""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient
from psycopg import connect
import pytest

from egp_db.dev_postgres import TempPostgresCluster, postgres_binaries_available
from tests.support.app_factory import create_test_app


REPO_ROOT = Path(__file__).resolve().parents[2]
MIGRATIONS_DIR = REPO_ROOT / "packages/db/src/migrations"
WORKER_TOKEN = "u7b-worker-token"
AUTH = {"x-egp-worker-token": WORKER_TOKEN}


@pytest.fixture(scope="module")
def migrated_database_url() -> str:
    if not postgres_binaries_available():
        pytest.skip("PostgreSQL binaries are required for the U7b endpoint tests")

    from egp_db.migration_runner import apply_migrations

    with TempPostgresCluster() as cluster:
        cluster.create_database("egp_u7b_endpoints")
        database_url = cluster.database_url("egp_u7b_endpoints")
        apply_migrations(database_url=database_url, migrations_dir=MIGRATIONS_DIR)
        yield database_url


def _client(database_url: str, tmp_path: Path, *, protocol: str) -> TestClient:
    app = create_test_app(
        artifact_root=tmp_path,
        database_url=database_url,
        auth_required=True,
        jwt_secret="u7b-jwt",
        internal_worker_token=WORKER_TOKEN,
        background_runtime_mode="external",
        crawler_agent_protocol=protocol,
        bootstrap_schema=False,
    )
    return TestClient(app)


def _seed_agent_job(database_url: str) -> tuple[str, str]:
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
                VALUES (%s, %s, %s, 'custom', 'ครุภัณฑ์',
                        NOW() - INTERVAL '1 minute', 'agent')
                """,
                (job_id, tenant_id, profile_id),
            )
    return tenant_id, job_id


def _drain_agent_queue(client: TestClient) -> None:
    """Claim until empty.

    `claim_agent_job` is deliberately global and returns the oldest due job, and
    the PostgreSQL cluster here is module-scoped, so jobs seeded by earlier tests
    would otherwise be handed to a later one.
    """

    for _ in range(50):
        if (
            client.post(
                "/internal/worker/agent/v1/claim",
                json={"agent_id": "drain"},
                headers=AUTH,
            ).status_code
            == 204
        ):
            return
    raise AssertionError("agent queue did not drain")


# ---------------------------------------------------------------------------
# dark by default
# ---------------------------------------------------------------------------


def test_disabled_protocol_returns_404_and_writes_nothing(
    migrated_database_url, tmp_path
) -> None:
    client = _client(migrated_database_url, tmp_path, protocol="off")
    _tenant_id, job_id = _seed_agent_job(migrated_database_url)

    response = client.post(
        "/internal/worker/agent/v1/claim",
        json={"agent_id": "mac-1"},
        headers=AUTH,
    )

    assert response.status_code == 404
    with connect(migrated_database_url) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT job_status, claim_token FROM discovery_jobs WHERE id = %s",
                (job_id,),
            )
            job_status, claim_token = cursor.fetchone()
    assert job_status == "pending"
    assert claim_token is None


def test_disabled_protocol_rejects_before_body_validation(
    migrated_database_url, tmp_path
) -> None:
    """A malformed body against a disabled endpoint must still be 404, not 422.

    The gate is a router dependency precisely so it runs before FastAPI validates
    the payload; otherwise a disabled feature would still tell a caller what shape
    its body should have been.
    """

    client = _client(migrated_database_url, tmp_path, protocol="off")

    response = client.post(
        "/internal/worker/agent/v1/result",
        json={"totally": "wrong"},
        headers=AUTH,
    )

    assert response.status_code == 404


# ---------------------------------------------------------------------------
# enabled path — the non-vacuous evidence
# ---------------------------------------------------------------------------


def test_enabled_claim_renew_result_flow(migrated_database_url, tmp_path) -> None:
    client = _client(migrated_database_url, tmp_path, protocol="primary")
    _drain_agent_queue(client)
    tenant_id, job_id = _seed_agent_job(migrated_database_url)

    claimed = client.post(
        "/internal/worker/agent/v1/claim",
        json={"agent_id": "mac-1", "lease_seconds": 600},
        headers=AUTH,
    )
    assert claimed.status_code == 200, claimed.text
    claim = claimed.json()
    assert claim["job_id"] == job_id
    assert claim["tenant_id"] == tenant_id
    assert claim["contract_version"] == "v1"
    assert claim["keyword"] == "ครุภัณฑ์"

    renewed = client.post(
        "/internal/worker/agent/v1/renew",
        json={
            "tenant_id": claim["tenant_id"],
            "job_id": claim["job_id"],
            "claim_token": claim["claim_token"],
            "lease_seconds": 900,
        },
        headers=AUTH,
    )
    assert renewed.status_code == 200, renewed.text
    assert renewed.json()["lease_expires_at"] > claim["lease_expires_at"]

    body = {
        "tenant_id": claim["tenant_id"],
        "job_id": claim["job_id"],
        "claim_token": claim["claim_token"],
        "idempotency_key": "delivery-1",
        "contract_version": "v1",
        "envelope": {"kind": "discovery", "payload": {"projects_seen": 2}},
    }
    created = client.post("/internal/worker/agent/v1/result", json=body, headers=AUTH)
    assert created.status_code == 201, created.text
    assert created.json()["replayed"] is False

    replay = client.post("/internal/worker/agent/v1/result", json=body, headers=AUTH)
    assert replay.status_code == 200
    assert replay.json()["replayed"] is True
    assert replay.json()["result_id"] == created.json()["result_id"]

    conflicting = dict(body)
    conflicting["envelope"] = {"kind": "discovery", "payload": {"projects_seen": 999}}
    assert (
        client.post(
            "/internal/worker/agent/v1/result", json=conflicting, headers=AUTH
        ).status_code
        == 409
    )


def test_enabled_claim_returns_204_when_no_agent_work(
    migrated_database_url, tmp_path
) -> None:
    """An empty queue is not an error — the agent should back off, not retry-storm."""

    client = _client(migrated_database_url, tmp_path, protocol="primary")
    _drain_agent_queue(client)

    response = client.post(
        "/internal/worker/agent/v1/claim", json={"agent_id": "mac-1"}, headers=AUTH
    )

    assert response.status_code == 204


def test_enabled_renew_with_unknown_claim_token_is_409(
    migrated_database_url, tmp_path
) -> None:
    client = _client(migrated_database_url, tmp_path, protocol="primary")
    tenant_id, job_id = _seed_agent_job(migrated_database_url)

    response = client.post(
        "/internal/worker/agent/v1/renew",
        json={
            "tenant_id": tenant_id,
            "job_id": job_id,
            "claim_token": str(uuid4()),
        },
        headers=AUTH,
    )

    assert response.status_code == 409


def test_enabled_unsupported_contract_version_is_422(
    migrated_database_url, tmp_path
) -> None:
    client = _client(migrated_database_url, tmp_path, protocol="primary")
    _drain_agent_queue(client)
    tenant_id, job_id = _seed_agent_job(migrated_database_url)
    claim = client.post(
        "/internal/worker/agent/v1/claim",
        json={"agent_id": "mac-1"},
        headers=AUTH,
    ).json()

    response = client.post(
        "/internal/worker/agent/v1/result",
        json={
            "tenant_id": claim["tenant_id"],
            "job_id": claim["job_id"],
            "claim_token": claim["claim_token"],
            "idempotency_key": "bad-version",
            "contract_version": "v99",
            "envelope": {"kind": "discovery", "payload": {}},
        },
        headers=AUTH,
    )

    assert response.status_code == 422
    assert tenant_id and job_id  # seeded fixtures used by the claim above
