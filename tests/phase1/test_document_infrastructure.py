from __future__ import annotations

import base64
import logging
import sqlite3
from datetime import UTC, datetime

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import text

from egp_api.main import create_app
from egp_db.google_drive import GoogleDriveOAuthConfig
from egp_db.onedrive import OneDriveOAuthConfig
from egp_db.repositories.admin_repo import create_admin_repository
from egp_db.storage_credentials import StorageCredentialCipher
from egp_db.artifact_store import S3ArtifactStore, SupabaseArtifactStore
from egp_worker.browser_downloads import ingest_downloaded_documents
from egp_worker.workflows.document_ingest import ingest_document_artifact

TENANT_ID = "11111111-1111-1111-1111-111111111111"
PROJECT_ID = "22222222-2222-2222-2222-222222222222"


class FakeS3Client:
    def __init__(self) -> None:
        self.put_calls: list[dict[str, object]] = []
        self.delete_calls: list[dict[str, object]] = []
        self.presign_calls: list[dict[str, object]] = []

    def put_object(self, **kwargs):
        self.put_calls.append(kwargs)
        return {"ETag": "fake-etag"}

    def delete_object(self, **kwargs):
        self.delete_calls.append(kwargs)
        return {}

    def generate_presigned_url(self, client_method: str, *, Params, ExpiresIn: int):
        self.presign_calls.append(
            {
                "client_method": client_method,
                "params": Params,
                "expires_in": ExpiresIn,
            }
        )
        return f"https://signed.example/{Params['Bucket']}/{Params['Key']}"


class FakeSupabaseBucket:
    def __init__(self, bucket_name: str) -> None:
        self.bucket_name = bucket_name
        self.upload_calls: list[dict[str, object]] = []
        self.remove_calls: list[list[str]] = []
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

    def remove(self, paths: list[str]):
        self.remove_calls.append(paths)
        return {"paths": paths}

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


class FakeGoogleDriveClient:
    def __init__(self) -> None:
        self.refresh_calls: list[str] = []
        self.upload_calls: list[dict[str, object]] = []

    def refresh_access_token(
        self,
        *,
        config: GoogleDriveOAuthConfig,
        refresh_token: str,
    ) -> dict[str, object]:
        self.refresh_calls.append(refresh_token)
        return {"access_token": f"access-for-{config.client_id}"}

    def upload_file(
        self,
        *,
        access_token: str,
        folder_id: str | None,
        name: str,
        data: bytes,
        content_type: str | None = None,
    ) -> dict[str, object]:
        self.upload_calls.append(
            {
                "access_token": access_token,
                "folder_id": folder_id,
                "name": name,
                "data": data,
                "content_type": content_type,
            }
        )
        return {"id": "drive-file-id"}

    def download_file(self, *, access_token: str, file_id: str) -> bytes:
        return f"download:{access_token}:{file_id}".encode("utf-8")

    def delete_file(self, *, access_token: str, file_id: str) -> None:
        return None

    def download_url(self, *, file_id: str) -> str:
        return f"https://drive.example/{file_id}"


class FakeOneDriveClient:
    def __init__(self) -> None:
        self.refresh_calls: list[str] = []
        self.upload_calls: list[dict[str, object]] = []

    def refresh_access_token(
        self,
        *,
        config: OneDriveOAuthConfig,
        refresh_token: str,
    ) -> dict[str, object]:
        self.refresh_calls.append(refresh_token)
        return {"access_token": f"access-for-{config.client_id}"}

    def upload_file(
        self,
        *,
        access_token: str,
        folder_id: str | None,
        name: str,
        data: bytes,
        content_type: str | None = None,
    ) -> dict[str, object]:
        self.upload_calls.append(
            {
                "access_token": access_token,
                "folder_id": folder_id,
                "name": name,
                "data": data,
                "content_type": content_type,
            }
        )
        return {"id": "onedrive-item-id"}

    def download_file(self, *, access_token: str, file_id: str) -> bytes:
        return f"download:{access_token}:{file_id}".encode("utf-8")

    def delete_file(self, *, access_token: str, file_id: str) -> None:
        return None

    def download_url(self, *, access_token: str, file_id: str) -> str:
        return f"https://onedrive.example/{file_id}"


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


