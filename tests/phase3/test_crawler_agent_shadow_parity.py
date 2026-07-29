"""U8c acceptance tests: shadow dual-report and parity comparison.

Shadow mode observes a real crawl without disturbing it. The Mac executes an
ordinary **legacy** discovery job and, while still holding that job's claim,
additionally reports the agent result envelope it *would* have sent. That envelope
is recorded and compared against what the legacy path durably wrote for the same
run. One crawl, two reports, no extra load on e-GP.

The load-bearing property is negative: **the shadow report must not consume the
legacy claim.** The naive implementation reuses the primary path, which transitions
the job to `result_received` and clears its lease — actively breaking the crawl it
was meant to observe. `test_shadow_result_does_not_consume_the_legacy_claim` is the
gate on that.

Real PostgreSQL throughout: the acceptance guard takes a row lock, which SQLite
cannot model.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from psycopg import connect
from psycopg.errors import CheckViolation
import pytest

from egp_shared_types.enums import AgentDeliveryMode


REPO_ROOT = Path(__file__).resolve().parents[2]
MIGRATIONS_DIR = REPO_ROOT / "packages/db/src/migrations"

DISCOVERABLE_STATUS = "ประกาศเชิญชวน"


@pytest.fixture(scope="module")
def migrated_database_url() -> str:
    from egp_db.dev_postgres import TempPostgresCluster, postgres_binaries_available

    if not postgres_binaries_available():
        pytest.skip("PostgreSQL binaries are required for the U8c shadow tests")

    from egp_db.migration_runner import apply_migrations

    with TempPostgresCluster() as cluster:
        cluster.create_database("egp_u8c_shadow")
        database_url = cluster.database_url("egp_u8c_shadow")
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
    from egp_db.repositories.crawler_agent_repo import create_crawler_agent_repository

    return create_crawler_agent_repository(database_url=migrated_database_url)


def _now() -> datetime:
    return datetime.now(UTC)


def _seed_legacy_claim(database_url: str) -> tuple[str, str, str]:
    """Seed a LEGACY job that is claimed and running. Returns (tenant, job, token)."""

    tenant_id, profile_id, job_id = str(uuid4()), str(uuid4()), str(uuid4())
    claim_token = str(uuid4())
    with connect(database_url) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO tenants (id, name, slug) VALUES (%s, 'U8c', %s)",
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
                     next_attempt_at, execution_backend, job_status,
                     claim_token, lease_expires_at, processing_started_at)
                VALUES (%s, %s, %s, 'custom', 'ครุภัณฑ์', NOW(), 'legacy', 'pending',
                        %s, NOW() + INTERVAL '10 minutes', NOW())
                """,
                (job_id, tenant_id, profile_id, claim_token),
            )
        connection.commit()
    return tenant_id, job_id, claim_token


