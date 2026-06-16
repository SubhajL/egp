from __future__ import annotations

from pathlib import Path


def test_restore_drill_evidence_records_required_dr_outcomes(repo_root: Path) -> None:
    evidence = repo_root / "docs" / "DR_RESTORE_DRILL_EVIDENCE.md"
    assert evidence.exists()
    text = evidence.read_text(encoding="utf-8")
    required_markers = [
        "2026-06-16",
        "tests/operations/test_pg_backup_restore.py::test_pg_backup_restore_round_trips_temp_postgres",
        "restored_tenant_count=2",
        "restored_project_count=1",
        "restored_document_count=1",
        "restored_billing_record_count=1",
        "tenant_isolation_preserved=True",
        "document_sha256_preserved=True",
        "billing_status_preserved=True",
        "sha256_verified=True",
        "EGP_ARTIFACT_BACKUP_SRC_REMOTE",
        "EGP_ARTIFACT_BACKUP_DEST_REMOTE",
    ]
    missing = [marker for marker in required_markers if marker not in text]
    assert not missing, f"restore-drill evidence missing markers: {missing}"
