from __future__ import annotations

from pathlib import Path

from egp_db.dev_postgres import (
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
    assert result["download_url"]


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
