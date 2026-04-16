"""Event-emitting discover workflow extraction."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from egp_crawler_core.discovery_authorization import (
    build_discovery_authorization_snapshot,
    require_discovery_authorization,
)
from egp_db.google_drive import GoogleDriveOAuthConfig
from egp_db.onedrive import OneDriveOAuthConfig
from egp_db.repositories.billing_repo import create_billing_repository
from egp_db.repositories.profile_repo import create_profile_repository
from egp_db.repositories.project_repo import ProjectRecord, SqlProjectRepository
from egp_db.repositories.run_repo import CrawlRunDetail, SqlRunRepository, create_run_repository
from egp_shared_types.project_events import DiscoveredProjectEvent
from egp_worker.browser_downloads import ingest_downloaded_documents
from egp_worker.browser_discovery import crawl_live_discovery
from egp_worker.project_event_sink import (
    ProjectEventSink,
    create_project_event_sink,
    create_service_backed_project_event_sink_from_repository,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from egp_notifications.dispatcher import NotificationDispatcher


@dataclass(frozen=True, slots=True)
class DiscoverWorkflowResult:
    run: CrawlRunDetail
    projects: list[ProjectRecord]


def _authorize_discovery(*, database_url: str, tenant_id: str, keyword: str) -> None:
    billing_repository = create_billing_repository(
        database_url=database_url,
        bootstrap_schema=False,
    )
    profile_repository = create_profile_repository(
        database_url=database_url,
        bootstrap_schema=False,
    )
    subscriptions = billing_repository.list_subscriptions_for_tenant(tenant_id=tenant_id)
    active_keywords = profile_repository.list_active_keywords(tenant_id=tenant_id)
    require_discovery_authorization(
        snapshot=build_discovery_authorization_snapshot(
            subscriptions=subscriptions,
            active_keywords=active_keywords,
        ),
        keyword=keyword,
    )


def _task_safe_payload(discovered: dict[str, object]) -> dict[str, object]:
    safe_payload = dict(discovered)
    downloaded_documents = list(discovered.get("downloaded_documents") or [])
    if downloaded_documents:
        safe_payload["downloaded_documents"] = [
            {
                "file_name": str(document.get("file_name") or ""),
                "source_label": str(document.get("source_label") or ""),
                "source_status_text": str(document.get("source_status_text") or ""),
                "source_page_text": str(document.get("source_page_text") or ""),
                "project_state": (
                    str(document["project_state"])
                    if document.get("project_state") is not None
                    else None
                ),
            }
            for document in downloaded_documents
        ]
    return safe_payload


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
    live: bool = False,
    profile: str | None = None,
    live_discovery: Callable[[str], list[dict[str, object]]] | None = None,
    artifact_root: Path | str = Path("artifacts"),
    storage_credentials_secret: str | None = None,
    google_drive_oauth_config: GoogleDriveOAuthConfig | None = None,
    google_drive_client: object | None = None,
    onedrive_oauth_config: OneDriveOAuthConfig | None = None,
    onedrive_client: object | None = None,
) -> DiscoverWorkflowResult:
    if database_url is not None:
        _authorize_discovery(database_url=database_url, tenant_id=tenant_id, keyword=keyword)
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

    resolved_projects = list(discovered_projects)
    if live_discovery is not None and not resolved_projects:
        resolved_projects = list(live_discovery(keyword))
    elif live:
        resolved_projects = crawl_live_discovery(
            keyword=keyword,
            profile=profile,
            include_documents=True,
        )

    run = run_repository.create_run(tenant_id=tenant_id, trigger_type=trigger_type)
    run_repository.mark_run_started(run.id)
    persisted_projects: list[ProjectRecord] = []
    error_count = 0

    for discovered in resolved_projects:
        task_keyword = str(discovered.get("keyword") or keyword)
        if database_url is not None:
            _authorize_discovery(
                database_url=database_url,
                tenant_id=tenant_id,
                keyword=task_keyword,
            )
        task = run_repository.create_task(
            run_id=run.id,
            task_type="discover",
            keyword=task_keyword,
            payload=_task_safe_payload(discovered),
        )
        try:
            run_repository.mark_task_started(task.id)
            event = DiscoveredProjectEvent(
                tenant_id=tenant_id,
                keyword=task_keyword,
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
            downloaded_documents = list(discovered.get("downloaded_documents") or [])
            if downloaded_documents:
                ingest_downloaded_documents(
                    artifact_root=artifact_root,
                    database_url=database_url,
                    storage_credentials_secret=storage_credentials_secret,
                    google_drive_oauth_config=google_drive_oauth_config,
                    google_drive_client=google_drive_client,
                    onedrive_oauth_config=onedrive_oauth_config,
                    onedrive_client=onedrive_client,
                    tenant_id=tenant_id,
                    project_id=project.id,
                    downloaded_documents=downloaded_documents,
                )
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
