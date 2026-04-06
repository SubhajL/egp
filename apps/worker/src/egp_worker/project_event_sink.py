"""Worker sink abstraction for API-owned project state writes."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

import httpx

from egp_shared_types.enums import ClosedReason, ProcurementType, ProjectState
from egp_shared_types.project_events import CloseCheckProjectEvent, DiscoveredProjectEvent
from egp_worker.config import (
    get_internal_api_base_url,
    get_internal_api_timeout_seconds,
    get_internal_worker_token,
)

if TYPE_CHECKING:
    from egp_api.services.project_ingest_service import ProjectIngestService
    from egp_db.repositories.project_repo import ProjectRecord
    from egp_notifications.dispatcher import NotificationDispatcher


class ProjectEventSink(Protocol):
    def record_discovery(self, event: DiscoveredProjectEvent) -> "ProjectRecord": ...

    def record_close_check(self, event: CloseCheckProjectEvent) -> "ProjectRecord": ...


@dataclass(frozen=True, slots=True)
class ProjectIngestTransportError(RuntimeError):
    message: str
    status_code: int | None = None
    response_body: str | None = None

    def __str__(self) -> str:
        return self.message


class ServiceBackedProjectEventSink:
    def __init__(self, service: "ProjectIngestService") -> None:
        self._service = service

    def record_discovery(self, event: DiscoveredProjectEvent):
        return self._service.ingest_discovered_project(event=event).project

    def record_close_check(self, event: CloseCheckProjectEvent):
        return self._service.ingest_close_check_event(event=event)


class ApiProjectEventSink:
    def __init__(
        self,
        *,
        base_url: str,
        worker_token: str | None = None,
        timeout_seconds: float = 10.0,
        client=None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._worker_token = worker_token
        self._timeout_seconds = float(timeout_seconds)
        self._client = client

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self._worker_token:
            headers["X-EGP-Worker-Token"] = self._worker_token
        return headers

    def _post(self, path: str, payload: dict[str, object]):
        if self._client is not None:
            return self._client.post(path, json=payload, headers=self._headers())
        with httpx.Client(base_url=self._base_url, timeout=self._timeout_seconds) as client:
            return client.post(path, json=payload, headers=self._headers())

    def record_discovery(self, event: DiscoveredProjectEvent):
        response = self._post(
            "/internal/worker/projects/discover",
            {
                "tenant_id": event.tenant_id,
                "run_id": event.run_id,
                "keyword": event.keyword,
                "project_number": event.project_number,
                "search_name": event.search_name,
                "detail_name": event.detail_name,
                "project_name": event.project_name,
                "organization_name": event.organization_name,
                "proposal_submission_date": event.proposal_submission_date,
                "budget_amount": event.budget_amount,
                "procurement_type": _enum_value(event.procurement_type),
                "project_state": _enum_value(event.project_state),
                "source_status_text": event.source_status_text,
                "raw_snapshot": event.raw_snapshot,
            },
        )
        return _project_from_response(response)

    def record_close_check(self, event: CloseCheckProjectEvent):
        response = self._post(
            "/internal/worker/projects/close-check",
            {
                "tenant_id": event.tenant_id,
                "run_id": event.run_id,
                "project_id": event.project_id,
                "closed_reason": _enum_value(event.closed_reason),
                "source_status_text": event.source_status_text,
                "raw_snapshot": event.raw_snapshot,
            },
        )
        return _project_from_response(response)


def _enum_value(value):
    return value.value if hasattr(value, "value") else value


def _project_from_response(response) -> "ProjectRecord":
    try:
        response.raise_for_status()
    except Exception as exc:
        status_code = getattr(response, "status_code", None)
        body = getattr(response, "text", None)
        raise ProjectIngestTransportError(
            f"project ingest request failed with status {status_code}",
            status_code=status_code,
            response_body=body,
        ) from exc
    payload = response.json()
    project_payload = payload["project"]
    from egp_db.repositories.project_repo import ProjectRecord

    return ProjectRecord(
        id=str(project_payload["id"]),
        tenant_id=str(project_payload["tenant_id"]),
        canonical_project_id=str(project_payload["canonical_project_id"]),
        project_number=project_payload.get("project_number"),
        project_name=str(project_payload["project_name"]),
        organization_name=str(project_payload["organization_name"]),
        procurement_type=ProcurementType(str(project_payload["procurement_type"])),
        proposal_submission_date=project_payload.get("proposal_submission_date"),
        budget_amount=project_payload.get("budget_amount"),
        project_state=ProjectState(str(project_payload["project_state"])),
        closed_reason=(
            ClosedReason(str(project_payload["closed_reason"]))
            if project_payload.get("closed_reason") is not None
            else None
        ),
        source_status_text=project_payload.get("source_status_text"),
        has_changed_tor=bool(project_payload.get("has_changed_tor", False)),
        first_seen_at=str(project_payload["first_seen_at"]),
        last_seen_at=str(project_payload["last_seen_at"]),
        last_changed_at=str(project_payload["last_changed_at"]),
        created_at=str(project_payload["created_at"]),
        updated_at=str(project_payload["updated_at"]),
    )


def create_service_backed_project_event_sink(
    *,
    database_url: str,
    notification_dispatcher: "NotificationDispatcher | None" = None,
) -> ProjectEventSink:
    from egp_api.services.project_ingest_service import create_project_ingest_service

    service = create_project_ingest_service(
        database_url=database_url,
        notification_dispatcher=notification_dispatcher,
    )
    return ServiceBackedProjectEventSink(service)


def create_project_event_sink(
    *,
    database_url: str | None = None,
    api_base_url: str | None = None,
    internal_worker_token: str | None = None,
    api_timeout_seconds: float | None = None,
    notification_dispatcher: "NotificationDispatcher | None" = None,
) -> ProjectEventSink:
    resolved_api_base_url = get_internal_api_base_url(api_base_url)
    if resolved_api_base_url is not None:
        return ApiProjectEventSink(
            base_url=resolved_api_base_url,
            worker_token=get_internal_worker_token(internal_worker_token),
            timeout_seconds=get_internal_api_timeout_seconds(api_timeout_seconds),
        )
    if database_url is None:
        raise ValueError("database_url is required when API transport is not configured")
    return create_service_backed_project_event_sink(
        database_url=database_url,
        notification_dispatcher=notification_dispatcher,
    )
