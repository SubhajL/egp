"""Repository-backed close-check workflow extraction."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from egp_crawler_core.closure_rules import check_winner_closure
from egp_db.repositories.project_repo import (
    ProjectRecord,
    SqlProjectRepository,
    create_project_repository,
)
from egp_db.repositories.run_repo import CrawlRunDetail, SqlRunRepository, create_run_repository
from egp_shared_types.enums import ClosedReason, NotificationType, ProjectState

if TYPE_CHECKING:
    from egp_notifications.dispatcher import NotificationDispatcher


_NEXT_STATE_BY_REASON = {
    ClosedReason.WINNER_ANNOUNCED: ProjectState.WINNER_ANNOUNCED,
    ClosedReason.CONTRACT_SIGNED: ProjectState.CONTRACT_SIGNED,
}


@dataclass(frozen=True, slots=True)
class CloseCheckWorkflowResult:
    run: CrawlRunDetail
    updated_projects: list[ProjectRecord]


def run_close_check_workflow(
    *,
    tenant_id: str,
    observations: list[dict[str, object]],
    trigger_type: str = "manual",
    database_url: str | None = None,
    project_repository: SqlProjectRepository | None = None,
    run_repository: SqlRunRepository | None = None,
    notification_dispatcher: NotificationDispatcher | None = None,
) -> CloseCheckWorkflowResult:
    if project_repository is None or run_repository is None:
        if database_url is None:
            raise ValueError("database_url is required when repositories are not provided")
        project_repository = project_repository or create_project_repository(
            database_url=database_url
        )
        run_repository = run_repository or create_run_repository(database_url=database_url)

    run = run_repository.create_run(tenant_id=tenant_id, trigger_type=trigger_type)
    run_repository.mark_run_started(run.id)
    updated_projects: list[ProjectRecord] = []
    error_count = 0

    for observation in observations:
        task = run_repository.create_task(
            run_id=run.id,
            task_type="close_check",
            project_id=str(observation["project_id"]),
            payload=observation,
        )
        try:
            run_repository.mark_task_started(task.id)
            closed_reason = check_winner_closure(str(observation.get("source_status_text") or ""))
            if closed_reason is None:
                run_repository.mark_task_finished(
                    task.id, status="skipped", result_json={"matched": False}
                )
                continue
            project = project_repository.transition_project(
                tenant_id=tenant_id,
                project_id=str(observation["project_id"]),
                next_state=_NEXT_STATE_BY_REASON[closed_reason],
                closed_reason=closed_reason,
                source_status_text=str(observation.get("source_status_text") or ""),
                run_id=run.id,
                raw_snapshot=observation,
            )
            run_repository.mark_task_finished(
                task.id,
                status="succeeded",
                result_json={"project_id": project.id, "next_state": project.project_state.value},
            )
            if notification_dispatcher is not None:
                notification_type = (
                    NotificationType.WINNER_ANNOUNCED
                    if project.project_state is ProjectState.WINNER_ANNOUNCED
                    else NotificationType.CONTRACT_SIGNED
                )
                notification_dispatcher.dispatch(
                    tenant_id=tenant_id,
                    notification_type=notification_type,
                    project_id=project.id,
                    template_vars={
                        "project_name": project.project_name,
                        "organization": project.organization_name,
                    },
                )
            updated_projects.append(project)
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
        if error_count and updated_projects
        else ("failed" if error_count else "succeeded"),
        summary_json={"updated_projects": len(updated_projects)},
        error_count=error_count,
    )
    detail = run_repository.get_run_detail(tenant_id=tenant_id, run_id=run.id)
    if detail is None:
        raise KeyError(run.id)
    return CloseCheckWorkflowResult(run=detail, updated_projects=updated_projects)
