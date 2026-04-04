"""Repository-backed discover workflow extraction."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from egp_db.repositories.project_repo import (
    ProjectRecord,
    SqlProjectRepository,
    build_project_upsert_record,
    create_project_repository,
)
from egp_db.repositories.run_repo import CrawlRunDetail, SqlRunRepository, create_run_repository
from egp_shared_types.enums import NotificationType

if TYPE_CHECKING:
    from egp_notifications.dispatcher import NotificationDispatcher


@dataclass(frozen=True, slots=True)
class DiscoverWorkflowResult:
    run: CrawlRunDetail
    projects: list[ProjectRecord]


def run_discover_workflow(
    *,
    tenant_id: str,
    keyword: str,
    discovered_projects: list[dict[str, object]],
    trigger_type: str = "manual",
    database_url: str | None = None,
    project_repository: SqlProjectRepository | None = None,
    run_repository: SqlRunRepository | None = None,
    notification_dispatcher: NotificationDispatcher | None = None,
) -> DiscoverWorkflowResult:
    if project_repository is None or run_repository is None:
        if database_url is None:
            raise ValueError("database_url is required when repositories are not provided")
        project_repository = project_repository or create_project_repository(
            database_url=database_url
        )
        run_repository = run_repository or create_run_repository(database_url=database_url)

    run = run_repository.create_run(tenant_id=tenant_id, trigger_type=trigger_type)
    run_repository.mark_run_started(run.id)
    persisted_projects: list[ProjectRecord] = []
    error_count = 0

    for discovered in discovered_projects:
        task = run_repository.create_task(
            run_id=run.id,
            task_type="discover",
            keyword=keyword,
            payload=discovered,
        )
        try:
            run_repository.mark_task_started(task.id)
            record = build_project_upsert_record(
                tenant_id=tenant_id,
                project_number=discovered.get("project_number"),
                search_name=discovered.get("search_name"),
                detail_name=discovered.get("detail_name"),
                project_name=str(discovered["project_name"]),
                organization_name=str(discovered["organization_name"]),
                proposal_submission_date=discovered.get("proposal_submission_date"),
                budget_amount=discovered.get("budget_amount"),
                procurement_type=discovered.get("procurement_type"),
                project_state=discovered.get("project_state", "discovered"),
            )
            existing = project_repository.find_existing_project(record)
            project = project_repository.upsert_project(
                record,
                source_status_text=str(discovered.get("source_status_text") or ""),
                run_id=run.id,
                raw_snapshot=discovered,
            )
            if notification_dispatcher is not None and existing is None:
                notification_dispatcher.dispatch(
                    tenant_id=tenant_id,
                    notification_type=NotificationType.NEW_PROJECT,
                    project_id=project.id,
                    template_vars={
                        "project_name": project.project_name,
                        "organization": project.organization_name,
                        "budget": project.budget_amount or "",
                    },
                )
            run_repository.mark_task_finished(
                task.id,
                status="succeeded",
                result_json={"project_id": project.id},
            )
            persisted_projects.append(project)
        except Exception as exc:
            error_count += 1
            run_repository.mark_task_finished(
                task.id,
                status="failed",
                result_json={"error": str(exc)},
            )

    run_repository.mark_run_finished(
        run.id,
        status="partial"
        if error_count and persisted_projects
        else ("failed" if error_count else "succeeded"),
        summary_json={"projects_seen": len(persisted_projects)},
        error_count=error_count,
    )
    detail = run_repository.get_run_detail(tenant_id=tenant_id, run_id=run.id)
    if detail is None:
        raise KeyError(run.id)
    return DiscoverWorkflowResult(run=detail, projects=persisted_projects)