def _seed_google_drive_storage(
    database_url: str,
    *,
    storage_secret: str = "storage-secret",
    managed_backup_enabled: bool = False,
) -> None:
    repository = create_admin_repository(
        database_url=database_url, bootstrap_schema=True
    )
    now = datetime.now(UTC)
    encrypted_payload = StorageCredentialCipher(storage_secret).encrypt_dict(
        {"refresh_token": "google-refresh-token"}
    )
    with repository._engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO tenants (
                    id, name, slug, plan_code, is_active, created_at, updated_at
                ) VALUES (
                    :tenant_id, 'Acme', 'acme', 'monthly_membership', 1, :now, :now
                )
                """
            ),
            {"tenant_id": TENANT_ID, "now": now},
        )
        connection.execute(
            text(
                """
                INSERT INTO tenant_storage_configs (
                    id,
                    tenant_id,
                    provider,
                    connection_status,
                    provider_folder_id,
                    managed_backup_enabled,
                    managed_fallback_enabled,
                    created_at,
                    updated_at
                ) VALUES (
                    '33333333-3333-3333-3333-333333333333',
                    :tenant_id,
                    'google_drive',
                    'connected',
                    'drive-folder-id',
                    :managed_backup_enabled,
                    0,
                    :now,
                    :now
                )
                """
            ),
            {
                "tenant_id": TENANT_ID,
                "managed_backup_enabled": int(managed_backup_enabled),
                "now": now,
            },
        )
        connection.execute(
            text(
                """
                INSERT INTO tenant_storage_credentials (
                    id,
                    tenant_id,
                    provider,
                    credential_type,
                    encrypted_payload,
                    created_at,
                    updated_at
                ) VALUES (
                    '44444444-4444-4444-4444-444444444444',
                    :tenant_id,
                    'google_drive',
                    'oauth_tokens',
                    :encrypted_payload,
                    :now,
                    :now
                )
                """
            ),
            {
                "tenant_id": TENANT_ID,
                "encrypted_payload": encrypted_payload,
                "now": now,
            },
        )


def _seed_onedrive_storage(
    database_url: str,
    *,
    storage_secret: str = "storage-secret",
    managed_backup_enabled: bool = False,
) -> None:
    repository = create_admin_repository(
        database_url=database_url, bootstrap_schema=True
    )
    now = datetime.now(UTC)
    encrypted_payload = StorageCredentialCipher(storage_secret).encrypt_dict(
        {"refresh_token": "onedrive-refresh-token"}
    )
    with repository._engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO tenants (
                    id, name, slug, plan_code, is_active, created_at, updated_at
                ) VALUES (
                    :tenant_id, 'Acme', 'acme', 'monthly_membership', 1, :now, :now
                )
                """
            ),
            {"tenant_id": TENANT_ID, "now": now},
        )
        connection.execute(
            text(
                """
                INSERT INTO tenant_storage_configs (
                    id,
                    tenant_id,
                    provider,
                    connection_status,
                    provider_folder_id,
                    managed_backup_enabled,
                    managed_fallback_enabled,
                    created_at,
                    updated_at
                ) VALUES (
                    '55555555-5555-5555-5555-555555555555',
                    :tenant_id,
                    'onedrive',
                    'connected',
                    'onedrive-folder-id',
                    :managed_backup_enabled,
                    0,
                    :now,
                    :now
                )
                """
            ),
            {
                "tenant_id": TENANT_ID,
                "managed_backup_enabled": int(managed_backup_enabled),
                "now": now,
            },
        )
        connection.execute(
            text(
                """
                INSERT INTO tenant_storage_credentials (
                    id,
                    tenant_id,
                    provider,
                    credential_type,
                    encrypted_payload,
                    created_at,
                    updated_at
                ) VALUES (
                    '66666666-6666-6666-6666-666666666666',
                    :tenant_id,
                    'onedrive',
                    'oauth_tokens',
                    :encrypted_payload,
                    :now,
                    :now
                )
                """
            ),
            {
                "tenant_id": TENANT_ID,
                "encrypted_payload": encrypted_payload,
                "now": now,
            },
        )


def test_create_app_uses_database_url_override_for_document_metadata(tmp_path) -> None:
    database_path = tmp_path / "metadata.sqlite3"
    database_url = f"sqlite+pysqlite:///{database_path}"
    artifact_root = tmp_path / "artifacts"
    client = TestClient(
        create_app(
            artifact_root=artifact_root, database_url=database_url, auth_required=False
        )
    )

    response = client.post(
        "/v1/documents/ingest",
        json={
            "tenant_id": TENANT_ID,
            "project_id": PROJECT_ID,
            "file_name": "tor.pdf",
            "content_base64": base64.b64encode(b"draft-tor").decode("ascii"),
            "source_label": "ร่างขอบเขตของงาน",
            "source_status_text": "เปิดรับฟังคำวิจารณ์",
        },
    )

    assert response.status_code == 201
    assert database_path.exists()
    with sqlite3.connect(database_path) as connection:
        row = connection.execute("SELECT COUNT(*) FROM documents").fetchone()
    assert row == (1,)


