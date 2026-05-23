from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import sqlite3
import threading

from egp_db.artifact_store import LocalArtifactStore
from egp_db.repositories.document_repo import (
    DocumentRecord,
    SqlDocumentRepository,
    StoreDocumentResult,
)
from egp_shared_types.enums import DocumentPhase, DocumentType


TENANT_ID = "11111111-1111-1111-1111-111111111111"
PROJECT_ID = "22222222-2222-2222-2222-222222222222"


class RaceHarnessDocumentRepository(SqlDocumentRepository):
    def __init__(
        self,
        *,
        participant_count: int,
        database_url: str,
        artifact_root: Path,
        bootstrap_schema: bool = True,
    ) -> None:
        super().__init__(
            database_url=database_url,
            artifact_store=LocalArtifactStore(artifact_root),
            bootstrap_schema=bootstrap_schema,
        )
        self._race_barrier = threading.Barrier(participant_count)

    def _find_existing_document(
        self,
        *,
        connection,
        tenant_id: str,
        project_id: str,
        sha256: str,
        document_type: DocumentType,
        document_phase: DocumentPhase,
    ) -> DocumentRecord | None:
        existing = super()._find_existing_document(
            connection=connection,
            tenant_id=tenant_id,
            project_id=project_id,
            sha256=sha256,
            document_type=document_type,
            document_phase=document_phase,
        )
        if existing is None:
            self._race_barrier.wait(timeout=10)
        return existing


def test_concurrent_document_upsert_is_idempotent(tmp_path) -> None:
    database_path = tmp_path / "phase1.sqlite3"
    artifact_root = tmp_path / "artifacts"
    participant_count = 3
    repository = RaceHarnessDocumentRepository(
        participant_count=participant_count,
        database_url=f"sqlite+pysqlite:///{database_path}",
        artifact_root=artifact_root,
        bootstrap_schema=True,
    )

    def store_once(index: int) -> StoreDocumentResult:
        return repository.store_document(
            tenant_id=TENANT_ID,
            project_id=PROJECT_ID,
            file_name=f"tor-copy-{index}.pdf",
            file_bytes=b"same-document-bytes",
            source_label="ร่างขอบเขตของงาน",
            source_status_text="เปิดรับฟังคำวิจารณ์",
        )

    with ThreadPoolExecutor(max_workers=participant_count) as executor:
        results = list(executor.map(store_once, range(participant_count)))

    document_ids = {result.document.id for result in results}
    blob_files = [path for path in artifact_root.rglob("*") if path.is_file()]
    with sqlite3.connect(database_path) as connection:
        document_count = connection.execute(
            """
            SELECT COUNT(*)
            FROM documents
            WHERE tenant_id = ?
              AND project_id = ?
              AND sha256 = ?
              AND document_type = ?
              AND document_phase = ?
            """,
            (
                TENANT_ID,
                PROJECT_ID,
                results[0].document.sha256,
                "tor",
                "public_hearing",
            ),
        ).fetchone()[0]

    assert document_ids == {results[0].document.id}
    assert sum(1 for result in results if result.created) == 1
    assert document_count == 1
    assert len(blob_files) == 1
    assert blob_files[0].read_bytes() == b"same-document-bytes"
