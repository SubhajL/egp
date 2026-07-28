"""U7c: the crawler-agent result-inbox processor.

Real PostgreSQL: the behaviours are transactional (processor lease, reclaim of a
crashed consumer, the job leaving `result_received` only when the row reaches a
terminal state).
"""

from __future__ import annotations

from pathlib import Path
import time
from uuid import uuid4

from psycopg import connect
import pytest

from egp_api.executors.crawler_agent_results import (
    CrawlerAgentInboxProcessor,
    PermanentApplyError,
    run_crawler_agent_inbox_loop,
)
from egp_db.dev_postgres import TempPostgresCluster, postgres_binaries_available


REPO_ROOT = Path(__file__).resolve().parents[2]
MIGRATIONS_DIR = REPO_ROOT / "packages/db/src/migrations"


class RecordingIngestService:
    """Stands in for ProjectIngestService; records what the processor applied."""

    def __init__(self, *, fail_with: Exception | None = None) -> None:
        self.discovered: list = []
        self.status_updates: list = []
        self._fail_with = fail_with

    def ingest_discovered_project(self, *, event):
        if self._fail_with is not None:
            raise self._fail_with
        self.discovered.append(event)
        return event

    def ingest_status_update_event(self, *, event):
        if self._fail_with is not None:
            raise self._fail_with
        self.status_updates.append(event)
        return event


@pytest.fixture(scope="module")
def migrated_database_url() -> str:
    if not postgres_binaries_available():
        pytest.skip("PostgreSQL binaries are required for the U7c processor tests")

    from egp_db.migration_runner import apply_migrations

    with TempPostgresCluster() as cluster:
        cluster.create_database("egp_u7c_processor")
        database_url = cluster.database_url("egp_u7c_processor")
        apply_migrations(database_url=database_url, migrations_dir=MIGRATIONS_DIR)
        yield database_url


@pytest.fixture(autouse=True)
def _isolate_inbox(migrated_database_url: str):
    """Reset seeded rows between tests.

    The cluster is module-scoped and both the job claimer and the inbox drain are
    global (each takes the oldest due row), so without this a test would routinely
    process another test's row and its assertions would be meaningless.

    Deleting tenants is enough: `crawl_profiles`, `discovery_jobs` and
    `crawler_agent_results` all cascade from it.
    """

    with connect(migrated_database_url) as connection:
        with connection.cursor() as cursor:
            cursor.execute("DELETE FROM tenants")
        connection.commit()
    yield


@pytest.fixture
def repository(migrated_database_url: str):
    from egp_db.repositories.crawler_agent_repo import create_crawler_agent_repository

    return create_crawler_agent_repository(database_url=migrated_database_url)


def _seed_submitted_result(repository, database_url: str, envelope: dict) -> tuple[str, str]:
    """Seed an agent job, claim it, and submit `envelope`. Returns (job_id, result_id)."""

    tenant_id, profile_id, job_id = str(uuid4()), str(uuid4()), str(uuid4())
    with connect(database_url) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO tenants (id, name, slug) VALUES (%s, 'U7c', %s)",
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
    claim = None
    for _ in range(50):
        candidate = repository.claim_agent_job(agent_id="mac-1")
        if candidate is None:
            break
        if candidate.job_id == job_id:
            claim = candidate
            break
    assert claim is not None, "failed to claim the seeded job"
    submission = repository.record_result_envelope(
        tenant_id=claim.tenant_id,
        job_id=claim.job_id,
        claim_token=claim.claim_token,
        idempotency_key=f"d-{uuid4()}",
        contract_version="v1",
        envelope=envelope,
    )
    return job_id, submission.result_id


def _row(database_url: str, result_id: str) -> tuple[str, int, str | None]:
    with connect(database_url) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT inbox_status, attempt_count, last_error_code "
                "FROM crawler_agent_results WHERE id = %s",
                (result_id,),
            )
            return cursor.fetchone()


def _job_status(database_url: str, job_id: str) -> str:
    with connect(database_url) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT job_status FROM discovery_jobs WHERE id = %s", (job_id,)
            )
            return cursor.fetchone()[0]


def _processor(repository, ingest) -> CrawlerAgentInboxProcessor:
    return CrawlerAgentInboxProcessor(
        repository=repository, project_ingest_service=ingest, backoff_seconds=60.0
    )


# ---------------------------------------------------------------------------


