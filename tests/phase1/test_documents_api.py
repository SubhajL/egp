from __future__ import annotations

import base64

from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError
from sqlalchemy import text

from egp_api.main import create_app
from egp_db.repositories.project_repo import build_project_upsert_record
from egp_shared_types.enums import ProcurementType, ProjectState

TENANT_ID = "11111111-1111-1111-1111-111111111111"


class FakeSupabaseBucket:
    def __init__(self, bucket_name: str) -> None:
        self.bucket_name = bucket_name
        self.upload_calls: list[dict[str, object]] = []
        self.sign_calls: list[dict[str, object]] = []

    def upload(self, path: str, file, file_options: dict[str, object] | None = None):
        self.upload_calls.append(
            {
                "path": path,
                "file": file,
                "file_options": file_options or {},
            }
        )
        return {"path": path}

    def create_signed_url(
        self,
        path: str,
        expires_in: int,
        options: dict[str, object] | None = None,
    ):
        self.sign_calls.append(
            {
                "path": path,
                "expires_in": expires_in,
                "options": options or {},
            }
        )
        return {"signedURL": f"https://project.supabase.co/storage/v1/object/sign/{self.bucket_name}/{path}"}

    def remove(self, paths: list[str]):
        return {"paths": paths}


class FakeSupabaseStorageClient:
    def __init__(self) -> None:
        self.buckets: dict[str, FakeSupabaseBucket] = {}

    def from_(self, bucket_name: str) -> FakeSupabaseBucket:
        bucket = self.buckets.get(bucket_name)
        if bucket is None:
            bucket = FakeSupabaseBucket(bucket_name)
            self.buckets[bucket_name] = bucket
        return bucket


class FakeSupabaseClient:
    def __init__(self) -> None:
        self.storage = FakeSupabaseStorageClient()


def seed_tenant(client: TestClient) -> None:
    with client.app.state.db_engine.begin() as connection:
        try:
            existing = connection.execute(
                text("SELECT 1 FROM tenants WHERE id = :tenant_id"),
                {"tenant_id": TENANT_ID},
            ).first()
        except OperationalError:
            return

        if existing is None:
            connection.execute(
                text(
                    """
                    INSERT INTO tenants (id, name, slug, plan_code)
                    VALUES (:tenant_id, :name, :slug, :plan_code)
                    """
                ),
                {
                    "tenant_id": TENANT_ID,
                    "name": "Documents Test Tenant",
                    "slug": "documents-test-tenant",
                    "plan_code": "dev",
                },
            )


def seed_project(client: TestClient) -> str:
    seed_tenant(client)
    project = client.app.state.project_repository.upsert_project(
        build_project_upsert_record(
            tenant_id=TENANT_ID,
            project_number="EGP-2026-DOCS",
            search_name="ระบบเอกสาร",
            detail_name="จัดซื้อระบบเอกสาร",
            project_name="จัดซื้อระบบเอกสาร",
            organization_name="กรมตัวอย่าง",
            proposal_submission_date="2026-05-01",
            budget_amount="1500000.00",
            procurement_type=ProcurementType.SERVICES,
            project_state=ProjectState.OPEN_INVITATION,
        ),
        source_status_text="ประกาศเชิญชวน",
    )
    return project.id


def test_ingest_document_endpoint_persists_and_classifies_document(tmp_path) -> None:
    client = TestClient(create_app(artifact_root=tmp_path, auth_required=False))
    project_id = seed_project(client)

    response = client.post(
        "/v1/documents/ingest",
        json={
            "tenant_id": TENANT_ID,
            "project_id": project_id,
            "file_name": "tor.pdf",
            "content_base64": base64.b64encode(b"draft-tor").decode("ascii"),
            "source_label": "ร่างขอบเขตของงาน",
            "source_status_text": "เปิดรับฟังคำวิจารณ์",
        },
    )

    body = response.json()
    assert response.status_code == 201
    assert body["created"] is True
    assert body["document"]["document_type"] == "tor"
    assert body["document"]["document_phase"] == "public_hearing"


def test_ingest_document_endpoint_is_idempotent_for_duplicate_bytes(tmp_path) -> None:
    client = TestClient(create_app(artifact_root=tmp_path, auth_required=False))
    project_id = seed_project(client)
    payload = {
        "tenant_id": TENANT_ID,
        "project_id": project_id,
        "file_name": "tor.pdf",
        "content_base64": base64.b64encode(b"same-bytes").decode("ascii"),
        "source_label": "ร่างขอบเขตของงาน",
        "source_status_text": "เปิดรับฟังคำวิจารณ์",
    }

    first = client.post("/v1/documents/ingest", json=payload)
    second = client.post("/v1/documents/ingest", json=payload)

    assert first.status_code == 201
    assert second.status_code == 200
    assert second.json()["created"] is False
    assert second.json()["document"]["id"] == first.json()["document"]["id"]


