from __future__ import annotations

from datetime import UTC, datetime, timedelta

from egp_db.repositories.document_repo import build_document_record
from egp_db.repositories.project_repo import build_project_upsert_record
from egp_shared_types.enums import ClosedReason, DocumentPhase, DocumentType, ProcurementType
from egp_worker.workflows.document_ingest import ingest_document_artifact
from egp_worker.workflows.timeout_sweep import evaluate_timeout_transition

TENANT_ID = "11111111-1111-1111-1111-111111111111"
PROJECT_ID = "22222222-2222-2222-2222-222222222222"


def test_build_project_upsert_record_wires_canonical_id_and_aliases() -> None:
    record = build_project_upsert_record(
        tenant_id="tenant-1",
        project_number="EGP-2026-0042",
        search_name="ระบบข้อมูลกลาง",
        detail_name="โครงการระบบข้อมูลกลาง",
        project_name="โครงการระบบข้อมูลกลาง",
        organization_name="กรมตัวอย่าง",
        proposal_submission_date="2026-05-01",
        budget_amount="1500000.00",
        procurement_type=ProcurementType.SERVICES,
    )

    assert record.canonical_project_id == "project-number:EGP-2026-0042"
    assert ("project_number", "EGP-2026-0042") in record.aliases
    assert ("search_name", "ระบบข้อมูลกลาง") in record.aliases


def test_build_document_record_wires_hasher_and_classifier() -> None:
    record = build_document_record(
        project_id="project-1",
        file_name="tor.pdf",
        file_bytes=b"tor-document-content",
        source_label="ร่างขอบเขตของงาน (TOR) สำหรับประชาพิจารณ์",
        source_status_text="เปิดรับฟังคำวิจารณ์",
        storage_key="tenant-1/project-1/tor.pdf",
    )

    assert record.document_type is DocumentType.TOR
    assert record.document_phase is DocumentPhase.PUBLIC_HEARING
    assert len(record.sha256) == 64


def test_evaluate_timeout_transition_wires_closure_rules_and_lifecycle() -> None:
    now = datetime(2026, 4, 2, tzinfo=UTC)
    result = evaluate_timeout_transition(
        procurement_type=ProcurementType.CONSULTING,
        project_state="open_consulting",
        last_changed_at=now - timedelta(days=31),
        now=now,
    )

    assert result is not None
    assert result["closed_reason"] is ClosedReason.CONSULTING_TIMEOUT_30D


def test_worker_document_ingest_wires_repository_backed_persistence(tmp_path) -> None:
    result = ingest_document_artifact(
        artifact_root=tmp_path,
        tenant_id=TENANT_ID,
        project_id=PROJECT_ID,
        file_name="tor.pdf",
        file_bytes=b"worker-ingested-tor",
        source_label="ร่างขอบเขตของงาน",
        source_status_text="เปิดรับฟังคำวิจารณ์",
    )

    assert result.created is True
    assert result.document.document_type is DocumentType.TOR
    assert (tmp_path / result.document.storage_key).read_bytes() == b"worker-ingested-tor"