def _seed_run_with_projects(
    database_url: str, *, tenant_id: str, project_names: list[str]
) -> tuple[str, list[dict]]:
    """Create a crawl run whose discover tasks durably recorded `project_names`.

    Mirrors what the discovery workflow writes: one succeeded `discover` task per
    project, with the project id in `result_json` (the `project_id` COLUMN is not
    populated by `mark_task_finished`, which is why the oracle reads the json).
    """

    from egp_crawler_core.canonical_id import generate_canonical_id

    run_id = str(uuid4())
    entries: list[dict] = []
    with connect(database_url) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO crawl_runs (id, tenant_id, trigger_type, status, started_at)
                VALUES (%s, %s, 'manual', 'succeeded', NOW())
                """,
                (run_id, tenant_id),
            )
            for name in project_names:
                project_id = str(uuid4())
                canonical = generate_canonical_id(
                    project_number=None,
                    organization_name="กรมตัวอย่าง",
                    project_name=name,
                    proposal_submission_date=None,
                    budget_amount=None,
                )
                cursor.execute(
                    """
                    INSERT INTO projects
                        (id, tenant_id, canonical_project_id, project_name,
                         organization_name, project_state, first_seen_at,
                         last_seen_at, last_changed_at)
                    VALUES (%s, %s, %s, %s, 'กรมตัวอย่าง', 'discovered',
                            NOW(), NOW(), NOW())
                    """,
                    (project_id, tenant_id, canonical, name),
                )
                cursor.execute(
                    """
                    INSERT INTO crawl_tasks
                        (id, run_id, task_type, status, result_json)
                    VALUES (%s, %s, 'discover', 'succeeded', %s)
                    """,
                    (str(uuid4()), run_id, f'{{"project_id": "{project_id}"}}'),
                )
                entries.append(
                    {
                        "run_id": run_id,
                        "keyword": "ครุภัณฑ์",
                        "project_name": name,
                        "organization_name": "กรมตัวอย่าง",
                        "source_status_text": DISCOVERABLE_STATUS,
                    }
                )
        connection.commit()
    return run_id, entries


def _job_row(database_url: str, job_id: str) -> dict:
    with connect(database_url) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT job_status, claim_token, lease_expires_at, "
                "processing_started_at, attempt_count "
                "FROM discovery_jobs WHERE id = %s",
                (job_id,),
            )
            row = cursor.fetchone()
    return {
        "job_status": row[0],
        "claim_token": str(row[1]) if row[1] else None,
        "lease_expires_at": row[2],
        "processing_started_at": row[3],
        "attempt_count": row[4],
    }


# ----------------------------------------------------------------------
# migration 036
# ----------------------------------------------------------------------


def test_migration_036_defaults_existing_rows_to_primary(
    migrated_database_url: str, repository
) -> None:
    """Rows accepted by the U7b contract only ever applied, so the default must
    preserve that meaning rather than silently reclassify history as shadow."""

    tenant_id, job_id, claim_token = _seed_legacy_claim(migrated_database_url)
    with connect(migrated_database_url) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO crawler_agent_results
                    (id, tenant_id, job_id, claim_token, contract_version,
                     idempotency_key, envelope, envelope_sha256, inbox_status,
                     next_attempt_at, received_at, updated_at)
                VALUES (%s, %s, %s, %s, 'v1', 'k', '{}'::jsonb, 's', 'pending',
                        NOW(), NOW(), NOW())
                """,
                (str(uuid4()), tenant_id, job_id, claim_token),
            )
            cursor.execute("SELECT delivery_mode FROM crawler_agent_results")
            assert cursor.fetchone()[0] == "primary"
        connection.commit()


def test_migration_036_rejects_an_unknown_delivery_mode(
    migrated_database_url: str,
) -> None:
    tenant_id, job_id, claim_token = _seed_legacy_claim(migrated_database_url)
    with connect(migrated_database_url) as connection:
        with connection.cursor() as cursor:
            with pytest.raises(CheckViolation):
                cursor.execute(
                    """
                    INSERT INTO crawler_agent_results
                        (id, tenant_id, job_id, claim_token, contract_version,
                         idempotency_key, envelope, envelope_sha256, inbox_status,
                         next_attempt_at, received_at, updated_at, delivery_mode)
                    VALUES (%s, %s, %s, %s, 'v1', 'k', '{}'::jsonb, 's', 'pending',
                            NOW(), NOW(), NOW(), 'telepathy')
                    """,
                    (str(uuid4()), tenant_id, job_id, claim_token),
                )


def test_migration_036_forbids_a_parity_verdict_on_a_primary_row(
    migrated_database_url: str,
) -> None:
    """Primary applies, it does not compare. A row with both would mean the
    processor's delivery-mode branch had gone wrong, so the database refuses it."""

    tenant_id, job_id, claim_token = _seed_legacy_claim(migrated_database_url)
    with connect(migrated_database_url) as connection:
        with connection.cursor() as cursor:
            with pytest.raises(CheckViolation):
                cursor.execute(
                    """
                    INSERT INTO crawler_agent_results
                        (id, tenant_id, job_id, claim_token, contract_version,
                         idempotency_key, envelope, envelope_sha256, inbox_status,
                         next_attempt_at, received_at, updated_at,
                         delivery_mode, parity_verdict)
                    VALUES (%s, %s, %s, %s, 'v1', 'k', '{}'::jsonb, 's', 'pending',
                            NOW(), NOW(), NOW(), 'primary', 'match')
                    """,
                    (str(uuid4()), tenant_id, job_id, claim_token),
                )


