"""Timeout sweep workflow helpers."""

from __future__ import annotations

from datetime import datetime

from egp_crawler_core.closure_rules import (
    check_consulting_timeout,
    check_stale_closure,
)
from egp_crawler_core.project_lifecycle import transition_state
from egp_shared_types.enums import ClosedReason, ProcurementType, ProjectState


_CLOSED_STATE_BY_REASON = {
    ClosedReason.CONSULTING_TIMEOUT_30D: ProjectState.CLOSED_TIMEOUT_CONSULTING,
    ClosedReason.STALE_NO_TOR: ProjectState.CLOSED_STALE_NO_TOR,
}


def evaluate_timeout_transition(
    *,
    procurement_type: ProcurementType | str | None,
    project_state: ProjectState | str,
    last_changed_at: datetime | None,
    now: datetime | None,
) -> dict[str, ProjectState | ClosedReason | None] | None:
    closed_reason = check_consulting_timeout(
        procurement_type=procurement_type,
        last_changed_at=last_changed_at,
        now=now,
    )
    if closed_reason is None:
        closed_reason = check_stale_closure(
            procurement_type=procurement_type,
            project_state=project_state,
            last_changed_at=last_changed_at,
            now=now,
        )
    if closed_reason is None:
        return None
    next_state = _CLOSED_STATE_BY_REASON[closed_reason]
    return transition_state(
        current_state=project_state,
        next_state=next_state,
        closed_reason=closed_reason,
    )
