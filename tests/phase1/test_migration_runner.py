from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from shutil import copy2
from uuid import UUID

from psycopg import connect
from psycopg.errors import CheckViolation, UniqueViolation
import pytest

from egp_db.dev_postgres import TempPostgresCluster, postgres_binaries_available
from egp_shared_types.enums import DiscoveryFailureCode


def test_migration_runner_applies_and_records_all_versions(repo_root: Path) -> None:
    if not postgres_binaries_available():
        return

    from egp_db.migration_runner import apply_migrations, list_migration_files

    migrations_dir = repo_root / "packages/db/src/migrations"
    expected_versions = [path.name for path in list_migration_files(migrations_dir)]

    with TempPostgresCluster() as cluster:
        cluster.create_database("egp_migration_runner_test")
        database_url = cluster.database_url("egp_migration_runner_test")

        first_run = apply_migrations(
            database_url=database_url, migrations_dir=migrations_dir
        )
        second_run = apply_migrations(
            database_url=database_url, migrations_dir=migrations_dir
        )

        with connect(database_url) as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT version FROM schema_migrations ORDER BY version")
                rows = [row[0] for row in cursor.fetchall()]

        assert first_run.applied_versions == expected_versions
        assert first_run.pending_versions == []
        assert second_run.applied_versions == []
        assert second_run.pending_versions == []
        assert rows == expected_versions