# ----------------------------------------------------------------------
# the load-bearing property
# ----------------------------------------------------------------------


def test_shadow_result_does_not_consume_the_legacy_claim(
    migrated_database_url: str, repository
) -> None:
    """The gate on the whole slice.

    The naive implementation reuses the primary path, which transitions the job to
    `result_received` and clears its claim and lease — actively breaking the live
    crawl it was supposed to observe. Every job column is snapshotted, not just
    the status.
    """

    tenant_id, job_id, claim_token = _seed_legacy_claim(migrated_database_url)
    before = _job_row(migrated_database_url, job_id)

    submission = repository.record_result_envelope(
        tenant_id=tenant_id,
        job_id=job_id,
        claim_token=claim_token,
        idempotency_key="shadow-1",
        contract_version="v1",
        envelope={"kind": "discovery", "payload": {"projects": []}},
        delivery_mode=AgentDeliveryMode.SHADOW.value,
    )

    assert submission.inbox_status == "pending"
    assert _job_row(migrated_database_url, job_id) == before


def test_shadow_result_is_rejected_when_the_legacy_claim_is_not_live(
    migrated_database_url: str, repository
) -> None:
    """Negative pair for the test above.

    NOTE on non-vacuity: the primary path also rejects an expired lease, so this
    would pass for the wrong reason against the old code. It is made meaningful by
    mutation — removing the shadow guard read makes exactly this test fail — and by
    asserting that NO inbox row is written.
    """

    from egp_db.repositories.crawler_agent_repo import StaleAgentClaimError

    tenant_id, job_id, claim_token = _seed_legacy_claim(migrated_database_url)
    with connect(migrated_database_url) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "UPDATE discovery_jobs SET lease_expires_at = NOW() - INTERVAL '1 minute' "
                "WHERE id = %s",
                (job_id,),
            )
        connection.commit()

    with pytest.raises(StaleAgentClaimError):
        repository.record_result_envelope(
            tenant_id=tenant_id,
            job_id=job_id,
            claim_token=claim_token,
            idempotency_key="shadow-stale",
            contract_version="v1",
            envelope={"kind": "discovery", "payload": {"projects": []}},
            delivery_mode=AgentDeliveryMode.SHADOW.value,
        )

    with connect(migrated_database_url) as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT COUNT(*) FROM crawler_agent_results")
            assert cursor.fetchone()[0] == 0


def test_the_same_envelope_cannot_be_replayed_under_a_different_mode(
    migrated_database_url: str, repository
) -> None:
    """Identical bytes offered as an observation and as a real write are different
    requests. Replaying one as the other is how a shadow rollout starts applying."""

    from egp_db.repositories.crawler_agent_repo import IdempotencyConflictError

    tenant_id, job_id, claim_token = _seed_legacy_claim(migrated_database_url)
    envelope = {"kind": "discovery", "payload": {"projects": []}}
    repository.record_result_envelope(
        tenant_id=tenant_id,
        job_id=job_id,
        claim_token=claim_token,
        idempotency_key="mode-clash",
        contract_version="v1",
        envelope=envelope,
        delivery_mode=AgentDeliveryMode.SHADOW.value,
    )
    with pytest.raises(IdempotencyConflictError):
        repository.record_result_envelope(
            tenant_id=tenant_id,
            job_id=job_id,
            claim_token=claim_token,
            idempotency_key="mode-clash",
            contract_version="v1",
            envelope=envelope,
            delivery_mode=AgentDeliveryMode.PRIMARY.value,
        )


def test_the_service_derives_the_delivery_mode_from_the_protocol() -> None:
    """The caller must never choose. `/internal/worker/*` carries one global token,
    so a caller-supplied mode would let any holder submit `primary` during shadow."""

    from egp_api.services.crawler_agent_service import CrawlerAgentService

    assert CrawlerAgentService(repository=object(), protocol="shadow").delivery_mode == (
        "shadow"
    )
    assert CrawlerAgentService(repository=object(), protocol="primary").delivery_mode == (
        "primary"
    )


