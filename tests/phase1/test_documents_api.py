from __future__ import annotations

import base64
from datetime import UTC, date, datetime, timedelta
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import OperationalError

from egp_api.main import create_app
from egp_db.google_drive import GoogleDriveOAuthConfig
from egp_db.onedrive import OneDriveOAuthConfig
from egp_db.repositories.admin_repo import create_admin_repository
from egp_shared_types.enums import NotificationType
from egp_db.storage_credentials import StorageCredentialCipher
from egp_db.repositories.project_repo import build_project_upsert_record
from egp_shared_types.enums import (
    DocumentReviewEventType,
    DocumentReviewStatus,
    ProcurementType,
    ProjectState,
)

TENANT_ID = "11111111-1111-1111-1111-111111111111"


class FakeSupabaseBucket:
    def __init__(self, bucket_name: str) -> None:
        self.bucket_name = bucket_name
        self.upload_calls: list[dict[str, object]] = []
        self.sign_calls: list[dict[str, object]] = []
        self.files: dict[str, bytes] = {}

    def upload(self, path: str, file, file_options: dict[str, object] | None = None):
        payload = file if isinstance(file, bytes) else bytes(file)
        self.files[path] = payload
        self.upload_calls.append(
            {
                "path": path,
                "file": payload,
                "file_options": file_options or {},
            }
        )
        return {"path": path}

    def download(self, path: str):
        return self.files[path]

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
        return {
            "signedURL": f"https://project.supabase.co/storage/v1/object/sign/{self.bucket_name}/{path}"
        }

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


class FakeGoogleDriveDownloadClient:
    def __init__(
        self,
        *,
        download_url: str = "https://drive.example/drive-file-id",
        download_bytes: bytes = b"drive-bytes",
        download_exception: Exception | None = None,
    ) -> None:
        self.download_url_value = download_url
        self.download_bytes_value = download_bytes
        self.download_exception = download_exception
        self.refresh_calls: list[str] = []
        self.download_url_calls: list[str] = []
        self.download_file_calls: list[str] = []

    def refresh_access_token(
        self,
        *,
        config: GoogleDriveOAuthConfig,
        refresh_token: str,
    ) -> dict[str, object]:
        self.refresh_calls.append(refresh_token)
        return {"access_token": f"access-for-{config.client_id}"}

    def download_url(self, *, file_id: str) -> str:
        self.download_url_calls.append(file_id)
        return self.download_url_value

    def download_file(self, *, access_token: str, file_id: str) -> bytes:
        self.download_file_calls.append(file_id)
        if self.download_exception is not None:
            raise self.download_exception
        return self.download_bytes_value


class FakeOneDriveDownloadClient:
    def __init__(
        self,
        *,
        download_url: str = "https://onedrive.example/onedrive-item-id",
        download_bytes: bytes = b"onedrive-bytes",
    ) -> None:
        self.download_url_value = download_url
        self.download_bytes_value = download_bytes
        self.refresh_calls: list[str] = []
        self.download_url_calls: list[str] = []
        self.download_file_calls: list[str] = []

    def refresh_access_token(
        self,
        *,
        config: OneDriveOAuthConfig,
        refresh_token: str,
    ) -> dict[str, object]:
        self.refresh_calls.append(refresh_token)
        return {"access_token": f"access-for-{config.client_id}"}

    def download_url(self, *, access_token: str, file_id: str) -> str:
        self.download_url_calls.append(file_id)
        return self.download_url_value

    def download_file(self, *, access_token: str, file_id: str) -> bytes:
        self.download_file_calls.append(file_id)
        return self.download_bytes_value


def _google_config() -> GoogleDriveOAuthConfig:
    return GoogleDriveOAuthConfig(
        client_id="google-client-id",
        client_secret="google-client-secret",
        redirect_uri="https://api.example/v1/admin/storage/google-drive/oauth/callback",
    )


def _onedrive_config() -> OneDriveOAuthConfig:
    return OneDriveOAuthConfig(
        client_id="onedrive-client-id",
        client_secret="onedrive-client-secret",
        redirect_uri="https://api.example/v1/admin/storage/onedrive/oauth/callback",
    )