def test_worker_document_ingest_uses_database_url_override(tmp_path) -> None:
    database_path = tmp_path / "worker.sqlite3"
    database_url = f"sqlite+pysqlite:///{database_path}"
    artifact_root = tmp_path / "artifacts"

    result = ingest_document_artifact(
        database_url=database_url,
        artifact_root=artifact_root,
        tenant_id=TENANT_ID,
        project_id=PROJECT_ID,
        file_name="tor.pdf",
        file_bytes=b"worker-tor",
        source_label="ร่างขอบเขตของงาน",
        source_status_text="เปิดรับฟังคำวิจารณ์",
    )

    assert result.created is True
    with sqlite3.connect(database_path) as connection:
        row = connection.execute(
            "SELECT file_name, storage_key FROM documents WHERE id = ?",
            (result.document.id,),
        ).fetchone()
    assert row == ("tor.pdf", result.document.storage_key)


def test_ingest_downloaded_documents_persists_multiple_downloads(tmp_path) -> None:
    database_path = tmp_path / "downloaded.sqlite3"
    database_url = f"sqlite+pysqlite:///{database_path}"
    artifact_root = tmp_path / "artifacts"

    results = ingest_downloaded_documents(
        database_url=database_url,
        artifact_root=artifact_root,
        tenant_id=TENANT_ID,
        project_id=PROJECT_ID,
        downloaded_documents=[
            {
                "file_name": "tor.pdf",
                "file_bytes": b"tor-v1",
                "source_label": "ร่างขอบเขตของงาน",
                "source_status_text": "หนังสือเชิญชวน/ประกาศเชิญชวน",
                "source_page_text": "ประชาพิจารณ์",
            },
            {
                "file_name": "announcement.pdf",
                "file_bytes": b"announce-v1",
                "source_label": "ประกาศเชิญชวน",
                "source_status_text": "หนังสือเชิญชวน/ประกาศเชิญชวน",
                "source_page_text": "",
            },
        ],
    )

    assert len(results) == 2
    assert results[0].created is True
    assert results[1].created is True
    with sqlite3.connect(database_path) as connection:
        row = connection.execute("SELECT COUNT(*) FROM documents").fetchone()
    assert row == (2,)


def test_ingest_downloaded_documents_logs_start_and_success(tmp_path, caplog) -> None:
    database_path = tmp_path / "downloaded.sqlite3"
    database_url = f"sqlite+pysqlite:///{database_path}"
    artifact_root = tmp_path / "artifacts"
    caplog.set_level(logging.INFO, logger="egp_worker.browser_downloads")

    results = ingest_downloaded_documents(
        database_url=database_url,
        artifact_root=artifact_root,
        tenant_id=TENANT_ID,
        project_id=PROJECT_ID,
        downloaded_documents=[
            {
                "file_name": "tor.pdf",
                "file_bytes": b"tor-v1",
                "source_label": "ร่างขอบเขตของงาน",
                "source_status_text": "เปิดรับฟังคำวิจารณ์",
            }
        ],
    )

    assert len(results) == 1
    events = [record for record in caplog.records if hasattr(record, "egp_event")]
    start_event = next(
        record for record in events if record.egp_event == "document_ingest_started"
    )
    success_event = next(
        record for record in events if record.egp_event == "document_ingest_succeeded"
    )
    assert start_event.file_name == "tor.pdf"
    assert start_event.document_index == 1
    assert start_event.document_count == 1
    assert success_event.file_name == "tor.pdf"
    assert success_event.document_created is True
    assert success_event.document_id == results[0].document.id


