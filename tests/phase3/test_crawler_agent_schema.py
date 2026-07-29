"""U7a acceptance tests: crawler-agent schema and execution-backend routing.

These are the executable contract for migration ``034_crawler_agent_results.sql``.
They run against a real ephemeral PostgreSQL cluster because the invariants under
test are database constraints (composite foreign keys, CHECK vocabularies,
partial uniqueness) that SQLite's bootstrap path cannot express faithfully.

Design notes these tests pin down (see the U7 coding log for the Codex review that
forced them):

* ``execution_backend`` defaults to ``legacy`` so that adding the column cannot
  change the behaviour of the already-deployed external discovery executor.
* One accepted result per claim attempt: ``UNIQUE (tenant_id, job_id,
  claim_token)``. The transport ``idempotency_key`` plus a canonical envelope
  SHA-256 distinguish an identical replay from a conflicting one at the
  application layer; they are deliberately NOT part of the uniqueness key.
* The inbox references ``discovery_jobs`` by the composite ``(tenant_id,
  job_id)`` so a result can never be attached to another tenant's job.
* ``next_attempt_at`` is ``NOT NULL DEFAULT now()`` because a retry query of the
  form ``next_attempt_at <= now()`` silently skips NULL rows forever.
"""

from __future__ import annotations

from pathlib import Path
from shutil import copy2
from uuid import uuid4

from psycopg import connect
from psycopg.errors import (
    CheckViolation,
    ForeignKeyViolation,
    NotNullViolation,
    UniqueViolation,
)
import pytest

from egp_db.dev_postgres import TempPostgresCluster, postgres_binaries_available


REPO_ROOT = Path(__file__).resolve().parents[2]
MIGRATIONS_DIR = REPO_ROOT / "packages/db/src/migrations"


def _seed_job(cursor, *, execution_backend: str | None = None) -> tuple[str, str]:
    """Insert a tenant/profile/discovery_job triple; return (tenant_id, job_id)."""

    tenant_id = str(uuid4())
    profile_id = str(uuid4())
    job_id = str(uuid4())
    slug = f"t-{tenant_id[:8]}"
    cursor.execute(
        "INSERT INTO tenants (id, name, slug) VALUES (%s, %s, %s)",
        (tenant_id, "U7 tenant", slug),
    )
    cursor.execute(
        "INSERT INTO crawl_profiles (id, tenant_id, name) VALUES (%s, %s, %s)",
        (profile_id, tenant_id, "U7 profile"),
    )
    if execution_backend is None:
        cursor.execute(
            """
            INSERT INTO discovery_jobs
                (id, tenant_id, profile_id, profile_type, keyword, next_attempt_at)
            VALUES (%s, %s, %s, 'tor', 'ครุภัณฑ์', NOW())
            """,
            (job_id, tenant_id, profile_id),
        )
    else:
        cursor.execute(
            """
            INSERT INTO discovery_jobs
                (id, tenant_id, profile_id, profile_type, keyword, next_attempt_at,
                 execution_backend)
            VALUES (%s, %s, %s, 'tor', 'ครุภัณฑ์', NOW(), %s)
            """,
            (job_id, tenant_id, profile_id, execution_backend),
        )
    return tenant_id, job_id


def _insert_result(
    cursor,
    *,
    tenant_id: str,
    job_id: str,
    claim_token: str,
    idempotency_key: str = "delivery-1",
    envelope_sha256: str = "a" * 64,
    include_next_attempt_at: bool = False,
) -> str:
    result_id = str(uuid4())
    columns = [
        "id",
        "tenant_id",
        "job_id",
        "claim_token",
        "contract_version",
        "idempotency_key",
        "envelope",
        "envelope_sha256",
        "inbox_status",
    ]
    values: list[object] = [
        result_id,
        tenant_id,
        job_id,
        claim_token,
        "v1",
        idempotency_key,
        "{}",
        envelope_sha256,
        "pending",
    ]
    if include_next_attempt_at:
        columns.append("next_attempt_at")
        values.append("NOW()")
    placeholders = ", ".join(["%s"] * len(values))
    cursor.execute(
        f"INSERT INTO crawler_agent_results ({', '.join(columns)}) "
        f"VALUES ({placeholders})",
        tuple(values),
    )
    return result_id


