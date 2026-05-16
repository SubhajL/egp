"""Project alias lookup and status-event persistence helpers."""

from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from sqlalchemy import and_, desc, insert, select

from .project_models import ProjectUpsertRecord
from .project_schema import (
    PROJECTS_TABLE,
    PROJECT_ALIASES_TABLE,
    PROJECT_STATUS_EVENTS_TABLE,
)
from .project_utils import (
    _normalize_optional_text,
    _status_event_signature,
    _STRONG_ALIAS_TYPES,
)


class ProjectAliasMixin:
    def _find_existing_row(
        self, connection, *, tenant_id: str, record: ProjectUpsertRecord
    ):
        row = (
            connection.execute(
                select(PROJECTS_TABLE)
                .where(
                    and_(
                        PROJECTS_TABLE.c.tenant_id == tenant_id,
                        PROJECTS_TABLE.c.canonical_project_id
                        == record.canonical_project_id,
                    )
                )
                .limit(1)
            )
            .mappings()
            .first()
        )
        if row is not None:
            return row

        alias_values = [
            alias_value
            for alias_type, alias_value in record.aliases
            if alias_type in _STRONG_ALIAS_TYPES
        ]
        if not alias_values:
            return None
        return (
            connection.execute(
                select(PROJECTS_TABLE)
                .join(
                    PROJECT_ALIASES_TABLE,
                    PROJECT_ALIASES_TABLE.c.project_id == PROJECTS_TABLE.c.id,
                )
                .where(
                    and_(
                        PROJECTS_TABLE.c.tenant_id == tenant_id,
                        PROJECT_ALIASES_TABLE.c.alias_value.in_(alias_values),
                    )
                )
                .order_by(desc(PROJECTS_TABLE.c.updated_at))
                .limit(1)
            )
            .mappings()
            .first()
        )

    def _upsert_aliases(
        self,
        connection,
        *,
        project_id: str,
        aliases: list[tuple[str, str]],
        created_at: datetime,
    ) -> None:
        for alias_type, alias_value in aliases:
            existing = connection.execute(
                select(PROJECT_ALIASES_TABLE.c.id).where(
                    and_(
                        PROJECT_ALIASES_TABLE.c.project_id == project_id,
                        PROJECT_ALIASES_TABLE.c.alias_type == alias_type,
                        PROJECT_ALIASES_TABLE.c.alias_value == alias_value,
                    )
                )
            ).first()
            if existing is not None:
                continue
            connection.execute(
                insert(PROJECT_ALIASES_TABLE).values(
                    id=str(uuid4()),
                    project_id=project_id,
                    alias_type=alias_type,
                    alias_value=alias_value,
                    created_at=created_at,
                )
            )

    def _insert_status_event(
        self,
        connection,
        *,
        project_id: str,
        observed_status_text: str,
        normalized_status: str,
        observed_at: datetime,
        run_id: str | None,
        raw_snapshot: dict[str, object] | None,
    ) -> None:
        latest_row = (
            connection.execute(
                select(PROJECT_STATUS_EVENTS_TABLE)
                .where(PROJECT_STATUS_EVENTS_TABLE.c.project_id == project_id)
                .order_by(
                    desc(PROJECT_STATUS_EVENTS_TABLE.c.observed_at),
                    desc(PROJECT_STATUS_EVENTS_TABLE.c.created_at),
                )
                .limit(1)
            )
            .mappings()
            .first()
        )
        if latest_row is not None:
            latest_signature = _status_event_signature(
                observed_status_text=str(latest_row["observed_status_text"]),
                normalized_status=_normalize_optional_text(
                    latest_row["normalized_status"]
                ),
            )
            next_signature = _status_event_signature(
                observed_status_text=observed_status_text,
                normalized_status=normalized_status,
            )
            if latest_signature == next_signature:
                return
        connection.execute(
            insert(PROJECT_STATUS_EVENTS_TABLE).values(
                id=str(uuid4()),
                project_id=project_id,
                observed_status_text=observed_status_text,
                normalized_status=normalized_status,
                observed_at=observed_at,
                run_id=run_id,
                raw_snapshot=raw_snapshot,
                created_at=observed_at,
            )
        )
