"""Project lifecycle transition operations."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import and_, select, update

from egp_crawler_core.project_lifecycle import transition_state
from egp_db.db_utils import normalize_uuid_string
from egp_shared_types.enums import ClosedReason, ProjectState

from .project_models import ProjectRecord
from .project_schema import PROJECTS_TABLE
from .project_utils import _now, _normalize_run_id, _project_from_mapping


class ProjectLifecycleMixin:
    def transition_project(
        self,
        *,
        tenant_id: str,
        project_id: str,
        next_state: ProjectState | str,
        closed_reason: ClosedReason | str | None = None,
        source_status_text: str,
        run_id: str | None = None,
        raw_snapshot: dict[str, object] | None = None,
        observed_at: str | None = None,
    ) -> ProjectRecord:
        normalized_tenant_id = normalize_uuid_string(tenant_id)
        normalized_project_id = normalize_uuid_string(project_id)
        now = datetime.fromisoformat(observed_at) if observed_at else _now()
        normalized_run_id = _normalize_run_id(run_id)

        with self._engine.begin() as connection:
            row = (
                connection.execute(
                    select(PROJECTS_TABLE)
                    .where(
                        and_(
                            PROJECTS_TABLE.c.tenant_id == normalized_tenant_id,
                            PROJECTS_TABLE.c.id == normalized_project_id,
                        )
                    )
                    .limit(1)
                )
                .mappings()
                .first()
            )
            if row is None:
                raise KeyError(project_id)
            existing = _project_from_mapping(row)
            transition = transition_state(
                current_state=existing.project_state,
                next_state=next_state,
                closed_reason=closed_reason,
            )
            connection.execute(
                update(PROJECTS_TABLE)
                .where(
                    and_(
                        PROJECTS_TABLE.c.tenant_id == normalized_tenant_id,
                        PROJECTS_TABLE.c.id == normalized_project_id,
                    )
                )
                .values(
                    project_state=transition["project_state"].value,
                    closed_reason=(
                        transition["closed_reason"].value
                        if transition["closed_reason"] is not None
                        else None
                    ),
                    source_status_text=source_status_text,
                    winner_announced_at=(
                        now.date()
                        if transition["project_state"] is ProjectState.WINNER_ANNOUNCED
                        else row["winner_announced_at"]
                    ),
                    contract_signed_at=(
                        now.date()
                        if transition["project_state"] is ProjectState.CONTRACT_SIGNED
                        else row["contract_signed_at"]
                    ),
                    last_seen_at=now,
                    last_changed_at=now,
                    last_run_id=normalized_run_id or row["last_run_id"],
                    updated_at=now,
                )
            )
            self._insert_status_event(
                connection,
                project_id=normalized_project_id,
                observed_status_text=source_status_text,
                normalized_status=transition["project_state"].value,
                observed_at=now,
                run_id=normalized_run_id,
                raw_snapshot=raw_snapshot,
            )
            updated_row = (
                connection.execute(
                    select(PROJECTS_TABLE)
                    .where(PROJECTS_TABLE.c.id == normalized_project_id)
                    .limit(1)
                )
                .mappings()
                .one()
            )
        return _project_from_mapping(updated_row)
