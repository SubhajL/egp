from __future__ import annotations

import gzip
import subprocess
from pathlib import Path

import pytest

from egp_db.backup_files import write_sha256_sidecar
from egp_db.dev_postgres import (
    TempPostgresCluster,
    postgres_backup_binaries_available,
    postgres_binaries_available,
    run_pg_backup_restore_smoke,
)
from egp_db.migration_runner import apply_migrations


def _pg_binaries_or_skip() -> None:
    if not postgres_binaries_available():
        pytest.skip("PostgreSQL server binaries not available")
    if not postgres_backup_binaries_available():
        pytest.skip("pg_dump / pg_restore not available")


def test_postgres_backup_binaries_available_returns_bool() -> None:
    assert isinstance(postgres_backup_binaries_available(), bool)


def test_pg_backup_restore_round_trips_temp_postgres(
    repo_root: Path, tmp_backup_root: Path
) -> None:
    _pg_binaries_or_skip()
    result = run_pg_backup_restore_smoke(
        repo_root=repo_root,
        backup_root=tmp_backup_root,
    )
    assert result["seeded_tenant_count"] == 1
    assert result["restored_tenant_count"] == 1
    assert result["sha256_verified"] is True
    assert result["archive_path"]
    assert result["sidecar_path"]
    archive = Path(str(result["archive_path"]))
    sidecar = Path(str(result["sidecar_path"]))
    assert archive.exists()
    assert sidecar.exists()
    assert archive.name.endswith(".dump.gz")


def test_temp_postgres_cluster_drop_database_removes_database(
    repo_root: Path,
) -> None:
    _pg_binaries_or_skip()
    with TempPostgresCluster() as cluster:
        cluster.create_database("egp_drop_test")
        cluster.drop_database("egp_drop_test")
        # Recreating with same name must succeed (i.e. the previous DB was gone)
        cluster.create_database("egp_drop_test")


def test_pg_restore_rejects_bad_sha256_sidecar(
    repo_root: Path, tmp_backup_root: Path
) -> None:
    _pg_binaries_or_skip()
    # Build a real dump first
    migrations_dir = repo_root / "packages/db/src/migrations"
    with TempPostgresCluster() as cluster:
        cluster.create_database("egp_corrupt_test")
        database_url = cluster.database_url("egp_corrupt_test")
        apply_migrations(database_url=database_url, migrations_dir=migrations_dir)

        dump_path = tmp_backup_root / "egp-pg-2026-05-26T143045Z-abc1234.dump.gz"
        raw = subprocess.run(
            ["pg_dump", "-Fc", "-Z0", database_url],
            check=True,
            capture_output=True,
        )
        with gzip.open(dump_path, "wb") as gz:
            gz.write(raw.stdout)
        # Write a sidecar with a WRONG digest
        sidecar = write_sha256_sidecar(dump_path, digest="0" * 64)

        # restore script should refuse — invoke via subprocess
        scripts_dir = repo_root / "scripts"
        if not (scripts_dir / "pg_restore.sh").exists():
            pytest.skip("pg_restore.sh not implemented yet")
        target_db = "egp_restore_target"
        cluster.create_database(target_db)
        target_url = cluster.database_url(target_db)
        completed = subprocess.run(
            [
                "bash",
                str(scripts_dir / "pg_restore.sh"),
                "--source-path",
                str(dump_path),
                "--sidecar-path",
                str(sidecar),
                "--target-url",
                target_url,
                "--yes",
            ],
            capture_output=True,
            text=True,
        )
        assert completed.returncode != 0
        assert (
            "sha256" in completed.stdout.lower() or "sha256" in completed.stderr.lower()
        )


def test_pg_restore_refuses_system_database_targets(
    repo_root: Path, tmp_backup_root: Path
) -> None:
    _pg_binaries_or_skip()
    scripts_dir = repo_root / "scripts"
    fake_dump = tmp_backup_root / "egp-pg-2026-05-26T143045Z-abc1234.dump.gz"
    fake_dump.write_bytes(b"x")
    with TempPostgresCluster() as cluster:
        target_url = cluster.database_url("postgres")
        completed = subprocess.run(
            [
                "bash",
                str(scripts_dir / "pg_restore.sh"),
                "--source-path",
                str(fake_dump),
                "--target-url",
                target_url,
                "--yes",
            ],
            capture_output=True,
            text=True,
        )
        assert completed.returncode != 0
        combined = (completed.stdout + completed.stderr).lower()
        assert "system database" in combined or "refus" in combined


def test_pg_restore_refuses_system_database_via_percent_encoded_name(
    repo_root: Path, tmp_backup_root: Path
) -> None:
    """Percent-encoded `postgres` (%70ostgres) must still be caught.

    The previous URL-parse-based guard would compare the literal path
    segment '%70ostgres' and let it through; the current_database()-based
    guard resolves the canonical name and catches it.
    """
    _pg_binaries_or_skip()
    scripts_dir = repo_root / "scripts"
    fake_dump = tmp_backup_root / "egp-pg-2026-05-26T143045Z-abc1234.dump.gz"
    fake_dump.write_bytes(b"x")
    with TempPostgresCluster() as cluster:
        # %70 = 'p' — libpq decodes the dbname segment so this resolves
        # to the system database `postgres`
        target_url = cluster.database_url("%70ostgres")
        completed = subprocess.run(
            [
                "bash",
                str(scripts_dir / "pg_restore.sh"),
                "--source-path",
                str(fake_dump),
                "--target-url",
                target_url,
                "--yes",
            ],
            capture_output=True,
            text=True,
        )
        assert completed.returncode != 0
        combined = (completed.stdout + completed.stderr).lower()
        assert "system database" in combined or "refus" in combined


def test_pg_restore_non_empty_guard_catches_non_public_schema(
    repo_root: Path, tmp_backup_root: Path
) -> None:
    """A table in a non-public schema must trip the non-empty guard.

    The previous check only counted information_schema.tables WHERE
    table_schema='public'; this verifies the broader pg_catalog query.
    """
    _pg_binaries_or_skip()
    scripts_dir = repo_root / "scripts"
    fake_dump = tmp_backup_root / "egp-pg-2026-05-26T143045Z-abc1234.dump.gz"
    fake_dump.write_bytes(b"x")
    with TempPostgresCluster() as cluster:
        cluster.create_database("egp_non_public_schema_test")
        target_url = cluster.database_url("egp_non_public_schema_test")
        from psycopg import connect

        with connect(target_url) as connection:
            with connection.cursor() as cursor:
                cursor.execute("CREATE SCHEMA other_schema")
                cursor.execute("CREATE TABLE other_schema.t (id INT)")
            connection.commit()
        completed = subprocess.run(
            [
                "bash",
                str(scripts_dir / "pg_restore.sh"),
                "--source-path",
                str(fake_dump),
                "--target-url",
                target_url,
                "--yes",
            ],
            capture_output=True,
            text=True,
        )
        assert completed.returncode != 0
        combined = (completed.stdout + completed.stderr).lower()
        assert "user object" in combined or "non-empty" in combined