@pytest.fixture(scope="module")
def migrated_database_url() -> str:
    """Apply the full migration set to a throwaway cluster once per module."""

    if not postgres_binaries_available():
        pytest.skip("PostgreSQL binaries are required for U7 schema contracts")

    from egp_db.migration_runner import apply_migrations

    with TempPostgresCluster() as cluster:
        cluster.create_database("egp_u7_schema")
        database_url = cluster.database_url("egp_u7_schema")
        apply_migrations(database_url=database_url, migrations_dir=MIGRATIONS_DIR)
        yield database_url


def test_migration_034_defaults_discovery_jobs_to_legacy_backend(
    migrated_database_url: str,
) -> None:
    """An insert that predates U7 must remain owned by the legacy executor."""

    with connect(migrated_database_url) as connection:
        with connection.cursor() as cursor:
            _tenant_id, job_id = _seed_job(cursor)
            cursor.execute(
                "SELECT execution_backend FROM discovery_jobs WHERE id = %s",
                (job_id,),
            )
            assert cursor.fetchone()[0] == "legacy"


def test_migration_034_rejects_unknown_execution_backend(
    migrated_database_url: str,
) -> None:
    with connect(migrated_database_url) as connection:
        with connection.cursor() as cursor:
            with pytest.raises(CheckViolation):
                _seed_job(cursor, execution_backend="quantum")


def test_migration_034_allows_result_received_job_status(
    migrated_database_url: str,
) -> None:
    """`result_received` is the non-claimable state a submitted result moves a job to."""

    with connect(migrated_database_url) as connection:
        with connection.cursor() as cursor:
            _tenant_id, job_id = _seed_job(cursor)
            cursor.execute(
                "UPDATE discovery_jobs SET job_status = 'result_received' WHERE id = %s",
                (job_id,),
            )
            cursor.execute(
                "SELECT job_status FROM discovery_jobs WHERE id = %s", (job_id,)
            )
            assert cursor.fetchone()[0] == "result_received"


def test_migration_034_still_rejects_unknown_job_status(
    migrated_database_url: str,
) -> None:
    """Widening the CHECK must not turn it into a free-text column."""

    with connect(migrated_database_url) as connection:
        with connection.cursor() as cursor:
            _tenant_id, job_id = _seed_job(cursor)
            with pytest.raises(CheckViolation):
                cursor.execute(
                    "UPDATE discovery_jobs SET job_status = 'teleported' WHERE id = %s",
                    (job_id,),
                )


def test_inbox_accepts_only_one_result_per_claim_attempt(
    migrated_database_url: str,
) -> None:
    """Two different deliveries for one claim token must collide (C5)."""

    with connect(migrated_database_url) as connection:
        with connection.cursor() as cursor:
            tenant_id, job_id = _seed_job(cursor, execution_backend="agent")
            claim_token = str(uuid4())
            _insert_result(
                cursor, tenant_id=tenant_id, job_id=job_id, claim_token=claim_token
            )
            with pytest.raises(UniqueViolation):
                _insert_result(
                    cursor,
                    tenant_id=tenant_id,
                    job_id=job_id,
                    claim_token=claim_token,
                    idempotency_key="delivery-2",
                    envelope_sha256="b" * 64,
                )


def test_inbox_allows_a_fresh_claim_token_for_the_same_job(
    migrated_database_url: str,
) -> None:
    """A reclaim after lease expiry gets its own row; uniqueness is per attempt."""

    with connect(migrated_database_url) as connection:
        with connection.cursor() as cursor:
            tenant_id, job_id = _seed_job(cursor, execution_backend="agent")
            _insert_result(
                cursor, tenant_id=tenant_id, job_id=job_id, claim_token=str(uuid4())
            )
            _insert_result(
                cursor, tenant_id=tenant_id, job_id=job_id, claim_token=str(uuid4())
            )
            cursor.execute(
                "SELECT COUNT(*) FROM crawler_agent_results WHERE job_id = %s",
                (job_id,),
            )
            assert cursor.fetchone()[0] == 2


