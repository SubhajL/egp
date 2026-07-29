"""The crawler-agent runtime: claim over HTTPS, crawl locally, report over HTTPS.

This is what makes `CrawlerAgentApiClient` an actual agent rather than a library.
It runs on the **Mac**, on the worker image — `apps/api/Dockerfile` deliberately
excludes `egp_worker`, and the container cannot pass e-GP attestation anyway (see
`docs/REMOTE_LOCAL_CRAWLER.md`).

    python -m egp_worker.agent_runtime --once

## The lease is renewed while the browser works

A discovery crawl takes minutes; the claim lease is measured in minutes too. The
loop therefore renews on a background timer for the duration of the crawl, and
**stops the moment the claim is rejected**: a 409 means someone else now owns the
job, so continuing to crawl would produce a result the API will refuse — wasted
e-GP traffic against a site that rate-limits.

## Failure handling is deliberately asymmetric

* Transport failure → back off and retry. The control plane being briefly unwell
  must not stop the crawler.
* Auth failure or protocol disabled → **stop the loop**. Retrying cannot fix
  either, and hammering a switched-off endpoint is exactly what the typed errors
  exist to prevent.
* Crawl failure → do not submit a result. The job's lease expires and it becomes
  claimable again, which is the existing at-least-once behaviour.
"""

from __future__ import annotations

import argparse
import logging
import threading
import time
from typing import Any


logger = logging.getLogger(__name__)

DEFAULT_LEASE_SECONDS = 300.0
DEFAULT_RENEW_INTERVAL_SECONDS = 90.0
DEFAULT_IDLE_SLEEP_SECONDS = 15.0
DEFAULT_ERROR_SLEEP_SECONDS = 30.0


class _LeaseRenewer:
    """Renew a claim on a timer while the crawl runs.

    Exposes `lost` so the caller can tell an expired/superseded claim from a
    transient renewal error: the first means abandon the work, the second means
    keep going and try again.
    """

    def __init__(
        self,
        *,
        client: Any,
        claim: Any,
        interval_seconds: float,
        lease_seconds: float,
    ) -> None:
        self._client = client
        self._claim = claim
        # Floor only guards against a zero/negative interval spinning the thread;
        # it is deliberately not a "sensible minimum". Production passes ~90s, and
        # imposing a 1s floor here would only stop tests driving the loop quickly.
        self._interval = max(0.01, float(interval_seconds))
        self._lease_seconds = lease_seconds
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.lost = False

    def __enter__(self) -> _LeaseRenewer:
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *exc_info) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5.0)

    def _run(self) -> None:
        from egp_worker.agent_client import (
            AgentClaimRejectedError,
            AgentClientError,
        )

        while not self._stop.wait(self._interval):
            try:
                self._claim = self._client.renew(
                    claim=self._claim, lease_seconds=self._lease_seconds
                )
            except AgentClaimRejectedError:
                # Someone else owns this job now. Continuing to crawl would burn
                # e-GP traffic on a result the API will refuse.
                logger.warning("agent lease lost for job %s", self._claim.job_id)
                self.lost = True
                return
            except AgentClientError:
                logger.warning("agent lease renewal failed; will retry", exc_info=True)


def run_once(
    *,
    client: Any,
    executor: Any,
    agent_id: str,
    lease_seconds: float = DEFAULT_LEASE_SECONDS,
    renew_interval_seconds: float = DEFAULT_RENEW_INTERVAL_SECONDS,
) -> str:
    """Claim, crawl, submit. Returns a bounded outcome word for the caller/log.

    `executor(claim) -> envelope` performs the actual crawl. It is injected so the
    loop can be tested without a browser, and so the browser stack is imported only
    where it is really used.
    """

    from egp_worker.agent_client import AgentClaimRejectedError

    claim = client.claim(agent_id=agent_id, lease_seconds=lease_seconds)
    if claim is None:
        return "idle"

    with _LeaseRenewer(
        client=client,
        claim=claim,
        interval_seconds=renew_interval_seconds,
        lease_seconds=lease_seconds,
    ) as renewer:
        try:
            envelope = executor(claim)
        except Exception:  # noqa: BLE001 - a failed crawl submits nothing
            # Deliberately no result: the lease expires and the job becomes
            # claimable again, which is the existing at-least-once behaviour.
            logger.warning("agent crawl failed for job %s", claim.job_id, exc_info=True)
            return "crawl_failed"
        if renewer.lost:
            return "lease_lost"

    try:
        client.submit_result(
            claim=claim,
            # Stable per claim attempt: a retried delivery is a replay, not a
            # second result.
            idempotency_key=f"agent:{claim.job_id}:{claim.claim_token}",
            envelope=envelope,
        )
    except AgentClaimRejectedError:
        logger.warning("agent result refused as stale for job %s", claim.job_id)
        return "lease_lost"
    return "applied"


