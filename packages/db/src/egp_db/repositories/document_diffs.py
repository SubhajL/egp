"""Document diff lookup and construction operations."""

from __future__ import annotations

import logging
from uuid import uuid4

from sqlalchemy import and_, desc, or_, select

from egp_db.db_utils import normalize_uuid_string
from egp_document_classifier.diff_engine import ComparisonScope, build_document_diff
from egp_shared_types.enums import DocumentPhase, DocumentType

from .document_models import (
    DocumentArtifactReadError,
    DocumentDiffRecord,
    DocumentRecord,
)
from .document_schema import DOCUMENTS_TABLE, DOCUMENT_DIFFS_TABLE
from .document_utils import _diff_from_mapping, _document_from_mapping, _now_iso


logger = logging.getLogger("egp_db.repositories.document_repo")


class DocumentDiffMixin:
    def _find_current_same_class(
        self,
        *,
        connection,
        tenant_id: str,
        project_id: str,
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
                        DOCUMENTS_TABLE.c.document_type == document_type.value,
                        DOCUMENTS_TABLE.c.document_phase == document_phase.value,
                        DOCUMENTS_TABLE.c.is_current.is_(True),
                    )
                )
                .order_by(desc(DOCUMENTS_TABLE.c.created_at))
                .limit(1)
            )
            .mappings()
            .first()
        )
        return _document_from_mapping(row) if row is not None else None

    def _find_phase_transition_target(
        self,
        *,
        connection,
        tenant_id: str,
        project_id: str,
        document_type: DocumentType,
        document_phase: DocumentPhase,
    ) -> DocumentRecord | None:
        if document_type is not DocumentType.TOR:
            return None
        if document_phase is DocumentPhase.PUBLIC_HEARING:
            other_phase = DocumentPhase.FINAL
        elif document_phase is DocumentPhase.FINAL:
            other_phase = DocumentPhase.PUBLIC_HEARING
        else:
            return None
        return self._find_current_same_class(
            connection=connection,
            tenant_id=tenant_id,
            project_id=project_id,
            document_type=document_type,
            document_phase=other_phase,
        )

    def _build_diff_record(
        self,
        *,
        tenant_id: str,
        project_id: str,
        comparison_target: DocumentRecord,
        stored_document: DocumentRecord,
        new_file_bytes: bytes,
        comparison_scope: ComparisonScope,
    ) -> DocumentDiffRecord:
        try:
            old_file_bytes = self._get_document_bytes(
                tenant_id=tenant_id,
                document=comparison_target,
            )
        except DocumentArtifactReadError as exc:
            logger.warning(
                "Previous document artifact missing during diff build",
                extra={
                    "egp_event": "document_diff_previous_artifact_missing",
                    "tenant_id": tenant_id,
                    "project_id": project_id,
                    "old_document_id": comparison_target.id,
                    "new_document_id": stored_document.id,
                    "previous_storage_key": comparison_target.storage_key,
                    "previous_provider": exc.provider,
                },
            )
            return DocumentDiffRecord(
                id=str(uuid4()),
                project_id=project_id,
                old_document_id=comparison_target.id,
                new_document_id=stored_document.id,
                diff_type="changed",
                summary_json={
                    "summary_version": 1,
                    "comparison_scope": comparison_scope,
                    "text_extraction_status": "previous_artifact_missing",
                    "text_diff_available": False,
                    "old_document_phase": comparison_target.document_phase.value,
                    "new_document_phase": stored_document.document_phase.value,
                    "old_sha256": comparison_target.sha256,
                    "new_sha256": stored_document.sha256,
                    "old_size_bytes": comparison_target.size_bytes,
                    "new_size_bytes": stored_document.size_bytes,
                    "size_delta_bytes": (
                        stored_document.size_bytes - comparison_target.size_bytes
                    ),
                    "old_file_name": comparison_target.file_name,
                    "new_file_name": stored_document.file_name,
                    "previous_artifact_missing": True,
                    "previous_storage_key": comparison_target.storage_key,
                    "previous_managed_backup_storage_key": (
                        comparison_target.managed_backup_storage_key
                    ),
                    "previous_provider": exc.provider,
                    "previous_read_error": str(exc.cause),
                },
                created_at=_now_iso(),
            )
        diff_result = build_document_diff(
            old_document_type=comparison_target.document_type,
            old_document_phase=comparison_target.document_phase,
            old_file_name=comparison_target.file_name,
            old_sha256=comparison_target.sha256,
            old_bytes=old_file_bytes,
            new_document_type=stored_document.document_type,
            new_document_phase=stored_document.document_phase,
            new_file_name=stored_document.file_name,
            new_sha256=stored_document.sha256,
            new_bytes=new_file_bytes,
            comparison_scope=comparison_scope,
        )
        return DocumentDiffRecord(
            id=str(uuid4()),
            project_id=project_id,
            old_document_id=comparison_target.id,
            new_document_id=stored_document.id,
            diff_type=diff_result.diff_type,
            summary_json=diff_result.summary_json,
            created_at=_now_iso(),
        )

    def list_document_diffs(
        self, *, tenant_id: str, project_id: str
    ) -> list[DocumentDiffRecord]:
        normalized_tenant_id = normalize_uuid_string(tenant_id)
        normalized_project_id = normalize_uuid_string(project_id)
        with self._engine.connect() as connection:
            rows = (
                connection.execute(
                    select(DOCUMENT_DIFFS_TABLE)
                    .where(
                        and_(
                            DOCUMENT_DIFFS_TABLE.c.tenant_id == normalized_tenant_id,
                            DOCUMENT_DIFFS_TABLE.c.project_id == normalized_project_id,
                        )
                    )
                    .order_by(desc(DOCUMENT_DIFFS_TABLE.c.created_at))
                )
                .mappings()
                .all()
            )
        return [_diff_from_mapping(row) for row in rows]

    def get_document_diff(
        self,
        *,
        tenant_id: str,
        document_id: str,
        other_document_id: str,
    ) -> DocumentDiffRecord | None:
        normalized_tenant_id = normalize_uuid_string(tenant_id)
        normalized_document_id = normalize_uuid_string(document_id)
        normalized_other_document_id = normalize_uuid_string(other_document_id)
        with self._engine.connect() as connection:
            row = (
                connection.execute(
                    select(DOCUMENT_DIFFS_TABLE)
                    .where(
                        and_(
                            DOCUMENT_DIFFS_TABLE.c.tenant_id == normalized_tenant_id,
                            or_(
                                and_(
                                    DOCUMENT_DIFFS_TABLE.c.old_document_id
                                    == normalized_other_document_id,
                                    DOCUMENT_DIFFS_TABLE.c.new_document_id
                                    == normalized_document_id,
                                ),
                                and_(
                                    DOCUMENT_DIFFS_TABLE.c.old_document_id
                                    == normalized_document_id,
                                    DOCUMENT_DIFFS_TABLE.c.new_document_id
                                    == normalized_other_document_id,
                                ),
                            ),
                        )
                    )
                    .order_by(desc(DOCUMENT_DIFFS_TABLE.c.created_at))
                    .limit(1)
                )
                .mappings()
                .first()
            )
        return _diff_from_mapping(row) if row is not None else None
