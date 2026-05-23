"""Project persistence operations."""

from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from sqlalchemy import and_, func, insert, select, update

from egp_crawler_core.project_lifecycle import transition_state
from egp_db.db_utils import normalize_uuid_string
from egp_shared_types.enums import ProjectState

from .project_models import ProjectRecord, ProjectUpsertRecord
from .project_schema import METADATA, PROJECTS_TABLE
from .project_utils import (
    _now,
    _normalize_budget_amount,
    _normalize_date,
    _normalize_optional_text,
    _normalize_run_id,
    _project_from_mapping,
)


class ProjectPersistenceMixin:
    def _ensure_schema(self) -> None:
        METADATA.create_all(self._engine)

    def upsert_project(
        self,
        record: ProjectUpsertRecord,
        *,
        source_status_text: str | None = None,
        run_id: str | None = None,
        raw_snapshot: dict[str, object] | None = None,
        observed_at: str | None = None,
    ) -> ProjectRecord:
        tenant_id = normalize_uuid_string(record.tenant_id)
        normalized_run_id = _normalize_run_id(run_id)
        now = datetime.fromisoformat(observed_at) if observed_at else _now()
        normalized_status_text = _normalize_optional_text(source_status_text)

        with self._engine.begin() as connection:
            existing_row = self._find_existing_row(
                connection, tenant_id=tenant_id, record=record
            )

            if existing_row is None:
                candidate_project_id = str(uuid4())
                row = self._upsert_project_by_canonical(
                    connection,
                    project_id=candidate_project_id,
                    tenant_id=tenant_id,
                    record=record,
                    normalized_status_text=normalized_status_text,
                    normalized_run_id=normalized_run_id,
                    now=now,
                )
                if str(row["id"]) == candidate_project_id:
                    project_id = candidate_project_id
                    persisted_project_state = str(row["project_state"])
                else:
                    existing_row = row

            if existing_row is not None:
                existing = _project_from_mapping(existing_row)
                transition = transition_state(
                    current_state=existing.project_state,
                    next_state=record.project_state,
                    closed_reason=record.closed_reason,
                )
                project_id = existing.id
                changed = any(
                    (
                        existing.canonical_project_id != record.canonical_project_id,
                        existing.project_number != record.project_number
                        and record.project_number is not None,
                        existing.project_name != record.project_name,
                        existing.organization_name != record.organization_name,
                        existing.procurement_type != record.procurement_type,
                        existing.proposal_submission_date
                        != record.proposal_submission_date,
                        existing.budget_amount != record.budget_amount,
                        existing.project_state != transition["project_state"],
                        existing.closed_reason != transition["closed_reason"],
                        existing.source_status_text != normalized_status_text
                        and normalized_status_text is not None,
                    )
                )
                connection.execute(
                    update(PROJECTS_TABLE)
                    .where(
                        and_(
                            PROJECTS_TABLE.c.tenant_id == tenant_id,
                            PROJECTS_TABLE.c.id == project_id,
                        )
                    )
                    .values(
                        canonical_project_id=record.canonical_project_id,
                        project_number=record.project_number or existing.project_number,
                        project_name=record.project_name,
                        organization_name=record.organization_name,
                        procurement_type=record.procurement_type.value,
                        budget_amount=_normalize_budget_amount(record.budget_amount)
                        if record.budget_amount is not None
                        else _normalize_budget_amount(existing.budget_amount),
                        currency="THB",
                        source_status_text=normalized_status_text
                        or existing.source_status_text,
                        proposal_submission_date=_normalize_date(
                            record.proposal_submission_date
                        )
                        or _normalize_date(existing.proposal_submission_date),
                        winner_announced_at=(
                            now.date()
                            if transition["project_state"]
                            is ProjectState.WINNER_ANNOUNCED
                            else existing_row["winner_announced_at"]
                        ),
                        contract_signed_at=(
                            now.date()
                            if transition["project_state"]
                            is ProjectState.CONTRACT_SIGNED
                            else existing_row["contract_signed_at"]
                        ),
                        project_state=transition["project_state"].value,
                        closed_reason=(
                            transition["closed_reason"].value
                            if transition["closed_reason"] is not None
                            else None
                        ),
                        last_seen_at=now,
                        last_changed_at=now
                        if changed
                        else datetime.fromisoformat(existing.last_changed_at),
                        last_run_id=normalized_run_id or existing_row["last_run_id"],
                        updated_at=now,
                    )
                )
                persisted_project_state = transition["project_state"].value

            self._upsert_aliases(
                connection,
                project_id=project_id,
                aliases=record.aliases,
                created_at=now,
            )
            if normalized_status_text is not None:
                self._insert_status_event(
                    connection,
                    project_id=project_id,
                    observed_status_text=normalized_status_text,
                    normalized_status=persisted_project_state,
                    observed_at=now,
                    run_id=normalized_run_id,
                    raw_snapshot=raw_snapshot,
                )

            row = (
                connection.execute(
                    select(PROJECTS_TABLE)
                    .where(PROJECTS_TABLE.c.id == project_id)
                    .limit(1)
                )
                .mappings()
                .one()
            )
        return _project_from_mapping(row)

    def _upsert_project_by_canonical(
        self,
        connection,
        *,
        project_id: str,
        tenant_id: str,
        record: ProjectUpsertRecord,
        normalized_status_text: str | None,
        normalized_run_id: str | None,
        now: datetime,
    ):
        statement = _dialect_insert(PROJECTS_TABLE, connection).values(
            id=project_id,
            tenant_id=tenant_id,
            canonical_project_id=record.canonical_project_id,
            project_number=record.project_number,
            project_name=record.project_name,
            organization_name=record.organization_name,
            procurement_type=record.procurement_type.value,
            budget_amount=_normalize_budget_amount(record.budget_amount),
            currency="THB",
            source_status_text=normalized_status_text,
            proposal_submission_date=_normalize_date(record.proposal_submission_date),
            invitation_announcement_date=None,
            winner_announced_at=(
                now.date()
                if record.project_state is ProjectState.WINNER_ANNOUNCED
                else None
            ),
            contract_signed_at=(
                now.date()
                if record.project_state is ProjectState.CONTRACT_SIGNED
                else None
            ),
            project_state=record.project_state.value,
            closed_reason=record.closed_reason.value if record.closed_reason else None,
            first_seen_at=now,
            last_seen_at=now,
            last_changed_at=now,
            last_run_id=normalized_run_id,
            is_active=True,
            created_at=now,
            updated_at=now,
        )
        if hasattr(statement, "on_conflict_do_update"):
            excluded = statement.excluded
            statement = statement.on_conflict_do_update(
                index_elements=[
                    PROJECTS_TABLE.c.tenant_id,
                    PROJECTS_TABLE.c.canonical_project_id,
                ],
                set_={
                    "last_seen_at": now,
                    "last_run_id": func.coalesce(
                        excluded.last_run_id,
                        PROJECTS_TABLE.c.last_run_id,
                    ),
                    "updated_at": now,
                },
            )
        connection.execute(statement)
        return (
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
            .one()
        )


def _dialect_insert(table, connection):
    if connection.dialect.name == "postgresql":
        from sqlalchemy.dialects.postgresql import insert as postgresql_insert

        return postgresql_insert(table)
    if connection.dialect.name == "sqlite":
        from sqlalchemy.dialects.sqlite import insert as sqlite_insert

        return sqlite_insert(table)
    return insert(table)
