"""Document metadata persistence operations."""

from __future__ import annotations

import logging
import mimetypes

from sqlalchemy import and_, desc, insert, select, update

from egp_db.artifact_store import ArtifactStore
from egp_db.db_utils import normalize_uuid_string
from egp_db.tenant_storage_resolver import ResolvedDocumentWritePlan
from egp_document_classifier.classifier import derive_artifact_bucket
from egp_document_classifier.diff_engine import ComparisonScope
from egp_shared_types.enums import ArtifactBucket, DocumentPhase, DocumentType

from .document_models import DocumentDiffRecord, DocumentRecord, StoreDocumentResult
from .document_schema import DOCUMENTS_TABLE, DOCUMENT_DIFFS_TABLE, METADATA
from .document_utils import (
    _document_from_mapping,
    _sanitize_file_name,
    _to_db_timestamp,
    build_document_record,
)


logger = logging.getLogger("egp_db.repositories.document_repo")


class DocumentPersistenceMixin:
    def _ensure_schema(self) -> None:
        METADATA.create_all(self._engine)

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
        row = (
            connection.execute(
                select(DOCUMENTS_TABLE)
                .where(
                    and_(
                        DOCUMENTS_TABLE.c.tenant_id == tenant_id,
                        DOCUMENTS_TABLE.c.project_id == project_id,
                        DOCUMENTS_TABLE.c.sha256 == sha256,
                        DOCUMENTS_TABLE.c.document_type == document_type.value,
                        DOCUMENTS_TABLE.c.document_phase == document_phase.value,
                    )
                )
                .limit(1)
            )
            .mappings()
            .first()
        )
        return _document_from_mapping(row) if row is not None else None

    def store_document(
        self,
        *,
        tenant_id: str,
        project_id: str,
        file_name: str,
        file_bytes: bytes,
        source_label: str,
        source_status_text: str,
        source_page_text: str = "",
        project_state: str | None = None,
    ) -> StoreDocumentResult:
        tenant_id = normalize_uuid_string(tenant_id)
        project_id = normalize_uuid_string(project_id)
        from egp_db.repositories import document_repo

        document_sha256 = document_repo.hash_file(file_bytes)
        document_type, document_phase = document_repo.classify_document(
            label=source_label,
            source_status_text=source_status_text,
            source_page_text=source_page_text,
            project_state=project_state,
            file_name=file_name,
        )
        draft_document = build_document_record(
            project_id=project_id,
            file_name=file_name,
            file_bytes=file_bytes,
            source_label=source_label,
            source_status_text=source_status_text,
            storage_key="",
            source_page_text=source_page_text,
            project_state=project_state,
            sha256=document_sha256,
            document_type=document_type,
            document_phase=document_phase,
        )
        safe_name = _sanitize_file_name(file_name)
        blob_key = f"tenants/{tenant_id}/projects/{project_id}/artifacts/{draft_document.sha256}/{safe_name}"
        content_type = mimetypes.guess_type(file_name)[0]

        cleanup_targets: list[tuple[str, ArtifactStore, str]] = []
        write_plan: ResolvedDocumentWritePlan | None = None
        try:
            with self._engine.begin() as connection:
                existing = self._find_existing_document(
                    connection=connection,
                    tenant_id=tenant_id,
                    project_id=project_id,
                    sha256=draft_document.sha256,
                    document_type=draft_document.document_type,
                    document_phase=draft_document.document_phase,
                )
                if existing is not None:
                    logger.info(
                        "Duplicate document replay detected for %s",
                        file_name,
                        extra={
                            "egp_event": "document_store_duplicate_replay_detected",
                            "tenant_id": tenant_id,
                            "project_id": project_id,
                            "file_name": file_name,
                            "existing_document_id": existing.id,
                            "document_sha256": draft_document.sha256,
                            "document_type": draft_document.document_type.value,
                            "document_phase": draft_document.document_phase.value,
                        },
                    )
                    return StoreDocumentResult(
                        created=False,
                        document=existing,
                        diff_records=[],
                    )

                current_same_class = self._find_current_same_class(
                    connection=connection,
                    tenant_id=tenant_id,
                    project_id=project_id,
                    document_type=draft_document.document_type,
                    document_phase=draft_document.document_phase,
                )
                comparison_target = current_same_class
                comparison_scope: ComparisonScope | None = (
                    "same_phase_version" if current_same_class is not None else None
                )
                if comparison_target is None:
                    comparison_target = self._find_phase_transition_target(
                        connection=connection,
                        tenant_id=tenant_id,
                        project_id=project_id,
                        document_type=draft_document.document_type,
                        document_phase=draft_document.document_phase,
                    )
                    if comparison_target is not None:
                        comparison_scope = "phase_transition"

                write_plan = self._resolve_document_write_plan(tenant_id=tenant_id)
                logger.info(
                    "Resolved document write plan for %s",
                    file_name,
                    extra={
                        "egp_event": "document_store_write_plan_resolved",
                        "tenant_id": tenant_id,
                        "project_id": project_id,
                        "file_name": file_name,
                        "document_sha256": draft_document.sha256,
                        "document_type": draft_document.document_type.value,
                        "document_phase": draft_document.document_phase.value,
                        "blob_key": blob_key,
                        "primary_provider": write_plan.primary.provider,
                        "managed_backup_enabled": write_plan.managed_backup is not None,
                        "managed_backup_provider": (
                            write_plan.managed_backup.provider
                            if write_plan.managed_backup is not None
                            else None
                        ),
                    },
                )
                raw_stored_key = write_plan.primary.store.put_bytes(
                    key=blob_key,
                    data=file_bytes,
                    content_type=content_type,
                )
                cleanup_targets.append(
                    (
                        write_plan.primary.provider,
                        write_plan.primary.store,
                        raw_stored_key,
                    )
                )
                stored_key = write_plan.primary.encode_storage_key(raw_stored_key)
                logger.info(
                    "Primary document write succeeded for %s",
                    file_name,
                    extra={
                        "egp_event": "document_store_primary_write_succeeded",
                        "tenant_id": tenant_id,
                        "project_id": project_id,
                        "file_name": file_name,
                        "blob_key": blob_key,
                        "primary_provider": write_plan.primary.provider,
                        "raw_storage_key": raw_stored_key,
                        "storage_key": stored_key,
                    },
                )
                managed_backup_storage_key: str | None = None
                if write_plan.managed_backup is not None:
                    managed_backup_storage_key = (
                        write_plan.managed_backup.store.put_bytes(
                            key=blob_key,
                            data=file_bytes,
                            content_type=content_type,
                        )
                    )
                    cleanup_targets.append(
                        (
                            write_plan.managed_backup.provider,
                            write_plan.managed_backup.store,
                            managed_backup_storage_key,
                        )
                    )
                    logger.info(
                        "Managed backup write succeeded for %s",
                        file_name,
                        extra={
                            "egp_event": "document_store_backup_write_succeeded",
                            "tenant_id": tenant_id,
                            "project_id": project_id,
                            "file_name": file_name,
                            "blob_key": blob_key,
                            "primary_provider": write_plan.primary.provider,
                            "managed_backup_provider": write_plan.managed_backup.provider,
                            "managed_backup_storage_key": managed_backup_storage_key,
                        },
                    )
                stored_document = build_document_record(
                    project_id=project_id,
                    file_name=file_name,
                    file_bytes=file_bytes,
                    source_label=source_label,
                    source_status_text=source_status_text,
                    storage_key=stored_key,
                    managed_backup_storage_key=managed_backup_storage_key,
                    source_page_text=source_page_text,
                    project_state=project_state,
                    supersedes_document_id=(
                        current_same_class.id
                        if current_same_class is not None
                        else None
                    ),
                    sha256=document_sha256,
                    document_type=document_type,
                    document_phase=document_phase,
                )

                if current_same_class is not None:
                    connection.execute(
                        update(DOCUMENTS_TABLE)
                        .where(
                            and_(
                                DOCUMENTS_TABLE.c.tenant_id == tenant_id,
                                DOCUMENTS_TABLE.c.id == current_same_class.id,
                            )
                        )
                        .values(is_current=False)
                    )

                connection.execute(
                    insert(DOCUMENTS_TABLE).values(
                        id=stored_document.id,
                        tenant_id=tenant_id,
                        project_id=stored_document.project_id,
                        file_name=stored_document.file_name,
                        sha256=stored_document.sha256,
                        storage_key=stored_document.storage_key,
                        managed_backup_storage_key=stored_document.managed_backup_storage_key,
                        document_type=stored_document.document_type.value,
                        document_phase=stored_document.document_phase.value,
                        source_label=stored_document.source_label,
                        source_status_text=stored_document.source_status_text,
                        size_bytes=stored_document.size_bytes,
                        is_current=stored_document.is_current,
                        supersedes_document_id=stored_document.supersedes_document_id,
                        created_at=_to_db_timestamp(stored_document.created_at),
                    )
                )

                new_diff_records: list[DocumentDiffRecord] = []
                if comparison_target is not None and comparison_scope is not None:
                    diff_record = self._build_diff_record(
                        tenant_id=tenant_id,
                        project_id=project_id,
                        comparison_target=comparison_target,
                        stored_document=stored_document,
                        new_file_bytes=file_bytes,
                        comparison_scope=comparison_scope,
                    )
                    connection.execute(
                        insert(DOCUMENT_DIFFS_TABLE).values(
                            id=diff_record.id,
                            tenant_id=tenant_id,
                            project_id=diff_record.project_id,
                            old_document_id=diff_record.old_document_id,
                            new_document_id=diff_record.new_document_id,
                            diff_type=diff_record.diff_type,
                            summary_json=diff_record.summary_json,
                            created_at=_to_db_timestamp(diff_record.created_at),
                        )
                    )
                    new_diff_records.append(diff_record)
                    if diff_record.diff_type == "changed":
                        self._create_review_for_changed_diff(
                            connection,
                            tenant_id=tenant_id,
                            project_id=project_id,
                            diff_record=diff_record,
                        )

                return StoreDocumentResult(
                    created=True,
                    document=stored_document,
                    diff_records=new_diff_records,
                )
        except Exception:
            logger.exception(
                "Document store failed before cleanup for %s",
                file_name,
                extra={
                    "egp_event": "document_store_failed_before_cleanup",
                    "tenant_id": tenant_id,
                    "project_id": project_id,
                    "file_name": file_name,
                    "document_sha256": draft_document.sha256,
                    "document_type": draft_document.document_type.value,
                    "document_phase": draft_document.document_phase.value,
                    "blob_key": blob_key,
                    "primary_provider": (
                        write_plan.primary.provider
                        if write_plan is not None
                        else "unresolved"
                    ),
                    "managed_backup_enabled": (
                        write_plan.managed_backup is not None
                        if write_plan is not None
                        else False
                    ),
                    "cleanup_target_count": len(cleanup_targets),
                    "cleanup_storage_keys": [
                        cleanup_storage_key
                        for _, _, cleanup_storage_key in cleanup_targets
                    ],
                    "cleanup_providers": [
                        cleanup_provider for cleanup_provider, _, _ in cleanup_targets
                    ],
                },
            )
            for _, cleanup_artifact_store, cleanup_storage_key in reversed(
                cleanup_targets
            ):
                cleanup_artifact_store.delete(cleanup_storage_key)
            raise

    def list_documents(self, tenant_id: str, project_id: str) -> list[DocumentRecord]:
        tenant_id = normalize_uuid_string(tenant_id)
        project_id = normalize_uuid_string(project_id)
        with self._engine.connect() as connection:
            rows = (
                connection.execute(
                    select(DOCUMENTS_TABLE)
                    .where(
                        and_(
                            DOCUMENTS_TABLE.c.tenant_id == tenant_id,
                            DOCUMENTS_TABLE.c.project_id == project_id,
                        )
                    )
                    .order_by(desc(DOCUMENTS_TABLE.c.created_at))
                )
                .mappings()
                .all()
            )
        return [_document_from_mapping(row) for row in rows]

    def get_artifact_bucket(self, tenant_id: str, project_id: str) -> ArtifactBucket:
        documents = self.list_documents(tenant_id, project_id)
        return derive_artifact_bucket(
            documents=[
                {
                    "document_type": document.document_type.value,
                    "document_phase": document.document_phase.value,
                }
                for document in documents
                if document.is_current
            ]
        )

    def get_document(
        self, *, tenant_id: str, document_id: str
    ) -> DocumentRecord | None:
        tenant_id = normalize_uuid_string(tenant_id)
        document_id = normalize_uuid_string(document_id)
        with self._engine.connect() as connection:
            row = (
                connection.execute(
                    select(DOCUMENTS_TABLE)
                    .where(
                        and_(
                            DOCUMENTS_TABLE.c.tenant_id == tenant_id,
                            DOCUMENTS_TABLE.c.id == document_id,
                        )
                    )
                    .limit(1)
                )
                .mappings()
                .first()
            )
        return _document_from_mapping(row) if row is not None else None
