"""Event-emitting close-check workflow extraction."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from egp_crawler_core.closure_rules import check_winner_closure
from egp_db.repositories.project_repo import ProjectRecord, SqlProjectRepository
from egp_db.repositories.run_repo import CrawlRunDetail, SqlRunRepository, create_run_repository
from egp_shared_types.enums import ProjectState
from egp_shared_types.project_events import CloseCheckProjectEvent
from egp_worker.browser_close_check import crawl_live_close_check
from egp_worker.json_safety import make_json_safe
from egp_worker.project_event_sink import (
    ProjectEventSink,
    create_project_event_sink,
    create_service_backed_project_event_sink_from_repository,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from egp_notifications.dispatcher import NotificationDispatcher


@dataclass(frozen=True, slots=True)
class CloseCheckWorkflowResult:
    run: CrawlRunDetail
    updated_projects: list[ProjectRecord]


def _task_safe_payload(observation: dict[str, object]) -> dict[str, object]:
    safe_payload = make_json_safe(observation)
    if isinstance(safe_payload, dict):
        return safe_payload
    return {"value": safe_payload}


def run_close_check_workflow(
    *,
    tenant_id: str,
    observations: list[dict[str, object]],
    trigger_type: str = "manual",
    database_url: str | None = None,
    run_repository: SqlRunRepository | None = None,
    project_repository: SqlProjectRepository | None = None,
    project_event_sink: ProjectEventSink | None = None,
    notification_dispatcher: NotificationDispatcher | None = None,
    live: bool = False,
    live_projects: list[dict[str, object]] | None = None,
    live_observation_sweep: Callable[[list[dict[str, object]]], list[dict[str, object]]]
    | None = None,
) -> CloseCheckWorkflowResult:
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

    resolved_live_projects = list(live_projects or [])
    if live and not resolved_live_projects:
        if project_repository is None:
            if database_url is None:
                raise ValueError("database_url is required when live close-check loads projects")
            project_repository = SqlProjectRepository(
                database_url=database_url,
                bootstrap_schema=False,
            )
        resolved_live_projects = [
            {
                "project_id": project.id,
                "project_name": project.project_name,
                "project_number": project.project_number,
                "organization_name": project.organization_name,
                "project_state": project.project_state.value,
            }
            for project in project_repository.list_projects(
                tenant_id=tenant_id,
                project_states=[ProjectState.OPEN_INVITATION, ProjectState.OPEN_CONSULTING],
                limit=200,
            ).items
        ]

    resolved_observations = list(observations)
    if not resolved_observations and live and live_observation_sweep is None:
        resolved_observations = list(crawl_live_close_check(projects=resolved_live_projects))
    elif live_observation_sweep is not None and not resolved_observations:
        resolved_observations = list(live_observation_sweep(resolved_live_projects))

    run = run_repository.create_run(tenant_id=tenant_id, trigger_type=trigger_type)
    run_repository.mark_run_started(run.id)
    updated_projects: list[ProjectRecord] = []
    error_count = 0
    run_level_error: str | None = None

    try:
        for observation in resolved_observations:
            safe_observation = _task_safe_payload(observation)
            task = None
            try:
                task = run_repository.create_task(
                    run_id=run.id,
                    task_type="close_check",
                    project_id=str(observation["project_id"]),
                    payload=safe_observation,
                )
                run_repository.mark_task_started(task.id)
                closed_reason = check_winner_closure(
                    str(observation.get("source_status_text") or "")
                )
                if closed_reason is None:
                    run_repository.mark_task_finished(
                        task.id, status="skipped", result_json={"matched": False}
                    )
                    continue
                project = project_event_sink.record_close_check(
                    CloseCheckProjectEvent(
                        tenant_id=tenant_id,
                        project_id=str(observation["project_id"]),
                        closed_reason=closed_reason,
                        source_status_text=str(observation.get("source_status_text") or ""),
                        run_id=run.id,
                        raw_snapshot=safe_observation,
                    )
                )
                run_repository.mark_task_finished(
                    task.id,
                    status="succeeded",
                    result_json={
                        "project_id": project.id,
                        "next_state": project.project_state.value,
                    },
                )
                updated_projects.append(project)
            except Exception as exc:
                error_count += 1
                if task is not None:
                    run_repository.mark_task_finished(
                        task.id,
                        status="failed",
                        result_json={"error": str(exc)},
                    )
                else:
                    run_level_error = str(exc)
    except Exception as exc:
        run_level_error = str(exc)
        run_repository.mark_run_finished(
            run.id,
            status="failed",
            summary_json={
                "updated_projects": len(updated_projects),
                "error": run_level_error,
            },
            error_count=max(1, error_count),
        )
        raise

    summary_json: dict[str, object] = {"updated_projects": len(updated_projects)}
    if run_level_error is not None:
        summary_json["error"] = run_level_error

    run_repository.mark_run_finished(
        run.id,
        status="partial"
        if error_count and updated_projects
        else ("failed" if error_count else "succeeded"),
        summary_json=summary_json,
        error_count=error_count,
    )
    detail = run_repository.get_run_detail(tenant_id=tenant_id, run_id=run.id)
    if detail is None:
        raise KeyError(run.id)
    return CloseCheckWorkflowResult(run=detail, updated_projects=updated_projects)