def test_inbox_rejects_a_job_belonging_to_another_tenant(
    migrated_database_url: str,
) -> None:
    """Composite (tenant_id, job_id) FK — the tenant-isolation invariant (C6, R9)."""

    with connect(migrated_database_url) as connection:
        with connection.cursor() as cursor:
            _tenant_a, job_a = _seed_job(cursor, execution_backend="agent")
            tenant_b, _job_b = _seed_job(cursor, execution_backend="agent")
            with pytest.raises(ForeignKeyViolation):
                _insert_result(
                    cursor,
                    tenant_id=tenant_b,
                    job_id=job_a,
                    claim_token=str(uuid4()),
                )


def test_inbox_next_attempt_at_is_never_null(migrated_database_url: str) -> None:
    """A NULL next_attempt_at would make the row invisible to the retry query (C3)."""

    with connect(migrated_database_url) as connection:
        with connection.cursor() as cursor:
            tenant_id, job_id = _seed_job(cursor, execution_backend="agent")
            result_id = _insert_result(
                cursor, tenant_id=tenant_id, job_id=job_id, claim_token=str(uuid4())
            )
            cursor.execute(
                "SELECT next_attempt_at FROM crawler_agent_results WHERE id = %s",
                (result_id,),
            )
            assert cursor.fetchone()[0] is not None


def test_inbox_rejects_an_explicit_null_next_attempt_at(
    migrated_database_url: str,
) -> None:
    """A DEFAULT alone would not stop a caller passing NULL explicitly."""

    with connect(migrated_database_url) as connection:
        with connection.cursor() as cursor:
            tenant_id, job_id = _seed_job(cursor, execution_backend="agent")
            with pytest.raises(NotNullViolation):
                cursor.execute(
                    """
                    INSERT INTO crawler_agent_results
                        (id, tenant_id, job_id, claim_token, contract_version,
                         idempotency_key, envelope, envelope_sha256, inbox_status,
                         next_attempt_at)
                    VALUES (%s, %s, %s, %s, 'v1', 'd', '{}', %s, 'pending', NULL)
                    """,
                    (str(uuid4()), tenant_id, job_id, str(uuid4()), "e" * 64),
                )


def test_inbox_rejects_processing_without_a_processor_lease(
    migrated_database_url: str,
) -> None:
    """'processing' without a lease is the stranded state the columns prevent."""

    with connect(migrated_database_url) as connection:
        with connection.cursor() as cursor:
            tenant_id, job_id = _seed_job(cursor, execution_backend="agent")
            with pytest.raises(CheckViolation):
                cursor.execute(
                    """
                    INSERT INTO crawler_agent_results
                        (id, tenant_id, job_id, claim_token, contract_version,
                         idempotency_key, envelope, envelope_sha256, inbox_status)
                    VALUES (%s, %s, %s, %s, 'v1', 'd', '{}', %s, 'processing')
                    """,
                    (str(uuid4()), tenant_id, job_id, str(uuid4()), "f" * 64),
                )


def test_inbox_accepts_processing_with_a_processor_lease(
    migrated_database_url: str,
) -> None:
    """The positive case, so the constraint above cannot be vacuously satisfied."""

    with connect(migrated_database_url) as connection:
        with connection.cursor() as cursor:
            tenant_id, job_id = _seed_job(cursor, execution_backend="agent")
            cursor.execute(
                """
                INSERT INTO crawler_agent_results
                    (id, tenant_id, job_id, claim_token, contract_version,
                     idempotency_key, envelope, envelope_sha256, inbox_status,
                     processor_token, processing_expires_at)
                VALUES (%s, %s, %s, %s, 'v1', 'd', '{}', %s, 'processing',
                        %s, NOW() + INTERVAL '5 minutes')
                """,
                (
                    str(uuid4()),
                    tenant_id,
                    job_id,
                    str(uuid4()),
                    "g" * 64,
                    str(uuid4()),
                ),
            )


