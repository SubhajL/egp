from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

from egp_db.dev_postgres import (
    build_local_dev_postgres_config,
    get_local_dev_postgres_status,
    postgres_binaries_available,
    run_phase1_postgres_project_run_smoke,
    run_phase1_postgres_smoke,
)


def test_run_phase1_postgres_smoke_round_trips_document_metadata_and_blob(
    tmp_path,
) -> None:
    if not postgres_binaries_available():
        return

    result = run_phase1_postgres_smoke(
        repo_root=Path(__file__).resolve().parents[2],
        artifact_root=tmp_path / "artifacts",
    )

    assert result["status_code"] == 201
    assert result["listed_documents"] == 1
    assert result["download_status_code"] == 200
    assert result["download_content_type"] == "application/pdf"
    assert result["download_size"] == len(b"smoke-tor")


def test_run_phase1_postgres_project_and_run_smoke_round_trips_repositories() -> None:
    if not postgres_binaries_available():
        return

    result = run_phase1_postgres_project_run_smoke(
        repo_root=Path(__file__).resolve().parents[2],
    )

    assert result["project_id"]
    assert result["alias_count"] == 4
    assert result["status_event_count"] == 1
    assert result["run_status"] == "succeeded"
    assert result["task_count"] == 1


def test_build_local_dev_postgres_config_uses_repo_data_dir_defaults(tmp_path) -> None:
    config = build_local_dev_postgres_config(repo_root=tmp_path)

    assert config.root_dir == tmp_path / ".data" / "local-postgres"
    assert config.data_dir == config.root_dir / "data"
    assert config.log_path == config.root_dir / "postgres.log"
    assert config.postgres_url == "postgresql://egp@127.0.0.1:55432/postgres"
    assert config.database_url == "postgresql://egp@127.0.0.1:55432/egp"


def test_get_local_dev_postgres_status_reports_uninitialized_cluster(tmp_path) -> None:
    status = get_local_dev_postgres_status(repo_root=tmp_path)

    assert status["initialized"] is False
    assert status["running"] is False
    assert status["database_url"] == "postgresql://egp@127.0.0.1:55432/egp"


def test_local_postgres_dev_status_cli_emits_json(tmp_path) -> None:
    repo_root = Path(__file__).resolve().parents[2]
    script_path = repo_root / "scripts" / "local_postgres_dev.py"

    completed = subprocess.run(
        [sys.executable, str(script_path), "status", "--repo-root", str(tmp_path)],
        check=True,
        capture_output=True,
        text=True,
    )

    payload = json.loads(completed.stdout)
    assert payload["initialized"] is False
    assert payload["running"] is False
    assert payload["database_url"] == "postgresql://egp@127.0.0.1:55432/egp"