def run_loop(
    *,
    client: Any,
    executor: Any,
    agent_id: str,
    max_iterations: int | None = None,
    idle_sleep_seconds: float = DEFAULT_IDLE_SLEEP_SECONDS,
    error_sleep_seconds: float = DEFAULT_ERROR_SLEEP_SECONDS,
    sleeper=time.sleep,
    lease_seconds: float = DEFAULT_LEASE_SECONDS,
) -> dict[str, int]:
    """Drain agent-backed work until stopped. Returns outcome counts."""

    from egp_worker.agent_client import (
        AgentAuthError,
        AgentProtocolDisabledError,
        AgentTransportError,
    )

    counts: dict[str, int] = {}
    iterations = 0
    while max_iterations is None or iterations < max_iterations:
        iterations += 1
        try:
            outcome = run_once(
                client=client,
                executor=executor,
                agent_id=agent_id,
                lease_seconds=lease_seconds,
            )
        except (AgentAuthError, AgentProtocolDisabledError) as exc:
            # Neither is retryable. Stopping is the correct response: retrying a
            # rejected token or a disabled protocol is pure noise against the
            # control plane.
            logger.error("agent runtime stopping: %s", exc)
            counts["stopped"] = counts.get("stopped", 0) + 1
            return counts
        except AgentTransportError:
            logger.warning("agent runtime transport error; backing off", exc_info=True)
            counts["transport_error"] = counts.get("transport_error", 0) + 1
            sleeper(error_sleep_seconds)
            continue
        counts[outcome] = counts.get(outcome, 0) + 1
        if outcome == "idle":
            sleeper(idle_sleep_seconds)
    return counts


def _build_browser_executor():  # pragma: no cover - requires a real browser
    """Run the claimed job through the existing discovery workflow.

    Imported lazily so `--once` on a machine without a browser still reports a
    clean configuration error rather than an import failure.
    """

    from pathlib import Path

    from egp_worker.agent_shadow import build_shadow_envelope
    from egp_worker.workflows.discover import run_discover_workflow

    def _execute(claim) -> dict:
        from egp_api.config import get_artifact_root, get_database_url

        artifact_root = get_artifact_root(None)
        result = run_discover_workflow(
            database_url=get_database_url(None, artifact_root=artifact_root),
            tenant_id=claim.tenant_id,
            profile_id=claim.profile_id,
            keyword=claim.keyword,
            trigger_type=claim.trigger_type,
            live=claim.live,
            profile=claim.profile_type,
            artifact_root=Path(str(artifact_root)),
        )
        return build_shadow_envelope(
            run_id=result.run.run.id,
            keyword=claim.keyword,
            projects=list(result.projects),
        )

    return _execute


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Claim and execute agent-backed e-GP discovery jobs over HTTPS."
    )
    parser.add_argument(
        "--agent-id",
        default=None,
        help="Identity reported when claiming. Defaults to EGP_CRAWLER_AGENT_ID.",
    )
    parser.add_argument("--once", action="store_true", help="Process one job and exit.")
    parser.add_argument("--lease-seconds", type=float, default=DEFAULT_LEASE_SECONDS)
    parser.add_argument(
        "--idle-sleep-seconds", type=float, default=DEFAULT_IDLE_SLEEP_SECONDS
    )
    parser.add_argument(
        "--allow-insecure-transport",
        action="store_true",
        help=(
            "Permit a plain-HTTP control plane. For loopback development only — the "
            "worker token has authority over every tenant's queue."
        ),
    )
    return parser


def main(argv: list[str] | None = None, *, client=None, executor=None) -> int:
    import os

    args = _build_parser().parse_args(argv)
    logging.basicConfig(level=logging.INFO)

    if client is None:
        from egp_worker.agent_client import build_agent_client_from_env

        client = build_agent_client_from_env(
            require_https=not args.allow_insecure_transport
        )
    if client is None:
        logger.error(
            "crawler-agent runtime needs EGP_INTERNAL_API_BASE_URL and "
            "EGP_INTERNAL_WORKER_TOKEN"
        )
        return 2

    agent_id = (
        args.agent_id
        or os.getenv("EGP_CRAWLER_AGENT_ID", "").strip()
        or "crawler-agent"
    )
    counts = run_loop(
        client=client,
        executor=executor or _build_browser_executor(),
        agent_id=agent_id,
        max_iterations=1 if args.once else None,
        idle_sleep_seconds=args.idle_sleep_seconds,
        lease_seconds=args.lease_seconds,
    )
    logger.info("crawler-agent runtime outcomes: %s", counts)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
