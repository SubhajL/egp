#!/usr/bin/env python3
"""Check whether local main matches the remote tracking branch and the worktree is clean."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys


def _run_git(repo_root: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=repo_root,
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip() or "git command failed"
        raise RuntimeError(f"`git {' '.join(args)}` failed: {detail}")
    return completed.stdout.rstrip("\n")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help="Git repository root to inspect.",
    )
    parser.add_argument("--remote", default="origin", help="Remote name to compare against.")
    parser.add_argument("--branch", default="main", help="Local branch name to compare.")
    parser.add_argument(
        "--no-fetch",
        action="store_true",
        help="Skip fetching the remote branch before comparing refs.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable JSON instead of a human summary.",
    )
    return parser


def _build_payload(
    *,
    repo_root: Path,
    remote: str,
    branch: str,
    fetch_performed: bool,
) -> dict[str, object]:
    current_branch = _run_git(repo_root, "branch", "--show-current")
    local_sha = _run_git(repo_root, "rev-parse", branch)
    remote_ref = f"{remote}/{branch}"
    remote_sha = _run_git(repo_root, "rev-parse", remote_ref)
    ahead_raw = _run_git(repo_root, "rev-list", "--left-right", "--count", f"{branch}...{remote_ref}")
    ahead_str, behind_str = ahead_raw.split()
    worktree_raw = _run_git(repo_root, "status", "--short")
    worktree_entries = [line for line in worktree_raw.splitlines() if line]
    ahead = int(ahead_str)
    behind = int(behind_str)
    branch_synced = ahead == 0 and behind == 0
    worktree_clean = not worktree_entries
    return {
        "repo_root": str(repo_root),
        "current_branch": current_branch,
        "target_branch": branch,
        "remote": remote,
        "remote_ref": remote_ref,
        "fetch_performed": fetch_performed,
        "local_sha": local_sha,
        "remote_sha": remote_sha,
        "ahead": ahead,
        "behind": behind,
        "branch_synced": branch_synced,
        "worktree_clean": worktree_clean,
        "worktree_entries": worktree_entries,
        "ok": branch_synced and worktree_clean,
    }


def _emit_human(payload: dict[str, object]) -> None:
    target = str(payload["target_branch"])
    remote_ref = str(payload["remote_ref"])
    if bool(payload["ok"]):
        print(f"OK: {target} matches {remote_ref} and the worktree is clean.")
        return
    if bool(payload["branch_synced"]) and not bool(payload["worktree_clean"]):
        print(f"DIRTY: {target} matches {remote_ref}, but the worktree has local changes.")
        for entry in payload["worktree_entries"]:
            print(f"  {entry}")
        return

    parts: list[str] = []
    ahead = int(payload["ahead"])
    behind = int(payload["behind"])
    if ahead:
        parts.append(f"ahead by {ahead}")
    if behind:
        parts.append(f"behind by {behind}")
    status = ", ".join(parts) if parts else "different"
    print(f"OUT-OF-SYNC: {target} is {status} relative to {remote_ref}.")
    if not bool(payload["worktree_clean"]):
        print("The worktree also has local changes:")
        for entry in payload["worktree_entries"]:
            print(f"  {entry}")


def main() -> int:
    args = _build_parser().parse_args()
    repo_root = Path(args.repo_root).resolve()

    try:
        if not args.no_fetch:
            _run_git(repo_root, "fetch", "--prune", args.remote, args.branch)
        payload = _build_payload(
            repo_root=repo_root,
            remote=str(args.remote),
            branch=str(args.branch),
            fetch_performed=not bool(args.no_fetch),
        )
    except RuntimeError as exc:
        if args.json:
            print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False, indent=2))
        else:
            print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        _emit_human(payload)
    return 0 if bool(payload["ok"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
