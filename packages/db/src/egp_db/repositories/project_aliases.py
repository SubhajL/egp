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
            statement = _dialect_insert(PROJECT_ALIASES_TABLE, connection).values(
                id=str(uuid4()),
                project_id=project_id,
                alias_type=alias_type,
                alias_value=alias_value,
                created_at=created_at,
            )
            if hasattr(statement, "on_conflict_do_nothing"):
                statement = statement.on_conflict_do_nothing(
                    index_elements=[
                        PROJECT_ALIASES_TABLE.c.project_id,
                        PROJECT_ALIASES_TABLE.c.alias_type,
                        PROJECT_ALIASES_TABLE.c.alias_value,
                    ]
                )
            connection.execute(statement)

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
        statement = _dialect_insert(PROJECT_STATUS_EVENTS_TABLE, connection).values(
            id=str(uuid4()),
            project_id=project_id,
            observed_status_text=observed_status_text,
            normalized_status=normalized_status,
            observed_at=observed_at,
            run_id=run_id,
            raw_snapshot=raw_snapshot,
            created_at=observed_at,
        )
        if hasattr(statement, "on_conflict_do_nothing"):
            statement = statement.on_conflict_do_nothing(
                index_elements=[
                    PROJECT_STATUS_EVENTS_TABLE.c.project_id,
                    PROJECT_STATUS_EVENTS_TABLE.c.normalized_status,
                    PROJECT_STATUS_EVENTS_TABLE.c.observed_at,
                ]
            )
        connection.execute(statement)


def _dialect_insert(table, connection):
    if connection.dialect.name == "postgresql":
        from sqlalchemy.dialects.postgresql import insert as postgresql_insert

        return postgresql_insert(table)
    if connection.dialect.name == "sqlite":
        from sqlalchemy.dialects.sqlite import insert as sqlite_insert

        return sqlite_insert(table)
    return insert(table)
