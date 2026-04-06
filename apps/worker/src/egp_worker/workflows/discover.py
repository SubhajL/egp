"""Event-emitting discover workflow extraction."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from egp_db.repositories.project_repo import ProjectRecord, SqlProjectRepository
from egp_db.repositories.run_repo import CrawlRunDetail, SqlRunRepository, create_run_repository
from egp_shared_types.project_events import DiscoveredProjectEvent
from egp_worker.project_event_sink import (
    ProjectEventSink,
    create_project_event_sink,
    create_service_backed_project_event_sink_from_repository,
)

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
    run_repository: SqlRunRepository | None = None,
    project_repository: SqlProjectRepository | None = None,
    project_event_sink: ProjectEventSink | None = None,
    notification_dispatcher: NotificationDispatcher | None = None,
) -> DiscoverWorkflowResult:
    if run_repository is None:
        if database_url is None:
            raise ValueError("database_url is required when repositories are not provided")
        run_repository = create_run_repository(database_url=database_url)
    if project_event_sink is None:
        if project_repository is not None:
            project_event_sink = create_service_backed_project_event_sink_from_repository(
                repository=project_repository,
                notification_dispatcher=notification_dispatcher,
            )
        elif database_url is None:
            raise ValueError("database_url is required when project_event_sink is not provided")
        else:
            project_event_sink = create_project_event_sink(
                database_url=database_url,
                notification_dispatcher=notification_dispatcher,
            )

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
            event = DiscoveredProjectEvent(
                tenant_id=tenant_id,
                keyword=keyword,
                project_number=discovered.get("project_number"),
                search_name=discovered.get("search_name"),
                detail_name=discovered.get("detail_name"),
                project_name=str(discovered["project_name"]),
                organization_name=str(discovered["organization_name"]),
                proposal_submission_date=discovered.get("proposal_submission_date"),
                budget_amount=discovered.get("budget_amount"),
                procurement_type=discovered.get("procurement_type"),
                project_state=discovered.get("project_state", "discovered"),
                run_id=run.id,
                source_status_text=str(discovered.get("source_status_text") or ""),
                raw_snapshot=discovered,
            )
            project = project_event_sink.record_discovery(event)
            run_repository.mark_task_finished(
                task.id, status="succeeded", result_json={"project_id": project.id}
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