# ----------------------------------------------------------------------
# the parity oracle and comparison
# ----------------------------------------------------------------------


def test_the_parity_oracle_reads_durable_task_evidence(
    migrated_database_url: str, repository
) -> None:
    """`crawl_tasks.result_json` is the only complete per-run ledger: status events
    are suppressed when the signature is unchanged, and `projects.last_run_id` is
    overwritten by any later run."""

    tenant_id, _job_id, _token = _seed_legacy_claim(migrated_database_url)
    run_id, _entries = _seed_run_with_projects(
        migrated_database_url, tenant_id=tenant_id, project_names=["ก", "ข"]
    )

    identities = repository.list_run_discovered_project_identities(
        tenant_id=tenant_id, run_id=run_id
    )
    assert len(identities) == 2


def test_the_parity_oracle_is_tenant_scoped(
    migrated_database_url: str, repository
) -> None:
    """`crawl_tasks` has no tenant column; scoping comes from the owning run."""

    tenant_id, _job, _token = _seed_legacy_claim(migrated_database_url)
    other_tenant_id, _job2, _token2 = _seed_legacy_claim(migrated_database_url)
    run_id, _entries = _seed_run_with_projects(
        migrated_database_url, tenant_id=tenant_id, project_names=["ก"]
    )

    assert (
        repository.list_run_discovered_project_identities(
            tenant_id=other_tenant_id, run_id=run_id
        )
        == set()
    )


def _drain_shadow(repository, project_ingest_service=None):
    from egp_api.executors.crawler_agent_results import CrawlerAgentInboxProcessor

    class _MustNotApply:
        def ingest_discovered_project(self, *, event):  # pragma: no cover
            raise AssertionError("a shadow row must never be applied")

        def ingest_status_update_event(self, *, event):  # pragma: no cover
            raise AssertionError("a shadow row must never be applied")

    processor = CrawlerAgentInboxProcessor(
        repository=repository,
        project_ingest_service=project_ingest_service or _MustNotApply(),
        processor_id="shadow-processor",
    )
    return processor.process_once()


def _verdict(database_url: str) -> tuple[str, dict]:
    import json as _json

    with connect(database_url) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT parity_verdict, parity_detail, inbox_status "
                "FROM crawler_agent_results"
            )
            verdict, detail, status = cursor.fetchone()
    if isinstance(detail, str):
        detail = _json.loads(detail)
    return verdict, {"detail": detail, "inbox_status": status}


def test_a_matching_shadow_envelope_is_compared_and_never_applied(
    migrated_database_url: str, repository
) -> None:
    tenant_id, job_id, claim_token = _seed_legacy_claim(migrated_database_url)
    _run_id, entries = _seed_run_with_projects(
        migrated_database_url, tenant_id=tenant_id, project_names=["ก", "ข"]
    )
    repository.record_result_envelope(
        tenant_id=tenant_id,
        job_id=job_id,
        claim_token=claim_token,
        idempotency_key="shadow-match",
        contract_version="v1",
        envelope={"kind": "discovery", "payload": {"projects": entries}},
        delivery_mode=AgentDeliveryMode.SHADOW.value,
    )

    before = _job_row(migrated_database_url, job_id)
    outcome = _drain_shadow(repository)

    assert outcome.applied
    verdict, extra = _verdict(migrated_database_url)
    assert verdict == "match"
    assert extra["detail"]["missing_count"] == 0
    assert extra["detail"]["extra_count"] == 0
    # The legacy job is untouched by the comparison too.
    assert _job_row(migrated_database_url, job_id) == before