def test_ingest_downloaded_documents_logs_failure_before_reraise(
    monkeypatch, tmp_path, caplog
) -> None:
    caplog.set_level(logging.INFO, logger="egp_worker.browser_downloads")

    def fake_ingest_document_artifact(**kwargs):
        raise RuntimeError(f"boom:{kwargs['file_name']}")

    monkeypatch.setattr(
        "egp_worker.browser_downloads.ingest_document_artifact",
        fake_ingest_document_artifact,
    )

    with pytest.raises(RuntimeError, match="boom:tor.pdf"):
        ingest_downloaded_documents(
            database_url=None,
            artifact_root=tmp_path / "artifacts",
            tenant_id=TENANT_ID,
            project_id=PROJECT_ID,
            downloaded_documents=[
                {
                    "file_name": "tor.pdf",
                    "file_bytes": b"tor-v1",
                    "source_label": "ร่างขอบเขตของงาน",
                    "source_status_text": "เปิดรับฟังคำวิจารณ์",
                }
            ],
        )

    failure_event = next(
        record
        for record in caplog.records
        if getattr(record, "egp_event", "") == "document_ingest_failed"
    )
    assert failure_event.file_name == "tor.pdf"
    assert failure_event.document_index == 1
    assert failure_event.document_count == 1


def test_s3_artifact_store_puts_prefixed_key_and_presigns_download_url() -> None:
    client = FakeS3Client()
    store = S3ArtifactStore(
        bucket="egp-documents",
        prefix="dev/raw",
        client=client,
    )

    stored_key = store.put_bytes(
        key="tenants/tenant-1/projects/project-1/artifacts/hash/tor.pdf",
        data=b"tor-bytes",
        content_type="application/pdf",
    )
    signed_url = store.download_url(stored_key, expires_in=900)

    assert (
        stored_key
        == "dev/raw/tenants/tenant-1/projects/project-1/artifacts/hash/tor.pdf"
    )
    assert client.put_calls == [
        {
            "Bucket": "egp-documents",
            "Key": stored_key,
            "Body": b"tor-bytes",
            "ContentType": "application/pdf",
        }
    ]
    assert signed_url == f"https://signed.example/egp-documents/{stored_key}"
    assert client.presign_calls == [
        {
            "client_method": "get_object",
            "params": {"Bucket": "egp-documents", "Key": stored_key},
            "expires_in": 900,
        }
    ]


def test_supabase_artifact_store_uploads_and_signs_download_url() -> None:
    client = FakeSupabaseClient()
    store = SupabaseArtifactStore(
        project_url="https://project.supabase.co",
        service_role_key="service-role-key",
        bucket="egp-documents",
        prefix="dev/raw",
        client=client,
    )

    stored_key = store.put_bytes(
        key="tenants/tenant-1/projects/project-1/artifacts/hash/tor.pdf",
        data=b"tor-bytes",
        content_type="application/pdf",
    )
    signed_url = store.download_url(stored_key, expires_in=900)

    bucket = client.storage.from_("egp-documents")
    assert (
        stored_key
        == "dev/raw/tenants/tenant-1/projects/project-1/artifacts/hash/tor.pdf"
    )
    assert bucket.upload_calls == [
        {
            "path": stored_key,
            "file": b"tor-bytes",
            "file_options": {
                "content-type": "application/pdf",
                "upsert": False,
            },
        }
    ]
    assert (
        signed_url
        == f"https://project.supabase.co/storage/v1/object/sign/egp-documents/{stored_key}"
    )
    assert bucket.sign_calls == [
        {
            "path": stored_key,
            "expires_in": 900,
            "options": {"download": True},
        }
    ]


def test_create_app_supports_supabase_storage_backend(tmp_path) -> None:
    database_path = tmp_path / "metadata.sqlite3"
    database_url = f"sqlite+pysqlite:///{database_path}"
    client = FakeSupabaseClient()
    app = create_app(
        artifact_root=tmp_path / "artifacts",
        database_url=database_url,
        auth_required=False,
        artifact_storage_backend="supabase",
        artifact_bucket="egp-documents",
        supabase_url="https://project.supabase.co",
        supabase_service_role_key="service-role-key",
        supabase_client=client,
    )
    test_client = TestClient(app)

    response = test_client.post(
        "/v1/documents/ingest",
        json={
            "tenant_id": TENANT_ID,
            "project_id": PROJECT_ID,
            "file_name": "tor.pdf",
            "content_base64": base64.b64encode(b"draft-tor").decode("ascii"),
            "source_label": "ร่างขอบเขตของงาน",
            "source_status_text": "เปิดรับฟังคำวิจารณ์",
        },
    )

    assert response.status_code == 201
    bucket = client.storage.from_("egp-documents")
    assert len(bucket.upload_calls) == 1
    with sqlite3.connect(database_path) as connection:
        row = connection.execute("SELECT COUNT(*) FROM documents").fetchone()
    assert row == (1,)


