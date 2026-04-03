#!/usr/bin/env python3
"""Run a Dockerless Phase 1 document persistence smoke test."""

from __future__ import annotations

import json
from pathlib import Path

from egp_db.dev_postgres import postgres_binaries_available, run_phase1_postgres_smoke
from egp_db.dev_postgres import run_phase1_postgres_project_run_smoke


def main() -> int:
    repo_root = Path(__file__).resolve().parents[1]
    artifact_root = repo_root / ".data" / "phase1-postgres-smoke"

    if not postgres_binaries_available():
        print("PostgreSQL binaries are not available on PATH.")
        return 1

    result = run_phase1_postgres_smoke(repo_root=repo_root, artifact_root=artifact_root)
    repo_result = run_phase1_postgres_project_run_smoke(repo_root=repo_root)
    print(
        json.dumps(
            {
                "document_smoke": result,
                "project_run_smoke": repo_result,
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
