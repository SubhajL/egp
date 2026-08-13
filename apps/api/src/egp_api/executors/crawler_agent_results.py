"""Standalone crawler-agent result-inbox processor (U7c).

Drains `crawler_agent_results` and applies each envelope through the existing
project-ingest service, then marks the row `applied` and releases its job from
the in-flight `result_received` state.

Runs as its own process, not an API background loop: production sets
`EGP_BACKGROUND_RUNTIME_MODE=external`, and the existing executors build their own
repositories and services rather than reading `app.state`. This one follows that
shape.

## Delivery semantics — stated precisely, because the honest answer is not "exactly once"

Delivery is **at-least-once**, and the *effects* are only partially idempotent:

* `discovery` envelopes are applied through `ProjectIngestService.ingest_discovered_project`,
  which upserts on the canonical project identity. Re-applying the same envelope
  converges on the same project row — that part is genuinely idempotent.
* `status` envelopes apply a state transition, also convergent.
* Everything downstream of the project write is **not** covered: notification
  dispatch, audit rows and run creation are separate effects in separate
  transactions, committed after the project row.

Closing that gap needs an effect ledger or transactional outbox keyed by inbox
result id. That is deliberately NOT attempted here; this module does not claim a
guarantee it cannot keep. See the U7c coding log.

## Notifications reach parity with the API ingest path (U8a)

This executor builds its notification stack through
`egp_api.bootstrap.notifications.build_notification_stack` — the *same* builder the
API bootstrap uses — so a project first seen through an agent result produces the
same `NEW_PROJECT` in-app row, email and webhook delivery, gated by the same
entitlement capability check. U7c shipped this path with no dispatcher at all and
recorded it as a known gap; that gap is closed.

### The residual notification gap is LOSS, not duplication

An earlier draft of this docstring said retries make a *duplicate* notification
possible. That is wrong, and the truth matters more because it is the less
obvious failure. `ingest_discovered_project` dispatches only when the pre-upsert
lookup found no project (`project_ingest.py:68,79`), and the project row commits
*before* the dispatch. So:

1. the project upsert commits;
2. entitlement lookup, recipient resolution, the in-app insert or webhook enqueue
   raises (or the process dies);
3. the inbox row is re-queued and retried;
4. the retry now finds the project **exists**, so `existing is not None`;
5. dispatch is skipped and the row is marked `applied`.

The notification is then **permanently lost** — silently, with the inbox row in a
successful terminal state. A failure part-way through dispatch loses whichever
channels had not yet been written (e.g. the webhook, after the in-app row).

Duplication *is* reachable, but only through a genuine concurrency race: two
processors handling first-sightings of the same canonical project can both observe
`existing is None` before either upsert commits, and both dispatch.

Both properties are inherited from `ProjectIngestService` and are shared with the
API ingest path — U8a does not introduce either one, it makes them reachable from
agent-result processing. `test_a_dispatch_failure_after_project_commit_currently_
loses_the_notification` pins the loss window so it cannot regress unnoticed, and
that test must be **inverted** by the effect-ledger work that closes it.

## Document envelopes are rejected, not half-applied

`document` results are refused as a permanent failure. Document ingestion needs
the actual file bytes and scoped artifact upload is U9, so a descriptor-only
envelope cannot reproduce real document ingestion. Rejecting loudly is better than
writing a document row with no artifact behind it.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import logging
import os
from pathlib import Path
import time
from typing import Any, Protocol
from uuid import uuid4

from egp_api.config import (
    get_artifact_root,
    get_crawler_agent_protocol,
    get_database_url,
)
from egp_db.connection import create_shared_engine
from egp_db.repositories.crawler_agent_repo import (
    InboxRecord,
    create_crawler_agent_repository,
)
from egp_shared_types.crawler_agent import (
    AGENT_RESULT_KIND_DISCOVERY,
    AGENT_RESULT_KIND_DOCUMENT,
    AGENT_RESULT_KIND_STATUS,
    SUPPORTED_AGENT_RESULT_KINDS,
)
from egp_shared_types.enums import (
    AgentDeliveryMode,
    AgentInboxDrainOutcome,
    AgentInboxErrorCode,
    AgentInboxProcessorStatus,
    AgentParityVerdict,
)


_logger = logging.getLogger(__name__)

DEFAULT_LEASE_SECONDS = 300.0
DEFAULT_POLL_INTERVAL_SECONDS = 5.0
DEFAULT_BACKOFF_SECONDS = 60.0
MAX_ATTEMPTS_BEFORE_REJECT = 5
DEFAULT_PROCESSOR_ID = "crawler-agent-inbox"


def _drain_outcome(outcome: "ProcessOutcome") -> AgentInboxDrainOutcome:
    """Map one iteration to the bounded heartbeat vocabulary.

    Ordered most- to least-specific: what the iteration *did* to a row beats the
    fact that it reclaimed some, which beats "nothing was due".
    """

    if outcome.applied:
        return AgentInboxDrainOutcome.APPLIED
    if outcome.rejected:
        return AgentInboxDrainOutcome.REJECTED
    if outcome.retried:
        return AgentInboxDrainOutcome.RETRIED
    if outcome.error_code == AgentInboxErrorCode.PROCESSOR_LEASE_LOST.value:
        return AgentInboxDrainOutcome.LEASE_LOST
    if outcome.claimed:
        # Claimed but no terminal transition: the lease was lost mid-flight.
        return AgentInboxDrainOutcome.LEASE_LOST
    if outcome.reclaimed:
        return AgentInboxDrainOutcome.RECLAIMED
    return AgentInboxDrainOutcome.IDLE


class TransientApplyError(RuntimeError):
    """The apply failed for a reason worth retrying (e.g. the database blinked)."""


class PermanentApplyError(RuntimeError):
    """The envelope can never be applied; retrying would loop forever."""


class ProjectIngestLike(Protocol):
    def ingest_discovered_project(self, *, event: Any) -> Any: ...

    def ingest_status_update_event(self, *, event: Any) -> Any: ...


@dataclass
class ProcessOutcome:
    """What one drain iteration did — the loop's only observable."""

    reclaimed: int = 0
    claimed: bool = False
    applied: bool = False
    retried: bool = False
    rejected: bool = False
    error_code: str | None = None


