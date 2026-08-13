"""U8e acceptance tests: the HTTPS agent client.

The client is the seam that lets the Mac crawler stop being a database client, so
two properties are structural rather than cosmetic:

* it must reach the control plane over **HTTPS only** — the internal worker token
  is a bearer credential with authority over every tenant's queue, so sending it
  in clear text hands that authority to anyone on the path; and
* it must **never import a database driver**, because U9 removes the Mac's DB and
  storage credentials on exactly that basis.

The round-trip test drives the real FastAPI app over httpx's ASGI transport against
a real PostgreSQL cluster — no mocked HTTP, no mocked repository. What it does not
prove is TLS itself, which is why the scheme check is asserted separately.
"""

from __future__ import annotations

import ast
from pathlib import Path
from uuid import uuid4

from psycopg import connect
import pytest

from tests.support.jwt_factory import TEST_JWT_AUDIENCE, TEST_JWT_ISSUER


REPO_ROOT = Path(__file__).resolve().parents[2]
MIGRATIONS_DIR = REPO_ROOT / "packages/db/src/migrations"
AGENT_CLIENT_PATH = (
    REPO_ROOT / "apps/worker/src/egp_worker/agent_client.py"
)
WORKER_TOKEN = "u8e-internal-worker-token"


@pytest.fixture(scope="module")
def migrated_database_url() -> str:
    from egp_db.dev_postgres import TempPostgresCluster, postgres_binaries_available

    if not postgres_binaries_available():
        pytest.skip("PostgreSQL binaries are required for the U8e client tests")

    from egp_db.migration_runner import apply_migrations

    with TempPostgresCluster() as cluster:
        cluster.create_database("egp_u8e_client")
        database_url = cluster.database_url("egp_u8e_client")
        apply_migrations(database_url=database_url, migrations_dir=MIGRATIONS_DIR)
        yield database_url


@pytest.fixture(autouse=True)
def _isolate(migrated_database_url: str):
    with connect(migrated_database_url) as connection:
        with connection.cursor() as cursor:
            cursor.execute("DELETE FROM tenants")
        connection.commit()
    yield


def _app_client(migrated_database_url: str, tmp_path: Path, *, protocol: str):
    from fastapi.testclient import TestClient

    from egp_api.main import create_app

    return TestClient(
        create_app(
            artifact_root=tmp_path,
            database_url=migrated_database_url,
            auth_required=True,
            jwt_secret="u8e-user-jwt-secret-at-least-32-bytes-long",
            jwt_issuer=TEST_JWT_ISSUER,
            jwt_audience=TEST_JWT_AUDIENCE,
            internal_worker_token=WORKER_TOKEN,
            background_runtime_mode="external",
            crawler_agent_protocol=protocol,
        )
    )


def _agent_client(transport, *, token: str = WORKER_TOKEN):
    from egp_worker.agent_client import CrawlerAgentApiClient

    return CrawlerAgentApiClient(
        base_url="http://testserver",
        worker_token=token,
        client=transport,
        # Loopback ASGI transport only; production construction refuses non-HTTPS.
        require_https=False,
    )