def create_test_client(
    tmp_path, *, raise_server_exceptions: bool = True, **overrides
) -> TestClient:
    client = TestClient(
        create_app(
            artifact_root=tmp_path,
            database_url=f"sqlite+pysqlite:///{tmp_path / 'phase1.sqlite3'}",
            auth_required=False,
            **overrides,
        ),
        raise_server_exceptions=raise_server_exceptions,
    )
    seed_active_subscription(client)
    return client


def seed_active_subscription(client: TestClient) -> None:
    today = date.today()
    now = datetime.now(UTC).isoformat()
    record_id = str(uuid4())
    with client.app.state.db_engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO billing_records (
                    id,
                    tenant_id,
                    record_number,
                    plan_code,
                    status,
                    billing_period_start,
                    billing_period_end,
                    currency,
                    amount_due,
                    created_at,
                    updated_at
                ) VALUES (
                    :id,
                    :tenant_id,
                    :record_number,
                    'monthly_membership',
                    'paid',
                    :billing_period_start,
                    :billing_period_end,
                    'THB',
                    '1500.00',
                    :created_at,
                    :updated_at
                )
                """
            ),
            {
                "id": record_id,
                "tenant_id": TENANT_ID,
                "record_number": f"INV-{record_id[:8]}",
                "billing_period_start": (today - timedelta(days=1)).isoformat(),
                "billing_period_end": (today + timedelta(days=29)).isoformat(),
                "created_at": now,
                "updated_at": now,
            },
        )
        connection.execute(
            text(
                """
                INSERT INTO billing_subscriptions (
                    id,
                    tenant_id,
                    billing_record_id,
                    plan_code,
                    status,
                    billing_period_start,
                    billing_period_end,
                    keyword_limit,
                    activated_at,
                    created_at,
                    updated_at
                ) VALUES (
                    :id,
                    :tenant_id,
                    :billing_record_id,
                    'monthly_membership',
                    'active',
                    :billing_period_start,
                    :billing_period_end,
                    5,
                    :activated_at,
                    :created_at,
                    :updated_at
                )
                """
            ),
            {
                "id": str(uuid4()),
                "tenant_id": TENANT_ID,
                "billing_record_id": record_id,
                "billing_period_start": (today - timedelta(days=1)).isoformat(),
                "billing_period_end": (today + timedelta(days=29)).isoformat(),
                "activated_at": now,
                "created_at": now,
                "updated_at": now,
            },
        )


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
            now = datetime.now(UTC).isoformat()
            connection.execute(
                text(
                    """
                    INSERT INTO tenants (
                        id,
                        name,
                        slug,
                        plan_code,
                        is_active,
                        created_at,
                        updated_at
                    ) VALUES (
                        :tenant_id,
                        :name,
                        :slug,
                        :plan_code,
                        :is_active,
                        :created_at,
                        :updated_at
                    )
                    """
                ),
                {
                    "tenant_id": TENANT_ID,
                    "name": "Documents Test Tenant",
                    "slug": "documents-test-tenant",
                    "plan_code": "dev",
                    "is_active": True,
                    "created_at": now,
                    "updated_at": now,
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


def seed_external_storage(
    client: TestClient,
    *,
    provider: str,
    refresh_token: str | None = "provider-refresh-token",
    connection_status: str = "connected",
    storage_secret: str = "phase1-storage-secret",
) -> None:
    repository = create_admin_repository(
        engine=client.app.state.db_engine,
    )
    now = datetime.now(UTC)
    encrypted_payload = (
        StorageCredentialCipher(storage_secret).encrypt_dict(
            {"refresh_token": refresh_token}
        )
        if refresh_token is not None
        else None
    )
    with repository._engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT OR REPLACE INTO tenant_storage_configs (
                    id,
                    tenant_id,
                    provider,
                    connection_status,
                    provider_folder_id,
                    provider_folder_url,
                    managed_fallback_enabled,
                    managed_backup_enabled,
                    created_at,
                    updated_at
                ) VALUES (
                    :id,
                    :tenant_id,
                    :provider,
                    :connection_status,
                    :provider_folder_id,
                    :provider_folder_url,
                    0,
                    0,
                    :now,
                    :now
                )
                """
            ),
            {
                "id": str(uuid4()),
                "tenant_id": TENANT_ID,
                "provider": provider,
                "connection_status": connection_status,
                "provider_folder_id": f"{provider}-folder-id",
                "provider_folder_url": f"https://example.com/{provider}/folder",
                "now": now,
            },
        )
        if encrypted_payload is not None:
            connection.execute(
                text(
                    """
                    INSERT OR REPLACE INTO tenant_storage_credentials (
                        id,
                        tenant_id,
                        provider,
                        credential_type,
                        encrypted_payload,
                        created_at,
                        updated_at
                    ) VALUES (
                        :id,
                        :tenant_id,
                        :provider,
                        'oauth_tokens',
                        :encrypted_payload,
                        :now,
                        :now
                    )
                    """
                ),
                {
                    "id": str(uuid4()),
                    "tenant_id": TENANT_ID,
                    "provider": provider,
                    "encrypted_payload": encrypted_payload,
                    "now": now,
                },
            )


