from __future__ import annotations

from egp_db.repositories import project_models, project_schema
from egp_db.repositories.project_aliases import ProjectAliasMixin
from egp_db.repositories.project_dashboard import ProjectDashboardMixin
from egp_db.repositories.project_lifecycle import ProjectLifecycleMixin
from egp_db.repositories.project_persistence import ProjectPersistenceMixin
from egp_db.repositories.project_queries import ProjectQueryMixin
from egp_db.repositories.project_repo import (
    PROJECTS_TABLE,
    DashboardProjectSummary,
    ProjectRecord,
    ProjectUpsertRecord,
    SqlProjectRepository,
)


def test_project_repository_facade_preserves_contract_through_domain_mixins() -> None:
    assert issubclass(SqlProjectRepository, ProjectPersistenceMixin)
    assert issubclass(SqlProjectRepository, ProjectAliasMixin)
    assert issubclass(SqlProjectRepository, ProjectLifecycleMixin)
    assert issubclass(SqlProjectRepository, ProjectQueryMixin)
    assert issubclass(SqlProjectRepository, ProjectDashboardMixin)

    assert ProjectUpsertRecord is project_models.ProjectUpsertRecord
    assert ProjectRecord is project_models.ProjectRecord
    assert DashboardProjectSummary is project_models.DashboardProjectSummary
    assert PROJECTS_TABLE is project_schema.PROJECTS_TABLE
