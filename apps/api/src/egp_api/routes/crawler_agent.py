"""Crawler-agent V1 endpoints — authenticated, and dark by default.

Dependency order is deliberate and load-bearing:

``require_internal_worker_token`` runs first, so the auth matrix (401 missing /
403 wrong / accepted for valid) applies exactly as it does to every other
``/internal/worker/*`` route. ``require_crawler_agent_enabled`` runs next, as a
*router-level dependency*, so a disabled contract answers 404 before FastAPI
validates the request body — otherwise a malformed body against a disabled
endpoint would return 422 and leak that the payload shape was even inspected.

404 (not 503) for the disabled state: 503 means "enabled but a dependency is
unhealthy", which is a different operational signal an agent should retry
differently. It is a feature gate, not concealment — `/openapi.json` and `/docs`
are public and already publish every internal path.
"""

from __future__ import annotations

from typing import Any

from dataclasses import asdict

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, Field

from egp_api.auth import require_internal_worker_token, require_run_operator_role
from egp_api.services.crawler_agent_service import (
    CrawlerAgentService,
    ProtocolDisabledError,
)
from egp_db.repositories.crawler_agent_repo import (
    IdempotencyConflictError,
    StaleAgentClaimError,
    UnsupportedContractVersionError,
)
from egp_shared_types.crawler_agent import CRAWLER_AGENT_CONTRACT_VERSION


def require_crawler_agent_enabled(request: Request) -> None:
    """Refuse every agent endpoint while the protocol is off.

    Registered as a router dependency so it runs before body validation.
    """

    service = getattr(request.app.state, "crawler_agent_service", None)
    if service is None or not service.enabled:
        raise HTTPException(status_code=404, detail="crawler agent protocol disabled")


internal_router = APIRouter(
    prefix="/internal/worker/agent/v1",
    tags=["crawler-agent"],
    dependencies=[
        Depends(require_internal_worker_token),
        Depends(require_crawler_agent_enabled),
    ],
)

# Operator reads. Deliberately NOT under /internal/worker: this is answered for a
# signed-in operator, not for the worker token, and it is NOT gated on the
# protocol flag — "is the processor draining?" must stay answerable exactly when
# the protocol is off, because the processor drains then too.
router = APIRouter(tags=["crawler-agent"])


class AgentClaimRequest(BaseModel):
    agent_id: str = Field(min_length=1, max_length=128)
    lease_seconds: float = Field(default=300.0, gt=0, le=3600)


class AgentClaimResponse(BaseModel):
    contract_version: str
    job_id: str
    tenant_id: str
    profile_id: str
    profile_type: str
    keyword: str
    trigger_type: str
    live: bool
    recrawl_request_id: str | None
    claim_token: str
    lease_expires_at: str
    attempt_count: int


class AgentRenewRequest(BaseModel):
    tenant_id: str = Field(min_length=1)
    job_id: str = Field(min_length=1)
    claim_token: str = Field(min_length=1)
    lease_seconds: float = Field(default=300.0, gt=0, le=3600)


class AgentResultRequest(BaseModel):
    tenant_id: str = Field(min_length=1)
    job_id: str = Field(min_length=1)
    claim_token: str = Field(min_length=1)
    idempotency_key: str = Field(min_length=1, max_length=200)
    contract_version: str = Field(default=CRAWLER_AGENT_CONTRACT_VERSION)
    envelope: dict[str, Any]


class AgentResultResponse(BaseModel):
    result_id: str
    job_id: str
    tenant_id: str
    inbox_status: str
    replayed: bool
    received_at: str


def _service(request: Request) -> CrawlerAgentService:
    return request.app.state.crawler_agent_service


@internal_router.post(
    "/claim",
    response_model=AgentClaimResponse | None,
    responses={
        200: {"description": "A job was claimed."},
        204: {"description": "No agent-backed work is currently due."},
        401: {"description": "Missing internal worker token."},
        403: {"description": "Invalid internal worker token."},
        404: {"description": "Crawler-agent protocol is disabled."},
    },
)
def claim_agent_job(
    payload: AgentClaimRequest,
    request: Request,
    response: Response,
) -> AgentClaimResponse | None:
    try:
        claim = _service(request).claim(
            agent_id=payload.agent_id, lease_seconds=payload.lease_seconds
        )
    except ProtocolDisabledError as exc:  # pragma: no cover - dependency guards first
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if claim is None:
        response.status_code = status.HTTP_204_NO_CONTENT
        return None
    return AgentClaimResponse(**claim.__dict__)