def set_document_storage_key(
    client: TestClient, *, document_id: str, storage_key: str
) -> None:
    with client.app.state.db_engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE documents SET storage_key = :storage_key WHERE id = :document_id"
            ),
            {"storage_key": storage_key, "document_id": document_id},
        )


def set_managed_backup_storage_key(
    client: TestClient, *, document_id: str, managed_backup_storage_key: str | None
) -> None:
    with client.app.state.db_engine.begin() as connection:
        connection.execute(
            text(
                """
                UPDATE documents
                SET managed_backup_storage_key = :managed_backup_storage_key
                WHERE id = :document_id
                """
            ),
            {
                "managed_backup_storage_key": managed_backup_storage_key,
                "document_id": document_id,
            },
        )


def seed_notification_user(
    client: TestClient, *, email: str = "alerts@example.com"
) -> None:
    client.app.state.notification_repository.create_user(
        tenant_id=TENANT_ID,
        email=email,
        role="owner",
    )


def ingest_changed_tor_pair(
    client: TestClient, *, project_id: str
) -> tuple[dict, dict]:
    first = client.post(
        "/v1/documents/ingest",
        json={
            "tenant_id": TENANT_ID,
            "project_id": project_id,
            "file_name": "tor-v1.pdf",
            "content_base64": base64.b64encode(b"tor-v1").decode("ascii"),
            "source_label": "เอกสารประกวดราคา",
            "source_status_text": "ประกาศเชิญชวน",
        },
    )
    second = client.post(
        "/v1/documents/ingest",
        json={
            "tenant_id": TENANT_ID,
            "project_id": project_id,
            "file_name": "tor-v2.pdf",
            "content_base64": base64.b64encode(b"tor-v2").decode("ascii"),
            "source_label": "เอกสารประกวดราคา",
            "source_status_text": "ประกาศเชิญชวน",
        },
    )

    assert first.status_code == 201
    assert second.status_code == 201
    return first.json(), second.json()


def test_ingest_document_endpoint_persists_and_classifies_document(tmp_path) -> None:
    client = create_test_client(tmp_path)
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
    client = create_test_client(tmp_path)
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
    client = create_test_client(tmp_path)
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

    response = client.get(
        f"/v1/documents/projects/{project_id}", params={"tenant_id": TENANT_ID}
    )

    assert response.status_code == 200
    body = response.json()
    assert len(body["documents"]) == 1
    assert body["documents"][0]["document_type"] == "mid_price"


def test_ingest_document_endpoint_keeps_same_bytes_for_different_phase(
    tmp_path,
) -> None:
    client = create_test_client(tmp_path)
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
    listed = client.get(
        f"/v1/documents/projects/{project_id}", params={"tenant_id": TENANT_ID}
    )

    assert first.status_code == 201
    assert second.status_code == 201
    assert len(listed.json()["documents"]) == 2
    assert second.json()["diff_records"] == [
        {
            "id": second.json()["diff_records"][0]["id"],
            "project_id": project_id,
            "old_document_id": first.json()["document"]["id"],
            "new_document_id": second.json()["document"]["id"],
            "diff_type": "identical",
            "summary_json": {
                "summary_version": 1,
                "comparison_scope": "phase_transition",
                "text_extraction_status": "inline_text",
                "text_diff_available": True,
                "similarity_ratio": 1.0,
                "old_document_phase": "public_hearing",
                "new_document_phase": "final",
                "old_sha256": first.json()["document"]["sha256"],
                "new_sha256": second.json()["document"]["sha256"],
                "old_size_bytes": len(b"same-tor-bytes"),
                "new_size_bytes": len(b"same-tor-bytes"),
                "size_delta_bytes": 0,
                "old_file_name": "tor-hearing.pdf",
                "new_file_name": "tor-final.pdf",
                "added_line_count": 0,
                "removed_line_count": 0,
                "changed_line_count": 0,
                "old_text_preview": "same-tor-bytes",
                "new_text_preview": "same-tor-bytes",
            },
            "created_at": second.json()["diff_records"][0]["created_at"],
        }
    ]