def test_api_document_ingest_uses_google_drive_for_connected_tenant(tmp_path) -> None:
    database_path = tmp_path / "metadata.sqlite3"
    database_url = f"sqlite+pysqlite:///{database_path}"
    _seed_google_drive_storage(database_url)
    google_client = FakeGoogleDriveClient()
    app = create_app(
        artifact_root=tmp_path / "artifacts",
        database_url=database_url,
        auth_required=False,
        storage_credentials_secret="storage-secret",
        google_drive_oauth_config=_google_config(),
        google_drive_client=google_client,
    )
    test_client = TestClient(app)

    response = test_client.post(
        "/v1/documents/ingest",
        json={
            "tenant_id": TENANT_ID,
            "project_id": PROJECT_ID,
            "file_name": "tor.pdf",
            "content_base64": base64.b64encode(b"draft-tor").decode("ascii"),
            "source_label": "ร่างขอบเขตของงาน",
            "source_status_text": "เปิดรับฟังคำวิจารณ์",
        },
    )

    assert response.status_code == 201
    assert google_client.refresh_calls == ["google-refresh-token"]
    assert google_client.upload_calls[0]["folder_id"] == "drive-folder-id"
    with sqlite3.connect(database_path) as connection:
        row = connection.execute("SELECT storage_key FROM documents").fetchone()
    assert row == ("google_drive:drive-file-id",)


def test_api_document_ingest_dual_writes_managed_backup_for_google_drive_tenant(
    tmp_path,
) -> None:
    database_path = tmp_path / "metadata.sqlite3"
    database_url = f"sqlite+pysqlite:///{database_path}"
    _seed_google_drive_storage(database_url, managed_backup_enabled=True)
    google_client = FakeGoogleDriveClient()
    app = create_app(
        artifact_root=tmp_path / "artifacts",
        database_url=database_url,
        auth_required=False,
        storage_credentials_secret="storage-secret",
        google_drive_oauth_config=_google_config(),
        google_drive_client=google_client,
    )
    test_client = TestClient(app)

    response = test_client.post(
        "/v1/documents/ingest",
        json={
            "tenant_id": TENANT_ID,
            "project_id": PROJECT_ID,
            "file_name": "tor.pdf",
            "content_base64": base64.b64encode(b"draft-tor").decode("ascii"),
            "source_label": "ร่างขอบเขตของงาน",
            "source_status_text": "เปิดรับฟังคำวิจารณ์",
        },
    )

    assert response.status_code == 201
    with sqlite3.connect(database_path) as connection:
        row = connection.execute(
            "SELECT storage_key, managed_backup_storage_key FROM documents"
        ).fetchone()
    assert row is not None
    assert row[0] == "google_drive:drive-file-id"
    assert row[1] is not None
    assert (tmp_path / "artifacts" / row[1]).read_bytes() == b"draft-tor"


def test_worker_document_ingest_supports_supabase_storage_backend(tmp_path) -> None:
    database_path = tmp_path / "worker.sqlite3"
    database_url = f"sqlite+pysqlite:///{database_path}"
    client = FakeSupabaseClient()

    result = ingest_document_artifact(
        database_url=database_url,
        artifact_root=tmp_path / "artifacts",
        artifact_storage_backend="supabase",
        artifact_bucket="egp-documents",
        supabase_url="https://project.supabase.co",
        supabase_service_role_key="service-role-key",
        supabase_client=client,
        tenant_id=TENANT_ID,
        project_id=PROJECT_ID,
        file_name="tor.pdf",
        file_bytes=b"worker-tor",
        source_label="ร่างขอบเขตของงาน",
        source_status_text="เปิดรับฟังคำวิจารณ์",
    )

    assert result.created is True
    bucket = client.storage.from_("egp-documents")
    assert len(bucket.upload_calls) == 1
    with sqlite3.connect(database_path) as connection:
        row = connection.execute(
            "SELECT file_name, storage_key FROM documents WHERE id = ?",
            (result.document.id,),
        ).fetchone()
    assert row == ("tor.pdf", result.document.storage_key)


