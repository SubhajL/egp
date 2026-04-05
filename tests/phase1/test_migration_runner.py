from __future__ import annotations

from pathlib import Path

from psycopg import connect

from egp_db.dev_postgres import TempPostgresCluster, postgres_binaries_available


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
