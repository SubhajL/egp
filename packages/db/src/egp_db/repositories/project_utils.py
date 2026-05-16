"""Project repository normalization and mapping helpers."""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation

from sqlalchemy.engine import RowMapping

from egp_crawler_core.canonical_id import build_project_aliases, generate_canonical_id
from egp_crawler_core.project_lifecycle import transition_state
from egp_db.db_utils import normalize_uuid_string
from egp_shared_types.enums import ClosedReason, ProcurementType, ProjectState

from .project_models import (
    ProjectAliasRecord,
    ProjectRecord,
    ProjectStatusEventRecord,
    ProjectUpsertRecord,
)


def _now() -> datetime:
    return datetime.now(UTC)


def _now_iso() -> str:
    return _now().isoformat()


def _normalize_optional_text(value: str | None) -> str | None:
    normalized = str(value).strip() if value is not None else ""
    return normalized or None


def _normalize_date(value: str | None) -> date | None:
    if value is None or not str(value).strip():
        return None
    return date.fromisoformat(str(value).strip())


def _normalize_budget_amount(value: object) -> Decimal | None:
    if value is None:
        return None
    text = str(value).strip().replace(",", "")
    if not text:
        return None
    try:
        return Decimal(text)
    except InvalidOperation as exc:
        raise ValueError("budget_amount must be numeric") from exc


def _normalize_run_id(value: str | None) -> str | None:
    if value is None:
        return None
    return normalize_uuid_string(value)


def _normalize_decimal_filter(
    value: Decimal | float | int | str | None,
) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    text = str(value).strip().replace(",", "")
    if not text:
        return None
    try:
        return Decimal(text)
    except InvalidOperation as exc:
        raise ValueError("budget filter must be numeric") from exc


def _normalize_datetime_filter(value: datetime | str | None) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    text = str(value).strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text)
    except ValueError as exc:
        raise ValueError("updated_after must be ISO-8601 datetime") from exc


def _normalize_multi_value_filter(
    values: list[object] | tuple[object, ...] | None,
) -> list[str]:
    normalized_values: list[str] = []
    for raw_value in values or []:
        for part in str(raw_value).split(","):
            normalized = part.strip()
            if normalized:
                normalized_values.append(normalized)
    return normalized_values


_STRONG_ALIAS_TYPES = {"project_number", "fingerprint"}
_DASHBOARD_CLOSED_STATES = {
    ProjectState.CLOSED_TIMEOUT_CONSULTING.value,
    ProjectState.CLOSED_STALE_NO_TOR.value,
    ProjectState.CLOSED_MANUAL.value,
}
_DASHBOARD_WINNER_STATES = {
    ProjectState.WINNER_ANNOUNCED.value,
    ProjectState.CONTRACT_SIGNED.value,
}
_DASHBOARD_BREAKDOWN_BUCKETS = (
    "discovered",
    "open_invitation",
    "open_consulting",
    "tor_downloaded",
    "winner",
    "closed",
)


def _dashboard_bucket_for_state(project_state: str) -> str | None:
    if project_state == ProjectState.DISCOVERED.value:
        return "discovered"
    if project_state in {
        ProjectState.OPEN_INVITATION.value,
        ProjectState.OPEN_PUBLIC_HEARING.value,
        ProjectState.PRELIM_PRICING_SEEN.value,
    }:
        return "open_invitation"
    if project_state == ProjectState.OPEN_CONSULTING.value:
        return "open_consulting"
    if project_state == ProjectState.TOR_DOWNLOADED.value:
        return "tor_downloaded"
    if project_state in _DASHBOARD_WINNER_STATES:
        return "winner"
    if project_state in _DASHBOARD_CLOSED_STATES:
        return "closed"
    return None


def _date_value_to_iso(value: object) -> str:
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


def _datetime_value_to_iso(value: object) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _project_from_mapping(row: RowMapping) -> ProjectRecord:
    def as_iso(value):
        return value.isoformat() if isinstance(value, datetime) else str(value)

    budget_amount = row["budget_amount"]
    if isinstance(budget_amount, Decimal):
        normalized_budget_amount = format(budget_amount, "f")
        if "." in normalized_budget_amount:
            normalized_budget_amount = normalized_budget_amount.rstrip("0").rstrip(".")
    else:
        normalized_budget_amount = _normalize_optional_text(budget_amount)

    return ProjectRecord(
        id=str(row["id"]),
        tenant_id=str(row["tenant_id"]),
        canonical_project_id=str(row["canonical_project_id"]),
        project_number=_normalize_optional_text(row["project_number"]),
        project_name=str(row["project_name"]),
        organization_name=str(row["organization_name"] or ""),
        procurement_type=ProcurementType(str(row["procurement_type"])),
        proposal_submission_date=(
            row["proposal_submission_date"].isoformat()
            if isinstance(row["proposal_submission_date"], date)
            else _normalize_optional_text(row["proposal_submission_date"])
        ),
        budget_amount=normalized_budget_amount or None,
        project_state=ProjectState(str(row["project_state"])),
        closed_reason=(
            ClosedReason(str(row["closed_reason"]))
            if row["closed_reason"] is not None
            else None
        ),
        source_status_text=_normalize_optional_text(row["source_status_text"]),
        has_changed_tor=bool(row["has_changed_tor"])
        if "has_changed_tor" in row
        else False,
        first_seen_at=as_iso(row["first_seen_at"]),
        last_seen_at=as_iso(row["last_seen_at"]),
        last_changed_at=as_iso(row["last_changed_at"]),
        created_at=as_iso(row["created_at"]),
        updated_at=as_iso(row["updated_at"]),
    )


