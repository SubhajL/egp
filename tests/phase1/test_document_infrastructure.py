from __future__ import annotations

import base64
import sqlite3

from fastapi.testclient import TestClient

from egp_api.main import create_app
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
