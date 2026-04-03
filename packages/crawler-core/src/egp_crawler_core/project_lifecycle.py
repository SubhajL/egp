"""Explicit lifecycle transition helpers for Phase 1 state correctness."""

from __future__ import annotations

from egp_shared_types.enums import ClosedReason, ProjectState


_STATE_ORDER = {
    ProjectState.DISCOVERED: 0,
    ProjectState.OPEN_INVITATION: 1,
    ProjectState.OPEN_CONSULTING: 2,
    ProjectState.OPEN_PUBLIC_HEARING: 3,
    ProjectState.TOR_DOWNLOADED: 4,
    ProjectState.PRELIM_PRICING_SEEN: 5,
    ProjectState.WINNER_ANNOUNCED: 6,
    ProjectState.CONTRACT_SIGNED: 7,
    ProjectState.CLOSED_TIMEOUT_CONSULTING: 8,
    ProjectState.CLOSED_STALE_NO_TOR: 8,
    ProjectState.CLOSED_MANUAL: 8,
    ProjectState.ERROR: 99,
}
_CLOSED_STATES = {
    ProjectState.WINNER_ANNOUNCED,
    ProjectState.CONTRACT_SIGNED,
    ProjectState.CLOSED_TIMEOUT_CONSULTING,
    ProjectState.CLOSED_STALE_NO_TOR,
    ProjectState.CLOSED_MANUAL,
}
_EXPECTED_CLOSED_REASONS = {
    ProjectState.WINNER_ANNOUNCED: ClosedReason.WINNER_ANNOUNCED,
    ProjectState.CONTRACT_SIGNED: ClosedReason.CONTRACT_SIGNED,
    ProjectState.CLOSED_TIMEOUT_CONSULTING: ClosedReason.CONSULTING_TIMEOUT_30D,
    ProjectState.CLOSED_STALE_NO_TOR: ClosedReason.STALE_NO_TOR,
    ProjectState.CLOSED_MANUAL: ClosedReason.MANUAL,
}


def _coerce_project_state(value: ProjectState | str) -> ProjectState:
    if isinstance(value, ProjectState):
        return value
    return ProjectState(str(value).strip())


def _coerce_closed_reason(value: ClosedReason | str | None) -> ClosedReason | None:
    if isinstance(value, ClosedReason) or value is None:
        return value
    return ClosedReason(str(value).strip())


def transition_state(
    *,
    current_state: ProjectState | str,
    next_state: ProjectState | str,
    closed_reason: ClosedReason | str | None = None,
) -> dict[str, ProjectState | ClosedReason | None]:
    normalized_current_state = _coerce_project_state(current_state)
    normalized_next_state = _coerce_project_state(next_state)
    normalized_closed_reason = _coerce_closed_reason(closed_reason)

    if (
        normalized_current_state != ProjectState.ERROR
        and normalized_next_state != ProjectState.ERROR
        and _STATE_ORDER[normalized_next_state] < _STATE_ORDER[normalized_current_state]
    ):
        raise ValueError(
            "illegal project state transition: "
            f"{normalized_current_state.value} -> {normalized_next_state.value}"
        )

    if normalized_next_state in _CLOSED_STATES and normalized_closed_reason is None:
        raise ValueError("closed_reason is required for closed project states")

    if normalized_next_state in _CLOSED_STATES:
        expected_closed_reason = _EXPECTED_CLOSED_REASONS[normalized_next_state]
        if normalized_closed_reason != expected_closed_reason:
            raise ValueError(
                "closed_reason does not match the requested closed project state"
            )
    else:
        normalized_closed_reason = None

    return {
        "project_state": normalized_next_state,
        "closed_reason": normalized_closed_reason,
    }
