"""Project read/query operations."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import and_, desc, func, or_, select

from egp_db.db_utils import normalize_uuid_string
from egp_shared_types.enums import ClosedReason, ProcurementType, ProjectState

from .document_schema import DOCUMENTS_TABLE, DOCUMENT_DIFFS_TABLE
from .project_models import (
    ProjectDetail,
    ProjectPage,
    ProjectRecord,
    ProjectUpsertRecord,
)
from .project_schema import (
    PROJECTS_TABLE,
    PROJECT_ALIASES_TABLE,
    PROJECT_STATUS_EVENTS_TABLE,
)
from .project_utils import (
    _alias_from_mapping,
    _dedupe_status_events,
    _normalize_datetime_filter,
    _normalize_decimal_filter,
    _normalize_multi_value_filter,
    _normalize_optional_text,
    _project_from_mapping,
    _status_event_from_mapping,
)


class ProjectQueryMixin:
    def get_project(self, *, tenant_id: str, project_id: str) -> ProjectRecord | None:
        normalized_tenant_id = normalize_uuid_string(tenant_id)
        normalized_project_id = normalize_uuid_string(project_id)
        with self._engine.connect() as connection:
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
        return _project_from_mapping(row) if row is not None else None

    def find_existing_project(
        self, record: ProjectUpsertRecord
    ) -> ProjectRecord | None:
        normalized_tenant_id = normalize_uuid_string(record.tenant_id)
        with self._engine.connect() as connection:
            row = self._find_existing_row(
                connection,
                tenant_id=normalized_tenant_id,
                record=record,
            )
        return _project_from_mapping(row) if row is not None else None

    def get_project_detail(
        self, *, tenant_id: str, project_id: str
    ) -> ProjectDetail | None:
        project = self.get_project(tenant_id=tenant_id, project_id=project_id)
        if project is None:
            return None
        with self._engine.connect() as connection:
            aliases = (
                connection.execute(
                    select(PROJECT_ALIASES_TABLE)
                    .where(PROJECT_ALIASES_TABLE.c.project_id == project.id)
                    .order_by(PROJECT_ALIASES_TABLE.c.created_at)
                )
                .mappings()
                .all()
            )
            status_events = (
                connection.execute(
                    select(PROJECT_STATUS_EVENTS_TABLE)
                    .where(PROJECT_STATUS_EVENTS_TABLE.c.project_id == project.id)
                    .order_by(PROJECT_STATUS_EVENTS_TABLE.c.observed_at)
                )
                .mappings()
                .all()
            )
        return ProjectDetail(
            project=project,
            aliases=[_alias_from_mapping(alias) for alias in aliases],
            status_events=_dedupe_status_events(
                [_status_event_from_mapping(row) for row in status_events]
            ),
        )

    def list_projects(
        self,
        *,
        tenant_id: str,
        project_states: list[ProjectState | str] | None = None,
        procurement_types: list[ProcurementType | str] | None = None,
        closed_reasons: list[ClosedReason | str] | None = None,
        organization: str | None = None,
        keyword: str | None = None,
        budget_min: Decimal | float | int | str | None = None,
        budget_max: Decimal | float | int | str | None = None,
        updated_after: datetime | str | None = None,
        has_changed_tor: bool | None = None,
        has_winner: bool | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> ProjectPage:
        normalized_tenant_id = normalize_uuid_string(tenant_id)
        normalized_limit = max(1, min(int(limit), 200))
        normalized_offset = max(0, int(offset))
        normalized_project_states = _normalize_multi_value_filter(project_states)
        normalized_procurement_types = _normalize_multi_value_filter(procurement_types)
        normalized_closed_reasons = _normalize_multi_value_filter(closed_reasons)
        normalized_organization = _normalize_optional_text(organization)
        normalized_keyword = _normalize_optional_text(keyword)
        normalized_budget_min = _normalize_decimal_filter(budget_min)
        normalized_budget_max = _normalize_decimal_filter(budget_max)
        normalized_updated_after = _normalize_datetime_filter(updated_after)
        statement = select(PROJECTS_TABLE).where(
            PROJECTS_TABLE.c.tenant_id == normalized_tenant_id
        )
        count_statement = (
            select(func.count())
            .select_from(PROJECTS_TABLE)
            .where(PROJECTS_TABLE.c.tenant_id == normalized_tenant_id)
        )
        conditions = []

        if normalized_project_states:
            conditions.append(
                PROJECTS_TABLE.c.project_state.in_(normalized_project_states)
            )
        if normalized_procurement_types:
            conditions.append(
                PROJECTS_TABLE.c.procurement_type.in_(normalized_procurement_types)
            )
        if normalized_closed_reasons:
            conditions.append(
                PROJECTS_TABLE.c.closed_reason.in_(normalized_closed_reasons)
            )
        if normalized_organization is not None:
            conditions.append(
                PROJECTS_TABLE.c.organization_name.ilike(f"%{normalized_organization}%")
            )
        if normalized_budget_min is not None:
            conditions.append(PROJECTS_TABLE.c.budget_amount >= normalized_budget_min)
        if normalized_budget_max is not None:
            conditions.append(PROJECTS_TABLE.c.budget_amount <= normalized_budget_max)
        if normalized_updated_after is not None:
            conditions.append(
                PROJECTS_TABLE.c.last_changed_at >= normalized_updated_after
            )
        changed_tor_project_ids = (
            select(DOCUMENT_DIFFS_TABLE.c.project_id)
            .join(
                DOCUMENTS_TABLE,
                DOCUMENTS_TABLE.c.id == DOCUMENT_DIFFS_TABLE.c.new_document_id,
            )
            .where(
                and_(
                    DOCUMENT_DIFFS_TABLE.c.tenant_id == normalized_tenant_id,
                    DOCUMENTS_TABLE.c.tenant_id == normalized_tenant_id,
                    DOCUMENT_DIFFS_TABLE.c.diff_type == "changed",
                    DOCUMENTS_TABLE.c.document_type == "tor",
                )
            )
            .distinct()
        )
        has_changed_tor_column = PROJECTS_TABLE.c.id.in_(changed_tor_project_ids).label(
            "has_changed_tor"
        )
        if has_winner is not None:
            winner_states = [
                ProjectState.WINNER_ANNOUNCED.value,
                ProjectState.CONTRACT_SIGNED.value,
            ]
            if has_winner:
                conditions.append(PROJECTS_TABLE.c.project_state.in_(winner_states))
            else:
                conditions.append(PROJECTS_TABLE.c.project_state.not_in(winner_states))
        if has_changed_tor is not None:
            if has_changed_tor:
                conditions.append(PROJECTS_TABLE.c.id.in_(changed_tor_project_ids))
            else:
                conditions.append(PROJECTS_TABLE.c.id.not_in(changed_tor_project_ids))
        if normalized_keyword is not None:
            keyword_like = f"%{normalized_keyword}%"
            alias_project_ids = select(PROJECT_ALIASES_TABLE.c.project_id).where(
                PROJECT_ALIASES_TABLE.c.alias_value.ilike(keyword_like)
            )
            conditions.append(
                or_(
                    PROJECTS_TABLE.c.project_name.ilike(keyword_like),
                    PROJECTS_TABLE.c.organization_name.ilike(keyword_like),
                    PROJECTS_TABLE.c.project_number.ilike(keyword_like),
                    PROJECTS_TABLE.c.id.in_(alias_project_ids),
                )
            )

        if conditions:
            statement = statement.where(*conditions)
            count_statement = count_statement.where(*conditions)
        statement = statement.add_columns(has_changed_tor_column)
        statement = (
            statement.order_by(desc(PROJECTS_TABLE.c.last_changed_at))
            .limit(normalized_limit)
            .offset(normalized_offset)
        )
        with self._engine.connect() as connection:
            total = int(connection.execute(count_statement).scalar_one())
            rows = connection.execute(statement).mappings().all()
        return ProjectPage(
            items=[_project_from_mapping(row) for row in rows],
            total=total,
            limit=normalized_limit,
            offset=normalized_offset,
        )