def test_a_shadow_envelope_missing_a_project_reports_mismatch(
    migrated_database_url: str, repository
) -> None:
    """Control for the test above: without it, an "always match" implementation
    passes. Same counts on both sides would also pass a counts-only comparison, so
    the identities themselves are what differ here."""

    tenant_id, job_id, claim_token = _seed_legacy_claim(migrated_database_url)
    _run_id, entries = _seed_run_with_projects(
        migrated_database_url, tenant_id=tenant_id, project_names=["ก", "ข"]
    )
    repository.record_result_envelope(
        tenant_id=tenant_id,
        job_id=job_id,
        claim_token=claim_token,
        idempotency_key="shadow-mismatch",
        contract_version="v1",
        envelope={"kind": "discovery", "payload": {"projects": entries[:1]}},
        delivery_mode=AgentDeliveryMode.SHADOW.value,
    )

    assert _drain_shadow(repository).applied
    verdict, extra = _verdict(migrated_database_url)
    assert verdict == "mismatch"
    assert extra["detail"]["missing_count"] == 1


def test_equal_counts_with_different_identities_still_mismatch(
    migrated_database_url: str, repository
) -> None:
    """Kills a counts-only comparison, which would call this a match."""

    tenant_id, job_id, claim_token = _seed_legacy_claim(migrated_database_url)
    run_id, entries = _seed_run_with_projects(
        migrated_database_url, tenant_id=tenant_id, project_names=["ก", "ข"]
    )
    swapped = [dict(entries[0]), dict(entries[1])]
    swapped[1]["project_name"] = "โครงการที่ไม่มีอยู่จริง"
    repository.record_result_envelope(
        tenant_id=tenant_id,
        job_id=job_id,
        claim_token=claim_token,
        idempotency_key="shadow-swapped",
        contract_version="v1",
        envelope={"kind": "discovery", "payload": {"projects": swapped}},
        delivery_mode=AgentDeliveryMode.SHADOW.value,
    )
    del run_id

    assert _drain_shadow(repository).applied
    verdict, extra = _verdict(migrated_database_url)
    assert verdict == "mismatch"
    assert extra["detail"]["envelope_count"] == 2
    assert extra["detail"]["durable_count"] == 2
    assert extra["detail"]["missing_count"] == 1
    assert extra["detail"]["extra_count"] == 1


def test_an_envelope_without_a_single_run_reference_is_unavailable_not_mismatch(
    migrated_database_url: str, repository
) -> None:
    """`unavailable` is not a failure — conflating "could not resolve the evidence"
    with "the outputs differ" would manufacture false alarms during rollout."""

    tenant_id, job_id, claim_token = _seed_legacy_claim(migrated_database_url)
    repository.record_result_envelope(
        tenant_id=tenant_id,
        job_id=job_id,
        claim_token=claim_token,
        idempotency_key="shadow-norun",
        contract_version="v1",
        envelope={
            "kind": "discovery",
            "payload": {"projects": [{"project_name": "ไม่มี run_id"}]},
        },
        delivery_mode=AgentDeliveryMode.SHADOW.value,
    )

    assert _drain_shadow(repository).applied
    verdict, _extra = _verdict(migrated_database_url)
    assert verdict == "unavailable"


def test_delivery_mode_is_decided_at_acceptance_not_at_processing(
    migrated_database_url: str, repository
) -> None:
    """Pins the design, not the code shape.

    A row accepted while the protocol was `shadow` must stay an observation even if
    the operator flips to `primary` before it drains. An implementation that read
    the live protocol at processing time would apply it — and the whole point of
    stamping the mode on the row is that this cannot happen.
    """

    tenant_id, job_id, claim_token = _seed_legacy_claim(migrated_database_url)
    _run_id, entries = _seed_run_with_projects(
        migrated_database_url, tenant_id=tenant_id, project_names=["ก"]
    )
    repository.record_result_envelope(
        tenant_id=tenant_id,
        job_id=job_id,
        claim_token=claim_token,
        idempotency_key="shadow-stamped",
        contract_version="v1",
        envelope={"kind": "discovery", "payload": {"projects": entries}},
        delivery_mode=AgentDeliveryMode.SHADOW.value,
    )

    # The processor here is configured exactly as a `primary` deployment would be.
    # `_MustNotApply` raises if anything tries to apply.
    outcome = _drain_shadow(repository)
    assert outcome.applied
    assert _verdict(migrated_database_url)[0] == "match"