def _seed_agent_job(database_url: str) -> str:
    tenant_id, profile_id, job_id = str(uuid4()), str(uuid4()), str(uuid4())
    with connect(database_url) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO tenants (id, name, slug) VALUES (%s, 'U8e', %s)",
                (tenant_id, f"t-{tenant_id[:8]}"),
            )
            cursor.execute(
                "INSERT INTO crawl_profiles (id, tenant_id, name, execution_backend) "
                "VALUES (%s, %s, 'p', 'agent')",
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
        connection.commit()
    return tenant_id


# ----------------------------------------------------------------------
# structural guarantees
# ----------------------------------------------------------------------


def test_the_agent_client_never_reaches_a_database() -> None:
    """U9 removes the Mac's DB and storage credentials on the strength of this.

    An AST scan rather than a comment, because the guarantee is the point of the
    module and a stray convenience import would silently undo it.
    """

    tree = ast.parse(AGENT_CLIENT_PATH.read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)

    forbidden = {"egp_db", "sqlalchemy", "psycopg", "psycopg2", "asyncpg"}
    offenders = {
        name
        for name in imported
        if any(name == bad or name.startswith(f"{bad}.") for bad in forbidden)
    }
    assert not offenders, f"agent client must not import a database driver: {offenders}"


def test_the_agent_client_refuses_a_plaintext_base_url() -> None:
    """The worker token has authority over every tenant's queue; sending it in
    clear text hands that authority to anyone on the path."""

    from egp_worker.agent_client import CrawlerAgentApiClient

    with pytest.raises(ValueError, match="https"):
        CrawlerAgentApiClient(
            base_url="http://api.example.invalid", worker_token="t"
        )
    # And the https form is accepted, so the check is not simply always-raise.
    CrawlerAgentApiClient(base_url="https://api.example.invalid", worker_token="t")


# ----------------------------------------------------------------------
# failure-mode discrimination
# ----------------------------------------------------------------------


def test_a_disabled_protocol_is_distinguished_from_an_auth_failure(
    migrated_database_url: str, tmp_path: Path
) -> None:
    """An agent that cannot tell these apart will either hammer a switched-off
    endpoint forever or abandon work over a fixable credential problem."""

    from egp_worker.agent_client import AgentAuthError, AgentProtocolDisabledError

    with _app_client(migrated_database_url, tmp_path, protocol="off") as transport:
        with pytest.raises(AgentProtocolDisabledError):
            _agent_client(transport).claim(agent_id="canary")

    with _app_client(migrated_database_url, tmp_path, protocol="primary") as transport:
        with pytest.raises(AgentAuthError):
            _agent_client(transport, token="wrong-token").claim(agent_id="canary")


def test_a_transport_failure_is_retryable_and_typed(
    migrated_database_url: str, tmp_path: Path
) -> None:
    """The raising transport is a double injected to make an otherwise unreachable
    network fault reachable."""

    from egp_worker.agent_client import AgentTransportError

    class _Unreachable:
        def post(self, *args, **kwargs):
            raise OSError("connection refused")

    with pytest.raises(AgentTransportError):
        _agent_client(_Unreachable()).claim(agent_id="canary")


# ----------------------------------------------------------------------
# the round trip
# ----------------------------------------------------------------------


def test_claim_renew_and_submit_round_trip_over_http(
    migrated_database_url: str, tmp_path: Path
) -> None:
    tenant_id = _seed_agent_job(migrated_database_url)

    with _app_client(migrated_database_url, tmp_path, protocol="primary") as transport:
        client = _agent_client(transport)

        claim = client.claim(agent_id="canary", lease_seconds=120)
        assert claim is not None
        # The tenant is DERIVED by the API from the claimed row; the client never
        # supplies one, because the worker token carries no tenant identity.
        assert claim.tenant_id == tenant_id
        assert claim.keyword == "ครุภัณฑ์"

        renewed = client.renew(claim=claim, lease_seconds=300)
        assert renewed.job_id == claim.job_id
        assert renewed.lease_expires_at >= claim.lease_expires_at

        envelope = {"kind": "discovery", "payload": {"projects": []}}
        accepted = client.submit_result(
            claim=claim, idempotency_key="round-trip", envelope=envelope
        )
        assert not accepted.replayed

        replay = client.submit_result(
            claim=claim, idempotency_key="round-trip", envelope=envelope
        )
        assert replay.replayed
        assert replay.result_id == accepted.result_id


def test_claim_returns_none_when_no_agent_work_is_due(
    migrated_database_url: str, tmp_path: Path
) -> None:
    """Control for the round trip: a client that returned a claim unconditionally,
    or raised on 204, would pass the test above and fail here."""

    with _app_client(migrated_database_url, tmp_path, protocol="primary") as transport:
        assert _agent_client(transport).claim(agent_id="canary") is None


def test_a_stale_claim_is_reported_as_rejected_not_as_a_transport_fault(
    migrated_database_url: str, tmp_path: Path
) -> None:
    """Stale means "drop this work and re-claim". Misreporting it as a transport
    fault would make the agent retry a claim it can never satisfy."""

    from egp_shared_types.crawler_agent import AgentClaim
    from egp_worker.agent_client import AgentClaimRejectedError

    tenant_id = _seed_agent_job(migrated_database_url)
    bogus = AgentClaim(
        contract_version="v1",
        job_id=str(uuid4()),
        tenant_id=tenant_id,
        profile_id=str(uuid4()),
        profile_type="custom",
        keyword="ครุภัณฑ์",
        trigger_type="manual",
        live=True,
        recrawl_request_id=None,
        claim_token=str(uuid4()),
        lease_expires_at="2026-01-01T00:00:00+00:00",
        attempt_count=0,
    )
    with _app_client(migrated_database_url, tmp_path, protocol="primary") as transport:
        with pytest.raises(AgentClaimRejectedError):
            _agent_client(transport).renew(claim=bogus)