@internal_router.post(
    "/renew",
    response_model=AgentClaimResponse,
    responses={
        200: {"description": "Lease extended."},
        401: {"description": "Missing internal worker token."},
        403: {"description": "Invalid internal worker token."},
        404: {"description": "Crawler-agent protocol is disabled."},
        409: {"description": "Claim token is stale, expired, or superseded."},
    },
)
def renew_agent_claim(
    payload: AgentRenewRequest,
    request: Request,
) -> AgentClaimResponse:
    try:
        claim = _service(request).renew(
            tenant_id=payload.tenant_id,
            job_id=payload.job_id,
            claim_token=payload.claim_token,
            lease_seconds=payload.lease_seconds,
        )
    except ProtocolDisabledError as exc:  # pragma: no cover
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except StaleAgentClaimError as exc:
        raise HTTPException(status_code=409, detail="stale agent claim") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return AgentClaimResponse(**claim.__dict__)


@internal_router.post(
    "/result",
    response_model=AgentResultResponse,
    status_code=status.HTTP_201_CREATED,
    responses={
        201: {"description": "Result accepted into the inbox."},
        200: {"description": "Identical delivery replayed; original row returned."},
        401: {"description": "Missing internal worker token."},
        403: {"description": "Invalid internal worker token."},
        404: {"description": "Crawler-agent protocol is disabled."},
        409: {
            "description": "Stale claim, or a different result already recorded "
            "for this claim attempt."
        },
        422: {"description": "Unsupported contract version or malformed envelope."},
    },
)
def submit_agent_result(
    payload: AgentResultRequest,
    request: Request,
    response: Response,
) -> AgentResultResponse:
    try:
        submission = _service(request).submit_result(
            tenant_id=payload.tenant_id,
            job_id=payload.job_id,
            claim_token=payload.claim_token,
            idempotency_key=payload.idempotency_key,
            contract_version=payload.contract_version,
            envelope=payload.envelope,
        )
    except ProtocolDisabledError as exc:  # pragma: no cover
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except UnsupportedContractVersionError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except IdempotencyConflictError as exc:
        raise HTTPException(
            status_code=409, detail="conflicting result for this claim"
        ) from exc
    except StaleAgentClaimError as exc:
        raise HTTPException(status_code=409, detail="stale agent claim") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    # A replay is not a fresh creation.
    response.status_code = (
        status.HTTP_200_OK if submission.replayed else status.HTTP_201_CREATED
    )
    return AgentResultResponse(**submission.__dict__)


class CrawlerAgentInboxHealthResponse(BaseModel):
    """Counts only — no tenant ids, project names, or envelope payloads."""

    backlog_depth: int
    due_backlog_depth: int
    stuck_processing_count: int
    oldest_pending_age_seconds: int | None
    last_applied_at: str | None
    heartbeat_processor_id: str | None
    heartbeat_status: str | None
    heartbeat_last_outcome: str | None
    heartbeat_reported_at: str | None
    heartbeat_age_seconds: int | None
    drain_status: str
    agent_queue_pending_count: int
    agent_queue_claimable_count: int
    agent_queue_leased_count: int
    agent_queue_retry_scheduled_count: int


@router.get(
    "/v1/rules/crawler-agent-inbox",
    response_model=CrawlerAgentInboxHealthResponse,
    responses={
        200: {"description": "Inbox drain health and agent queue depth."},
        401: {"description": "Not authenticated."},
        403: {"description": "Run operator role required."},
    },
)
def get_crawler_agent_inbox_health(request: Request) -> CrawlerAgentInboxHealthResponse:
    """Answer "can the inbox processor drain?" from durable state.

    A running PID is not proof; `drain_status` distinguishes an idle processor
    from a dead one by requiring a fresh heartbeat, which is why this exists.
    """

    require_run_operator_role(request)
    repository = request.app.state.crawler_agent_repository
    health = repository.get_inbox_health(
        stale_after_seconds=request.app.state.crawler_agent_inbox_stale_after_seconds
    )
    queue = repository.get_agent_queue_snapshot()
    return CrawlerAgentInboxHealthResponse(
        **asdict(health),
        agent_queue_pending_count=queue.pending_count,
        agent_queue_claimable_count=queue.claimable_count,
        agent_queue_leased_count=queue.leased_count,
        agent_queue_retry_scheduled_count=queue.retry_scheduled_count,
    )
