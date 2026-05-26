from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path


def _write_fake_rclone(bin_dir: Path, *, fail: bool = False) -> Path:
    bin_dir.mkdir(parents=True, exist_ok=True)
    log = bin_dir / "rclone.log"
    fake = bin_dir / "rclone"
    body = "#!/usr/bin/env bash\n"
    body += f'echo "$@" >> {log}\n'
    if fail:
        body += "exit 1\n"
    else:
        body += "exit 0\n"
    fake.write_text(body, encoding="ascii")
    fake.chmod(fake.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return log


def _run(
    script: Path, env: dict[str, str], args: list[str]
) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", str(script), *args],
        capture_output=True,
        text=True,
        env=env,
    )


def test_artifact_backup_help_exits_zero(repo_root: Path) -> None:
    script = repo_root / "scripts" / "artifact_backup.sh"
    completed = subprocess.run(
        ["bash", str(script), "--help"], capture_output=True, text=True
    )
    assert completed.returncode == 0
    combined = completed.stdout + completed.stderr
    assert "EGP_ARTIFACT_BACKUP_SRC_REMOTE" in combined
    assert "rclone" in combined.lower()


def test_artifact_backup_uses_rclone_copy_not_sync(
    repo_root: Path, tmp_path: Path
) -> None:
    bin_dir = tmp_path / "bin"
    log = _write_fake_rclone(bin_dir)
    env = {
        "PATH": f"{bin_dir}:{os.environ.get('PATH', '/usr/bin:/bin')}",
        "EGP_ARTIFACT_BACKUP_SRC_REMOTE": "supabase-prod:egp-documents",
        "EGP_ARTIFACT_BACKUP_DEST_REMOTE": "r2-backups:egp-artifacts-mirror",
    }
    completed = _run(repo_root / "scripts" / "artifact_backup.sh", env, [])
    assert completed.returncode == 0, completed.stderr
    log_contents = log.read_text(encoding="ascii")
    assert " copy " in log_contents or log_contents.startswith("copy ")
    assert "sync" not in log_contents


def test_artifact_backup_propagates_dry_run_flag(
    repo_root: Path, tmp_path: Path
) -> None:
    bin_dir = tmp_path / "bin"
    log = _write_fake_rclone(bin_dir)
    env = {
        "PATH": f"{bin_dir}:{os.environ.get('PATH', '/usr/bin:/bin')}",
        "EGP_ARTIFACT_BACKUP_SRC_REMOTE": "supabase-prod:egp-documents",
        "EGP_ARTIFACT_BACKUP_DEST_REMOTE": "r2-backups:egp-artifacts-mirror",
    }
    completed = _run(repo_root / "scripts" / "artifact_backup.sh", env, ["--dry-run"])
    assert completed.returncode == 0
    assert "--dry-run" in log.read_text(encoding="ascii")


def test_artifact_backup_requires_explicit_source_and_dest_remotes(
    repo_root: Path,
) -> None:
    env = {"PATH": "/usr/bin:/bin"}
    completed = _run(repo_root / "scripts" / "artifact_backup.sh", env, [])
    assert completed.returncode != 0
    combined = (completed.stdout + completed.stderr).lower()
    assert "egp_artifact_backup_src_remote" in combined


def test_artifact_backup_hard_fails_when_rclone_missing(
    repo_root: Path,
) -> None:
    # Sanitized PATH that does not contain rclone
    env = {
        "PATH": "/usr/bin:/bin",
        "EGP_ARTIFACT_BACKUP_SRC_REMOTE": "supabase-prod:egp-documents",
        "EGP_ARTIFACT_BACKUP_DEST_REMOTE": "r2-backups:egp-artifacts-mirror",
    }
    completed = _run(repo_root / "scripts" / "artifact_backup.sh", env, [])
    assert completed.returncode != 0
    combined = (completed.stdout + completed.stderr).lower()
    assert "rclone" in combined