def test_ingest_document_endpoint_uses_project_state_for_hearing_phase(
    tmp_path,
) -> None:
    client = create_test_client(tmp_path)
    project_id = seed_project(client)
    client.app.state.project_repository.upsert_project(
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
            project_state=ProjectState.OPEN_PUBLIC_HEARING,
        ),
        source_status_text="เปิดรับฟังคำวิจารณ์",
    )

    response = client.post(
        "/v1/documents/ingest",
        json={
            "tenant_id": TENANT_ID,
            "project_id": project_id,
            "file_name": "tor.pdf",
            "content_base64": base64.b64encode(b"hearing-tor").decode("ascii"),
            "source_label": "เอกสารประกวดราคา",
            "source_status_text": "",
        },
    )

    assert response.status_code == 201
    assert response.json()["document"]["document_phase"] == "public_hearing"


def test_ingest_document_endpoint_uses_page_text_for_hearing_phase(tmp_path) -> None:
    client = create_test_client(tmp_path)
    project_id = seed_project(client)

    response = client.post(
        "/v1/documents/ingest",
        json={
            "tenant_id": TENANT_ID,
            "project_id": project_id,
            "file_name": "tor.pdf",
            "content_base64": base64.b64encode(b"page-hearing-tor").decode("ascii"),
            "source_label": "เอกสารประกวดราคา",
            "source_status_text": "",
            "source_page_text": "เอกสารนี้เผยแพร่เพื่อรับฟังความคิดเห็นและประชาพิจารณ์",
        },
    )

    assert response.status_code == 201
    assert response.json()["document"]["document_phase"] == "public_hearing"


def test_ingest_document_endpoint_creates_pending_review_and_defers_tor_notification(
    tmp_path,
) -> None:
    sent: list[str] = []
    client = create_test_client(
        tmp_path, notification_email_sender=lambda *, to, subject, body: sent.append(to)
    )
    project_id = seed_project(client)
    seed_notification_user(client)

    _, second = ingest_changed_tor_pair(client, project_id=project_id)
    reviews = client.get(
        f"/v1/documents/projects/{project_id}/reviews",
        params={"tenant_id": TENANT_ID},
    )

    notifications = client.app.state.notification_repository.list_for_tenant(TENANT_ID)

    assert reviews.status_code == 200
    assert sent == []
    assert notifications == []
    assert reviews.json()["total"] == 1
    assert (
        reviews.json()["reviews"][0]["document_diff_id"]
        == second["diff_records"][0]["id"]
    )
    assert reviews.json()["reviews"][0]["status"] == DocumentReviewStatus.PENDING
    assert reviews.json()["reviews"][0]["events"][0]["event_type"] == (
        DocumentReviewEventType.CREATED
    )


def test_ingest_document_endpoint_duplicate_hash_does_not_emit_tor_changed_notification(
    tmp_path,
) -> None:
    sent: list[str] = []
    client = create_test_client(
        tmp_path, notification_email_sender=lambda *, to, subject, body: sent.append(to)
    )
    project_id = seed_project(client)
    seed_notification_user(client)

    payload = {
        "tenant_id": TENANT_ID,
        "project_id": project_id,
        "file_name": "tor-v1.pdf",
        "content_base64": base64.b64encode(b"same-bytes").decode("ascii"),
        "source_label": "เอกสารประกวดราคา",
        "source_status_text": "ประกาศเชิญชวน",
    }
    first = client.post("/v1/documents/ingest", json=payload)
    second = client.post("/v1/documents/ingest", json=payload)

    assert first.status_code == 201
    assert second.status_code == 200
    assert sent == []
    assert client.app.state.notification_repository.list_for_tenant(TENANT_ID) == []


