"""HTTPS client for the V1 crawler-agent contract.

This is the seam that lets the Mac crawler stop being a database client. It
speaks only HTTP to the control plane: claim work, renew the lease, submit the
result. **It must never import a database driver** — that is the whole point, and
U9 removes the Mac's remaining DB/storage credentials on the strength of it.
`test_the_agent_client_never_reaches_a_database` enforces it rather than trusting
the docstring.

Failure modes are distinguished deliberately. An agent that cannot tell "the
feature is switched off" from "my token is wrong" from "the control plane is
briefly unwell" will either hammer a disabled endpoint forever or give up on a
transient blip. So:

* 404 → `AgentProtocolDisabledError` — stop, this deployment is not accepting agent
  work. Not retryable.
* 401/403 → `AgentAuthError` — stop, credentials are wrong. Retrying cannot help.
* timeout / 5xx → `AgentTransportError` — retryable.
* 409 → `AgentClaimRejectedError` — this claim is stale; drop the work and re-claim.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

import httpx

from egp_shared_types.crawler_agent import AgentClaim


CLAIM_PATH = "/internal/worker/agent/v1/claim"
RENEW_PATH = "/internal/worker/agent/v1/renew"
RESULT_PATH = "/internal/worker/agent/v1/result"


class AgentClientError(RuntimeError):
    """Base class for every crawler-agent transport failure."""


class AgentTransportError(AgentClientError):
    """The control plane could not be reached, or answered 5xx. Retryable."""


class AgentAuthError(AgentClientError):
    """The internal worker token is missing or rejected. NOT retryable."""


class AgentProtocolDisabledError(AgentClientError):
    """This deployment is not accepting agent work (protocol off). NOT retryable."""


class AgentClaimRejectedError(AgentClientError):
    """The claim is stale, expired, or superseded. Drop the work and re-claim."""


@dataclass(frozen=True)
class AgentResultAccepted:
    result_id: str
    replayed: bool


class CrawlerAgentApiClient:
    """Claim / renew / submit over HTTPS, using only the internal worker token."""

    def __init__(
        self,
        *,
        base_url: str,
        worker_token: str,
        timeout_seconds: float = 30.0,
        client: Any | None = None,
        require_https: bool = True,
    ) -> None:
        scheme = urlparse(base_url).scheme.lower()
        if require_https and scheme != "https":
            # The token is a bearer credential with authority over every tenant's
            # queue. Sending it in clear text would hand that authority to anyone
            # on the path, so plain HTTP is refused rather than warned about.
            # `require_https=False` exists for loopback tests only.
            raise ValueError(
                f"crawler-agent base URL must be https, got {scheme or 'no'} scheme"
            )
        self._base_url = base_url.rstrip("/")
        self._worker_token = worker_token
        self._timeout_seconds = float(timeout_seconds)
        self._client = client

    # ------------------------------------------------------------------

    def _headers(self) -> dict[str, str]:
        return {
            "Content-Type": "application/json",
            "X-EGP-Worker-Token": self._worker_token,
        }

    def _post(self, path: str, payload: dict[str, Any]):
        try:
            if self._client is not None:
                return self._client.post(path, json=payload, headers=self._headers())
            with httpx.Client(
                base_url=self._base_url, timeout=self._timeout_seconds
            ) as client:
                return client.post(path, json=payload, headers=self._headers())
        except Exception as exc:  # noqa: BLE001 - every transport fault is retryable
            raise AgentTransportError(f"POST {path} failed: {exc}") from exc

    @staticmethod
    def _raise_for_status(response, *, path: str) -> None:
        status = int(getattr(response, "status_code", 0))
        if status in (401, 403):
            raise AgentAuthError(f"POST {path} rejected the internal worker token")
        if status == 404:
            raise AgentProtocolDisabledError(
                f"POST {path} is not available; the crawler-agent protocol is off"
            )
        if status == 409:
            raise AgentClaimRejectedError(f"POST {path} reports a stale claim")
        if status >= 500:
            raise AgentTransportError(f"POST {path} returned {status}")
        if status >= 400:
            raise AgentClientError(f"POST {path} returned {status}")

    # ------------------------------------------------------------------

    def claim(self, *, agent_id: str, lease_seconds: float = 300.0) -> AgentClaim | None:
        """Claim one agent-backed job, or None when nothing is due.

        The returned ``tenant_id`` is DERIVED by the API from the claimed row. The
        client never supplies one — the worker token carries no tenant identity, so
        a client-asserted tenant would be an authorization hole.
        """

        response = self._post(
            CLAIM_PATH, {"agent_id": agent_id, "lease_seconds": lease_seconds}
        )
        self._raise_for_status(response, path=CLAIM_PATH)
        if int(getattr(response, "status_code", 0)) == 204:
            return None
        body = response.json()
        if not body:
            return None
        return AgentClaim(**body)

    def renew(
        self,
        *,
        claim: AgentClaim,
        lease_seconds: float = 300.0,
    ) -> AgentClaim:
        response = self._post(
            RENEW_PATH,
            {
                "tenant_id": claim.tenant_id,
                "job_id": claim.job_id,
                "claim_token": claim.claim_token,
                "lease_seconds": lease_seconds,
            },
        )
        self._raise_for_status(response, path=RENEW_PATH)
        return AgentClaim(**response.json())

    def submit_result(
        self,
        *,
        claim: AgentClaim,
        idempotency_key: str,
        envelope: dict[str, Any],
    ) -> AgentResultAccepted:
        """Submit the result for a claimed job.

        Note there is no ``delivery_mode`` here: the API derives it from its own
        configured protocol. A client-chosen mode would let any token holder submit
        a real write while the operator believed the system was in shadow.
        """

        response = self._post(
            RESULT_PATH,
            {
                "tenant_id": claim.tenant_id,
                "job_id": claim.job_id,
                "claim_token": claim.claim_token,
                "idempotency_key": idempotency_key,
                "contract_version": claim.contract_version,
                "envelope": envelope,
            },
        )
        self._raise_for_status(response, path=RESULT_PATH)
        body = response.json()
        return AgentResultAccepted(
            result_id=str(body["result_id"]),
            replayed=bool(body.get("replayed", False)),
        )


def build_agent_client_from_env(
    *,
    require_https: bool = True,
) -> CrawlerAgentApiClient | None:
    """Build the client from the worker's existing internal-API configuration.

    Returns None when the control plane is not configured, so a runtime can report
    that plainly instead of constructing a client that fails on first use.
    """

    from egp_worker.config import (
        get_internal_api_base_url,
        get_internal_api_timeout_seconds,
        get_internal_worker_token,
    )

    base_url = get_internal_api_base_url(None)
    worker_token = get_internal_worker_token(None)
    if not base_url or not worker_token:
        return None
    return CrawlerAgentApiClient(
        base_url=base_url,
        worker_token=worker_token,
        timeout_seconds=get_internal_api_timeout_seconds(None),
        require_https=require_https,
    )