def test_keyword_group_lifecycle_migration_backfills_intent_and_unique_names(
    repo_root: Path,
    tmp_path: Path,
) -> None:
    if not postgres_binaries_available():
        return

    from egp_db.migration_runner import apply_migrations, list_migration_files

    migrations_dir = repo_root / "packages/db/src/migrations"
    lifecycle_migration = migrations_dir / "028_keyword_group_lifecycle.sql"
    assert lifecycle_migration.exists()

    staged_migrations = tmp_path / "migrations"
    staged_migrations.mkdir()
    for migration in list_migration_files(migrations_dir):
        if migration.name != lifecycle_migration.name:
            copy2(migration, staged_migrations / migration.name)

    with TempPostgresCluster() as cluster:
        cluster.create_database("egp_keyword_group_migration_test")
        database_url = cluster.database_url("egp_keyword_group_migration_test")
        apply_migrations(database_url=database_url, migrations_dir=staged_migrations)

        with connect(database_url) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO tenants (id, name, slug)
                    VALUES ('11111111-1111-1111-1111-111111111111', 'LLL', 'lll')
                    """
                )
                cursor.execute(
                    """
                    INSERT INTO crawl_profiles (
                        id, tenant_id, name, profile_type, is_active, created_at, updated_at
                    ) VALUES
                        (
                            'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa',
                            '11111111-1111-1111-1111-111111111111',
                            'คำค้นหลัก', 'custom', FALSE,
                            '2026-07-01T00:00:00+00:00', '2026-07-01T00:00:00+00:00'
                        ),
                        (
                            'bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb',
                            '11111111-1111-1111-1111-111111111111',
                            ' คำค้นหลัก ', 'custom', FALSE,
                            '2026-07-02T00:00:00+00:00', '2026-07-02T00:00:00+00:00'
                        ),
                        (
                            'cccccccc-cccc-cccc-cccc-cccccccccccc',
                            '11111111-1111-1111-1111-111111111111',
                            'Empty paused group', 'custom', FALSE,
                            '2026-07-03T00:00:00+00:00', '2026-07-03T00:00:00+00:00'
                        )
                    """
                )
                cursor.execute(
                    """
                    INSERT INTO crawl_profile_keywords (id, profile_id, keyword, position)
                    VALUES
                        (
                            'dddddddd-dddd-dddd-dddd-dddddddddddd',
                            'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa',
                            'analytics', 1
                        ),
                        (
                            'eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee',
                            'bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb',
                            'platform', 1
                        )
                    """
                )
            connection.commit()

        copy2(lifecycle_migration, staged_migrations / lifecycle_migration.name)
        migration_result = apply_migrations(
            database_url=database_url,
            migrations_dir=staged_migrations,
        )

        with connect(database_url) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT name, enabled_by_user, is_active
                    FROM crawl_profiles
                    ORDER BY created_at, id
                    """
                )
                profiles = cursor.fetchall()
                cursor.execute("SELECT count(*) FROM crawl_profile_keywords")
                keyword_count = cursor.fetchone()[0]

        assert migration_result.applied_versions == [lifecycle_migration.name]
        assert profiles == [
            ("คำค้นหลัก", True, True),
            ("คำค้นหลัก (2)", True, True),
            ("Empty paused group", False, False),
        ]
        assert keyword_count == 2

        with connect(database_url) as connection:
            with pytest.raises(UniqueViolation):
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        INSERT INTO crawl_profiles (tenant_id, name)
                        VALUES (
                            '11111111-1111-1111-1111-111111111111',
                            '  คำค้นหลัก  '
                        )
                        """
                    )


def test_recrawl_request_correlation_migration_upgrades_existing_rows(
    repo_root: Path,
    tmp_path: Path,
) -> None:
    if not postgres_binaries_available():
        return

    from egp_db.migration_runner import apply_migrations, list_migration_files

    migrations_dir = repo_root / "packages/db/src/migrations"
    correlation_migration = migrations_dir / "029_recrawl_request_correlation.sql"
    assert correlation_migration.exists()
    staged_migrations = tmp_path / "recrawl-migrations"
    staged_migrations.mkdir()
    for migration in list_migration_files(migrations_dir):
        if migration.name < correlation_migration.name:
            copy2(migration, staged_migrations / migration.name)

    with TempPostgresCluster() as cluster:
        cluster.create_database("egp_recrawl_correlation_migration_test")
        database_url = cluster.database_url("egp_recrawl_correlation_migration_test")
        apply_migrations(database_url=database_url, migrations_dir=staged_migrations)

        with connect(database_url) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO tenants (id, name, slug)
                    VALUES ('11111111-1111-1111-1111-111111111111', 'LLL', 'lll')
                    """
                )
                cursor.execute(
                    """
                    INSERT INTO crawl_profiles (id, tenant_id, name, profile_type)
                    VALUES (
                        '22222222-2222-2222-2222-222222222222',
                        '11111111-1111-1111-1111-111111111111',
                        'Status batch',
                        'custom'
                    )
                    """
                )
                cursor.execute(
                    """
                    INSERT INTO discovery_jobs (
                        id, tenant_id, profile_id, profile_type, keyword,
                        trigger_type, live, job_status, attempt_count,
                        next_attempt_at
                    ) VALUES (
                        '33333333-3333-3333-3333-333333333333',
                        '11111111-1111-1111-1111-111111111111',
                        '22222222-2222-2222-2222-222222222222',
                        'custom', 'analytics', 'manual', TRUE, 'pending', 0, NOW()
                    )
                    """
                )
                cursor.execute(
                    """
                    INSERT INTO crawl_runs (
                        id, tenant_id, profile_id, trigger_type, status
                    ) VALUES (
                        '44444444-4444-4444-4444-444444444444',
                        '11111111-1111-1111-1111-111111111111',
                        '22222222-2222-2222-2222-222222222222',
                        'manual', 'queued'
                    )
                    """
                )
            connection.commit()

        copy2(correlation_migration, staged_migrations / correlation_migration.name)
        result = apply_migrations(database_url=database_url, migrations_dir=staged_migrations)

        with connect(database_url) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT recrawl_request_id
                    FROM discovery_jobs
                    WHERE id = '33333333-3333-3333-3333-333333333333'
                    """
                )
                assert cursor.fetchone() == (None,)
                cursor.execute(
                    """
                    SELECT discovery_job_id, recrawl_request_id
                    FROM crawl_runs
                    WHERE id = '44444444-4444-4444-4444-444444444444'
                    """
                )
                assert cursor.fetchone() == (None, None)
                cursor.execute(
                    """
                    INSERT INTO recrawl_requests (
                        id, tenant_id, requested_keyword_count
                    ) VALUES (
                        '55555555-5555-5555-5555-555555555555',
                        '11111111-1111-1111-1111-111111111111',
                        1
                    )
                    """
                )
                cursor.execute(
                    """
                    UPDATE discovery_jobs
                    SET recrawl_request_id = '55555555-5555-5555-5555-555555555555'
                    WHERE id = '33333333-3333-3333-3333-333333333333'
                    """
                )
                cursor.execute(
                    """
                    UPDATE crawl_runs
                    SET discovery_job_id = '33333333-3333-3333-3333-333333333333',
                        recrawl_request_id = '55555555-5555-5555-5555-555555555555'
                    WHERE id = '44444444-4444-4444-4444-444444444444'
                    """
                )
            connection.commit()

        assert result.applied_versions == [correlation_migration.name]


def test_crawler_runtime_migration_has_no_tenant_or_customer_payload(
    repo_root: Path,
) -> None:
    runtime_migration = (
        repo_root
        / "packages/db/src/migrations/033_crawler_runtime_heartbeats.sql"
    )

    assert runtime_migration.exists()
    runtime_sql = runtime_migration.read_text(encoding="utf-8")
    assert "CREATE TABLE crawler_runtime_heartbeats" in runtime_sql
    assert "tenant_id" not in runtime_sql
    assert "customer_id" not in runtime_sql


def test_operator_recovery_request_migration_is_additive_and_idempotent(
    repo_root: Path,
    tmp_path: Path,
) -> None:
    if not postgres_binaries_available():
        return

    from egp_db.migration_runner import apply_migrations, list_migration_files

    migrations_dir = repo_root / "packages/db/src/migrations"
    recovery_migration = migrations_dir / "030_operator_recovery_requests.sql"
    assert recovery_migration.exists()
    staged_migrations = tmp_path / "operator-recovery-migrations"
    staged_migrations.mkdir()
    for migration in list_migration_files(migrations_dir):
        if migration.name < recovery_migration.name:
            copy2(migration, staged_migrations / migration.name)

    with TempPostgresCluster() as cluster:
        cluster.create_database("egp_operator_recovery_migration_test")
        database_url = cluster.database_url("egp_operator_recovery_migration_test")
        apply_migrations(database_url=database_url, migrations_dir=staged_migrations)

        with connect(database_url) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO tenants (id, name, slug)
                    VALUES ('11111111-1111-1111-1111-111111111111', 'LLL', 'lll')
                    """
                )
                cursor.execute(
                    """
                    INSERT INTO recrawl_requests (
                        id, tenant_id, requested_keyword_count
                    ) VALUES (
                        '22222222-2222-2222-2222-222222222222',
                        '11111111-1111-1111-1111-111111111111',
                        1
                    )
                    """
                )
            connection.commit()

        copy2(recovery_migration, staged_migrations / recovery_migration.name)
        result = apply_migrations(database_url=database_url, migrations_dir=staged_migrations)

        with connect(database_url) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT source, idempotency_key
                    FROM recrawl_requests
                    WHERE id = '22222222-2222-2222-2222-222222222222'
                    """
                )
                assert cursor.fetchone() == ("manual", None)
                cursor.execute(
                    """
                    INSERT INTO recrawl_requests (
                        id, tenant_id, source, idempotency_key,
                        requested_keyword_count
                    ) VALUES (
                        '33333333-3333-3333-3333-333333333333',
                        '11111111-1111-1111-1111-111111111111',
                        'operator_recovery', 'incident-manifest', 1
                    )
                    """
                )
            connection.commit()

        with connect(database_url) as connection:
            with pytest.raises(UniqueViolation):
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        INSERT INTO recrawl_requests (
                            id, tenant_id, source, idempotency_key,
                            requested_keyword_count
                        ) VALUES (
                            '44444444-4444-4444-4444-444444444444',
                            '11111111-1111-1111-1111-111111111111',
                            'operator_recovery', 'incident-manifest', 1
                        )
                        """
                    )

        assert result.applied_versions == [recovery_migration.name]


