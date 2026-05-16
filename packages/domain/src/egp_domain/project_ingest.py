"""Shared project state ingestion for worker-emitted events."""

from __future__ import annotations

from dataclasses import dataclass

from egp_db.repositories.project_repo import (
    ProjectRecord,
    SqlProjectRepository,
    build_project_upsert_record,
    create_project_repository,
)
from egp_shared_types.enums import ClosedReason, NotificationType, ProjectState
from egp_shared_types.project_events import CloseCheckProjectEvent, DiscoveredProjectEvent


_NEXT_STATE_BY_REASON = {
    ClosedReason.WINNER_ANNOUNCED: ProjectState.WINNER_ANNOUNCED,
    ClosedReason.CONTRACT_SIGNED: ProjectState.CONTRACT_SIGNED,
}


@dataclass(frozen=True, slots=True)
class DiscoverProjectIngestResult:
    created: bool
    project: ProjectRecord


class ProjectIngestService:
    def __init__(
        self,
        repository: SqlProjectRepository,
        *,
        notification_dispatcher=None,
    ) -> None:
        self._repository = repository
        self._notification_dispatcher = notification_dispatcher

    def ingest_discovered_project(
        self,
        *,
        event: DiscoveredProjectEvent,
    ) -> DiscoverProjectIngestResult:
        record = build_project_upsert_record(
            tenant_id=event.tenant_id,
            project_number=event.project_number,
            search_name=event.search_name,
            detail_name=event.detail_name,
            project_name=event.project_name,
            organization_name=event.organization_name,
            proposal_submission_date=event.proposal_submission_date,
            budget_amount=event.budget_amount,
            procurement_type=event.procurement_type,
            project_state=event.project_state,
        )
        existing = self._repository.find_existing_project(record)
        project = self._repository.upsert_project(
            record,
            source_status_text=event.source_status_text,
            run_id=event.run_id,
            raw_snapshot=event.raw_snapshot,
        )
        if self._notification_dispatcher is not None and existing is None:
            self._notification_dispatcher.dispatch(
                tenant_id=event.tenant_id,
                notification_type=NotificationType.NEW_PROJECT,
                project_id=project.id,
                template_vars={
                    "project_name": project.project_name,
                    "organization": project.organization_name,
                    "budget": project.budget_amount or "",
                },
            )
        return DiscoverProjectIngestResult(created=existing is None, project=project)

    def ingest_close_check_event(
        self,
        *,
        event: CloseCheckProjectEvent,
    ) -> ProjectRecord:
        closed_reason = ClosedReason(event.closed_reason)
        project = self._repository.transition_project(
            tenant_id=event.tenant_id,
            project_id=event.project_id,
            next_state=_NEXT_STATE_BY_REASON[closed_reason],
            closed_reason=closed_reason,
            source_status_text=event.source_status_text,
            run_id=event.run_id,
            raw_snapshot=event.raw_snapshot,
        )
        if self._notification_dispatcher is not None:
            notification_type = (
                NotificationType.WINNER_ANNOUNCED
                if project.project_state is ProjectState.WINNER_ANNOUNCED
                else NotificationType.CONTRACT_SIGNED
            )
            self._notification_dispatcher.dispatch(
                tenant_id=event.tenant_id,
                notification_type=notification_type,
                project_id=project.id,
                template_vars={
                    "project_name": project.project_name,
                    "organization": project.organization_name,
                },
            )
        return project


def create_project_ingest_service(
    *,
    database_url: str,
    notification_dispatcher=None,
) -> ProjectIngestService:
    repository = create_project_repository(database_url=database_url)
    return ProjectIngestService(
        repository,
        notification_dispatcher=notification_dispatcher,
    )