def test_ingest_document_endpoint_phase_transition_same_bytes_does_not_emit_tor_changed_notification(
    tmp_path,
) -> None:
    sent: list[str] = []
    client = create_test_client(
        tmp_path, notification_email_sender=lambda *, to, subject, body: sent.append(to)
    )
    project_id = seed_project(client)
    seed_notification_user(client)

    first = client.post(
        "/v1/documents/ingest",
        json={
            "tenant_id": TENANT_ID,
            "project_id": project_id,
            "file_name": "tor-hearing.pdf",
            "content_base64": base64.b64encode(b"same-phase-transition").decode(
                "ascii"
            ),
            "source_label": "ร่างขอบเขตของงาน",
            "source_status_text": "เปิดรับฟังคำวิจารณ์",
        },
    )
    second = client.post(
        "/v1/documents/ingest",
        json={
            "tenant_id": TENANT_ID,
            "project_id": project_id,
            "file_name": "tor-final.pdf",
            "content_base64": base64.b64encode(b"same-phase-transition").decode(
                "ascii"
            ),
            "source_label": "เอกสารประกวดราคา",
            "source_status_text": "ประกาศเชิญชวน",
        },
    )

    assert first.status_code == 201
    assert second.status_code == 201
    assert second.json()["diff_records"][0]["diff_type"] == "identical"
    assert sent == []
    assert client.app.state.notification_repository.list_for_tenant(TENANT_ID) == []


def test_approve_document_review_dispatches_tor_changed_notification_once(
    tmp_path,
) -> None:
    sent: list[str] = []
    client = create_test_client(
        tmp_path, notification_email_sender=lambda *, to, subject, body: sent.append(to)
    )
    project_id = seed_project(client)
    seed_notification_user(client)
    ingest_changed_tor_pair(client, project_id=project_id)

    review_list = client.get(
        f"/v1/documents/projects/{project_id}/reviews",
        params={"tenant_id": TENANT_ID},
    )
    review_id = review_list.json()["reviews"][0]["id"]

    first = client.post(
        f"/v1/documents/reviews/{review_id}/actions",
        json={
            "tenant_id": TENANT_ID,
            "action": "approve",
            "note": "Confirmed meaningful TOR change",
        },
    )
    second = client.post(
        f"/v1/documents/reviews/{review_id}/actions",
        json={
            "tenant_id": TENANT_ID,
            "action": "approve",
            "note": "Duplicate approval should fail",
        },
    )

    notifications = client.app.state.notification_repository.list_for_tenant(TENANT_ID)

    assert first.status_code == 200
    assert first.json()["review"]["status"] == DocumentReviewStatus.APPROVED
    assert first.json()["review"]["events"][-1]["event_type"] == (
        DocumentReviewEventType.APPROVED
    )
    assert first.json()["review"]["events"][-1]["actor_subject"] == "manual-operator"
    assert sent == ["alerts@example.com"]
    assert [entry.notification_type for entry in notifications] == [
        NotificationType.TOR_CHANGED
    ]
    assert second.status_code == 422


def test_reject_document_review_records_actor_and_note(tmp_path) -> None:
    client = create_test_client(tmp_path)
    project_id = seed_project(client)
    ingest_changed_tor_pair(client, project_id=project_id)
    review_list = client.get(
        f"/v1/documents/projects/{project_id}/reviews",
        params={"tenant_id": TENANT_ID},
    )
    review_id = review_list.json()["reviews"][0]["id"]

    response = client.post(
        f"/v1/documents/reviews/{review_id}/actions",
        json={
            "tenant_id": TENANT_ID,
            "action": "reject",
            "note": "False positive change",
        },
    )

    assert response.status_code == 200
    assert response.json()["review"]["status"] == DocumentReviewStatus.REJECTED
    assert response.json()["review"]["events"][-1] == {
        "id": response.json()["review"]["events"][-1]["id"],
        "review_id": review_id,
        "document_diff_id": response.json()["review"]["document_diff_id"],
        "event_type": DocumentReviewEventType.REJECTED,
        "actor_subject": "manual-operator",
        "note": "False positive change",
        "from_status": DocumentReviewStatus.PENDING,
        "to_status": DocumentReviewStatus.REJECTED,
        "created_at": response.json()["review"]["events"][-1]["created_at"],
    }


