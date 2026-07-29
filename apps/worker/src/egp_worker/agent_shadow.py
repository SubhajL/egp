"""Worker-side shadow dual-report: the producer for U8's parity comparison.

While the Mac executes an ordinary **legacy** discovery job, this additionally
reports the agent result envelope it *would* have sent, using that job's own claim.
The API records it without applying it and compares it against what the legacy path
durably wrote for the same run. One crawl, two reports, no extra load on e-GP.

**Why this lives in the child process.** The parent dispatcher cannot build the
envelope: `DiscoveryDispatcher.dispatch` returns `None`, and the structured result
it decodes from the subprocess carries ids and counts, not project bodies. The
discovered projects only exist here, in the process that crawled them.

**Fail-open, always.** A shadow report is an observation. If it cannot be
delivered, the real crawl has still succeeded and must be reported as such — a
parity probe that can fail a production crawl is worse than no parity probe.
"""

from __future__ import annotations

import logging
from typing import Any


logger = logging.getLogger(__name__)


def build_shadow_envelope(
    *,
    run_id: str,
    keyword: str,
    projects: list[Any],
) -> dict[str, Any]:
    """Build the discovery envelope the agent path would have submitted.

    Every entry carries `run_id`, which is what binds the envelope to the durable
    evidence the comparison reads. The fields chosen are exactly those that feed
    the canonical project identity, because identity is what parity compares — a
    richer envelope would not make the comparison stronger, and would put more
    tenant data on the wire.
    """

    return {
        "kind": "discovery",
        "payload": {
            "projects": [
                {
                    "run_id": run_id,
                    "keyword": keyword,
                    "project_number": getattr(project, "project_number", None),
                    "project_name": getattr(project, "project_name", "") or "",
                    "organization_name": getattr(project, "organization_name", "") or "",
                    "proposal_submission_date": getattr(
                        project, "proposal_submission_date", None
                    ),
                    "budget_amount": getattr(project, "budget_amount", None),
                    "source_status_text": getattr(project, "source_status_text", "")
                    or "",
                }
                for project in projects
            ]
        },
    }


def report_shadow_result(
    *,
    job_id: str,
    tenant_id: str,
    claim_token: str,
    run_id: str,
    keyword: str,
    projects: list[Any],
    client: Any | None = None,
) -> bool:
    """Submit the shadow envelope. Returns True when accepted.

    Never raises: every failure is logged and swallowed. The crawl this observes
    has already succeeded, and failing it because a parity probe could not be
    delivered would be a strictly worse outcome than losing the observation.
    """

    from egp_shared_types.crawler_agent import (
        CRAWLER_AGENT_CONTRACT_VERSION,
        AgentClaim,
    )

    try:
        if client is None:
            from egp_worker.agent_client import build_agent_client_from_env

            client = build_agent_client_from_env()
        if client is None:
            logger.info(
                "shadow report skipped: no internal API base URL / worker token"
            )
            return False

        envelope = build_shadow_envelope(
            run_id=run_id, keyword=keyword, projects=projects
        )
        # The claim this reports under is the LEGACY job's own claim. The API
        # verifies it under a row lock and deliberately does NOT consume it — the
        # legacy path is still executing and still owns it.
        claim = AgentClaim(
            contract_version=CRAWLER_AGENT_CONTRACT_VERSION,
            job_id=job_id,
            tenant_id=tenant_id,
            profile_id="",
            profile_type="",
            keyword=keyword,
            trigger_type="",
            live=True,
            recrawl_request_id=None,
            claim_token=claim_token,
            lease_expires_at="",
            attempt_count=0,
        )
        client.submit_result(
            claim=claim,
            # Stable per (job, run): a retried delivery of the same observation is
            # a replay, not a second report.
            idempotency_key=f"shadow:{job_id}:{run_id}",
            envelope=envelope,
        )
    except Exception:  # noqa: BLE001 - an observation must never fail a real crawl
        logger.warning("shadow parity report failed", exc_info=True)
        return False
    logger.info(
        "shadow parity report submitted: job=%s run=%s projects=%d",
        job_id,
        run_id,
        len(projects),
    )
    return True