def test_worker_document_ingest_uses_google_drive_for_connected_tenant(
    tmp_path,
) -> None:
    database_path = tmp_path / "worker.sqlite3"
    database_url = f"sqlite+pysqlite:///{database_path}"
    _seed_google_drive_storage(database_url)
    google_client = FakeGoogleDriveClient()

    result = ingest_document_artifact(
        database_url=database_url,
        artifact_root=tmp_path / "artifacts",
        storage_credentials_secret="storage-secret",
        google_drive_oauth_config=_google_config(),
        google_drive_client=google_client,
        tenant_id=TENANT_ID,
        project_id=PROJECT_ID,
        file_name="tor.pdf",
        file_bytes=b"worker-tor",
        source_label="ร่างขอบเขตของงาน",
        source_status_text="เปิดรับฟังคำวิจารณ์",
    )

    assert result.created is True
    assert result.document.storage_key == "google_drive:drive-file-id"
    assert google_client.refresh_calls == ["google-refresh-token"]
    assert google_client.upload_calls[0]["folder_id"] == "drive-folder-id"


def test_api_document_ingest_uses_onedrive_for_connected_tenant(tmp_path) -> None:
    database_path = tmp_path / "metadata.sqlite3"
    database_url = f"sqlite+pysqlite:///{database_path}"
    _seed_onedrive_storage(database_url)
    onedrive_client = FakeOneDriveClient()
    app = create_app(
        artifact_root=tmp_path / "artifacts",
        database_url=database_url,
        auth_required=False,
        storage_credentials_secret="storage-secret",
        onedrive_oauth_config=_onedrive_config(),
        onedrive_client=onedrive_client,
    )
    test_client = TestClient(app)

    response = test_client.post(
        "/v1/documents/ingest",
        json={
            "tenant_id": TENANT_ID,
            "project_id": PROJECT_ID,
            "file_name": "tor.pdf",
            "content_base64": base64.b64encode(b"draft-tor").decode("ascii"),
            "source_label": "ร่างขอบเขตของงาน",
            "source_status_text": "เปิดรับฟังคำวิจารณ์",
        },
    )

    assert response.status_code == 201
    assert onedrive_client.refresh_calls == ["onedrive-refresh-token"]
    assert onedrive_client.upload_calls[0]["folder_id"] == "onedrive-folder-id"
    with sqlite3.connect(database_path) as connection:
        row = connection.execute("SELECT storage_key FROM documents").fetchone()
    assert row == ("onedrive:onedrive-item-id",)


def test_worker_document_ingest_uses_onedrive_for_connected_tenant(tmp_path) -> None:
    database_path = tmp_path / "worker.sqlite3"
    database_url = f"sqlite+pysqlite:///{database_path}"
    _seed_onedrive_storage(database_url)
    onedrive_client = FakeOneDriveClient()

    result = ingest_document_artifact(
        database_url=database_url,
        artifact_root=tmp_path / "artifacts",
        storage_credentials_secret="storage-secret",
        onedrive_oauth_config=_onedrive_config(),
        onedrive_client=onedrive_client,
        tenant_id=TENANT_ID,
        project_id=PROJECT_ID,
        file_name="tor.pdf",
        file_bytes=b"worker-tor",
        source_label="ร่างขอบเขตของงาน",
        source_status_text="เปิดรับฟังคำวิจารณ์",
    )

    assert result.created is True
    assert result.document.storage_key == "onedrive:onedrive-item-id"
    assert onedrive_client.refresh_calls == ["onedrive-refresh-token"]
    assert onedrive_client.upload_calls[0]["folder_id"] == "onedrive-folder-id"


def test_worker_document_ingest_dual_writes_managed_backup_for_onedrive_tenant(
    tmp_path,
) -> None:
    database_path = tmp_path / "worker.sqlite3"
    database_url = f"sqlite+pysqlite:///{database_path}"
    _seed_onedrive_storage(database_url, managed_backup_enabled=True)
    onedrive_client = FakeOneDriveClient()

    result = ingest_document_artifact(
        database_url=database_url,
        artifact_root=tmp_path / "artifacts",
        storage_credentials_secret="storage-secret",
        onedrive_oauth_config=_onedrive_config(),
        onedrive_client=onedrive_client,
        tenant_id=TENANT_ID,
        project_id=PROJECT_ID,
        file_name="tor.pdf",
        file_bytes=b"worker-tor",
        source_label="ร่างขอบเขตของงาน",
        source_status_text="เปิดรับฟังคำวิจารณ์",
    )

    assert result.created is True
    assert result.document.storage_key == "onedrive:onedrive-item-id"
    assert result.document.managed_backup_storage_key is not None
    assert (
        tmp_path / "artifacts" / result.document.managed_backup_storage_key
    ).read_bytes() == b"worker-tor"