def test_document_review_action_rejects_invalid_transition(tmp_path) -> None:
    client = create_test_client(tmp_path)
    project_id = seed_project(client)
    ingest_changed_tor_pair(client, project_id=project_id)
    review_list = client.get(
        f"/v1/documents/projects/{project_id}/reviews",
        params={"tenant_id": TENANT_ID},
    )
    review_id = review_list.json()["reviews"][0]["id"]

    first = client.post(
        f"/v1/documents/reviews/{review_id}/actions",
        json={"tenant_id": TENANT_ID, "action": "reject", "note": "Reject once"},
    )
    second = client.post(
        f"/v1/documents/reviews/{review_id}/actions",
        json={"tenant_id": TENANT_ID, "action": "reject", "note": "Reject twice"},
    )

    assert first.status_code == 200
    assert second.status_code == 422


def test_document_diff_endpoints_surface_project_change_alerts(tmp_path) -> None:
    client = create_test_client(tmp_path)
    project_id = seed_project(client)

    hearing = client.post(
        "/v1/documents/ingest",
        json={
            "tenant_id": TENANT_ID,
            "project_id": project_id,
            "file_name": "tor-hearing.pdf",
            "content_base64": base64.b64encode(b"draft line\nshared line\n").decode(
                "ascii"
            ),
            "source_label": "ร่างขอบเขตของงาน",
            "source_status_text": "เปิดรับฟังคำวิจารณ์",
        },
    )
    final = client.post(
        "/v1/documents/ingest",
        json={
            "tenant_id": TENANT_ID,
            "project_id": project_id,
            "file_name": "tor-final.pdf",
            "content_base64": base64.b64encode(b"final line\nshared line\n").decode(
                "ascii"
            ),
            "source_label": "เอกสารประกวดราคา",
            "source_status_text": "ประกาศเชิญชวน",
        },
    )

    diff_list = client.get(
        f"/v1/documents/projects/{project_id}/diffs", params={"tenant_id": TENANT_ID}
    )
    diff_detail = client.get(
        f"/v1/documents/{final.json()['document']['id']}/diff/{hearing.json()['document']['id']}",
        params={"tenant_id": TENANT_ID},
    )

    assert hearing.status_code == 201
    assert final.status_code == 201
    assert diff_list.status_code == 200
    assert len(diff_list.json()["diffs"]) == 1
    assert diff_list.json()["diffs"][0]["diff_type"] == "changed"
    assert (
        diff_list.json()["diffs"][0]["summary_json"]["comparison_scope"]
        == "phase_transition"
    )
    assert diff_detail.status_code == 200
    assert (
        diff_detail.json()["diff"]["old_document_id"]
        == hearing.json()["document"]["id"]
    )
    assert (
        diff_detail.json()["diff"]["new_document_id"] == final.json()["document"]["id"]
    )


def test_document_download_endpoint_streams_local_artifact_bytes(tmp_path) -> None:
    client = create_test_client(tmp_path)
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

    response = client.get(
        f"/v1/documents/{document_id}/download",
        params={"tenant_id": TENANT_ID},
    )

    assert response.status_code == 200
    assert response.content == b"tor-bytes"
    assert response.headers["content-type"] == "application/pdf"
    assert "attachment;" in response.headers["content-disposition"]
    assert "tor.pdf" in response.headers["content-disposition"]


