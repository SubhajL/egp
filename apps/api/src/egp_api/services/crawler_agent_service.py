"""Crawler-agent V1 service: the protocol gate and tenant-assertion boundary.

Two responsibilities that must not live in the repository or the route:

1. **The dark gate.** While ``EGP_CRAWLER_AGENT_PROTOCOL`` is ``off`` the contract
   accepts no work at all. The gate is exposed as a predicate so the router can
   enforce it as a dependency *before* request-body validation runs — otherwise
   FastAPI would answer a malformed body with 422 even though the feature is
   disabled, contradicting "disabled endpoints mutate nothing and reveal nothing
   about their payload shape".

2. **Tenant assertion.** ``/internal/worker/*`` authenticates with a single global
   token that carries no tenant identity, so a caller-supplied ``tenant_id`` is an
   *assertion*, never an authorisation. Every repository predicate includes it,
   so a mismatch simply fails to match a row and surfaces as a stale claim. The
   authoritative tenant for a piece of work is the one returned by ``claim``.
"""

from __future__ import annotations

from typing import Any

from egp_api.config import CrawlerAgentProtocol
from egp_shared_types.crawler_agent import AgentClaim, InboxSubmission


class ProtocolDisabledError(RuntimeError):
    """The crawler-agent protocol is off; the endpoint must not accept work."""


class CrawlerAgentService:
    def __init__(
        self,
        *,
        repository: Any,
        protocol: CrawlerAgentProtocol = "off",
    ) -> None:
        self._repository = repository
        self._protocol = protocol

    @property
    def protocol(self) -> CrawlerAgentProtocol:
        return self._protocol

    @property
    def enabled(self) -> bool:
        """Whether the contract currently accepts work.

        ``shadow`` and ``primary`` both accept work; they differ in how a future
        agent client is expected to *use* the results (U8 defines the comparison
        and cutover semantics). Deliberately not collapsed to a boolean flag so
        that distinction has somewhere to live.
        """

        return self._protocol != "off"

    def _require_enabled(self) -> None:
        if not self.enabled:
            raise ProtocolDisabledError("crawler agent protocol is disabled")

    def claim(self, *, agent_id: str, lease_seconds: float = 300.0) -> AgentClaim | None:
        self._require_enabled()
        return self._repository.claim_agent_job(
            agent_id=agent_id, lease_seconds=lease_seconds
        )

    def renew(
        self,
        *,
        tenant_id: str,
        job_id: str,
        claim_token: str,
        lease_seconds: float = 300.0,
    ) -> AgentClaim:
        self._require_enabled()
        return self._repository.renew_agent_claim(
            tenant_id=tenant_id,
            job_id=job_id,
            claim_token=claim_token,
            lease_seconds=lease_seconds,
        )

    def submit_result(
        self,
        *,
        tenant_id: str,
        job_id: str,
        claim_token: str,
        idempotency_key: str,
        contract_version: str,
        envelope: dict[str, Any],
    ) -> InboxSubmission:
        self._require_enabled()
        return self._repository.record_result_envelope(
            tenant_id=tenant_id,
            job_id=job_id,
            claim_token=claim_token,
            idempotency_key=idempotency_key,
            contract_version=contract_version,
            envelope=envelope,
        )
