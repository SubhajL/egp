"""Typed recovery decisions for manual multi-keyword crawl requests."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from egp_shared_types.enums import CrawlerBlockerCode, DiscoveryFailureCode


RecoveryAction = Literal["continue", "stop", "complete"]


@dataclass(frozen=True, slots=True)
class RecoveryDecision:
    action: RecoveryAction
    code: str
    blocker_code: str | None


_HARD_STOP_BLOCKERS = {
    CrawlerBlockerCode.AGENT_OFFLINE,
    CrawlerBlockerCode.DATABASE_UNREACHABLE,
    CrawlerBlockerCode.CIRCUIT_OPEN,
    CrawlerBlockerCode.PROFILE_OPERATOR_ACTION_REQUIRED,
}


def evaluate_recovery_decision(
    *,
    is_terminal: bool,
    correlation_matches: bool,
    runtime_blocker: CrawlerBlockerCode | str | None,
    job_failure_codes: tuple[DiscoveryFailureCode | str, ...],
) -> RecoveryDecision:
    """Decide from typed state; keyword failures never become a global burst."""

    if not correlation_matches:
        return RecoveryDecision(
            action="stop",
            code=CrawlerBlockerCode.CORRELATION_MISMATCH.value,
            blocker_code=CrawlerBlockerCode.CORRELATION_MISMATCH.value,
        )
    if is_terminal:
        return RecoveryDecision(
            action="complete",
            code="request_complete",
            blocker_code=None,
        )
    blocker = CrawlerBlockerCode(runtime_blocker) if runtime_blocker else None
    if blocker in _HARD_STOP_BLOCKERS:
        return RecoveryDecision(
            action="stop",
            code=blocker.value,
            blocker_code=blocker.value,
        )
    if job_failure_codes:
        return RecoveryDecision(
            action="continue",
            code="jobs_retrying",
            blocker_code=blocker.value if blocker else None,
        )
    if blocker in {
        CrawlerBlockerCode.PROFILE_BUSY,
        CrawlerBlockerCode.PROFILE_WARM_RETRY,
    }:
        return RecoveryDecision(
            action="continue",
            code="shared_dependency_retrying",
            blocker_code=blocker.value,
        )
    return RecoveryDecision(
        action="continue",
        code="request_in_progress",
        blocker_code=None,
    )