class CrawlerAgentInboxProcessor:
    def __init__(
        self,
        *,
        repository: Any,
        project_ingest_service: ProjectIngestLike,
        lease_seconds: float = DEFAULT_LEASE_SECONDS,
        backoff_seconds: float = DEFAULT_BACKOFF_SECONDS,
        max_attempts: int = MAX_ATTEMPTS_BEFORE_REJECT,
        processor_id: str = DEFAULT_PROCESSOR_ID,
    ) -> None:
        self._repository = repository
        self._project_ingest_service = project_ingest_service
        self._lease_seconds = lease_seconds
        self._backoff_seconds = backoff_seconds
        self._max_attempts = max_attempts
        self._processor_id = processor_id

    def process_once(self) -> ProcessOutcome:
        """Reclaim stranded rows, then claim and apply at most one result.

        Every exit path reports a heartbeat — including the one that claims
        nothing. That is not symmetry for its own sake: with an empty queue, a
        dead processor and a healthy idle one are indistinguishable from the
        queue side, so the idle iteration is precisely the one whose heartbeat
        carries information.
        """

        outcome = ProcessOutcome()
        try:
            result = self._process_once_inner(outcome)
        except BaseException:
            # A processing failure must NEVER be reported as healthy. Reporting
            # `running`/`idle` from a blanket `finally` was a real defect: a
            # processor that raises from reclaim/claim on every iteration would
            # write a fresh healthy heartbeat, die, be restarted by Compose, and
            # refresh it again — so the operator route reads `idle` forever while
            # nothing drains. Telemetry stays fail-open, but it tells the truth.
            self._report_heartbeat(
                outcome,
                status=AgentInboxProcessorStatus.ERROR,
                drain_outcome=AgentInboxDrainOutcome.ERROR,
            )
            raise
        self._report_heartbeat(outcome)
        return result

    def _process_once_inner(self, outcome: ProcessOutcome) -> ProcessOutcome:
        outcome.reclaimed = self._repository.reclaim_expired_processing()

        processor_token = str(uuid4())
        record = self._repository.claim_next_result(
            processor_token=processor_token, lease_seconds=self._lease_seconds
        )
        if record is None:
            return outcome
        outcome.claimed = True

        try:
            if record.delivery_mode == AgentDeliveryMode.SHADOW.value:
                # Observation only. Never touches product state, and terminates
                # through the shadow-specific mark so it does not try to release a
                # job that was never in `result_received`.
                parity = self._compare_shadow(record)
                outcome.applied = self._repository.mark_shadow_compared(
                    result_id=record.result_id,
                    processor_token=processor_token,
                    parity_verdict=parity[0],
                    parity_detail=parity[1],
                )
                outcome.error_code = (
                    None if outcome.applied else (AgentInboxErrorCode.PROCESSOR_LEASE_LOST.value)
                )
                return outcome
            self._apply(record)
        except PermanentApplyError as exc:
            outcome.rejected = True
            outcome.error_code = AgentInboxErrorCode.APPLY_FAILED_PERMANENT.value
            _logger.warning(
                "crawler agent result rejected: result_id=%s reason=%s",
                record.result_id,
                exc,
            )
            if not self._repository.mark_result_rejected(
                result_id=record.result_id,
                processor_token=processor_token,
                error_code=outcome.error_code,
            ):
                outcome.rejected = False
                outcome.error_code = AgentInboxErrorCode.PROCESSOR_LEASE_LOST.value
                _logger.warning(
                    "crawler agent result lost its lease before rejection: %s",
                    record.result_id,
                )
            return outcome
        except Exception as exc:  # noqa: BLE001 - classified below, never swallowed
            # Retry until the attempt budget is spent, then stop looping forever.
            if record.attempt_count + 1 >= self._max_attempts:
                outcome.rejected = True
                outcome.error_code = AgentInboxErrorCode.APPLY_FAILED_PERMANENT.value
                _logger.error(
                    "crawler agent result exhausted retries: result_id=%s error=%s",
                    record.result_id,
                    exc,
                )
                if not self._repository.mark_result_rejected(
                    result_id=record.result_id,
                    processor_token=processor_token,
                    error_code=outcome.error_code,
                ):
                    outcome.rejected = False
                    outcome.error_code = AgentInboxErrorCode.PROCESSOR_LEASE_LOST.value
                return outcome
            outcome.retried = True
            outcome.error_code = AgentInboxErrorCode.APPLY_FAILED_TRANSIENT.value
            _logger.warning(
                "crawler agent result retry: result_id=%s attempt=%s error=%s",
                record.result_id,
                record.attempt_count + 1,
                exc,
            )
            if not self._repository.mark_result_retry(
                result_id=record.result_id,
                processor_token=processor_token,
                error_code=outcome.error_code,
                backoff_seconds=self._backoff_seconds,
            ):
                outcome.retried = False
                outcome.error_code = AgentInboxErrorCode.PROCESSOR_LEASE_LOST.value
                _logger.warning(
                    "crawler agent result lost its lease before retry: %s",
                    record.result_id,
                )
            return outcome

        outcome.applied = self._repository.mark_result_applied(
            result_id=record.result_id, processor_token=processor_token
        )
        return outcome

    # ------------------------------------------------------------------

    def _report_heartbeat(
        self,
        outcome: ProcessOutcome,
        *,
        status: AgentInboxProcessorStatus = AgentInboxProcessorStatus.RUNNING,
        drain_outcome: AgentInboxDrainOutcome | None = None,
    ) -> None:
        """Publish liveness. Never allowed to interrupt draining.

        Telemetry that can break the thing it observes is worse than no
        telemetry, so every failure here is logged and swallowed — the same
        fail-open rule `CrawlerRuntimeReporter` follows for HTTP heartbeats.

        The backlog is a cheap COUNT over the partial drain index, NOT the full
        health aggregate. Calling `get_inbox_health()` here was a real defect: its
        SUM/MIN/MAX span the whole table with no WHERE, and this runs once every
        idle poll AND once per drained row — so the observability feature would
        have made draining progressively slower as applied history grew. The API
        recomputes the rich aggregate on the operator request path, where it is
        paid for once per human.
        """

        try:
            backlog_depth = int(self._repository.count_queued_results())
        except Exception:  # noqa: BLE001 - telemetry must not break the drain
            _logger.warning("crawler agent inbox: backlog probe failed", exc_info=True)
            backlog_depth = 0
        try:
            self._repository.record_inbox_heartbeat(
                processor_id=self._processor_id,
                status=status.value,
                backlog_depth=backlog_depth,
                last_outcome=(drain_outcome or _drain_outcome(outcome)).value,
            )
        except Exception:  # noqa: BLE001 - telemetry must not break the drain
            _logger.warning("crawler agent inbox: heartbeat failed", exc_info=True)

    def _compare_shadow(self, record: InboxRecord) -> tuple[str, dict[str, Any] | None]:
        """Compare a shadow envelope against what the legacy run durably recorded.

        MUTATES NOTHING. The envelope is decoded exactly as `_apply_discovery`
        would decode it, so what is compared is the thing that *would* have been
        applied — a decode that diverged would make the whole exercise worthless.

        Detail is COUNTS ONLY. A diff of project names would put tenant
        procurement data into a column operator tooling reads across tenants.
        """

        from egp_crawler_core.canonical_id import generate_canonical_id

        envelope = record.envelope or {}
        payload = envelope.get("payload")
        if not isinstance(payload, dict):
            raise PermanentApplyError("shadow envelope payload must be an object")

        projects = payload.get("projects") or []
        if not isinstance(projects, list):
            raise PermanentApplyError("shadow payload 'projects' must be a list")

        run_ids = {
            str(entry.get("run_id"))
            for entry in projects
            if isinstance(entry, dict) and entry.get("run_id")
        }
        if len(run_ids) != 1:
            # No single run to compare against. NOT a mismatch: reporting one
            # would manufacture false alarms during rollout, when the honest
            # answer is that the evidence could not be resolved.
            return (
                AgentParityVerdict.UNAVAILABLE.value,
                {"envelope_count": len(projects), "run_id_count": len(run_ids)},
            )

        envelope_identities = {
            generate_canonical_id(
                project_number=entry.get("project_number"),
                organization_name=entry.get("organization_name"),
                project_name=entry.get("project_name"),
                proposal_submission_date=entry.get("proposal_submission_date"),
                budget_amount=entry.get("budget_amount"),
            )
            for entry in projects
            if isinstance(entry, dict)
        }
        durable_identities = self._repository.list_run_discovered_project_identities(
            tenant_id=record.tenant_id, run_id=run_ids.pop()
        )

        missing = durable_identities - envelope_identities
        extra = envelope_identities - durable_identities
        detail = {
            "envelope_count": len(envelope_identities),
            "durable_count": len(durable_identities),
            "missing_count": len(missing),
            "extra_count": len(extra),
        }
        verdict = (
            AgentParityVerdict.MATCH.value
            if not missing and not extra
            else AgentParityVerdict.MISMATCH.value
        )
        return verdict, detail

    def _apply(self, record: InboxRecord) -> None:
        envelope = record.envelope or {}
        kind = str(envelope.get("kind") or "").strip()

        if kind == AGENT_RESULT_KIND_DOCUMENT:
            raise PermanentApplyError(
                "document result envelopes are not supported until U9 provides "
                "scoped artifact upload; document ingestion requires file bytes"
            )
        if kind not in SUPPORTED_AGENT_RESULT_KINDS:
            raise PermanentApplyError(f"unsupported result envelope kind: {kind!r}")

        payload = envelope.get("payload")
        if not isinstance(payload, dict):
            raise PermanentApplyError("result envelope payload must be an object")

        if kind == AGENT_RESULT_KIND_DISCOVERY:
            self._apply_discovery(record, payload)
        elif kind == AGENT_RESULT_KIND_STATUS:
            self._apply_status(record, payload)

    def _apply_discovery(self, record: InboxRecord, payload: dict[str, Any]) -> None:
        from egp_shared_types.project_events import DiscoveredProjectEvent

        projects = payload.get("projects")
        if projects is None:
            projects = []
        if not isinstance(projects, list):
            raise PermanentApplyError("discovery payload 'projects' must be a list")

        # Two phases on purpose. Validating while applying would persist the
        # projects before a malformed later entry, then reject the whole inbox
        # row — the applied ones stay, the rest are lost forever, and the row is
        # never retried. Build every event first; a bad entry then costs nothing.
        events = []
        for entry in projects:
            if not isinstance(entry, dict):
                raise PermanentApplyError("each discovered project must be an object")
            # Tenant comes from the INBOX ROW, never from the envelope. The row's
            # tenant is bound to the claimed job by a composite foreign key, so it
            # is the only trustworthy source here.
            events.append(
                DiscoveredProjectEvent(
                    tenant_id=record.tenant_id,
                    run_id=entry.get("run_id"),
                    keyword=str(entry.get("keyword") or ""),
                    project_number=entry.get("project_number"),
                    search_name=entry.get("search_name"),
                    detail_name=entry.get("detail_name"),
                    project_name=str(entry.get("project_name") or ""),
                    organization_name=str(entry.get("organization_name") or ""),
                    proposal_submission_date=entry.get("proposal_submission_date"),
                    budget_amount=entry.get("budget_amount"),
                    procurement_type=entry.get("procurement_type"),
                    project_state=entry.get("project_state") or "discovered",
                    source_status_text=str(entry.get("source_status_text") or ""),
                    raw_snapshot=entry.get("raw_snapshot"),
                )
            )

        for event in events:
            self._project_ingest_service.ingest_discovered_project(event=event)

    def _apply_status(self, record: InboxRecord, payload: dict[str, Any]) -> None:
        from egp_shared_types.project_events import ProjectStatusUpdateEvent

        project_id = payload.get("project_id")
        if not project_id:
            raise PermanentApplyError("status payload requires 'project_id'")
        self._project_ingest_service.ingest_status_update_event(
            event=ProjectStatusUpdateEvent(
                tenant_id=record.tenant_id,
                run_id=payload.get("run_id"),
                project_id=str(project_id),
                project_state=payload.get("project_state") or "discovered",
                source_status_text=str(payload.get("source_status_text") or ""),
                raw_snapshot=payload.get("raw_snapshot"),
            )
        )