def test_inbox_rejects_unknown_inbox_status(migrated_database_url: str) -> None:
    # A fresh connection per expected violation: a CHECK failure aborts the whole
    # transaction, so a second attempt on the same connection would raise
    # InFailedSqlTransaction instead of the CheckViolation under test.
    with connect(migrated_database_url) as connection:
        with connection.cursor() as cursor:
            tenant_id, job_id = _seed_job(cursor, execution_backend="agent")
            with pytest.raises(CheckViolation):
                cursor.execute(
                    """
                    INSERT INTO crawler_agent_results
                        (id, tenant_id, job_id, claim_token, contract_version,
                         idempotency_key, envelope, envelope_sha256, inbox_status)
                    VALUES (%s, %s, %s, %s, 'v1', 'd', '{}', %s, 'teleporting')
                    """,
                    (str(uuid4()), tenant_id, job_id, str(uuid4()), "c" * 64),
                )


def test_inbox_rejects_unsupported_contract_version(
    migrated_database_url: str,
) -> None:
    with connect(migrated_database_url) as connection:
        with connection.cursor() as cursor:
            tenant_id, job_id = _seed_job(cursor, execution_backend="agent")
            with pytest.raises(CheckViolation):
                cursor.execute(
                    """
                    INSERT INTO crawler_agent_results
                        (id, tenant_id, job_id, claim_token, contract_version,
                         idempotency_key, envelope, envelope_sha256, inbox_status)
                    VALUES (%s, %s, %s, %s, 'v99', 'd', '{}', %s, 'pending')
                    """,
                    (str(uuid4()), tenant_id, job_id, str(uuid4()), "d" * 64),
                )


def test_migration_034_upgrades_a_database_that_already_has_jobs(
    tmp_path: Path,
) -> None:
    """Upgrade path, not just fresh install.

    A production database already contains ``discovery_jobs`` rows when 034
    lands. ``ADD COLUMN ... NOT NULL DEFAULT 'legacy'`` must backfill those rows
    to legacy ownership, otherwise the running external discovery executor would
    stop claiming its own in-flight work the moment the migration is applied.
    """

    if not postgres_binaries_available():
        pytest.skip("PostgreSQL binaries are required for U7 schema contracts")

    from egp_db.migration_runner import apply_migrations

    staged_dir = tmp_path / "migrations"
    staged_dir.mkdir()
    all_sql = sorted(MIGRATIONS_DIR.glob("*.sql"))
    target = next(path for path in all_sql if path.name.startswith("034_"))
    # Stage everything BEFORE 034, not "everything except 034". Later migrations
    # legitimately build on the tables 034 creates (036 alters
    # `crawler_agent_results`), so applying them first fails with UndefinedTable —
    # a limitation of the staging technique, not of the property under test, which
    # is only that 034 backfills pre-existing discovery_jobs rows.
    for path in all_sql:
        if path.name < target.name:
            copy2(path, staged_dir / path.name)

    with TempPostgresCluster() as cluster:
        cluster.create_database("egp_u7_upgrade")
        database_url = cluster.database_url("egp_u7_upgrade")

        # 1. Pre-U7 schema, with a job already queued.
        apply_migrations(database_url=database_url, migrations_dir=staged_dir)
        with connect(database_url) as connection:
            with connection.cursor() as cursor:
                _tenant_id, job_id = _seed_job(cursor)
                cursor.execute(
                    "SELECT COUNT(*) FROM information_schema.columns "
                    "WHERE table_name = 'discovery_jobs' "
                    "AND column_name = 'execution_backend'"
                )
                assert cursor.fetchone()[0] == 0, "column must not exist pre-034"

        # 2. Apply 034 on top of the populated database.
        copy2(target, staged_dir / target.name)
        result = apply_migrations(
            database_url=database_url, migrations_dir=staged_dir
        )
        assert target.name in result.applied_versions

        # 3. The pre-existing row must now be legacy-owned.
        with connect(database_url) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT execution_backend, job_status FROM discovery_jobs "
                    "WHERE id = %s",
                    (job_id,),
                )
                execution_backend, job_status = cursor.fetchone()
                assert execution_backend == "legacy"
                assert job_status == "pending"
