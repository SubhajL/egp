from __future__ import annotations

import sqlite3
from unittest.mock import patch

from egp_db.repositories.document_repo import FilesystemDocumentRepository
from egp_shared_types.enums import DocumentPhase, DocumentType

TENANT_ID = "11111111-1111-1111-1111-111111111111"
PROJECT_ID = "22222222-2222-2222-2222-222222222222"


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
    assert any(doc.id == first.document.id and doc.is_current is False for doc in listed)
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


def test_store_document_persists_structured_diff_summary_for_phase_transition(tmp_path) -> None:
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


def test_store_document_handles_missing_text_extraction_in_diff_summary(tmp_path) -> None:
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
    assert second.diff_records[0].summary_json["text_extraction_status"] == "unavailable"
    assert second.diff_records[0].summary_json["text_diff_available"] is False


def test_store_document_hashes_and_classifies_once(tmp_path) -> None:
    repository = FilesystemDocumentRepository(tmp_path)

    with (
        patch("egp_db.repositories.document_repo.hash_file", return_value="hash-once") as hash_mock,
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