def test_document_download_endpoint_streams_supabase_backed_bytes(tmp_path) -> None:
    supabase_client = FakeSupabaseClient()
    client = create_test_client(
        tmp_path,
        artifact_storage_backend="supabase",
        artifact_bucket="egp-documents",
        supabase_url="https://project.supabase.co",
        supabase_service_role_key="service-role-key",
        supabase_client=supabase_client,
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

    response = client.get(
        f"/v1/documents/{document_id}/download",
        params={"tenant_id": TENANT_ID, "expires_in": 900},
    )

    assert response.status_code == 200
    assert response.content == b"tor-bytes"
    assert response.headers["content-type"] == "application/pdf"
    assert "tor.pdf" in response.headers["content-disposition"]


def test_document_download_endpoint_streams_google_drive_bytes_for_prefixed_storage_key(
    tmp_path,
) -> None:
    google_client = FakeGoogleDriveDownloadClient(download_bytes=b"drive-pdf-bytes")
    client = create_test_client(
        tmp_path,
        storage_credentials_secret="phase1-storage-secret",
        google_drive_oauth_config=_google_config(),
        google_drive_client=google_client,
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
    seed_external_storage(client, provider="google_drive")
    set_document_storage_key(
        client, document_id=document_id, storage_key="google_drive:drive-file-id"
    )

    response = client.get(
        f"/v1/documents/{document_id}/download",
        params={"tenant_id": TENANT_ID},
    )

    assert response.status_code == 200
    assert response.content == b"drive-pdf-bytes"
    assert google_client.refresh_calls == ["provider-refresh-token"]
    assert google_client.download_file_calls == ["drive-file-id"]


def test_document_download_endpoint_streams_onedrive_bytes_for_prefixed_storage_key(
    tmp_path,
) -> None:
    onedrive_client = FakeOneDriveDownloadClient(download_bytes=b"onedrive-pdf-bytes")
    client = create_test_client(
        tmp_path,
        storage_credentials_secret="phase1-storage-secret",
        onedrive_oauth_config=_onedrive_config(),
        onedrive_client=onedrive_client,
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
    seed_external_storage(client, provider="onedrive")
    set_document_storage_key(
        client, document_id=document_id, storage_key="onedrive:onedrive-item-id"
    )

    response = client.get(
        f"/v1/documents/{document_id}/download",
        params={"tenant_id": TENANT_ID},
    )

    assert response.status_code == 200
    assert response.content == b"onedrive-pdf-bytes"
    assert onedrive_client.refresh_calls == ["provider-refresh-token"]
    assert onedrive_client.download_file_calls == ["onedrive-item-id"]


def test_document_download_endpoint_streams_managed_backup_when_provider_read_fails(
    tmp_path,
) -> None:
    google_client = FakeGoogleDriveDownloadClient(
        download_exception=RuntimeError("provider read failed")
    )
    client = create_test_client(
        tmp_path,
        storage_credentials_secret="phase1-storage-secret",
        google_drive_oauth_config=_google_config(),
        google_drive_client=google_client,
    )
    project_id = seed_project(client)
    ingest_response = client.post(
        "/v1/documents/ingest",
        json={
            "tenant_id": TENANT_ID,
            "project_id": project_id,
            "file_name": "tor.pdf",
            "content_base64": base64.b64encode(b"backup-tor-bytes").decode("ascii"),
            "source_label": "เอกสารประกวดราคา",
            "source_status_text": "ประกาศเชิญชวน",
        },
    )
    document_id = ingest_response.json()["document"]["id"]
    storage_key = ingest_response.json()["document"]["storage_key"]
    seed_external_storage(client, provider="google_drive")
    set_document_storage_key(
        client, document_id=document_id, storage_key="google_drive:drive-file-id"
    )
    set_managed_backup_storage_key(
        client,
        document_id=document_id,
        managed_backup_storage_key=storage_key,
    )

    response = client.get(
        f"/v1/documents/{document_id}/download",
        params={"tenant_id": TENANT_ID},
    )

    assert response.status_code == 200
    assert response.content == b"backup-tor-bytes"
    assert google_client.download_file_calls == ["drive-file-id"]


def test_document_download_endpoint_returns_422_when_external_provider_download_is_misconfigured(
    tmp_path,
) -> None:
    google_client = FakeGoogleDriveDownloadClient()
    client = create_test_client(
        tmp_path,
        raise_server_exceptions=False,
        storage_credentials_secret="phase1-storage-secret",
        google_drive_oauth_config=_google_config(),
        google_drive_client=google_client,
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
    seed_external_storage(client, provider="google_drive", refresh_token=None)
    set_document_storage_key(
        client, document_id=document_id, storage_key="google_drive:drive-file-id"
    )

    response = client.get(
        f"/v1/documents/{document_id}/download",
        params={"tenant_id": TENANT_ID},
    )

    assert response.status_code == 422
    assert "credentials missing" in response.json()["detail"]
