from __future__ import annotations

import base64
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import text

from egp_api.main import create_app
from egp_db.repositories.project_repo import build_project_upsert_record
from egp_shared_types.enums import ProcurementType, ProjectState
from egp_worker.workflows import document_ingest as worker_document_ingest
from egp_worker.workflows.document_ingest import ingest_document_artifact

TENANT_ID = "11111111-1111-1111-1111-111111111111"


def _create_test_client(tmp_path, *, database_name: str) -> TestClient:
    return TestClient(
        create_app(
            artifact_root=tmp_path / f"{database_name}-artifacts",
            database_url=f"sqlite+pysqlite:///{tmp_path / f'{database_name}.sqlite3'}",
            auth_required=False,
        )
    )


def _seed_public_hearing_project(client: TestClient, *, project_number: str) -> str:
    project = client.app.state.project_repository.upsert_project(
        build_project_upsert_record(
            tenant_id=TENANT_ID,
            project_number=project_number,
            search_name="ระบบเอกสาร",
            detail_name="จัดซื้อระบบเอกสาร",
            project_name="จัดซื้อระบบเอกสาร",
            organization_name="กรมตัวอย่าง",
            proposal_submission_date="2026-05-01",
            budget_amount="1500000.00",
            procurement_type=ProcurementType.SERVICES,
            project_state=ProjectState.OPEN_PUBLIC_HEARING,
        ),
        source_status_text="เปิดรับฟังคำวิจารณ์",
    )
    return project.id


def _api_ingest(
    client: TestClient,
    *,
    project_id: str,
    file_name: str,
    file_bytes: bytes,
) -> dict[str, Any]:
    response = client.post(
        "/v1/documents/ingest",
        json={
            "tenant_id": TENANT_ID,
            "project_id": project_id,
            "file_name": file_name,
            "content_base64": base64.b64encode(file_bytes).decode("ascii"),
            "source_label": "เอกสารประกวดราคา",
            "source_status_text": "",
        },
    )
    assert response.status_code == 201
    return response.json()


def _worker_ingest(
    client: TestClient,
    tmp_path,
    *,
    database_name: str,
    project_id: str,
    file_name: str,
    file_bytes: bytes,
):
    return ingest_document_artifact(
        artifact_root=tmp_path / f"{database_name}-artifacts",
        database_url=f"sqlite+pysqlite:///{tmp_path / f'{database_name}.sqlite3'}",
        tenant_id=TENANT_ID,
        project_id=project_id,
        file_name=file_name,
        file_bytes=file_bytes,
        source_label="เอกสารประกวดราคา",
        source_status_text="",
    )


def _stable_document_contract(document: dict[str, Any]) -> dict[str, Any]:
    return {
        "file_name": document["file_name"],
        "sha256": document["sha256"],
        "document_type": document["document_type"],
        "document_phase": document["document_phase"],
        "source_label": document["source_label"],
        "source_status_text": document["source_status_text"],
        "size_bytes": document["size_bytes"],
        "is_current": document["is_current"],
        "has_supersedes_document_id": document["supersedes_document_id"] is not None,
    }


def _stable_worker_document_contract(result) -> dict[str, Any]:
    return {
        "file_name": result.document.file_name,
        "sha256": result.document.sha256,
        "document_type": result.document.document_type.value,
        "document_phase": result.document.document_phase.value,
        "source_label": result.document.source_label,
        "source_status_text": result.document.source_status_text,
        "size_bytes": result.document.size_bytes,
        "is_current": result.document.is_current,
        "has_supersedes_document_id": result.document.supersedes_document_id is not None,
    }


def _stable_diff_contract(diff: dict[str, Any]) -> dict[str, Any]:
    summary_json = diff["summary_json"] or {}
    return {
        "diff_type": diff["diff_type"],
        "comparison_scope": summary_json.get("comparison_scope"),
        "old_document_phase": summary_json.get("old_document_phase"),
        "new_document_phase": summary_json.get("new_document_phase"),
        "text_diff_available": summary_json.get("text_diff_available"),
    }


def _stable_worker_diff_contract(result) -> dict[str, Any]:
    diff = result.diff_records[0]
    summary_json = diff.summary_json or {}
    return {
        "diff_type": diff.diff_type,
        "comparison_scope": summary_json.get("comparison_scope"),
        "old_document_phase": summary_json.get("old_document_phase"),
        "new_document_phase": summary_json.get("new_document_phase"),
        "text_diff_available": summary_json.get("text_diff_available"),
    }


