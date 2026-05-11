from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys


def _run_git(*args: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    )


def _seed_remote(tmp_path: Path) -> tuple[Path, Path]:
    remote = tmp_path / "remote.git"
    seed = tmp_path / "seed"
    work = tmp_path / "work"
    _run_git("init", "--bare", str(remote), cwd=tmp_path)
    _run_git("clone", str(remote), str(seed), cwd=tmp_path)
    _run_git("config", "user.name", "Codex Test", cwd=seed)
    _run_git("config", "user.email", "codex@example.com", cwd=seed)
    (seed / "README.md").write_text("seed\n", encoding="utf-8")
    _run_git("add", "README.md", cwd=seed)
    _run_git("commit", "-m", "seed", cwd=seed)
    _run_git("branch", "-M", "main", cwd=seed)
    _run_git("push", "-u", "origin", "main", cwd=seed)
    _run_git("symbolic-ref", "HEAD", "refs/heads/main", cwd=remote)
    _run_git("clone", str(remote), str(work), cwd=tmp_path)
    _run_git("config", "user.name", "Codex Test", cwd=work)
    _run_git("config", "user.email", "codex@example.com", cwd=work)
    return seed, work


def _run_sync_script(repo_root: Path, *, target_repo: Path) -> subprocess.CompletedProcess[str]:
    script_path = repo_root / "scripts" / "check_main_sync.py"
    return subprocess.run(
        [sys.executable, str(script_path), "--repo-root", str(target_repo), "--json"],
        check=False,
        capture_output=True,
        text=True,
    )


def test_check_main_sync_reports_clean_synced_repo(tmp_path, repo_root: Path) -> None:
    _, work = _seed_remote(tmp_path)

    completed = _run_sync_script(repo_root, target_repo=work)

    assert completed.returncode == 0
    payload = json.loads(completed.stdout)
    assert payload["branch_synced"] is True
    assert payload["worktree_clean"] is True
    assert payload["ok"] is True
    assert payload["ahead"] == 0
    assert payload["behind"] == 0


def test_check_main_sync_reports_dirty_repo_even_when_commits_match(
    tmp_path, repo_root: Path
) -> None:
    _, work = _seed_remote(tmp_path)
    (work / "README.md").write_text("dirty\n", encoding="utf-8")

    completed = _run_sync_script(repo_root, target_repo=work)

    assert completed.returncode == 1
    payload = json.loads(completed.stdout)
    assert payload["branch_synced"] is True
    assert payload["worktree_clean"] is False
    assert payload["ok"] is False
    assert payload["worktree_entries"] == [" M README.md"]


def test_check_main_sync_reports_when_local_main_is_behind_remote(
    tmp_path, repo_root: Path
) -> None:
    seed, work = _seed_remote(tmp_path)
    (seed / "README.md").write_text("ahead\n", encoding="utf-8")
    _run_git("add", "README.md", cwd=seed)
    _run_git("commit", "-m", "ahead", cwd=seed)
    _run_git("push", "origin", "main", cwd=seed)

    completed = _run_sync_script(repo_root, target_repo=work)

    assert completed.returncode == 1
    payload = json.loads(completed.stdout)
    assert payload["branch_synced"] is False
    assert payload["worktree_clean"] is True
    assert payload["ok"] is False
    assert payload["ahead"] == 0
    assert payload["behind"] == 1
