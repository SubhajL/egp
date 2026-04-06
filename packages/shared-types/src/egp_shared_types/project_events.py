"""Shared worker-to-API project event contracts."""

from __future__ import annotations

from dataclasses import dataclass

from .enums import ClosedReason, ProcurementType, ProjectState


@dataclass(frozen=True, slots=True)
class DiscoveredProjectEvent:
    tenant_id: str
    keyword: str
    project_name: str
    organization_name: str
    project_number: str | None = None
    search_name: str | None = None
    detail_name: str | None = None
    proposal_submission_date: str | None = None
    budget_amount: str | None = None
    procurement_type: ProcurementType | str | None = None
    project_state: ProjectState | str = ProjectState.DISCOVERED
    source_status_text: str = ""
    run_id: str | None = None
    raw_snapshot: dict[str, object] | None = None


@dataclass(frozen=True, slots=True)
class CloseCheckProjectEvent:
    tenant_id: str
    project_id: str
    closed_reason: ClosedReason | str
    source_status_text: str
    run_id: str | None = None
    raw_snapshot: dict[str, object] | None = None
