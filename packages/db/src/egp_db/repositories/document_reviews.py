"""Document review lifecycle operations."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import and_, desc, func, insert, select, update
from sqlalchemy.engine import RowMapping

from egp_db.db_utils import normalize_uuid_string
from egp_shared_types.enums import (
    DocumentReviewAction,
    DocumentReviewEventType,
    DocumentReviewStatus,
)

from .document_models import (
    DocumentDiffRecord,
    DocumentReviewDetail,
    DocumentReviewEventRecord,
    DocumentReviewPage,
)
from .document_schema import (
    DOCUMENT_DIFFS_TABLE,
    DOCUMENT_DIFF_REVIEWS_TABLE,
    DOCUMENT_REVIEW_EVENTS_TABLE,
)
from .document_utils import (
    _diff_from_mapping,
    _normalize_limit_offset,
    _normalize_review_action,
    _normalize_review_status,
    _review_event_from_mapping,
    _to_db_timestamp,
)


class DocumentReviewMixin:
    def _append_review_event(
        self,
        connection,
        *,
        tenant_id: str,
        project_id: str,
        review_id: str,
        document_diff_id: str,
        event_type: DocumentReviewEventType,
        actor_subject: str | None,
        note: str | None,
        from_status: DocumentReviewStatus | None,
        to_status: DocumentReviewStatus | None,
        created_at: datetime,
    ) -> None:
        connection.execute(
            insert(DOCUMENT_REVIEW_EVENTS_TABLE).values(
                id=str(uuid4()),
                tenant_id=tenant_id,
                project_id=project_id,
                review_id=review_id,
                document_diff_id=document_diff_id,
                event_type=event_type.value,
                actor_subject=str(actor_subject).strip() if actor_subject else None,
                note=str(note).strip() if note else None,
                from_status=from_status.value if from_status is not None else None,
                to_status=to_status.value if to_status is not None else None,
                created_at=created_at,
            )
        )

    def _create_review_for_changed_diff(
        self,
        connection,
        *,
        tenant_id: str,
        project_id: str,
        diff_record: DocumentDiffRecord,
    ) -> None:
        existing = (
            connection.execute(
                select(DOCUMENT_DIFF_REVIEWS_TABLE.c.id).where(
                    and_(
                        DOCUMENT_DIFF_REVIEWS_TABLE.c.tenant_id == tenant_id,
                        DOCUMENT_DIFF_REVIEWS_TABLE.c.document_diff_id
                        == diff_record.id,
                    )
                )
            )
            .mappings()
            .first()
        )
        if existing is not None:
            return
        now = _to_db_timestamp(diff_record.created_at)
        review_id = str(uuid4())
        connection.execute(
            insert(DOCUMENT_DIFF_REVIEWS_TABLE).values(
                id=review_id,
                tenant_id=tenant_id,
                project_id=project_id,
                document_diff_id=diff_record.id,
                status=DocumentReviewStatus.PENDING.value,
                resolved_at=None,
                created_at=now,
                updated_at=now,
            )
        )
        self._append_review_event(
            connection,
            tenant_id=tenant_id,
            project_id=project_id,
            review_id=review_id,
            document_diff_id=diff_record.id,
            event_type=DocumentReviewEventType.CREATED,
            actor_subject=None,
            note=None,
            from_status=None,
            to_status=DocumentReviewStatus.PENDING,
            created_at=now,
        )

    def _load_review_events(
        self,
        connection,
        *,
        review_ids: list[str],
    ) -> dict[str, list[DocumentReviewEventRecord]]:
        if not review_ids:
            return {}
        rows = (
            connection.execute(
                select(DOCUMENT_REVIEW_EVENTS_TABLE)
                .where(DOCUMENT_REVIEW_EVENTS_TABLE.c.review_id.in_(review_ids))
                .order_by(DOCUMENT_REVIEW_EVENTS_TABLE.c.created_at.asc())
            )
            .mappings()
            .all()
        )
        grouped: dict[str, list[DocumentReviewEventRecord]] = {}
        for row in rows:
            event = _review_event_from_mapping(row)
            grouped.setdefault(event.review_id, []).append(event)
        return grouped

    def _load_diffs_by_id(
        self,
        connection,
        *,
        diff_ids: list[str],
    ) -> dict[str, DocumentDiffRecord]:
        if not diff_ids:
            return {}
        rows = (
            connection.execute(
                select(DOCUMENT_DIFFS_TABLE).where(
                    DOCUMENT_DIFFS_TABLE.c.id.in_(diff_ids)
                )
            )
            .mappings()
            .all()
        )
        return {str(row["id"]): _diff_from_mapping(row) for row in rows}

    def _build_review_detail(
        self,
        *,
        row: RowMapping,
        diff: DocumentDiffRecord,
        events: list[DocumentReviewEventRecord],
    ) -> DocumentReviewDetail:
        resolved_at = row["resolved_at"]
        created_at = row["created_at"]
        updated_at = row["updated_at"]
        return DocumentReviewDetail(
            id=str(row["id"]),
            project_id=str(row["project_id"]),
            document_diff_id=str(row["document_diff_id"]),
            status=DocumentReviewStatus(str(row["status"])),
            resolved_at=resolved_at.isoformat()
            if isinstance(resolved_at, datetime)
            else (str(resolved_at) if resolved_at is not None else None),
            created_at=created_at.isoformat()
            if isinstance(created_at, datetime)
            else str(created_at),
            updated_at=updated_at.isoformat()
            if isinstance(updated_at, datetime)
            else str(updated_at),
            diff=diff,
            events=events,
        )

    def list_document_reviews(
        self,
        *,
        tenant_id: str,
        project_id: str,
        status: DocumentReviewStatus | str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> DocumentReviewPage:
        normalized_tenant_id = normalize_uuid_string(tenant_id)
        normalized_project_id = normalize_uuid_string(project_id)
        normalized_status = _normalize_review_status(status)
        normalized_limit, normalized_offset = _normalize_limit_offset(
            limit=limit,
            offset=offset,
        )
        criteria = [
            DOCUMENT_DIFF_REVIEWS_TABLE.c.tenant_id == normalized_tenant_id,
            DOCUMENT_DIFF_REVIEWS_TABLE.c.project_id == normalized_project_id,
        ]
        if normalized_status is not None:
            criteria.append(
                DOCUMENT_DIFF_REVIEWS_TABLE.c.status == normalized_status.value
            )
        with self._engine.connect() as connection:
            total = int(
                connection.execute(
                    select(func.count())
                    .select_from(DOCUMENT_DIFF_REVIEWS_TABLE)
                    .where(and_(*criteria))
                ).scalar_one()
            )
            rows = (
                connection.execute(
                    select(DOCUMENT_DIFF_REVIEWS_TABLE)
                    .where(and_(*criteria))
                    .order_by(desc(DOCUMENT_DIFF_REVIEWS_TABLE.c.created_at))
                    .limit(normalized_limit)
                    .offset(normalized_offset)
                )
                .mappings()
                .all()
            )
            review_ids = [str(row["id"]) for row in rows]
            diff_ids = [str(row["document_diff_id"]) for row in rows]
            event_map = self._load_review_events(connection, review_ids=review_ids)
            diff_map = self._load_diffs_by_id(connection, diff_ids=diff_ids)
        reviews = [
            self._build_review_detail(
                row=row,
                diff=diff_map[str(row["document_diff_id"])],
                events=event_map.get(str(row["id"]), []),
            )
            for row in rows
        ]
        return DocumentReviewPage(
            reviews=reviews,
            total=total,
            limit=normalized_limit,
            offset=normalized_offset,
        )

    def get_document_review(
        self,
        *,
        tenant_id: str,
        review_id: str,
    ) -> DocumentReviewDetail | None:
        normalized_tenant_id = normalize_uuid_string(tenant_id)
        normalized_review_id = normalize_uuid_string(review_id)
        with self._engine.connect() as connection:
            row = (
                connection.execute(
                    select(DOCUMENT_DIFF_REVIEWS_TABLE)
                    .where(
                        and_(
                            DOCUMENT_DIFF_REVIEWS_TABLE.c.tenant_id
                            == normalized_tenant_id,
                            DOCUMENT_DIFF_REVIEWS_TABLE.c.id == normalized_review_id,
                        )
                    )
                    .limit(1)
                )
                .mappings()
                .first()
            )
            if row is None:
                return None
            event_map = self._load_review_events(
                connection, review_ids=[normalized_review_id]
            )
            diff_map = self._load_diffs_by_id(
                connection,
                diff_ids=[str(row["document_diff_id"])],
            )
        return self._build_review_detail(
            row=row,
            diff=diff_map[str(row["document_diff_id"])],
            events=event_map.get(normalized_review_id, []),
        )

    def apply_document_review_action(
        self,
        *,
        tenant_id: str,
        review_id: str,
        action: DocumentReviewAction | str,
        actor_subject: str | None = None,
        note: str | None = None,
    ) -> DocumentReviewDetail:
        normalized_tenant_id = normalize_uuid_string(tenant_id)
        normalized_review_id = normalize_uuid_string(review_id)
        normalized_action = _normalize_review_action(action)
        now = datetime.now(UTC)
        with self._engine.begin() as connection:
            row = (
                connection.execute(
                    select(DOCUMENT_DIFF_REVIEWS_TABLE)
                    .where(
                        and_(
                            DOCUMENT_DIFF_REVIEWS_TABLE.c.tenant_id
                            == normalized_tenant_id,
                            DOCUMENT_DIFF_REVIEWS_TABLE.c.id == normalized_review_id,
                        )
                    )
                    .limit(1)
                )
                .mappings()
                .first()
            )
            if row is None:
                raise KeyError(normalized_review_id)
            current_status = DocumentReviewStatus(str(row["status"]))
            if normalized_action is DocumentReviewAction.APPROVE:
                if current_status is not DocumentReviewStatus.PENDING:
                    raise ValueError("approve action requires pending review status")
                next_status = DocumentReviewStatus.APPROVED
                event_type = DocumentReviewEventType.APPROVED
                resolved_at = now
            elif normalized_action is DocumentReviewAction.REJECT:
                if current_status is not DocumentReviewStatus.PENDING:
                    raise ValueError("reject action requires pending review status")
                next_status = DocumentReviewStatus.REJECTED
                event_type = DocumentReviewEventType.REJECTED
                resolved_at = now
            else:
                if current_status is DocumentReviewStatus.PENDING:
                    raise ValueError(
                        "reopen action requires approved or rejected review status"
                    )
                next_status = DocumentReviewStatus.PENDING
                event_type = DocumentReviewEventType.REOPENED
                resolved_at = None
            connection.execute(
                update(DOCUMENT_DIFF_REVIEWS_TABLE)
                .where(
                    and_(
                        DOCUMENT_DIFF_REVIEWS_TABLE.c.tenant_id == normalized_tenant_id,
                        DOCUMENT_DIFF_REVIEWS_TABLE.c.id == normalized_review_id,
                    )
                )
                .values(
                    status=next_status.value,
                    resolved_at=resolved_at,
                    updated_at=now,
                )
            )
            self._append_review_event(
                connection,
                tenant_id=normalized_tenant_id,
                project_id=str(row["project_id"]),
                review_id=normalized_review_id,
                document_diff_id=str(row["document_diff_id"]),
                event_type=event_type,
                actor_subject=actor_subject,
                note=note,
                from_status=current_status,
                to_status=next_status,
                created_at=now,
            )
        detail = self.get_document_review(
            tenant_id=normalized_tenant_id,
            review_id=normalized_review_id,
        )
        if detail is None:
            raise KeyError(normalized_review_id)
        return detail