def test_list_documents_endpoint_returns_persisted_documents(tmp_path) -> None:
    client = TestClient(create_app(artifact_root=tmp_path, auth_required=False))
    project_id = seed_project(client)
    ingest_response = client.post(
        "/v1/documents/ingest",
        json={
            "tenant_id": TENANT_ID,
            "project_id": project_id,
            "file_name": "mid-price.pdf",
            "content_base64": base64.b64encode(b"mid-price").decode("ascii"),
            "source_label": "ประกาศราคากลาง",
            "source_status_text": "ประกาศราคากลาง",
        },
    )
    assert ingest_response.status_code == 201

    response = client.get(f"/v1/documents/projects/{project_id}", params={"tenant_id": TENANT_ID})

    assert response.status_code == 200
    body = response.json()
    assert len(body["documents"]) == 1
    assert body["documents"][0]["document_type"] == "mid_price"


def test_ingest_document_endpoint_keeps_same_bytes_for_different_phase(tmp_path) -> None:
    client = TestClient(create_app(artifact_root=tmp_path, auth_required=False))
    project_id = seed_project(client)
    payload = {
        "tenant_id": TENANT_ID,
        "project_id": project_id,
        "content_base64": base64.b64encode(b"same-tor-bytes").decode("ascii"),
    }

    first = client.post(
        "/v1/documents/ingest",
        json={
            **payload,
            "file_name": "tor-hearing.pdf",
            "source_label": "ร่างขอบเขตของงาน",
            "source_status_text": "เปิดรับฟังคำวิจารณ์",
        },
    )
    second = client.post(
        "/v1/documents/ingest",
        json={
            **payload,
            "file_name": "tor-final.pdf",
            "source_label": "เอกสารประกวดราคา",
            "source_status_text": "ประกาศเชิญชวน",
        },
    )
    listed = client.get(f"/v1/documents/projects/{project_id}", params={"tenant_id": TENANT_ID})

    assert first.status_code == 201
    assert second.status_code == 201
    assert len(listed.json()["documents"]) == 2


def test_document_download_endpoint_returns_storage_backed_url(tmp_path) -> None:
    client = TestClient(create_app(artifact_root=tmp_path, auth_required=False))
    project_id = seed_project(client)
    ingest_response = client.post(
        "/v1/documents/ingest",
        json={
            "tenant_id": TENANT_ID,
            "project_id": project_id,
            "file_name": "tor.pdf",
            "content_base64": base64.b64encode(b"tor-bytes").decode("ascii"),
            "source_label": "เอกสารประกวดราคา",
            "source_status_text": "ประกาศเชิญชวน",
        },
    )
    document_id = ingest_response.json()["document"]["id"]
    storage_key = ingest_response.json()["document"]["storage_key"]

    response = client.get(
        f"/v1/documents/{document_id}/download",
        params={"tenant_id": TENANT_ID},
    )

    assert response.status_code == 200
    assert response.json()["download_url"] == str((tmp_path / storage_key).resolve())


def test_document_download_endpoint_returns_supabase_signed_url(tmp_path) -> None:
    supabase_client = FakeSupabaseClient()
    client = TestClient(
        create_app(
            artifact_root=tmp_path,
            auth_required=False,
            artifact_storage_backend="supabase",
            artifact_bucket="egp-documents",
            supabase_url="https://project.supabase.co",
            supabase_service_role_key="service-role-key",
            supabase_client=supabase_client,
        )
    )
    project_id = seed_project(client)
    ingest_response = client.post(
        "/v1/documents/ingest",
        json={
            "tenant_id": TENANT_ID,
            "project_id": project_id,
            "file_name": "tor.pdf",
            "content_base64": base64.b64encode(b"tor-bytes").decode("ascii"),
            "source_label": "เอกสารประกวดราคา",
            "source_status_text": "ประกาศเชิญชวน",
        },
    )
    document_id = ingest_response.json()["document"]["id"]
    storage_key = ingest_response.json()["document"]["storage_key"]

    response = client.get(
        f"/v1/documents/{document_id}/download",
        params={"tenant_id": TENANT_ID, "expires_in": 900},
    )

    assert response.status_code == 200
    assert response.json()["download_url"] == (
        f"https://project.supabase.co/storage/v1/object/sign/egp-documents/{storage_key}"
    )
