"""Project repository record models."""

from __future__ import annotations

from dataclasses import dataclass

from egp_shared_types.enums import ClosedReason, ProcurementType, ProjectState


@dataclass(frozen=True, slots=True)
class ProjectUpsertRecord:
    tenant_id: str
    canonical_project_id: str
    project_name: str
    organization_name: str
    project_number: str | None
    procurement_type: ProcurementType
    proposal_submission_date: str | None
    budget_amount: str | None
    project_state: ProjectState
    closed_reason: ClosedReason | None
    aliases: list[tuple[str, str]]


@dataclass(frozen=True, slots=True)
class ProjectRecord:
    id: str
    tenant_id: str
    canonical_project_id: str
    project_number: str | None
    project_name: str
    organization_name: str
    procurement_type: ProcurementType
    proposal_submission_date: str | None
    budget_amount: str | None
    project_state: ProjectState
    closed_reason: ClosedReason | None
    source_status_text: str | None
    has_changed_tor: bool
    first_seen_at: str
    last_seen_at: str
    last_changed_at: str
    created_at: str
    updated_at: str


@dataclass(frozen=True, slots=True)
class ProjectAliasRecord:
    id: str
    project_id: str
    alias_type: str
    alias_value: str
    created_at: str


@dataclass(frozen=True, slots=True)
class ProjectStatusEventRecord:
    id: str
    project_id: str
    observed_status_text: str
    normalized_status: str | None
    observed_at: str
    run_id: str | None
    raw_snapshot: dict[str, object] | None
    created_at: str


@dataclass(frozen=True, slots=True)
class ProjectDetail:
    project: ProjectRecord
    aliases: list[ProjectAliasRecord]
    status_events: list[ProjectStatusEventRecord]


@dataclass(frozen=True, slots=True)
class ProjectPage:
    items: list[ProjectRecord]
    total: int
    limit: int
    offset: int


@dataclass(frozen=True, slots=True)
class DashboardRecentProjectChangeRecord:
    project_id: str
    project_name: str
    project_state: str
    last_changed_at: str


@dataclass(frozen=True, slots=True)
class DashboardWinnerProjectRecord:
    project_id: str
    project_name: str
    project_state: str
    awarded_at: str


@dataclass(frozen=True, slots=True)
class DashboardDailyDiscoveryPoint:
    date: str
    count: int


@dataclass(frozen=True, slots=True)
class DashboardStateBreakdownPoint:
    bucket: str
    count: int


@dataclass(frozen=True, slots=True)
class DashboardProjectSummary:
    active_projects: int
    discovered_today: int
    winner_projects_this_week: int
    closed_today: int
    changed_tor_projects: int
    recent_changes: list[DashboardRecentProjectChangeRecord]
    winner_projects: list[DashboardWinnerProjectRecord]
    daily_discovery: list[DashboardDailyDiscoveryPoint]
    project_state_breakdown: list[DashboardStateBreakdownPoint]