# ----------------------------------------------------------------------
# standalone runtime
# ----------------------------------------------------------------------


@dataclass
class CrawlerAgentInboxRuntime:
    processor: CrawlerAgentInboxProcessor
    protocol: str


def build_crawler_agent_inbox_runtime(
    database_url: str | None = None,
    *,
    artifact_root: Path | None = None,
) -> CrawlerAgentInboxRuntime:
    """Build the processor with its own repositories and services.

    Deliberately does not read `app.state`: this runs as its own container.
    """

    from egp_api.bootstrap.notifications import build_notification_stack
    from egp_api.config import get_smtp_config
    from egp_api.services.webhook_security_audit import WebhookSecurityAuditRecorder
    from egp_db.repositories.billing_repo import create_billing_repository
    from egp_db.repositories.audit_repo import create_audit_repository
    from egp_db.repositories.discovery_job_repo import create_discovery_job_repository
    from egp_db.repositories.document_repo import create_artifact_store
    from egp_db.repositories.notification_repo import create_notification_repository
    from egp_db.repositories.profile_repo import create_profile_repository
    from egp_db.repositories.project_repo import create_project_repository
    from egp_db.repositories.run_repo import create_run_repository
    from egp_db.repositories.tenant_entitlement_repo import (
        create_tenant_entitlement_repository,
    )
    from egp_domain.project_ingest import ProjectIngestService

    resolved_artifact_root = get_artifact_root(artifact_root)
    resolved_database_url = get_database_url(database_url, artifact_root=resolved_artifact_root)
    shared_engine = create_shared_engine(resolved_database_url)

    project_repository = create_project_repository(
        database_url=resolved_database_url, engine=shared_engine
    )
    # Every repository is bound to THIS process's engine. A builder that resolved
    # them from DATABASE_URL itself would open a second engine here and diverge
    # from the connection the processor's own transactions use.
    notification_stack = build_notification_stack(
        notification_repository=create_notification_repository(
            database_url=resolved_database_url, engine=shared_engine
        ),
        billing_repository=create_billing_repository(
            database_url=resolved_database_url, engine=shared_engine
        ),
        profile_repository=create_profile_repository(
            database_url=resolved_database_url, engine=shared_engine
        ),
        run_repository=create_run_repository(
            database_url=resolved_database_url, engine=shared_engine
        ),
        discovery_job_repository=create_discovery_job_repository(
            database_url=resolved_database_url, engine=shared_engine
        ),
        tenant_entitlement_repository=create_tenant_entitlement_repository(
            database_url=resolved_database_url, engine=shared_engine
        ),
        smtp_config=get_smtp_config(None),
        email_sender=None,
        security_audit_recorder=WebhookSecurityAuditRecorder(
            create_audit_repository(
                database_url=resolved_database_url,
                engine=shared_engine,
            )
        ),
    )
    project_ingest_service = ProjectIngestService(
        project_repository,
        notification_dispatcher=notification_stack.gated_dispatcher,
    )
    _logger.info(
        "crawler agent inbox: NEW_PROJECT notifications are wired through the "
        "shared entitlement-gated dispatcher (parity with the API ingest path)"
    )
    repository = create_crawler_agent_repository(
        database_url=resolved_database_url, engine=shared_engine
    )
    assert create_artifact_store is not None  # imported for parity with peers

    return CrawlerAgentInboxRuntime(
        processor=CrawlerAgentInboxProcessor(
            repository=repository,
            project_ingest_service=project_ingest_service,
            lease_seconds=_env_float(
                "EGP_CRAWLER_AGENT_INBOX_LEASE_SECONDS", DEFAULT_LEASE_SECONDS
            ),
            backoff_seconds=_env_float(
                "EGP_CRAWLER_AGENT_INBOX_BACKOFF_SECONDS", DEFAULT_BACKOFF_SECONDS
            ),
            processor_id=(
                os.getenv("EGP_CRAWLER_AGENT_INBOX_PROCESSOR_ID", "").strip()
                or DEFAULT_PROCESSOR_ID
            ),
        ),
        protocol=get_crawler_agent_protocol(None),
    )


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def run_crawler_agent_inbox_loop(
    *,
    processor: CrawlerAgentInboxProcessor,
    poll_interval_seconds: float = DEFAULT_POLL_INTERVAL_SECONDS,
    max_iterations: int | None = None,
    sleeper=time.sleep,
) -> int:
    """Drain continuously. Returns the number of rows applied."""

    applied = 0
    iterations = 0
    while max_iterations is None or iterations < max_iterations:
        iterations += 1
        outcome = processor.process_once()
        if outcome.applied:
            applied += 1
        if not outcome.claimed:
            sleeper(poll_interval_seconds)
    return applied


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Apply queued e-GP crawler-agent results.")
    parser.add_argument("--database-url", default=None)
    parser.add_argument("--artifact-root", type=Path, default=None)
    parser.add_argument(
        "--once",
        action="store_true",
        help="Process one result and exit instead of polling forever.",
    )
    parser.add_argument(
        "--poll-interval-seconds", type=float, default=DEFAULT_POLL_INTERVAL_SECONDS
    )
    return parser


def main(
    argv: list[str] | None = None,
    *,
    runtime_factory=build_crawler_agent_inbox_runtime,
) -> int:
    args = _build_parser().parse_args(argv)
    logging.basicConfig(level=logging.INFO)
    runtime = runtime_factory(args.database_url, artifact_root=args.artifact_root)

    if runtime.protocol == "off":
        # Deliberately drains anyway. Turning ingress off must not strand results
        # that were already accepted while it was on; a separate stop of this
        # container is the emergency control.
        _logger.info("crawler agent protocol is off; draining already-accepted results only")

    if args.once:
        outcome = runtime.processor.process_once()
        _logger.info("crawler agent inbox one-shot: %s", outcome)
        return 0

    run_crawler_agent_inbox_loop(
        processor=runtime.processor,
        poll_interval_seconds=args.poll_interval_seconds,
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
