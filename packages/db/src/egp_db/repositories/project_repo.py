"""Compatibility facade for tenant-scoped project persistence."""

from __future__ import annotations

from sqlalchemy.engine import Engine

from egp_db.connection import create_shared_engine
from egp_db.db_utils import normalize_database_url

from .project_aliases import ProjectAliasMixin
from .project_dashboard import ProjectDashboardMixin
from .project_lifecycle import ProjectLifecycleMixin
from .project_models import (
    DashboardDailyDiscoveryPoint,
    DashboardProjectSummary,
    DashboardRecentProjectChangeRecord,
    DashboardStateBreakdownPoint,
    DashboardWinnerProjectRecord,
    ProjectAliasRecord,
    ProjectDetail,
    ProjectPage,
    ProjectRecord,
    ProjectStatusEventRecord,
    ProjectUpsertRecord,
)
from .project_persistence import ProjectPersistenceMixin
from .project_queries import ProjectQueryMixin
from .project_schema import (
    METADATA,
    PROJECTS_TABLE,
    PROJECT_ALIASES_TABLE,
    PROJECT_STATUS_EVENTS_TABLE,
)
from .project_utils import build_project_upsert_record


__all__ = [
    "DashboardDailyDiscoveryPoint",
    "DashboardProjectSummary",
    "DashboardRecentProjectChangeRecord",
    "DashboardStateBreakdownPoint",
    "DashboardWinnerProjectRecord",
    "METADATA",
    "PROJECTS_TABLE",
    "PROJECT_ALIASES_TABLE",
    "PROJECT_STATUS_EVENTS_TABLE",
    "ProjectAliasRecord",
    "ProjectDetail",
    "ProjectPage",
    "ProjectRecord",
    "ProjectStatusEventRecord",
    "ProjectUpsertRecord",
    "SqlProjectRepository",
    "build_project_upsert_record",
    "create_project_repository",
]


class SqlProjectRepository(
    ProjectPersistenceMixin,
    ProjectAliasMixin,
    ProjectLifecycleMixin,
    ProjectQueryMixin,
    ProjectDashboardMixin,
):
    """Relational project repository with canonical-id and alias dedup."""

    def __init__(
        self,
        *,
        database_url: str | None = None,
        engine: Engine | None = None,
        bootstrap_schema: bool = False,
    ) -> None:
        if engine is None and database_url is None:
            raise ValueError("database_url or engine is required")
        self._database_url = (
            normalize_database_url(database_url) if database_url is not None else None
        )
        self._engine = engine or create_shared_engine(self._database_url or "")
        if bootstrap_schema:
            self._ensure_schema()


def create_project_repository(
    *,
    database_url: str | None = None,
    engine: Engine | None = None,
    bootstrap_schema: bool = True,
) -> SqlProjectRepository:
    return SqlProjectRepository(
        database_url=database_url, engine=engine, bootstrap_schema=bootstrap_schema
    )