def test_discovery_result_is_applied_and_releases_the_job(
    repository, migrated_database_url
) -> None:
    """The job must leave `result_received`, or it stays in-flight forever."""

    job_id, result_id = _seed_submitted_result(
        repository,
        migrated_database_url,
        {
            "kind": "discovery",
            "payload": {
                "projects": [
                    {
                        "keyword": "ครุภัณฑ์",
                        "project_name": "โครงการทดสอบ",
                        "organization_name": "กรมตัวอย่าง",
                        "source_status_text": "ประกาศเชิญชวน",
                    }
                ]
            },
        },
    )
    assert _job_status(migrated_database_url, job_id) == "result_received"
    ingest = RecordingIngestService()

    outcome = _processor(repository, ingest).process_once()

    assert outcome.applied is True
    assert len(ingest.discovered) == 1
    assert ingest.discovered[0].project_name == "โครงการทดสอบ"
    assert _row(migrated_database_url, result_id)[0] == "applied"
    assert _job_status(migrated_database_url, job_id) == "dispatched"


def test_tenant_comes_from_the_inbox_row_not_the_envelope(
    repository, migrated_database_url
) -> None:
    """An envelope-supplied tenant must never be able to redirect a write."""

    job_id, _result_id = _seed_submitted_result(
        repository,
        migrated_database_url,
        {
            "kind": "discovery",
            "payload": {
                "projects": [
                    {
                        "tenant_id": "99999999-9999-9999-9999-999999999999",
                        "project_name": "ผู้บุกรุก",
                        "organization_name": "องค์กร",
                    }
                ]
            },
        },
    )
    ingest = RecordingIngestService()

    _processor(repository, ingest).process_once()

    assert ingest.discovered
    with connect(migrated_database_url) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT tenant_id FROM discovery_jobs WHERE id = %s", (job_id,)
            )
            owning_tenant = str(cursor.fetchone()[0])
    # Equality, not merely "not the attacker": the write must land on the tenant
    # that owns the claimed job.
    assert ingest.discovered[0].tenant_id == owning_tenant
    assert ingest.discovered[0].tenant_id != "99999999-9999-9999-9999-999999999999"


def test_document_envelope_is_rejected_not_half_applied(
    repository, migrated_database_url
) -> None:
    """Document ingestion needs file bytes; scoped artifact upload is U9."""

    job_id, result_id = _seed_submitted_result(
        repository,
        migrated_database_url,
        {"kind": "document", "payload": {"filename": "tor.pdf"}},
    )
    ingest = RecordingIngestService()

    outcome = _processor(repository, ingest).process_once()

    assert outcome.rejected is True
    assert not ingest.discovered
    status, _attempts, error_code = _row(migrated_database_url, result_id)
    assert status == "rejected"
    assert error_code == "apply_failed_permanent"
    assert _job_status(migrated_database_url, job_id) == "failed"


def test_unknown_envelope_kind_is_rejected(repository, migrated_database_url) -> None:
    _job_id, result_id = _seed_submitted_result(
        repository, migrated_database_url, {"kind": "telepathy", "payload": {}}
    )

    outcome = _processor(repository, RecordingIngestService()).process_once()

    assert outcome.rejected is True
    assert _row(migrated_database_url, result_id)[0] == "rejected"


def test_transient_failure_requeues_with_backoff(
    repository, migrated_database_url
) -> None:
    """A retry must bump the attempt count and NOT apply anything."""

    job_id, result_id = _seed_submitted_result(
        repository,
        migrated_database_url,
        {
            "kind": "discovery",
            "payload": {
                "projects": [{"project_name": "ชั่วคราว", "organization_name": "อ"}]
            },
        },
    )
    ingest = RecordingIngestService(fail_with=RuntimeError("database blinked"))

    outcome = _processor(repository, ingest).process_once()

    assert outcome.retried is True
    assert outcome.applied is False
    status, attempts, error_code = _row(migrated_database_url, result_id)
    assert status == "failed"
    assert attempts == 1
    assert error_code == "apply_failed_transient"
    # A zero backoff would pass the assertions above while hot-looping the row.
    with connect(migrated_database_url) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT next_attempt_at > NOW() FROM crawler_agent_results "
                "WHERE id = %s",
                (result_id,),
            )
            assert cursor.fetchone()[0] is True, "retry was not actually delayed"
    # The job stays in-flight until the result reaches a terminal state.
    assert _job_status(migrated_database_url, job_id) == "result_received"


