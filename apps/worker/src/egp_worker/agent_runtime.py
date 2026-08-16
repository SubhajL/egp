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
from datetime import UTC, datetime
import logging
import threading
import time
from typing import Any


logger = logging.getLogger(__name__)

DEFAULT_LEASE_SECONDS = 300.0
DEFAULT_RENEW_INTERVAL_SECONDS = 90.0
DEFAULT_IDLE_SLEEP_SECONDS = 15.0
DEFAULT_ERROR_SLEEP_SECONDS = 30.0


def _close_evidence_writer_safely(*, writer: Any, run_repository: Any, run_id: str) -> None:
    """Contain close failures so completed work is not retried as a crawl failure."""

    try:
        writer.close()
    except Exception as exc:  # noqa: BLE001 - cleanup must not mask the crawl result
        logger.exception("Failed to close agent evidence writer")
        try:
            run_repository.update_run_summary(
                run_id,
                summary_json={"evidence_close_error_type": type(exc).__name__},
            )
        except Exception:  # noqa: BLE001 - the original result still owns outcome
            logger.exception("Failed to persist evidence close failure")


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
        self._cancellation = threading.Event()
        self._lease_deadline = self._deadline_from_claim(claim)

    def __enter__(self) -> _LeaseRenewer:
        if self._lease_deadline is None or self._lease_deadline <= time.monotonic():
            self._mark_lost()
            return self
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

        assert self._lease_deadline is not None
        while True:
            remaining = self._lease_deadline - time.monotonic()
            if remaining <= 0:
                logger.warning("agent lease expired for job %s", self._claim.job_id)
                self._mark_lost()
                return
            if self._stop.wait(min(self._interval, remaining)):
                return
            try:
                self._claim = self._client.renew(
                    claim=self._claim, lease_seconds=self._lease_seconds
                )
            except AgentClaimRejectedError:
                # Someone else owns this job now. Continuing to crawl would burn
                # e-GP traffic on a result the API will refuse.
                logger.warning("agent lease lost for job %s", self._claim.job_id)
                self._mark_lost()
                return
            except AgentClientError:
                logger.warning("agent lease renewal failed; will retry", exc_info=True)
                continue
            renewed_deadline = self._deadline_from_claim(self._claim)
            if renewed_deadline is None:
                logger.warning("agent lease renewal returned no valid expiry")
                self._mark_lost()
                return
            self._lease_deadline = renewed_deadline

    @property
    def cancellation_event(self) -> threading.Event:
        return self._cancellation

    def _mark_lost(self) -> None:
        self.lost = True
        self._cancellation.set()
        self._stop.set()

    @staticmethod
    def _deadline_from_claim(claim: Any) -> float | None:
        raw_expiry = str(getattr(claim, "lease_expires_at", "") or "").strip()
        if not raw_expiry:
            return None
        try:
            expiry = datetime.fromisoformat(raw_expiry)
        except ValueError:
            return None
        if expiry.tzinfo is None:
            expiry = expiry.replace(tzinfo=UTC)
        else:
            expiry = expiry.astimezone(UTC)
        remaining = max(0.0, (expiry - datetime.now(UTC)).total_seconds())
        return time.monotonic() + remaining


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
        if renewer.lost:
            return "lease_lost"
        try:
            cancellable = getattr(executor, "execute_cancellable", None)
            if callable(cancellable):
                envelope = cancellable(
                    claim,
                    cancellation_event=renewer.cancellation_event,
                )
            else:
                envelope = executor(claim)
        except Exception:  # noqa: BLE001 - a failed crawl submits nothing
            # Deliberately no result: the lease expires and the job becomes
            # claimable again, which is the existing at-least-once behaviour.
            if renewer.lost:
                return "lease_lost"
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
    """Run claimed work in a cancellable worker-owned subprocess.

    Imported lazily so `--once` on a machine without a browser still reports a
    clean configuration error rather than an import failure.
    """

    import json
    import os
    from pathlib import Path
    import subprocess
    import sys
    from uuid import uuid4

    from egp_db.abnormal_run_completion import complete_abnormal_run
    from egp_db.repositories.candidate_attempt_repo import (
        create_candidate_attempt_repository,
    )
    from egp_db.repositories.project_repo import create_project_repository
    from egp_db.repositories.run_repo import create_run_repository
    from egp_observability.subprocess_evidence import (
        BoundedEvidenceWriter,
        BoundedResultDecoder,
        EvidenceCorrelation,
        build_run_log_path,
        observe_child_process,
        prune_run_evidence,
    )
    from egp_shared_types.enums import CandidateTerminalReason
    from egp_worker.agent_shadow import build_shadow_envelope

    from egp_api.config import get_artifact_root, get_database_url

    artifact_root = Path(str(get_artifact_root(None)))
    database_url = get_database_url(None, artifact_root=artifact_root)
    run_repository = create_run_repository(database_url=database_url)
    project_repository = create_project_repository(database_url=database_url)
    candidate_repository = create_candidate_attempt_repository(database_url=database_url)

    def _prepare_run_evidence(claim, run_id: str, trigger_type: str):
        log_path = build_run_log_path(
            artifact_root=artifact_root,
            tenant_id=claim.tenant_id,
            run_id=run_id,
        )
        writer = BoundedEvidenceWriter(
            path=log_path,
            correlation=EvidenceCorrelation(
                tenant_id=claim.tenant_id,
                run_id=run_id,
                job_id=claim.job_id,
                owner_pid=os.getpid(),
                child_pid=None,
                execution_backend="agent",
                release_sha=os.environ.get("EGP_RELEASE_SHA") or None,
            ),
        )
        try:
            writer.write_lifecycle("dispatch_started")
            payload = json.dumps(
                {
                    "command": "discover",
                    "database_url": database_url,
                    "artifact_root": str(artifact_root),
                    "tenant_id": claim.tenant_id,
                    "run_id": run_id,
                    "profile_id": claim.profile_id,
                    "keyword": claim.keyword,
                    "profile": claim.profile_type,
                    "trigger_type": trigger_type,
                    "live": claim.live,
                    "live_include_documents": True,
                    "browser_settings": {},
                },
                ensure_ascii=False,
            ).encode()
        except Exception:
            try:
                writer.close()
            except Exception:
                logger.exception("Failed to close agent evidence after preparation failure")
            raise
        return log_path, writer, payload, BoundedResultDecoder()

    def _record_incomplete_completion(*, report, writer, run_id: str) -> None:
        if report.succeeded:
            return
        evidence = report.evidence()
        logger.error(
            "Agent abnormal completion incomplete "
            "(tenant_id=%s run_id=%s candidate_error=%s run_error=%s)",
            report.tenant_id,
            run_id,
            report.candidate_reconciliation_error_type,
            report.run_terminalization_error_type,
        )
        if writer is not None:
            try:
                writer.write_lifecycle(
                    "abnormal_completion_incomplete",
                    abnormal_completion=evidence,
                )
            except Exception:
                logger.exception("Failed to write abnormal completion evidence")
        try:
            run_repository.update_run_summary(
                run_id,
                summary_json={"abnormal_completion": evidence},
            )
        except Exception:
            logger.exception("Failed to persist abnormal completion evidence")

    class _AgentSubprocessExecutor:
        def execute_cancellable(self, claim, *, cancellation_event) -> dict:
            run_id = str(uuid4())
            trigger_type = str(claim.trigger_type or "").strip().lower()
            if trigger_type not in {"schedule", "manual", "retry", "backfill"}:
                trigger_type = "manual"
            run_repository.create_run(
                tenant_id=claim.tenant_id,
                profile_id=claim.profile_id,
                trigger_type=trigger_type,
                run_id=run_id,
            )
            try:
                log_path, writer, payload, decoder = _prepare_run_evidence(
                    claim,
                    run_id,
                    trigger_type,
                )
            except Exception as exc:
                report = complete_abnormal_run(
                    tenant_id=claim.tenant_id,
                    run_id=run_id,
                    failure_code="dispatch_exception",
                    candidate_reason=CandidateTerminalReason.WORKER_LOST.value,
                    error=str(exc),
                    candidate_repository=candidate_repository,
                    run_repository=run_repository,
                )
                _record_incomplete_completion(report=report, writer=None, run_id=run_id)
                raise
            proc = None
            try:
                proc = subprocess.Popen(
                    [sys.executable, "-m", "egp_worker.main"],
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    start_new_session=True,
                )
                writer.update_child_pid(proc.pid)
                run_repository.update_run_summary(
                    run_id,
                    summary_json={
                        "worker_log_path": str(log_path),
                        "worker_owner_pid": os.getpid(),
                        "worker_pid": proc.pid,
                        "execution_backend": "agent",
                        "discovery_job_id": claim.job_id,
                    },
                )
                collected = observe_child_process(
                    proc,
                    payload=payload,
                    writer=writer,
                    result_decoder=decoder,
                    timeout_seconds=3 * 60 * 60,
                    cancellation_event=cancellation_event,
                )
                result = decoder.decode()
                if collected.returncode != 0:
                    raise RuntimeError(
                        f"agent discovery child exited non-zero ({collected.returncode})"
                    )
                if not isinstance(result, dict):
                    raise RuntimeError("agent discovery child returned no valid result")
                if str(result.get("run_id") or "") != run_id:
                    raise RuntimeError("agent discovery child returned an invalid run_id")
                if str(result.get("run_status") or "") not in {"succeeded", "partial"}:
                    raise RuntimeError("agent discovery child reported failure")
                writer.write_lifecycle("dispatch_finished")
            except Exception as exc:
                if proc is not None and proc.poll() is None:
                    try:
                        os.killpg(os.getpgid(proc.pid), 9)
                    except OSError:
                        try:
                            proc.kill()
                        except OSError:
                            pass
                    try:
                        proc.wait(timeout=5)
                    except Exception:
                        pass
                lease_lost = cancellation_event.is_set()
                writer.write_lifecycle(
                    "dispatch_failed",
                    reason="lease_lost" if lease_lost else "agent_child_failure",
                )
                report = complete_abnormal_run(
                    tenant_id=claim.tenant_id,
                    run_id=run_id,
                    failure_code="lease_lost" if lease_lost else "dispatch_exception",
                    candidate_reason=(
                        CandidateTerminalReason.LEASE_LOST.value
                        if lease_lost
                        else CandidateTerminalReason.WORKER_LOST.value
                    ),
                    error=str(exc),
                    candidate_repository=candidate_repository,
                    run_repository=run_repository,
                )
                _record_incomplete_completion(report=report, writer=writer, run_id=run_id)
                raise
            finally:
                try:
                    _close_evidence_writer_safely(
                        writer=writer,
                        run_repository=run_repository,
                        run_id=run_id,
                    )
                finally:
                    try:
                        prune_run_evidence(
                            artifact_root=artifact_root,
                            tenant_id=claim.tenant_id,
                        )
                    except Exception:
                        pass
            projects = []
            for raw_project_id in result.get("project_ids") or []:
                project = project_repository.get_project(
                    tenant_id=claim.tenant_id,
                    project_id=str(raw_project_id),
                )
                if project is not None:
                    projects.append(project)
            return build_shadow_envelope(
                run_id=run_id,
                keyword=claim.keyword,
                projects=projects,
            )

    return _AgentSubprocessExecutor()


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
