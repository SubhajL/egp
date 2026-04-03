"""Closure rules extracted from the legacy crawler behavior."""

from __future__ import annotations

from datetime import UTC, datetime

from egp_shared_types.enums import ClosedReason, ProcurementType, ProjectState


_WINNER_STATUSES = ("ประกาศผู้ชนะ", "ผู้ชนะการเสนอราคา")
_CONTRACT_STATUSES = ("ลงนามสัญญา", "อยู่ระหว่างลงนามสัญญา")
_STALE_ELIGIBLE_STATES = {
    ProjectState.DISCOVERED,
    ProjectState.OPEN_INVITATION,
    ProjectState.OPEN_CONSULTING,
    ProjectState.OPEN_PUBLIC_HEARING,
}


def _coerce_procurement_type(
    value: ProcurementType | str | None,
) -> ProcurementType | None:
    if isinstance(value, ProcurementType):
        return value
    if value is None:
        return None
    try:
        return ProcurementType(str(value).strip())
    except ValueError:
        return None


def _coerce_project_state(value: ProjectState | str) -> ProjectState | None:
    if isinstance(value, ProjectState):
        return value
    try:
        return ProjectState(str(value).strip())
    except ValueError:
        return None


def _coerce_datetime(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value


def check_winner_closure(source_status_text: str | None) -> ClosedReason | None:
    normalized_status = str(source_status_text or "").strip()
    if not normalized_status:
        return None
    if any(term in normalized_status for term in _CONTRACT_STATUSES):
        return ClosedReason.CONTRACT_SIGNED
    if any(term in normalized_status for term in _WINNER_STATUSES):
        return ClosedReason.WINNER_ANNOUNCED
    return None


def check_consulting_timeout(
    *,
    procurement_type: ProcurementType | str | None,
    last_changed_at: datetime | None,
    now: datetime | None,
    threshold_days: int = 30,
) -> ClosedReason | None:
    normalized_procurement_type = _coerce_procurement_type(procurement_type)
    normalized_last_changed_at = _coerce_datetime(last_changed_at)
    normalized_now = _coerce_datetime(now)
    if (
        normalized_last_changed_at is None
        or normalized_now is None
        or normalized_procurement_type != ProcurementType.CONSULTING
    ):
        return None
    if (normalized_now - normalized_last_changed_at).days < threshold_days:
        return None
    return ClosedReason.CONSULTING_TIMEOUT_30D


def check_stale_closure(
    *,
    procurement_type: ProcurementType | str | None,
    project_state: ProjectState | str,
    last_changed_at: datetime | None,
    now: datetime | None,
    threshold_days: int = 45,
) -> ClosedReason | None:
    normalized_procurement_type = _coerce_procurement_type(procurement_type)
    normalized_project_state = _coerce_project_state(project_state)
    normalized_last_changed_at = _coerce_datetime(last_changed_at)
    normalized_now = _coerce_datetime(now)
    if normalized_last_changed_at is None or normalized_now is None:
        return None
    if normalized_procurement_type == ProcurementType.CONSULTING:
        return None
    if normalized_project_state not in _STALE_ELIGIBLE_STATES:
        return None
    if (normalized_now - normalized_last_changed_at).days < threshold_days:
        return None
    return ClosedReason.STALE_NO_TOR