def _alias_from_mapping(row: RowMapping) -> ProjectAliasRecord:
    created_at = row["created_at"]
    return ProjectAliasRecord(
        id=str(row["id"]),
        project_id=str(row["project_id"]),
        alias_type=str(row["alias_type"]),
        alias_value=str(row["alias_value"]),
        created_at=created_at.isoformat()
        if isinstance(created_at, datetime)
        else str(created_at),
    )


def _status_event_from_mapping(row: RowMapping) -> ProjectStatusEventRecord:
    observed_at = row["observed_at"]
    created_at = row["created_at"]
    return ProjectStatusEventRecord(
        id=str(row["id"]),
        project_id=str(row["project_id"]),
        observed_status_text=str(row["observed_status_text"]),
        normalized_status=_normalize_optional_text(row["normalized_status"]),
        observed_at=observed_at.isoformat()
        if isinstance(observed_at, datetime)
        else str(observed_at),
        run_id=_normalize_optional_text(row["run_id"]),
        raw_snapshot=row["raw_snapshot"],
        created_at=created_at.isoformat()
        if isinstance(created_at, datetime)
        else str(created_at),
    )


def _status_event_signature(
    *,
    observed_status_text: str | None,
    normalized_status: str | None,
) -> tuple[str | None, str | None]:
    return (
        _normalize_optional_text(observed_status_text),
        _normalize_optional_text(normalized_status),
    )


def _dedupe_status_events(
    events: list[ProjectStatusEventRecord],
) -> list[ProjectStatusEventRecord]:
    deduped: list[ProjectStatusEventRecord] = []
    previous_signature: tuple[str | None, str | None] | None = None
    for event in events:
        signature = _status_event_signature(
            observed_status_text=event.observed_status_text,
            normalized_status=event.normalized_status,
        )
        if signature == previous_signature:
            continue
        deduped.append(event)
        previous_signature = signature
    return deduped


def build_project_upsert_record(
    *,
    tenant_id: str,
    project_number: str | None,
    search_name: str | None,
    detail_name: str | None,
    project_name: str,
    organization_name: str,
    proposal_submission_date: str | None,
    budget_amount: str | None,
    procurement_type: ProcurementType | str | None,
    project_state: ProjectState | str = ProjectState.DISCOVERED,
    closed_reason: ClosedReason | str | None = None,
) -> ProjectUpsertRecord:
    transition = transition_state(
        current_state=ProjectState.DISCOVERED,
        next_state=project_state,
        closed_reason=closed_reason,
    )
    canonical_project_id = generate_canonical_id(
        project_number=project_number,
        organization_name=organization_name,
        project_name=project_name,
        proposal_submission_date=proposal_submission_date,
        budget_amount=budget_amount,
    )
    aliases = build_project_aliases(
        project_number=project_number,
        search_name=search_name,
        detail_name=detail_name,
        organization_name=organization_name,
        project_name=project_name,
        proposal_submission_date=proposal_submission_date,
        budget_amount=budget_amount,
    )
    normalized_procurement_type = ProcurementType(
        str(procurement_type or ProcurementType.UNKNOWN).strip()
    )
    normalized_project_number = str(project_number).strip() if project_number else None
    normalized_budget_amount = str(budget_amount).strip() if budget_amount else None
    normalized_date = (
        str(proposal_submission_date).strip() if proposal_submission_date else None
    )
    return ProjectUpsertRecord(
        tenant_id=tenant_id,
        canonical_project_id=canonical_project_id,
        project_name=project_name,
        organization_name=organization_name,
        project_number=normalized_project_number,
        procurement_type=normalized_procurement_type,
        proposal_submission_date=normalized_date,
        budget_amount=normalized_budget_amount,
        project_state=transition["project_state"],
        closed_reason=transition["closed_reason"],
        aliases=aliases,
    )
