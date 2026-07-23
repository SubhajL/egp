"""Crawler-agent heartbeat write and operator runtime read routes."""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Request, status
from pydantic import BaseModel, Field

from egp_api.auth import require_internal_worker_token, require_run_operator_role
from egp_shared_types.enums import CrawlerBlockerCode


router = APIRouter(tags=["crawler-runtime"])


class CrawlerRuntimeResponse(BaseModel):
    agent_id: str
    runtime_mode: str
    heartbeat_status: str
    watcher_status: str
    database_status: str
    blocker_code: str | None
    profile_status: str
    circuit_state: str
    circuit_reset_at: str | None
    reported_at: str | None
    heartbeat_age_seconds: int | None


class CrawlerRuntimeHeartbeatRequest(BaseModel):
    agent_id: str = Field(min_length=1, max_length=128)
    runtime_mode: Literal["external"]
    watcher_status: Literal["running", "stopping", "error"]
    database_status: Literal["connected", "unreachable", "unknown"]
    blocker_code: CrawlerBlockerCode | None = None
    profile_status: Literal[
        "ready",
        "busy",
        "warm_retry",
        "operator_action_required",
        "unknown",
    ]
    circuit_state: Literal["closed", "open", "half_open", "unknown"]
    circuit_reset_at: datetime | None = None


@router.post(
    "/internal/worker/crawler-runtime/heartbeat",
    response_model=CrawlerRuntimeResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def record_crawler_runtime_heartbeat(
    payload: CrawlerRuntimeHeartbeatRequest,
    request: Request,
) -> CrawlerRuntimeResponse:
    require_internal_worker_token(request)
    snapshot = request.app.state.crawler_runtime_repository.record_heartbeat(
        agent_id=payload.agent_id,
        runtime_mode=payload.runtime_mode,
        watcher_status=payload.watcher_status,
        database_status=payload.database_status,
        blocker_code=payload.blocker_code,
        profile_status=payload.profile_status,
        circuit_state=payload.circuit_state,
        circuit_reset_at=payload.circuit_reset_at,
    )
    return CrawlerRuntimeResponse(**asdict(snapshot))


@router.get(
    "/v1/rules/crawler-runtime",
    response_model=CrawlerRuntimeResponse,
)
def get_crawler_runtime(request: Request) -> CrawlerRuntimeResponse:
    require_run_operator_role(request)
    snapshot = request.app.state.rules_service.get_crawler_runtime_status()
    return CrawlerRuntimeResponse(**asdict(snapshot))