def test_crawl_run_activity_migration_uses_next_unique_prefix(repo_root: Path) -> None:
    migrations_dir = repo_root / "packages/db/src/migrations"
    activity_migration = migrations_dir / "031_crawl_run_last_activity.sql"

    assert activity_migration.exists()
    assert [path.name for path in migrations_dir.glob("031_*.sql")] == [
        activity_migration.name
    ]


def test_crawl_run_activity_migration_backfills_existing_rows(
    repo_root: Path,
    tmp_path: Path,
) -> None:
    if not postgres_binaries_available():
        return

    from egp_db.migration_runner import apply_migrations, list_migration_files

    migrations_dir = repo_root / "packages/db/src/migrations"
    activity_migration = migrations_dir / "031_crawl_run_last_activity.sql"
    staged_migrations = tmp_path / "crawl-run-activity-migrations"
    staged_migrations.mkdir()
    for migration in list_migration_files(migrations_dir):
        if migration.name < activity_migration.name:
            copy2(migration, staged_migrations / migration.name)

    with TempPostgresCluster() as cluster:
        cluster.create_database("egp_crawl_run_activity_migration_test")
        database_url = cluster.database_url("egp_crawl_run_activity_migration_test")
        apply_migrations(database_url=database_url, migrations_dir=staged_migrations)
        with connect(database_url) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO tenants (id, name, slug)
                    VALUES ('11111111-1111-1111-1111-111111111111', 'LLL', 'lll')
                    """
                )
                cursor.execute(
                    """
                    INSERT INTO crawl_runs (
                        id, tenant_id, trigger_type, status, started_at, created_at
                    ) VALUES (
                        '22222222-2222-2222-2222-222222222222',
                        '11111111-1111-1111-1111-111111111111',
                        'manual', 'running',
                        '2026-07-23T01:00:00+00:00',
                        '2026-07-23T00:59:00+00:00'
                    )
                    """
                )
            connection.commit()

        copy2(activity_migration, staged_migrations / activity_migration.name)
        result = apply_migrations(database_url=database_url, migrations_dir=staged_migrations)

        with connect(database_url) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT last_activity_at, is_nullable
                    FROM crawl_runs
                    JOIN information_schema.columns
                      ON table_name = 'crawl_runs'
                     AND column_name = 'last_activity_at'
                    WHERE id = '22222222-2222-2222-2222-222222222222'
                    """
                )
                last_activity_at, is_nullable = cursor.fetchone()

        assert result.applied_versions == [activity_migration.name]
        assert last_activity_at.astimezone(UTC).isoformat() == "2026-07-23T01:00:00+00:00"
        assert is_nullable == "NO"


