from __future__ import annotations

import sqlite3
from unittest.mock import patch

from sqlalchemy import text

from egp_api.main import create_app
from egp_db.artifact_store import LocalArtifactStore
from egp_db.google_drive import GoogleDriveOAuthConfig
from egp_db.repositories.admin_repo import create_admin_repository
from egp_db.repositories.document_repo import (
    FilesystemDocumentRepository,
    SqlDocumentRepository,
)
from egp_db.storage_credentials import StorageCredentialCipher
from egp_db.tenant_storage_resolver import TenantArtifactStoreResolver
from egp_shared_types.enums import (
    ArtifactBucket,
    DocumentPhase,
    DocumentReviewAction,
    DocumentReviewEventType,
    DocumentReviewStatus,
    DocumentType,
)

TENANT_ID = "11111111-1111-1111-1111-111111111111"
PROJECT_ID = "22222222-2222-2222-2222-222222222222"


class FakeGoogleDriveClient:
    def __init__(self) -> None:
        self.refresh_calls: list[str] = []
        self.upload_calls: list[dict[str, object]] = []
        self.delete_calls: list[str] = []
        self.download_calls: list[str] = []
        self.refresh_exception: Exception | None = None
        self.download_exception: Exception | None = None

    def refresh_access_token(
        self,
        *,
        config: GoogleDriveOAuthConfig,
        refresh_token: str,
    ) -> dict[str, object]:
        self.refresh_calls.append(refresh_token)
        if self.refresh_exception is not None:
            raise self.refresh_exception
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
        return {"id": f"drive-file-{len(self.upload_calls)}"}

    def download_file(self, *, access_token: str, file_id: str) -> bytes:
        self.download_calls.append(file_id)
        if self.download_exception is not None:
            raise self.download_exception
        return f"drive:{access_token}:{file_id}".encode("utf-8")

    def delete_file(self, *, access_token: str, file_id: str) -> None:
        self.delete_calls.append(file_id)

    def download_url(self, *, file_id: str) -> str:
        return f"https://drive.example/{file_id}"


class FailingManagedArtifactStore(LocalArtifactStore):
    def put_bytes(
        self,
        *,
        key: str,
        data: bytes,
        content_type: str | None = None,
    ) -> str:
        raise RuntimeError("managed backup write failed")


def _google_config() -> GoogleDriveOAuthConfig:
    return GoogleDriveOAuthConfig(
        client_id="google-client-id",
        client_secret="google-client-secret",
        redirect_uri="https://api.example/v1/admin/storage/google-drive/oauth/callback",
    )