def test_worker_document_ingest_routes_through_canonical_service_boundary(
    tmp_path, monkeypatch
) -> None:
    captured: dict[str, Any] = {}
    expected_result = object()

    class ExplodingRepository:
        def store_document(self, **kwargs: object) -> object:
            raise AssertionError("worker must delegate to DocumentIngestService")

    class RecordingDocumentIngestService:
        def __init__(self, repository: object, **kwargs: object) -> None:
            captured["repository"] = repository
            captured["service_kwargs"] = kwargs

        def ingest_document_bytes(self, **kwargs: object) -> object:
            captured["ingest_kwargs"] = kwargs
            return expected_result

    repository = ExplodingRepository()
    monkeypatch.setattr(
        worker_document_ingest,
        "DocumentIngestService",
        RecordingDocumentIngestService,
    )

    result = ingest_document_artifact(
        artifact_root=tmp_path / "artifacts",
        database_url=f"sqlite+pysqlite:///{tmp_path / 'canonical-service.sqlite3'}",
        repository=repository,
        tenant_id=TENANT_ID,
        project_id="project-1",
        file_name="tor.pdf",
        file_bytes=b"tor-bytes",
        source_label="เอกสารประกวดราคา",
        source_status_text="เปิดรับฟังคำวิจารณ์",
        source_page_text="detail-page",
        project_state=ProjectState.OPEN_PUBLIC_HEARING.value,
    )

    assert result is expected_result
    assert captured["repository"] is repository
    assert captured["ingest_kwargs"] == {
        "tenant_id": TENANT_ID,
        "project_id": "project-1",
        "file_name": "tor.pdf",
        "file_bytes": b"tor-bytes",
        "source_label": "เอกสารประกวดราคา",
        "source_status_text": "เปิดรับฟังคำวิจารณ์",
        "source_page_text": "detail-page",
        "project_state": ProjectState.OPEN_PUBLIC_HEARING.value,
        "actor_subject": "system:worker",
    }


def test_api_and_worker_document_ingest_share_project_context_contract(tmp_path) -> None:
    api_client = _create_test_client(tmp_path, database_name="api")
    worker_client = _create_test_client(tmp_path, database_name="worker")
    api_project_id = _seed_public_hearing_project(
        api_client, project_number="EGP-2026-CONTRACT-API"
    )
    worker_project_id = _seed_public_hearing_project(
        worker_client, project_number="EGP-2026-CONTRACT-WORKER"
    )

    api_first = _api_ingest(
        api_client,
        project_id=api_project_id,
        file_name="tor-v1.pdf",
        file_bytes=b"version-one",
    )
    api_second = _api_ingest(
        api_client,
        project_id=api_project_id,
        file_name="tor-v2.pdf",
        file_bytes=b"version-two",
    )
    worker_first = _worker_ingest(
        worker_client,
        tmp_path,
        database_name="worker",
        project_id=worker_project_id,
        file_name="tor-v1.pdf",
        file_bytes=b"version-one",
    )
    worker_second = _worker_ingest(
        worker_client,
        tmp_path,
        database_name="worker",
        project_id=worker_project_id,
        file_name="tor-v2.pdf",
        file_bytes=b"version-two",
    )

    assert _stable_document_contract(api_first["document"]) == _stable_worker_document_contract(
        worker_first
    )
    assert _stable_document_contract(api_second["document"]) == _stable_worker_document_contract(
        worker_second
    )
    assert len(api_second["diff_records"]) == 1
    assert len(worker_second.diff_records) == 1
    assert _stable_diff_contract(api_second["diff_records"][0]) == _stable_worker_diff_contract(
        worker_second
    )


def test_cross_path_document_retry_is_idempotent(tmp_path) -> None:
    client = _create_test_client(tmp_path, database_name="retry")
    project_id = _seed_public_hearing_project(
        client, project_number="EGP-2026-CONTRACT-RETRY"
    )
    api_result = _api_ingest(
        client,
        project_id=project_id,
        file_name="tor.pdf",
        file_bytes=b"same-retried-artifact",
    )

    retry_result = _worker_ingest(
        client,
        tmp_path,
        database_name="retry",
        project_id=project_id,
        file_name="tor-retry.pdf",
        file_bytes=b"same-retried-artifact",
    )

    with client.app.state.db_engine.connect() as connection:
        row = connection.execute(
            text(
                """
                SELECT
                    (SELECT COUNT(*) FROM documents WHERE project_id = :project_id),
                    (SELECT COUNT(*) FROM document_diffs WHERE project_id = :project_id),
                    (SELECT COUNT(*) FROM document_diff_reviews WHERE project_id = :project_id)
                """
            ),
            {"project_id": project_id},
        ).one()

    assert retry_result.created is False
    assert retry_result.document.id == api_result["document"]["id"]
    assert retry_result.diff_records == []
    assert row == (1, 0, 0)
