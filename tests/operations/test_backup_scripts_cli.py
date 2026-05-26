from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from egp_db.dev_postgres import (
    postgres_backup_binaries_available,
    postgres_binaries_available,
)


def _pg_binaries_or_skip() -> None:
    if not postgres_binaries_available():
        pytest.skip("PostgreSQL server binaries not available")
    if not postgres_backup_binaries_available():
        pytest.skip("pg_dump / pg_restore not available")


def test_pg_backup_sh_help_exits_zero_and_mentions_env_vars(repo_root: Path) -> None:
    completed = subprocess.run(
        ["bash", str(repo_root / "scripts" / "pg_backup.sh"), "--help"],
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0
    combined = completed.stdout + completed.stderr
    assert "DATABASE_URL" in combined
    assert "EGP_BACKUP_TARGET" in combined
    assert "EGP_BACKUP_LOCAL_CACHE_DIR" in combined


def test_pg_backup_sh_fails_friendly_when_pg_dump_missing(
    repo_root: Path, tmp_path: Path
) -> None:
    # Sanitized PATH that does not contain pg_dump (no system bin dirs)
    safe_path = "/usr/bin:/bin"
    completed = subprocess.run(
        ["bash", str(repo_root / "scripts" / "pg_backup.sh")],
        capture_output=True,
        text=True,
        env={
            "PATH": safe_path,
            "DATABASE_URL": "postgresql://x/y",
            "EGP_BACKUP_TARGET": "local-fs",
            "EGP_BACKUP_LOCAL_CACHE_DIR": str(tmp_path),
        },
    )
    assert completed.returncode != 0
    assert "pg_dump" in (completed.stdout + completed.stderr)


def test_pg_restore_sh_help_exits_zero(repo_root: Path) -> None:
    completed = subprocess.run(
        ["bash", str(repo_root / "scripts" / "pg_restore.sh"), "--help"],
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0
    assert "--target-url" in (completed.stdout + completed.stderr)


def test_pg_restore_sh_rejects_non_postgres_target_url(repo_root: Path) -> None:
    completed = subprocess.run(
        [
            "bash",
            str(repo_root / "scripts" / "pg_restore.sh"),
            "--source-path",
            "/tmp/nonexistent.dump.gz",
            "--target-url",
            "mysql://x@h/d",
            "--yes",
        ],
        capture_output=True,
        text=True,
    )
    assert completed.returncode != 0
    combined = (completed.stdout + completed.stderr).lower()
    assert "postgresql" in combined


def test_pg_restore_sh_rejects_system_database_target(
    repo_root: Path, tmp_path: Path
) -> None:
    _pg_binaries_or_skip()
    fake_dump = tmp_path / "egp-pg-2026-05-26T143045Z-abc1234.dump.gz"
    fake_dump.write_bytes(b"x")
    completed = subprocess.run(
        [
            "bash",
            str(repo_root / "scripts" / "pg_restore.sh"),
            "--source-path",
            str(fake_dump),
            "--target-url",
            "postgresql://egp@127.0.0.1:5432/postgres",
            "--yes",
        ],
        capture_output=True,
        text=True,
    )
    assert completed.returncode != 0
    combined = (completed.stdout + completed.stderr).lower()
    assert "system database" in combined or "refus" in combined


def test_pg_backup_sh_succeeds_with_local_fs_target_against_temp_postgres(
    repo_root: Path, tmp_path: Path
) -> None:
    """End-to-end: pg_backup.sh with EGP_BACKUP_TARGET=local-fs and the
    same dir for cache + target must NOT fail (no self-copy SameFileError).
    """
    _pg_binaries_or_skip()
    from egp_db.dev_postgres import TempPostgresCluster

    with TempPostgresCluster() as cluster:
        cluster.create_database("egp_pg_backup_e2e")
        database_url = cluster.database_url("egp_pg_backup_e2e")
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir()
        env = {
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "DATABASE_URL": database_url,
            "EGP_BACKUP_TARGET": "local-fs",
            "EGP_BACKUP_LOCAL_CACHE_DIR": str(cache_dir),
        }
        completed = subprocess.run(
            ["bash", str(repo_root / "scripts" / "pg_backup.sh")],
            capture_output=True,
            text=True,
            env=env,
        )
        assert completed.returncode == 0, (
            f"stdout={completed.stdout}\nstderr={completed.stderr}"
        )
        archives = list(cache_dir.glob("egp-pg-*.dump.gz"))
        sidecars = list(cache_dir.glob("egp-pg-*.dump.gz.sha256"))
        assert len(archives) == 1
        assert len(sidecars) == 1


def test_pg_backup_sh_fails_when_required_env_vars_missing(repo_root: Path) -> None:
    completed = subprocess.run(
        ["bash", str(repo_root / "scripts" / "pg_backup.sh")],
        capture_output=True,
        text=True,
        env={"PATH": os.environ.get("PATH", "/usr/bin:/bin")},
    )
    assert completed.returncode != 0
    combined = (completed.stdout + completed.stderr).lower()
    assert "database_url" in combined or "required" in combined