def test_retries_are_bounded_then_rejected(repository, migrated_database_url) -> None:
    """Otherwise a permanently-failing row would loop forever."""

    _job_id, result_id = _seed_submitted_result(
        repository,
        migrated_database_url,
        {
            "kind": "discovery",
            "payload": {"projects": [{"project_name": "ล้มเหลว", "organization_name": "อ"}]},
        },
    )
    processor = CrawlerAgentInboxProcessor(
        repository=repository,
        project_ingest_service=RecordingIngestService(fail_with=RuntimeError("boom")),
        backoff_seconds=0.01,
        max_attempts=3,
    )

    statuses = []
    for _ in range(4):
        processor.process_once()
        statuses.append(_row(migrated_database_url, result_id)[0])
        # A retry schedules next_attempt_at slightly in the future; without this
        # wait the row is not yet due and the loop would make no progress.
        time.sleep(0.05)

    assert statuses[-1] == "rejected", statuses
    assert _row(migrated_database_url, result_id)[2] == "apply_failed_permanent"


def test_crashed_processor_lease_is_reclaimed(
    repository, migrated_database_url
) -> None:
    """A row stuck in `processing` with an expired lease must return to the queue."""

    _job_id, result_id = _seed_submitted_result(
        repository,
        migrated_database_url,
        {"kind": "discovery", "payload": {"projects": []}},
    )
    # Simulate a consumer that took the row and died.
    with connect(migrated_database_url) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "UPDATE crawler_agent_results SET inbox_status='processing', "
                "processor_token=%s, processing_expires_at=NOW() - INTERVAL '1 hour' "
                "WHERE id = %s",
                (str(uuid4()), result_id),
            )

    processor = _processor(repository, RecordingIngestService())
    outcome = processor.process_once()

    assert outcome.reclaimed >= 1
    status, attempts, _error = _row(migrated_database_url, result_id)
    # Terminal, not "processing" — allowing `processing` would let broken
    # terminalization pass.
    assert status == "applied", status
    # The reclaim consumed a retry attempt, so a row that repeatedly hard-kills
    # the process cannot cycle forever.
    assert attempts >= 1


def test_loop_stops_and_reports_applied_count(
    repository, migrated_database_url
) -> None:
    _seed_submitted_result(
        repository,
        migrated_database_url,
        {
            "kind": "discovery",
            "payload": {"projects": [{"project_name": "ลูป", "organization_name": "อ"}]},
        },
    )
    ingest = RecordingIngestService()

    applied = run_crawler_agent_inbox_loop(
        processor=_processor(repository, ingest),
        max_iterations=3,
        sleeper=lambda _seconds: None,
    )

    assert applied >= 1


def test_permanent_apply_error_is_exported() -> None:
    """The processor's own classification must stay importable for U8."""

    assert issubclass(PermanentApplyError, RuntimeError)


def test_a_malformed_entry_does_not_partially_apply_the_batch(
    repository, migrated_database_url
) -> None:
    """Validation must complete before ANY project is persisted.

    Applying while validating would persist the leading valid projects, then hit
    the malformed entry, reject the whole inbox row, and lose the trailing ones —
    permanently, because a rejected row is never retried.
    """

    _job_id, result_id = _seed_submitted_result(
        repository,
        migrated_database_url,
        {
            "kind": "discovery",
            "payload": {
                "projects": [
                    {"project_name": "ถูกต้อง", "organization_name": "อ"},
                    "this entry is not an object",
                    {"project_name": "ท้ายสุด", "organization_name": "อ"},
                ]
            },
        },
    )
    ingest = RecordingIngestService()

    outcome = _processor(repository, ingest).process_once()

    assert outcome.rejected is True
    assert ingest.discovered == [], "a malformed batch was partially applied"
    assert _row(migrated_database_url, result_id)[0] == "rejected"


def test_an_expired_lease_cannot_terminalize_the_row(
    repository, migrated_database_url
) -> None:
    """Matching the token is not enough — the lease must still be live.

    Between expiry and reclaim the previous owner still holds a matching token and
    would otherwise be able to mark a row it no longer owns.
    """

    _job_id, result_id = _seed_submitted_result(
        repository,
        migrated_database_url,
        {"kind": "discovery", "payload": {"projects": []}},
    )
    token = str(uuid4())
    with connect(migrated_database_url) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "UPDATE crawler_agent_results SET inbox_status='processing', "
                "processor_token=%s, processing_expires_at=NOW() - INTERVAL '1 hour' "
                "WHERE id = %s",
                (token, result_id),
            )
        connection.commit()

    assert (
        repository.mark_result_applied(result_id=result_id, processor_token=token)
        is False
    )
    assert _row(migrated_database_url, result_id)[0] == "processing"
