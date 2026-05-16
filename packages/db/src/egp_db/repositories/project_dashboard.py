"""Project dashboard projection queries."""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import and_, desc, func, or_, select

from egp_db.db_utils import normalize_uuid_string
from egp_shared_types.enums import ProjectState

from .document_schema import DOCUMENTS_TABLE, DOCUMENT_DIFFS_TABLE
from .project_models import (
    DashboardDailyDiscoveryPoint,
    DashboardProjectSummary,
    DashboardRecentProjectChangeRecord,
    DashboardStateBreakdownPoint,
    DashboardWinnerProjectRecord,
)
from .project_schema import PROJECTS_TABLE
from .project_utils import (
    _dashboard_bucket_for_state,
    _date_value_to_iso,
    _datetime_value_to_iso,
    _now,
    _DASHBOARD_BREAKDOWN_BUCKETS,
    _DASHBOARD_CLOSED_STATES,
    _DASHBOARD_WINNER_STATES,
)


class ProjectDashboardMixin:
    def get_dashboard_project_summary(
        self,
        *,
        tenant_id: str,
        now: datetime | None = None,
        discovery_days: int = 14,
        recent_changes_limit: int = 5,
        winner_limit: int = 5,
    ) -> DashboardProjectSummary:
        normalized_tenant_id = normalize_uuid_string(tenant_id)
        reference_now = now or _now()
        today = reference_now.date()
        discovery_window_days = max(1, int(discovery_days))
        discovery_start = today - timedelta(days=discovery_window_days - 1)
        winner_window_start = today - timedelta(days=6)
        recent_limit = max(1, int(recent_changes_limit))
        normalized_winner_limit = max(1, int(winner_limit))

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
            .subquery()
        )

        with self._engine.connect() as connection:
            active_projects = int(
                connection.execute(
                    select(func.count())
                    .select_from(PROJECTS_TABLE)
                    .where(
                        and_(
                            PROJECTS_TABLE.c.tenant_id == normalized_tenant_id,
                            PROJECTS_TABLE.c.project_state.not_in(
                                [
                                    *sorted(_DASHBOARD_CLOSED_STATES),
                                    ProjectState.ERROR.value,
                                ]
                            ),
                        )
                    )
                ).scalar_one()
            )
            discovered_today = int(
                connection.execute(
                    select(func.count())
                    .select_from(PROJECTS_TABLE)
                    .where(
                        and_(
                            PROJECTS_TABLE.c.tenant_id == normalized_tenant_id,
                            func.date(PROJECTS_TABLE.c.first_seen_at) == today,
                        )
                    )
                ).scalar_one()
            )
            winner_projects_this_week = int(
                connection.execute(
                    select(func.count())
                    .select_from(PROJECTS_TABLE)
                    .where(
                        and_(
                            PROJECTS_TABLE.c.tenant_id == normalized_tenant_id,
                            PROJECTS_TABLE.c.project_state.in_(
                                sorted(_DASHBOARD_WINNER_STATES)
                            ),
                            or_(
                                PROJECTS_TABLE.c.winner_announced_at
                                >= winner_window_start,
                                PROJECTS_TABLE.c.contract_signed_at
                                >= winner_window_start,
                            ),
                        )
                    )
                ).scalar_one()
            )
            closed_today = int(
                connection.execute(
                    select(func.count())
                    .select_from(PROJECTS_TABLE)
                    .where(
                        and_(
                            PROJECTS_TABLE.c.tenant_id == normalized_tenant_id,
                            PROJECTS_TABLE.c.project_state.in_(
                                sorted(_DASHBOARD_CLOSED_STATES)
                            ),
                            func.date(PROJECTS_TABLE.c.last_changed_at) == today,
                        )
                    )
                ).scalar_one()
            )
            changed_tor_projects = int(
                connection.execute(
                    select(func.count()).select_from(changed_tor_project_ids)
                ).scalar_one()
            )
            recent_change_rows = (
                connection.execute(
                    select(
                        PROJECTS_TABLE.c.id,
                        PROJECTS_TABLE.c.project_name,
                        PROJECTS_TABLE.c.project_state,
                        PROJECTS_TABLE.c.last_changed_at,
                    )
                    .where(PROJECTS_TABLE.c.tenant_id == normalized_tenant_id)
                    .order_by(
                        desc(PROJECTS_TABLE.c.last_changed_at),
                        desc(PROJECTS_TABLE.c.created_at),
                    )
                    .limit(recent_limit)
                )
                .mappings()
                .all()
            )
            winner_rows = (
                connection.execute(
                    select(
                        PROJECTS_TABLE.c.id,
                        PROJECTS_TABLE.c.project_name,
                        PROJECTS_TABLE.c.project_state,
                        func.coalesce(
                            PROJECTS_TABLE.c.winner_announced_at,
                            PROJECTS_TABLE.c.contract_signed_at,
                        ).label("awarded_at"),
                    )
                    .where(
                        and_(
                            PROJECTS_TABLE.c.tenant_id == normalized_tenant_id,
                            PROJECTS_TABLE.c.project_state.in_(
                                sorted(_DASHBOARD_WINNER_STATES)
                            ),
                            or_(
                                PROJECTS_TABLE.c.winner_announced_at
                                >= winner_window_start,
                                PROJECTS_TABLE.c.contract_signed_at
                                >= winner_window_start,
                            ),
                        )
                    )
                    .order_by(
                        desc(
                            func.coalesce(
                                PROJECTS_TABLE.c.winner_announced_at,
                                PROJECTS_TABLE.c.contract_signed_at,
                            )
                        ),
                        desc(PROJECTS_TABLE.c.updated_at),
                    )
                    .limit(normalized_winner_limit)
                )
                .mappings()
                .all()
            )
            discovery_date = func.date(PROJECTS_TABLE.c.first_seen_at)
            daily_rows = (
                connection.execute(
                    select(
                        discovery_date.label("discovery_date"),
                        func.count().label("count"),
                    )
                    .where(
                        and_(
                            PROJECTS_TABLE.c.tenant_id == normalized_tenant_id,
                            discovery_date >= discovery_start,
                            discovery_date <= today,
                        )
                    )
                    .group_by(discovery_date)
                )
                .mappings()
                .all()
            )
            state_rows = (
                connection.execute(
                    select(
                        PROJECTS_TABLE.c.project_state,
                        func.count().label("count"),
                    )
                    .where(PROJECTS_TABLE.c.tenant_id == normalized_tenant_id)
                    .group_by(PROJECTS_TABLE.c.project_state)
                )
                .mappings()
                .all()
            )

        daily_counts = {
            _date_value_to_iso(row["discovery_date"]): int(row["count"])
            for row in daily_rows
        }
        daily_discovery = [
            DashboardDailyDiscoveryPoint(
                date=(discovery_start + timedelta(days=offset)).isoformat(),
                count=daily_counts.get(
                    (discovery_start + timedelta(days=offset)).isoformat(),
                    0,
                ),
            )
            for offset in range(discovery_window_days)
        ]
        breakdown_counts = {bucket: 0 for bucket in _DASHBOARD_BREAKDOWN_BUCKETS}
        for row in state_rows:
            bucket = _dashboard_bucket_for_state(str(row["project_state"]))
            if bucket is not None:
                breakdown_counts[bucket] += int(row["count"])

        return DashboardProjectSummary(
            active_projects=active_projects,
            discovered_today=discovered_today,
            winner_projects_this_week=winner_projects_this_week,
            closed_today=closed_today,
            changed_tor_projects=changed_tor_projects,
            recent_changes=[
                DashboardRecentProjectChangeRecord(
                    project_id=str(row["id"]),
                    project_name=str(row["project_name"]),
                    project_state=str(row["project_state"]),
                    last_changed_at=_datetime_value_to_iso(row["last_changed_at"]),
                )
                for row in recent_change_rows
            ],
            winner_projects=[
                DashboardWinnerProjectRecord(
                    project_id=str(row["id"]),
                    project_name=str(row["project_name"]),
                    project_state=str(row["project_state"]),
                    awarded_at=_date_value_to_iso(row["awarded_at"]),
                )
                for row in winner_rows
                if row["awarded_at"] is not None
            ],
            daily_discovery=daily_discovery,
            project_state_breakdown=[
                DashboardStateBreakdownPoint(
                    bucket=bucket, count=breakdown_counts[bucket]
                )
                for bucket in _DASHBOARD_BREAKDOWN_BUCKETS
            ],
        )