def _seed_google_drive_storage(
    database_url: str,
    *,
    managed_backup_enabled: bool = False,
    engine=None,
) -> None:
    repository = create_admin_repository(
        database_url=database_url,
        engine=engine,
        bootstrap_schema=engine is None,
    )
    encrypted_payload = StorageCredentialCipher("storage-secret").encrypt_dict(
        {"refresh_token": "google-refresh-token"}
    )
    with repository._engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO tenants (
                    id, name, slug, plan_code, is_active, created_at, updated_at
                ) VALUES (
                    :tenant_id, 'Acme', 'acme', 'monthly_membership', 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
                )
                """
            ),
            {"tenant_id": TENANT_ID},
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
                    managed_fallback_enabled,
                    managed_backup_enabled,
                    created_at,
                    updated_at
                ) VALUES (
                    '33333333-3333-3333-3333-333333333333',
                    :tenant_id,
                    'google_drive',
                    'connected',
                    'drive-folder-id',
                    0,
                    :managed_backup_enabled,
                    CURRENT_TIMESTAMP,
                    CURRENT_TIMESTAMP
                )
                """
            ),
            {
                "tenant_id": TENANT_ID,
                "managed_backup_enabled": int(managed_backup_enabled),
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
                    CURRENT_TIMESTAMP,
                    CURRENT_TIMESTAMP
                )
                """
            ),
            {
                "tenant_id": TENANT_ID,
                "encrypted_payload": encrypted_payload,
            },
        )


def _google_repository(
    tmp_path,
    *,
    managed_backup_enabled: bool = False,
    artifact_store: LocalArtifactStore | None = None,
    google_client: FakeGoogleDriveClient | None = None,
) -> SqlDocumentRepository:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'dual-write.sqlite3'}"
    app = create_app(
        artifact_root=tmp_path / "managed-bootstrap",
        database_url=database_url,
        auth_required=False,
    )
    engine = app.state.db_engine
    _seed_google_drive_storage(
        database_url,
        managed_backup_enabled=managed_backup_enabled,
        engine=engine,
    )
    managed_store = artifact_store or LocalArtifactStore(tmp_path / "managed")
    admin_repository = create_admin_repository(
        database_url=database_url,
        engine=engine,
        bootstrap_schema=False,
    )
    resolver = TenantArtifactStoreResolver(
        admin_repository=admin_repository,
        managed_artifact_store=managed_store,
        credential_cipher=StorageCredentialCipher("storage-secret"),
        google_drive_oauth_config=_google_config(),
        google_drive_client=google_client or FakeGoogleDriveClient(),
    )
    return SqlDocumentRepository(
        database_url=database_url,
        engine=engine,
        artifact_store=managed_store,
        artifact_store_resolver=resolver,
        bootstrap_schema=False,
    )


def test_store_document_persists_artifact_and_sql_metadata(tmp_path) -> None:
    repository = FilesystemDocumentRepository(tmp_path)

    stored = repository.store_document(
        tenant_id=TENANT_ID,
        project_id=PROJECT_ID,
        file_name="tor.pdf",
        file_bytes=b"draft-tor",
        source_label="ร่างขอบเขตของงาน",
        source_status_text="เปิดรับฟังคำวิจารณ์",
    )

    artifact_path = tmp_path / stored.document.storage_key
    database_path = tmp_path / "document_metadata.sqlite3"

    assert stored.created is True
    assert stored.document.document_type is DocumentType.TOR
    assert stored.document.document_phase is DocumentPhase.PUBLIC_HEARING
    assert artifact_path.read_bytes() == b"draft-tor"
    assert database_path.exists()
    with sqlite3.connect(database_path) as connection:
        row = connection.execute(
            """
            SELECT project_id, file_name, document_type, document_phase, sha256, storage_key
            FROM documents
            WHERE id = ?
            """,
            (stored.document.id,),
        ).fetchone()
    assert row == (
        PROJECT_ID,
        "tor.pdf",
        "tor",
        "public_hearing",
        stored.document.sha256,
        stored.document.storage_key,
    )


def test_store_document_dual_writes_managed_backup_for_external_primary(
    tmp_path,
) -> None:
    google_client = FakeGoogleDriveClient()
    repository = _google_repository(
        tmp_path,
        managed_backup_enabled=True,
        google_client=google_client,
    )

    stored = repository.store_document(
        tenant_id=TENANT_ID,
        project_id=PROJECT_ID,
        file_name="tor.pdf",
        file_bytes=b"external-primary-with-backup",
        source_label="ร่างขอบเขตของงาน",
        source_status_text="เปิดรับฟังคำวิจารณ์",
    )

    assert stored.created is True
    assert stored.document.storage_key == "google_drive:drive-file-1"
    assert stored.document.managed_backup_storage_key is not None
    backup_path = tmp_path / "managed" / stored.document.managed_backup_storage_key
    assert backup_path.read_bytes() == b"external-primary-with-backup"
    assert google_client.upload_calls[0]["folder_id"] == "drive-folder-id"


def test_store_document_cleans_up_primary_when_backup_write_fails(tmp_path) -> None:
    google_client = FakeGoogleDriveClient()
    repository = _google_repository(
        tmp_path,
        managed_backup_enabled=True,
        artifact_store=FailingManagedArtifactStore(tmp_path / "managed"),
        google_client=google_client,
    )

    try:
        repository.store_document(
            tenant_id=TENANT_ID,
            project_id=PROJECT_ID,
            file_name="tor.pdf",
            file_bytes=b"must-clean-up",
            source_label="ร่างขอบเขตของงาน",
            source_status_text="เปิดรับฟังคำวิจารณ์",
        )
    except RuntimeError as exc:
        assert "managed backup write failed" in str(exc)
    else:
        raise AssertionError("expected dual-write failure to abort the write")

    assert google_client.delete_calls == ["drive-file-1"]


def test_get_download_url_falls_back_to_managed_backup_when_primary_download_resolution_fails(
    tmp_path,
) -> None:
    google_client = FakeGoogleDriveClient()
    repository = _google_repository(
        tmp_path,
        managed_backup_enabled=True,
        google_client=google_client,
    )
    stored = repository.store_document(
        tenant_id=TENANT_ID,
        project_id=PROJECT_ID,
        file_name="tor.pdf",
        file_bytes=b"backup-download-source",
        source_label="ร่างขอบเขตของงาน",
        source_status_text="เปิดรับฟังคำวิจารณ์",
    )
    google_client.refresh_exception = RuntimeError("google refresh failed")

    download_url = repository.get_download_url(
        tenant_id=TENANT_ID,
        document_id=stored.document.id,
    )

    assert stored.document.managed_backup_storage_key is not None
    assert download_url == str(
        (tmp_path / "managed" / stored.document.managed_backup_storage_key).resolve()
    )


def test_store_document_uses_backup_copy_for_diff_reads_with_external_primary(
    tmp_path,
) -> None:
    google_client = FakeGoogleDriveClient()
    repository = _google_repository(
        tmp_path,
        managed_backup_enabled=True,
        google_client=google_client,
    )
    first = repository.store_document(
        tenant_id=TENANT_ID,
        project_id=PROJECT_ID,
        file_name="tor-v1.pdf",
        file_bytes=b"version-one",
        source_label="เอกสารประกวดราคา",
        source_status_text="ประกาศเชิญชวน",
    )
    google_client.download_exception = RuntimeError(
        "provider download should not be needed"
    )

    second = repository.store_document(
        tenant_id=TENANT_ID,
        project_id=PROJECT_ID,
        file_name="tor-v2.pdf",
        file_bytes=b"version-two",
        source_label="เอกสารประกวดราคา",
        source_status_text="ประกาศเชิญชวน",
    )

    assert first.created is True
    assert second.created is True
    assert len(second.diff_records) == 1
    assert google_client.download_calls == []


def test_store_document_dedupes_same_project_and_hash(tmp_path) -> None:
    repository = FilesystemDocumentRepository(tmp_path)
    first = repository.store_document(
        tenant_id=TENANT_ID,
        project_id=PROJECT_ID,
        file_name="tor.pdf",
        file_bytes=b"same-bytes",
        source_label="ร่างขอบเขตของงาน",
        source_status_text="เปิดรับฟังคำวิจารณ์",
    )
    second = repository.store_document(
        tenant_id=TENANT_ID,
        project_id=PROJECT_ID,
        file_name="tor-copy.pdf",
        file_bytes=b"same-bytes",
        source_label="ร่างขอบเขตของงาน",
        source_status_text="เปิดรับฟังคำวิจารณ์",
    )

    assert first.created is True
    assert second.created is False
    assert second.document.id == first.document.id


def test_store_document_supersedes_previous_version_and_creates_diff(tmp_path) -> None:
    repository = FilesystemDocumentRepository(tmp_path)
    first = repository.store_document(
        tenant_id=TENANT_ID,
        project_id=PROJECT_ID,
        file_name="tor-v1.pdf",
        file_bytes=b"version-one",
        source_label="เอกสารประกวดราคา",
        source_status_text="ประกาศเชิญชวน",
    )
    second = repository.store_document(
        tenant_id=TENANT_ID,
        project_id=PROJECT_ID,
        file_name="tor-v2.pdf",
        file_bytes=b"version-two",
        source_label="เอกสารประกวดราคา",
        source_status_text="ประกาศเชิญชวน",
    )

    listed = repository.list_documents(TENANT_ID, PROJECT_ID)

    assert second.created is True
    assert second.document.supersedes_document_id == first.document.id
    assert second.document.is_current is True
    assert any(
        doc.id == first.document.id and doc.is_current is False for doc in listed
    )
    assert len(second.diff_records) == 1
    assert second.diff_records[0].diff_type == "changed"


def test_store_document_keeps_same_hash_for_different_phase(tmp_path) -> None:
    repository = FilesystemDocumentRepository(tmp_path)
    first = repository.store_document(
        tenant_id=TENANT_ID,
        project_id=PROJECT_ID,
        file_name="tor-hearing.pdf",
        file_bytes=b"same-tor-bytes",
        source_label="ร่างขอบเขตของงาน",
        source_status_text="เปิดรับฟังคำวิจารณ์",
    )
    second = repository.store_document(
        tenant_id=TENANT_ID,
        project_id=PROJECT_ID,
        file_name="tor-final.pdf",
        file_bytes=b"same-tor-bytes",
        source_label="เอกสารประกวดราคา",
        source_status_text="ประกาศเชิญชวน",
    )

    listed = repository.list_documents(TENANT_ID, PROJECT_ID)

    assert first.created is True
    assert second.created is True
    assert second.document.id != first.document.id
    assert len(listed) == 2
    assert len(second.diff_records) == 1
    assert second.diff_records[0].diff_type == "identical"
    assert second.diff_records[0].summary_json == {
        "summary_version": 1,
        "comparison_scope": "phase_transition",
        "text_extraction_status": "inline_text",
        "text_diff_available": True,
        "similarity_ratio": 1.0,
        "old_document_phase": "public_hearing",
        "new_document_phase": "final",
        "old_sha256": first.document.sha256,
        "new_sha256": second.document.sha256,
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
    }


def test_list_documents_returns_newest_first(tmp_path) -> None:
    repository = FilesystemDocumentRepository(tmp_path)
    first = repository.store_document(
        tenant_id=TENANT_ID,
        project_id=PROJECT_ID,
        file_name="first.pdf",
        file_bytes=b"first",
        source_label="ประกาศราคากลาง",
        source_status_text="ประกาศราคากลาง",
    )
    second = repository.store_document(
        tenant_id=TENANT_ID,
        project_id=PROJECT_ID,
        file_name="second.pdf",
        file_bytes=b"second",
        source_label="เอกสารประกวดราคา",
        source_status_text="ประกาศเชิญชวน",
    )

    listed = repository.list_documents(TENANT_ID, PROJECT_ID)

    assert [doc.id for doc in listed][:2] == [second.document.id, first.document.id]


def test_get_artifact_bucket_prefers_current_final_tor(tmp_path) -> None:
    repository = FilesystemDocumentRepository(tmp_path)
    repository.store_document(
        tenant_id=TENANT_ID,
        project_id=PROJECT_ID,
        file_name="price.pdf",
        file_bytes=b"price",
        source_label="ประกาศราคากลาง",
        source_status_text="ประกาศราคากลาง",
    )
    repository.store_document(
        tenant_id=TENANT_ID,
        project_id=PROJECT_ID,
        file_name="draft.pdf",
        file_bytes=b"draft",
        source_label="ร่างเอกสารประกวดราคา",
        source_status_text="รับฟังความคิดเห็น",
    )
    repository.store_document(
        tenant_id=TENANT_ID,
        project_id=PROJECT_ID,
        file_name="final.pdf",
        file_bytes=b"final",
        source_label="เอกสารประกวดราคา",
        source_status_text="ประกาศเชิญชวน",
    )

    assert (
        repository.get_artifact_bucket(TENANT_ID, PROJECT_ID)
        is ArtifactBucket.FINAL_TOR_DOWNLOADED
    )


def test_store_document_persists_diff_rows_in_sql_metadata(tmp_path) -> None:
    repository = FilesystemDocumentRepository(tmp_path)
    first = repository.store_document(
        tenant_id=TENANT_ID,
        project_id=PROJECT_ID,
        file_name="tor-v1.pdf",
        file_bytes=b"version-one",
        source_label="เอกสารประกวดราคา",
        source_status_text="ประกาศเชิญชวน",
    )
    second = repository.store_document(
        tenant_id=TENANT_ID,
        project_id=PROJECT_ID,
        file_name="tor-v2.pdf",
        file_bytes=b"version-two",
        source_label="เอกสารประกวดราคา",
        source_status_text="ประกาศเชิญชวน",
    )

    with sqlite3.connect(tmp_path / "document_metadata.sqlite3") as connection:
        row = connection.execute(
            """
            SELECT old_document_id, new_document_id, diff_type
            FROM document_diffs
            WHERE new_document_id = ?
            """,
            (second.document.id,),
        ).fetchone()

    assert first.created is True
    assert second.created is True
    assert row == (first.document.id, second.document.id, "changed")


def test_store_document_persists_structured_diff_summary_for_phase_transition(
    tmp_path,
) -> None:
    repository = FilesystemDocumentRepository(tmp_path)
    repository.store_document(
        tenant_id=TENANT_ID,
        project_id=PROJECT_ID,
        file_name="tor-hearing.pdf",
        file_bytes=b"draft line\nshared line\n",
        source_label="ร่างขอบเขตของงาน",
        source_status_text="เปิดรับฟังคำวิจารณ์",
    )
    second = repository.store_document(
        tenant_id=TENANT_ID,
        project_id=PROJECT_ID,
        file_name="tor-final.pdf",
        file_bytes=b"final line\nshared line\n",
        source_label="เอกสารประกวดราคา",
        source_status_text="ประกาศเชิญชวน",
    )

    with sqlite3.connect(tmp_path / "document_metadata.sqlite3") as connection:
        row = connection.execute(
            """
            SELECT diff_type, summary_json
            FROM document_diffs
            WHERE new_document_id = ?
            """,
            (second.document.id,),
        ).fetchone()

    assert second.created is True
    assert row[0] == "changed"
    assert row[1] is not None
    assert '"comparison_scope": "phase_transition"' in row[1]
    assert '"changed_line_count": 2' in row[1]


def test_store_document_handles_missing_text_extraction_in_diff_summary(
    tmp_path,
) -> None:
    repository = FilesystemDocumentRepository(tmp_path)
    repository.store_document(
        tenant_id=TENANT_ID,
        project_id=PROJECT_ID,
        file_name="tor-v1.pdf",
        file_bytes=b"\xff\x00\xfe\x01",
        source_label="เอกสารประกวดราคา",
        source_status_text="ประกาศเชิญชวน",
    )
    second = repository.store_document(
        tenant_id=TENANT_ID,
        project_id=PROJECT_ID,
        file_name="tor-v2.pdf",
        file_bytes=b"\xff\x00\xfe\x02",
        source_label="เอกสารประกวดราคา",
        source_status_text="ประกาศเชิญชวน",
    )

    assert second.created is True
    assert second.diff_records[0].summary_json is not None
    assert (
        second.diff_records[0].summary_json["text_extraction_status"] == "unavailable"
    )
    assert second.diff_records[0].summary_json["text_diff_available"] is False


def test_store_document_hashes_and_classifies_once(tmp_path) -> None:
    repository = FilesystemDocumentRepository(tmp_path)

    with (
        patch(
            "egp_db.repositories.document_repo.hash_file", return_value="hash-once"
        ) as hash_mock,
        patch(
            "egp_db.repositories.document_repo.classify_document",
            return_value=(DocumentType.TOR, DocumentPhase.FINAL),
        ) as classify_mock,
    ):
        stored = repository.store_document(
            tenant_id=TENANT_ID,
            project_id=PROJECT_ID,
            file_name="tor.pdf",
            file_bytes=b"tor-bytes",
            source_label="เอกสารประกวดราคา",
            source_status_text="ประกาศเชิญชวน",
        )

    assert stored.created is True
    assert stored.document.sha256 == "hash-once"
    assert stored.document.document_type is DocumentType.TOR
    assert stored.document.document_phase is DocumentPhase.FINAL
    assert hash_mock.call_count == 1
    assert classify_mock.call_count == 1


def test_store_document_creates_pending_review_for_changed_diff(tmp_path) -> None:
    repository = FilesystemDocumentRepository(tmp_path)
    repository.store_document(
        tenant_id=TENANT_ID,
        project_id=PROJECT_ID,
        file_name="tor-v1.pdf",
        file_bytes=b"version-one",
        source_label="เอกสารประกวดราคา",
        source_status_text="ประกาศเชิญชวน",
    )
    second = repository.store_document(
        tenant_id=TENANT_ID,
        project_id=PROJECT_ID,
        file_name="tor-v2.pdf",
        file_bytes=b"version-two",
        source_label="เอกสารประกวดราคา",
        source_status_text="ประกาศเชิญชวน",
    )

    page = repository.list_document_reviews(tenant_id=TENANT_ID, project_id=PROJECT_ID)

    assert second.created is True
    assert page.total == 1
    assert page.limit == 50
    review = page.reviews[0]
    assert review.document_diff_id == second.diff_records[0].id
    assert review.status is DocumentReviewStatus.PENDING
    assert [event.event_type for event in review.events] == [
        DocumentReviewEventType.CREATED
    ]


def test_store_document_skips_review_for_identical_diff(tmp_path) -> None:
    repository = FilesystemDocumentRepository(tmp_path)
    repository.store_document(
        tenant_id=TENANT_ID,
        project_id=PROJECT_ID,
        file_name="tor-hearing.pdf",
        file_bytes=b"same-tor-bytes",
        source_label="ร่างขอบเขตของงาน",
        source_status_text="เปิดรับฟังคำวิจารณ์",
    )
    second = repository.store_document(
        tenant_id=TENANT_ID,
        project_id=PROJECT_ID,
        file_name="tor-final.pdf",
        file_bytes=b"same-tor-bytes",
        source_label="เอกสารประกวดราคา",
        source_status_text="ประกาศเชิญชวน",
    )

    page = repository.list_document_reviews(tenant_id=TENANT_ID, project_id=PROJECT_ID)

    assert second.created is True
    assert second.diff_records[0].diff_type == "identical"
    assert page.total == 0
    assert page.reviews == []


def test_apply_document_review_action_records_history(tmp_path) -> None:
    repository = FilesystemDocumentRepository(tmp_path)
    repository.store_document(
        tenant_id=TENANT_ID,
        project_id=PROJECT_ID,
        file_name="tor-v1.pdf",
        file_bytes=b"version-one",
        source_label="เอกสารประกวดราคา",
        source_status_text="ประกาศเชิญชวน",
    )
    repository.store_document(
        tenant_id=TENANT_ID,
        project_id=PROJECT_ID,
        file_name="tor-v2.pdf",
        file_bytes=b"version-two",
        source_label="เอกสารประกวดราคา",
        source_status_text="ประกาศเชิญชวน",
    )
    review = repository.list_document_reviews(
        tenant_id=TENANT_ID, project_id=PROJECT_ID
    ).reviews[0]

    approved = repository.apply_document_review_action(
        tenant_id=TENANT_ID,
        review_id=review.id,
        action=DocumentReviewAction.APPROVE,
        actor_subject="operator-1",
        note="Confirmed meaningful TOR change",
    )

    assert approved.status is DocumentReviewStatus.APPROVED
    assert [event.event_type for event in approved.events] == [
        DocumentReviewEventType.CREATED,
        DocumentReviewEventType.APPROVED,
    ]
    assert approved.events[-1].actor_subject == "operator-1"
    assert approved.events[-1].note == "Confirmed meaningful TOR change"


def test_document_review_action_is_tenant_scoped(tmp_path) -> None:
    repository = FilesystemDocumentRepository(tmp_path)
    repository.store_document(
        tenant_id=TENANT_ID,
        project_id=PROJECT_ID,
        file_name="tor-v1.pdf",
        file_bytes=b"version-one",
        source_label="เอกสารประกวดราคา",
        source_status_text="ประกาศเชิญชวน",
    )
    repository.store_document(
        tenant_id=TENANT_ID,
        project_id=PROJECT_ID,
        file_name="tor-v2.pdf",
        file_bytes=b"version-two",
        source_label="เอกสารประกวดราคา",
        source_status_text="ประกาศเชิญชวน",
    )
    review = repository.list_document_reviews(
        tenant_id=TENANT_ID, project_id=PROJECT_ID
    ).reviews[0]

    try:
        repository.apply_document_review_action(
            tenant_id="99999999-9999-9999-9999-999999999999",
            review_id=review.id,
            action=DocumentReviewAction.REJECT,
            actor_subject="foreign-operator",
            note="Should not be allowed",
        )
    except KeyError as exc:
        assert str(exc) == f"'{review.id}'"
    else:
        raise AssertionError("expected tenant-scoped review lookup to fail")