def test_discovery_job_lease_migration_uses_next_unique_prefix(repo_root: Path) -> None:
    migrations_dir = repo_root / "packages/db/src/migrations"
    lease_migration = migrations_dir / "032_discovery_job_leases.sql"

    assert lease_migration.exists()
    assert [path.name for path in migrations_dir.glob("032_*.sql")] == [
        lease_migration.name
    ]
    migration_sql = lease_migration.read_text(encoding="utf-8")
    for failure_code in DiscoveryFailureCode:
        assert f"'{failure_code.value}'" in migration_sql


def test_discovery_job_lease_migration_guards_inflight_and_preserves_unstarted_jobs(
    repo_root: Path,
    tmp_path: Path,
) -> None:
    if not postgres_binaries_available():
        return

    from egp_db.migration_runner import apply_migrations, list_migration_files

    migrations_dir = repo_root / "packages/db/src/migrations"
    lease_migration = migrations_dir / "032_discovery_job_leases.sql"
    staged_migrations = tmp_path / "discovery-job-lease-migrations"
    staged_migrations.mkdir()
    for migration in list_migration_files(migrations_dir):
        if migration.name < lease_migration.name:
            copy2(migration, staged_migrations / migration.name)

    with TempPostgresCluster() as cluster:
        cluster.create_database("egp_discovery_job_lease_migration_test")
        database_url = cluster.database_url("egp_discovery_job_lease_migration_test")
        apply_migrations(database_url=database_url, migrations_dir=staged_migrations)
        with connect(database_url) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO tenants (id, name, slug)
                    VALUES ('11111111-1111-1111-1111-111111111111', 'Lease', 'lease')
                    """
                )
                cursor.execute(
                    """
                    INSERT INTO crawl_profiles (
                        id, tenant_id, name, profile_type, is_active,
                        max_pages_per_keyword, close_consulting_after_days,
                        close_stale_after_days
                    ) VALUES (
                        '22222222-2222-2222-2222-222222222222',
                        '11111111-1111-1111-1111-111111111111',
                        'Lease Profile', 'custom', TRUE, 15, 30, 45
                    )
                    """
                )
                cursor.execute(
                    """
                    INSERT INTO discovery_jobs (
                        id, tenant_id, profile_id, profile_type, keyword,
                        trigger_type, live, job_status, attempt_count,
                        next_attempt_at, processing_started_at
                    ) VALUES
                    (
                        '33333333-3333-3333-3333-333333333333',
                        '11111111-1111-1111-1111-111111111111',
                        '22222222-2222-2222-2222-222222222222',
                        'custom', 'lease', 'manual', TRUE, 'pending', 0,
                        '2026-07-23T01:00:00+00:00',
                        '2026-07-23T01:01:00+00:00'
                    ),
                    (
                        '44444444-4444-4444-4444-444444444444',
                        '11111111-1111-1111-1111-111111111111',
                        '22222222-2222-2222-2222-222222222222',
                        'custom', 'unstarted', 'manual', TRUE, 'pending', 0,
                        '2026-07-23T01:00:00+00:00',
                        NULL
                    )
                    """
                )
            connection.commit()

        copy2(lease_migration, staged_migrations / lease_migration.name)
        result = apply_migrations(database_url=database_url, migrations_dir=staged_migrations)

        with connect(database_url) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT claim_token, lease_expires_at, lease_heartbeat_at, last_error_code
                    FROM discovery_jobs
                    ORDER BY id
                    """
                )
                lease_fields = cursor.fetchall()

        assert result.applied_versions == [lease_migration.name]
        assert lease_fields == [
            (
                UUID("00000000-0000-0000-0000-000000000000"),
                datetime.fromisoformat("2026-07-23T04:01:00+00:00"),
                datetime.fromisoformat("2026-07-23T01:01:00+00:00"),
                None,
            ),
            (None, None, None, None),
        ]

        with connect(database_url) as connection:
            with pytest.raises(CheckViolation):
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        UPDATE discovery_jobs
                        SET last_error_code = 'not-a-real-code'
                        WHERE id = '44444444-4444-4444-4444-444444444444'
                        """
                    )
