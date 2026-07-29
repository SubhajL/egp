"""Crawler-agent V1 claim / renew / result-inbox persistence.

Ordering in `record_result_envelope` is the subtle part and was corrected after an
adversarial review of the first design:

Accepting a result moves the job to the non-claimable `result_received` state and
consumes its lease. That means a *replay* of the same delivery can no longer
satisfy a `WHERE job_status='pending' AND claim_token=…` guard — the first
submission already invalidated it. So the inbox is consulted **first**: an
existing row for `(tenant_id, job_id, claim_token)` with a matching envelope
fingerprint is a replay and is returned as-is; a differing fingerprint is a
conflict. Only when no row exists is the atomic transition attempted.

The transition and the inbox insert run on **one connection inside one
transaction**. A shared `Engine` is not a shared transaction — calling two
repository methods sequentially would give two, and a crash between them would
strand the job in `result_received` with no result to apply.

The insert is wrapped in a SAVEPOINT (`begin_nested`) because a UNIQUE violation
aborts the enclosing PostgreSQL transaction, making a plain
"catch IntegrityError then SELECT" unusable. This mirrors
`document_persistence.py`, which uses the same idiom for the same reason.
"""

from __future__ import annotations

from dataclasses import dataclass

from datetime import UTC, datetime, timedelta
import json
from typing import Any
from uuid import uuid4

from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    Integer,
    String,
    Table,
    UniqueConstraint,
    and_,
    case,
    func,
    insert,
    or_,
    select,
    text,
    update,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.types import JSON

from egp_db.connection import DB_METADATA, create_shared_engine
from egp_db.db_utils import UUID_SQL_TYPE, normalize_database_url, normalize_uuid_string
from egp_db.repositories.discovery_job_repo import (
    DISCOVERY_JOBS_TABLE,
    DiscoveryQueueSnapshot,
)
from egp_shared_types.crawler_agent import (
    AgentClaim,
    InboxSubmission,
    canonical_envelope_sha256,
)
from egp_shared_types.enums import (
    AgentContractVersion,
    AgentDeliveryMode,
    AgentParityVerdict,
    DiscoveryFailureCode,
    AgentInboxDrainOutcome,
    AgentInboxDrainStatus,
    AgentInboxErrorCode,
    AgentInboxProcessorStatus,
    AgentInboxStatus,
    DiscoveryJobStatus,
    ExecutionBackend,
)


METADATA = DB_METADATA

# How many contended rows to skip before reporting an empty queue.
_CLAIM_CONTENTION_RETRIES = 5

_INBOX_STATUS_SQL = ", ".join(f"'{status.value}'" for status in AgentInboxStatus)
_CONTRACT_VERSION_SQL = ", ".join(f"'{v.value}'" for v in AgentContractVersion)
_INBOX_ERROR_CODE_SQL = ", ".join(f"'{code.value}'" for code in AgentInboxErrorCode)
_PROCESSOR_STATUS_SQL = ", ".join(
    f"'{status.value}'" for status in AgentInboxProcessorStatus
)
_DRAIN_OUTCOME_SQL = ", ".join(f"'{o.value}'" for o in AgentInboxDrainOutcome)
_DELIVERY_MODE_SQL = ", ".join(f"'{m.value}'" for m in AgentDeliveryMode)
_PARITY_VERDICT_SQL = ", ".join(f"'{v.value}'" for v in AgentParityVerdict)

# JSONB on PostgreSQL, plain JSON on the SQLite bootstrap used by tests.
ENVELOPE_JSON_TYPE = JSONB().with_variant(JSON(), "sqlite")

CRAWLER_AGENT_RESULTS_TABLE = Table(
    "crawler_agent_results",
    METADATA,
    Column("id", UUID_SQL_TYPE, primary_key=True),
    Column("tenant_id", UUID_SQL_TYPE, nullable=False),
    Column("job_id", UUID_SQL_TYPE, nullable=False),
    Column("claim_token", UUID_SQL_TYPE, nullable=False),
    Column("contract_version", String, nullable=False),
    Column("idempotency_key", String, nullable=False),
    Column("envelope", ENVELOPE_JSON_TYPE, nullable=False),
    Column("envelope_sha256", String, nullable=False),
    Column("inbox_status", String, nullable=False, default=AgentInboxStatus.PENDING.value),
    Column("attempt_count", Integer, nullable=False, default=0),
    Column("next_attempt_at", DateTime(timezone=True), nullable=False),
    Column("last_error_code", String, nullable=True),
    Column("processor_token", UUID_SQL_TYPE, nullable=True),
    Column("processing_expires_at", DateTime(timezone=True), nullable=True),
    Column("processing_heartbeat_at", DateTime(timezone=True), nullable=True),
    Column("received_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
    Column("applied_at", DateTime(timezone=True), nullable=True),
    Column(
        "delivery_mode",
        String,
        nullable=False,
        default=AgentDeliveryMode.PRIMARY.value,
        server_default=text(f"'{AgentDeliveryMode.PRIMARY.value}'"),
    ),
    Column("parity_verdict", String, nullable=True),
    Column("parity_detail", ENVELOPE_JSON_TYPE, nullable=True),
    CheckConstraint(
        f"delivery_mode IN ({_DELIVERY_MODE_SQL})",
        name="crawler_agent_results_delivery_mode_check",
    ),
    CheckConstraint(
        f"parity_verdict IS NULL OR parity_verdict IN ({_PARITY_VERDICT_SQL})",
        name="crawler_agent_results_parity_verdict_check",
    ),
    CheckConstraint(
        "delivery_mode = 'shadow' OR parity_verdict IS NULL",
        name="crawler_agent_results_primary_has_no_verdict_check",
    ),
    CheckConstraint(
        f"contract_version IN ({_CONTRACT_VERSION_SQL})",
        name="crawler_agent_results_contract_version_check",
    ),
    CheckConstraint(
        f"inbox_status IN ({_INBOX_STATUS_SQL})",
        name="crawler_agent_results_status_check",
    ),
    CheckConstraint(
        f"last_error_code IS NULL OR last_error_code IN ({_INBOX_ERROR_CODE_SQL})",
        name="crawler_agent_results_error_code_check",
    ),
    CheckConstraint(
        "inbox_status <> 'processing' OR "
        "(processor_token IS NOT NULL AND processing_expires_at IS NOT NULL)",
        name="crawler_agent_results_processing_lease_check",
    ),
    UniqueConstraint(
        "tenant_id", "job_id", "claim_token", name="crawler_agent_results_claim_key"
    ),
)


CRAWLER_AGENT_INBOX_HEARTBEATS_TABLE = Table(
    "crawler_agent_inbox_heartbeats",
    METADATA,
    Column("processor_id", String, primary_key=True),
    Column("status", String, nullable=False),
    Column("backlog_depth", Integer, nullable=False, default=0, server_default=text("0")),
    Column("last_outcome", String, nullable=False),
    Column("reported_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
    # Mirrored onto the metadata so the SQLite bootstrap rejects what PostgreSQL
    # rejects. U7a shipped a table where it did not, and SQLite happily stored a
    # value invisible to every consumer.
    CheckConstraint(
        f"status IN ({_PROCESSOR_STATUS_SQL})",
        name="crawler_agent_inbox_heartbeats_status_check",
    ),
    CheckConstraint(
        f"last_outcome IN ({_DRAIN_OUTCOME_SQL})",
        name="crawler_agent_inbox_heartbeats_outcome_check",
    ),
    CheckConstraint(
        "backlog_depth >= 0",
        name="crawler_agent_inbox_heartbeats_backlog_check",
    ),
)


@dataclass(frozen=True)
class InboxHealthSnapshot:
    """Operator answer to "can the processor drain?".

    Global, not tenant-scoped — this is runtime state of the same class as
    ``crawler_runtime_heartbeats``. It returns COUNTS ONLY: no tenant ids, no
    project names, no envelopes.
    """

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


@dataclass(frozen=True)
class InboxRecord:
    """A claimed inbox row, as handed to the processor."""

    result_id: str
    tenant_id: str
    job_id: str
    claim_token: str
    contract_version: str
    idempotency_key: str
    envelope: dict[str, Any]
    envelope_sha256: str
    attempt_count: int
    processor_token: str
    delivery_mode: str = AgentDeliveryMode.PRIMARY.value


class StaleAgentClaimError(RuntimeError):
    """The claim token is unknown, expired, or superseded by a newer claimant."""


class IdempotencyConflictError(RuntimeError):
    """The same claim was already used to submit a *different* result body."""


class JobReleaseFailedError(RuntimeError):
    """A terminal inbox row could not release its job from `result_received`."""


class UnsupportedContractVersionError(ValueError):
    """The agent asked for a contract version this API does not implement."""


def _now() -> datetime:
    return datetime.now(UTC)


def _as_utc(value: datetime) -> datetime:
    """Treat a naive timestamp as UTC.

    The SQLite bootstrap returns naive datetimes where PostgreSQL returns aware
    ones, and subtracting one from the other raises. Same idiom as
    ``discovery_job_repo``.
    """

    return value.replace(tzinfo=UTC) if value.tzinfo is None else value


def _iso(value: datetime | None) -> str:
    if value is None:
        return ""
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat()


class SqlCrawlerAgentRepository:
    def __init__(
        self,
        *,
        database_url: str | None = None,
        engine: Engine | None = None,
        bootstrap_schema: bool = False,
    ) -> None:
        if engine is None and database_url is None:
            raise ValueError("database_url or engine is required")
        self._database_url = (
            normalize_database_url(database_url) if database_url is not None else None
        )
        self._engine = engine or create_shared_engine(self._database_url or "")
        # Defaults to False: no repository may run DDL at application startup —
        # production schema comes from the migration runner. Enforced by
        # tests/phase1/test_high_risk_architecture.py.
        if bootstrap_schema:
            self._ensure_schema()

    def _ensure_schema(self) -> None:
        METADATA.create_all(self._engine)

    # ------------------------------------------------------------------
    # claim
    # ------------------------------------------------------------------

    def claim_agent_job(
        self,
        *,
        agent_id: str,
        lease_seconds: float = 300.0,
    ) -> AgentClaim | None:
        """Claim one agent-backed discovery job, or return None if none is due.

        Deliberately global across tenants, exactly like the legacy claimer: the
        agent serves every tenant. The tenant identity of the work is DERIVED
        from the claimed row and returned to the caller — it is never accepted as
        input, because the internal worker token carries no tenant identity.
        """

        now = _now()
        lease_expires_at = now + timedelta(seconds=max(0.01, float(lease_seconds)))
        attempted: set[str] = set()

        with self._engine.begin() as connection:
            for _ in range(_CLAIM_CONTENTION_RETRIES):
                conditions = [
                    DISCOVERY_JOBS_TABLE.c.execution_backend
                    == ExecutionBackend.AGENT.value,
                    DISCOVERY_JOBS_TABLE.c.job_status
                    == DiscoveryJobStatus.PENDING.value,
                    DISCOVERY_JOBS_TABLE.c.next_attempt_at <= now,
                    _lease_is_free(now),
                ]
                if attempted:
                    conditions.append(DISCOVERY_JOBS_TABLE.c.id.not_in(attempted))

                candidate = (
                    connection.execute(
                        select(DISCOVERY_JOBS_TABLE)
                        .where(and_(*conditions))
                        .order_by(
                            DISCOVERY_JOBS_TABLE.c.next_attempt_at,
                            DISCOVERY_JOBS_TABLE.c.created_at,
                            DISCOVERY_JOBS_TABLE.c.id,
                        )
                        .limit(1)
                    )
                    .mappings()
                    .first()
                )
                if candidate is None:
                    return None

                claim_token = str(uuid4())
                claimed = connection.execute(
                    update(DISCOVERY_JOBS_TABLE)
                    .where(
                        and_(
                            DISCOVERY_JOBS_TABLE.c.id == candidate["id"],
                            # Every predicate is repeated here on purpose: this is
                            # the compare-and-swap. Trusting the candidate SELECT
                            # would let a concurrent claimant, or a backend
                            # reroute, slip through.
                            DISCOVERY_JOBS_TABLE.c.execution_backend
                            == ExecutionBackend.AGENT.value,
                            DISCOVERY_JOBS_TABLE.c.job_status
                            == DiscoveryJobStatus.PENDING.value,
                            DISCOVERY_JOBS_TABLE.c.next_attempt_at <= now,
                            _lease_is_free(now),
                        )
                    )
                    .values(
                        claim_token=claim_token,
                        lease_expires_at=lease_expires_at,
                        lease_heartbeat_at=now,
                        processing_started_at=now,
                        updated_at=now,
                    )
                )
                if not claimed.rowcount:
                    # Lost this row to a concurrent claimant. Do NOT report "no
                    # work": with two agents and two due jobs both may pick the
                    # same candidate, and returning None here would answer 204
                    # while work remains. Skip it and try the next one.
                    attempted.add(str(candidate["id"]))
                    continue

                row = (
                    connection.execute(
                        select(DISCOVERY_JOBS_TABLE).where(
                            DISCOVERY_JOBS_TABLE.c.id == candidate["id"]
                        )
                    )
                    .mappings()
                    .one()
                )
                return _claim_from_row(row, claim_token=claim_token)

        # Every candidate we looked at was taken by someone else.
        return None

    # ------------------------------------------------------------------
    # renew
    # ------------------------------------------------------------------

    def renew_agent_claim(
        self,
        *,
        tenant_id: str,
        job_id: str,
        claim_token: str,
        lease_seconds: float = 300.0,
    ) -> AgentClaim:
        normalized_tenant_id = normalize_uuid_string(tenant_id)
        normalized_job_id = normalize_uuid_string(job_id)
        normalized_claim_token = normalize_uuid_string(claim_token)
        now = _now()
        lease_expires_at = now + timedelta(seconds=max(0.01, float(lease_seconds)))
        with self._engine.begin() as connection:
            renewed = connection.execute(
                update(DISCOVERY_JOBS_TABLE)
                .where(
                    and_(
                        DISCOVERY_JOBS_TABLE.c.tenant_id == normalized_tenant_id,
                        DISCOVERY_JOBS_TABLE.c.id == normalized_job_id,
                        DISCOVERY_JOBS_TABLE.c.claim_token == normalized_claim_token,
                        DISCOVERY_JOBS_TABLE.c.job_status
                        == DiscoveryJobStatus.PENDING.value,
                        DISCOVERY_JOBS_TABLE.c.lease_expires_at.is_not(None),
                        DISCOVERY_JOBS_TABLE.c.lease_expires_at > now,
                    )
                )
                .values(
                    lease_expires_at=lease_expires_at,
                    lease_heartbeat_at=now,
                    updated_at=now,
                )
            )
            if not renewed.rowcount:
                raise StaleAgentClaimError(
                    f"agent claim is stale for job {job_id}"
                )
            row = (
                connection.execute(
                    select(DISCOVERY_JOBS_TABLE).where(
                        and_(
                            DISCOVERY_JOBS_TABLE.c.tenant_id == normalized_tenant_id,
                            DISCOVERY_JOBS_TABLE.c.id == normalized_job_id,
                        )
                    )
                )
                .mappings()
                .one()
            )
        return _claim_from_row(row, claim_token=normalized_claim_token)

    # ------------------------------------------------------------------
    # result
    # ------------------------------------------------------------------

    def record_result_envelope(
        self,
        *,
        tenant_id: str,
        job_id: str,
        claim_token: str,
        idempotency_key: str,
        contract_version: str,
        envelope: dict[str, Any],
        delivery_mode: str = AgentDeliveryMode.PRIMARY.value,
    ) -> InboxSubmission:
        """Accept a result envelope.

        ``primary`` consumes the claim and moves the job to ``result_received``.

        ``shadow`` does NOT: the job is still being executed by the legacy path
        that owns that claim token, and consuming it would break the very crawl
        being observed. The guard instead LOCKS the job row (``FOR UPDATE``) and
        re-checks the claim while holding the lock. A plain read is not safe under
        READ COMMITTED — between reading a live claim and inserting, the lease can
        expire and another worker can reclaim the job, leaving a shadow row bound
        to an obsolete claim.

        ``delivery_mode`` is supplied by the service from the configured protocol,
        never by the remote caller. See ``AgentDeliveryMode``.
        """
        resolved_mode = AgentDeliveryMode(delivery_mode)
        if contract_version not in {v.value for v in AgentContractVersion}:
            raise UnsupportedContractVersionError(
                f"unsupported crawler-agent contract version: {contract_version}"
            )

        normalized_tenant_id = normalize_uuid_string(tenant_id)
        normalized_job_id = normalize_uuid_string(job_id)
        normalized_claim_token = normalize_uuid_string(claim_token)
        envelope_sha256 = canonical_envelope_sha256(envelope)
        now = _now()

        with self._engine.begin() as connection:
            # 1. Replay check FIRST. Accepting a result makes the job
            #    non-claimable, so a replay can no longer satisfy the pending +
            #    live-lease guard below; consulting the inbox first is what makes
            #    replays return the original row instead of erroring.
            existing = _select_inbox_row(
                connection,
                tenant_id=normalized_tenant_id,
                job_id=normalized_job_id,
                claim_token=normalized_claim_token,
            )
            if existing is not None:
                if existing["envelope_sha256"] == envelope_sha256:
                    # Mode must agree: identical bytes offered as an observation
                    # and as a real write are different requests, and silently
                    # replaying one as the other is how a shadow rollout would
                    # start applying.
                    if str(existing["delivery_mode"]) != resolved_mode.value:
                        raise IdempotencyConflictError(
                            f"job {job_id} already has a "
                            f"{existing['delivery_mode']} result; refusing to "
                            f"replay it as {resolved_mode.value}"
                        )
                    return _submission_from_row(existing, replayed=True)
                # Same claim attempt, different body. Never overwrite: one claim
                # attempt yields exactly one terminal result.
                raise IdempotencyConflictError(
                    f"a different result was already recorded for job {job_id}"
                )

            if resolved_mode is AgentDeliveryMode.SHADOW:
                # SHADOW: observe without disturbing. The legacy path still owns
                # this claim and is still running, so the claim must NOT be
                # consumed. Lock the job row and re-check under the lock — a plain
                # read is a TOCTOU under READ COMMITTED, because the lease can
                # expire and another worker can reclaim between the read and the
                # insert. The lock is held until this transaction commits, so the
                # inbox row can never be bound to an obsolete claim.
                live = (
                    connection.execute(
                        select(DISCOVERY_JOBS_TABLE)
                        .where(
                            and_(
                                DISCOVERY_JOBS_TABLE.c.tenant_id
                                == normalized_tenant_id,
                                DISCOVERY_JOBS_TABLE.c.id == normalized_job_id,
                            )
                        )
                        .with_for_update()
                    )
                    .mappings()
                    .first()
                )
                if (
                    live is None
                    or str(live["claim_token"] or "") != normalized_claim_token
                    or str(live["job_status"]) != DiscoveryJobStatus.PENDING.value
                    or live["lease_expires_at"] is None
                    or _as_utc(live["lease_expires_at"]) <= now
                ):
                    raise StaleAgentClaimError(
                        f"shadow claim is stale for job {job_id}; report rejected"
                    )
                return self._insert_inbox_row(
                    connection,
                    tenant_id=normalized_tenant_id,
                    job_id=normalized_job_id,
                    claim_token=normalized_claim_token,
                    idempotency_key=idempotency_key,
                    contract_version=contract_version,
                    envelope=envelope,
                    envelope_sha256=envelope_sha256,
                    delivery_mode=resolved_mode.value,
                    now=now,
                )

            # 2. Consume the claim and make the job non-claimable, atomically with
            #    the insert below. rowcount 0 means the lease expired or another
            #    claimant took over — reject before writing anything.
            transitioned = connection.execute(
                update(DISCOVERY_JOBS_TABLE)
                .where(
                    and_(
                        DISCOVERY_JOBS_TABLE.c.tenant_id == normalized_tenant_id,
                        DISCOVERY_JOBS_TABLE.c.id == normalized_job_id,
                        DISCOVERY_JOBS_TABLE.c.claim_token == normalized_claim_token,
                        DISCOVERY_JOBS_TABLE.c.job_status
                        == DiscoveryJobStatus.PENDING.value,
                        DISCOVERY_JOBS_TABLE.c.lease_expires_at.is_not(None),
                        DISCOVERY_JOBS_TABLE.c.lease_expires_at > now,
                    )
                )
                .values(
                    job_status=DiscoveryJobStatus.RESULT_RECEIVED.value,
                    # Ownership fields are operational; the inbox keeps the
                    # immutable claim token for audit and replay identity.
                    claim_token=None,
                    lease_expires_at=None,
                    lease_heartbeat_at=None,
                    updated_at=now,
                )
            )
            if not transitioned.rowcount:
                # Zero rows is ambiguous, and the ambiguity is a real race: two
                # identical deliveries can both miss the lookup above, then one
                # wins the transition and commits while the other blocks on the
                # row lock and arrives here. Re-read the inbox before deciding —
                # a matching digest is a replay, a differing one is a conflict,
                # and only genuine absence is a stale claim.
                raced = _select_inbox_row(
                    connection,
                    tenant_id=normalized_tenant_id,
                    job_id=normalized_job_id,
                    claim_token=normalized_claim_token,
                )
                if raced is not None:
                    if raced["envelope_sha256"] == envelope_sha256:
                        return _submission_from_row(raced, replayed=True)
                    raise IdempotencyConflictError(
                        f"a different result was already recorded for job {job_id}"
                    )
                raise StaleAgentClaimError(
                    f"agent claim is stale for job {job_id}; result rejected"
                )

            return self._insert_inbox_row(
                connection,
                tenant_id=normalized_tenant_id,
                job_id=normalized_job_id,
                claim_token=normalized_claim_token,
                idempotency_key=idempotency_key,
                contract_version=contract_version,
                envelope=envelope,
                envelope_sha256=envelope_sha256,
                delivery_mode=resolved_mode.value,
                now=now,
            )

    def _insert_inbox_row(
        self,
        connection,
        *,
        tenant_id: str,
        job_id: str,
        claim_token: str,
        idempotency_key: str,
        contract_version: str,
        envelope: dict[str, Any],
        envelope_sha256: str,
        delivery_mode: str,
        now: datetime,
    ) -> InboxSubmission:
        """Insert the inbox row on the caller's connection and transaction.

        Shared by both delivery modes so the SAVEPOINT/replay recovery cannot
        drift between them.
        """

        result_id = str(uuid4())
        values = {
            "id": result_id,
            "tenant_id": tenant_id,
            "job_id": job_id,
            "claim_token": claim_token,
            "contract_version": contract_version,
            "idempotency_key": str(idempotency_key),
            "envelope": envelope,
            "envelope_sha256": envelope_sha256,
            "inbox_status": AgentInboxStatus.PENDING.value,
            "attempt_count": 0,
            "next_attempt_at": now,
            "last_error_code": None,
            "processor_token": None,
            "processing_expires_at": None,
            "processing_heartbeat_at": None,
            "received_at": now,
            "updated_at": now,
            "applied_at": None,
            # Stamped at ACCEPTANCE. Reading the protocol at processing time would
            # let a flip turn a shadow report into a real write.
            "delivery_mode": delivery_mode,
            "parity_verdict": None,
            "parity_detail": None,
        }
        try:
            # SAVEPOINT: a UNIQUE violation aborts the enclosing PostgreSQL
            # transaction, so a bare try/except around a plain INSERT could
            # not recover and re-read.
            with connection.begin_nested():
                connection.execute(insert(CRAWLER_AGENT_RESULTS_TABLE), values)
        except IntegrityError:
            raced = _select_inbox_row(
                connection,
                tenant_id=tenant_id,
                job_id=job_id,
                claim_token=claim_token,
            )
            if raced is not None and raced["envelope_sha256"] == envelope_sha256:
                # A replay must agree on MODE too: the same bytes submitted as a
                # shadow observation and as a primary write are different requests.
                if str(raced["delivery_mode"]) != delivery_mode:
                    raise IdempotencyConflictError(
                        f"job {job_id} already has a {raced['delivery_mode']} result; "
                        f"refusing to replay it as {delivery_mode}"
                    ) from None
                return _submission_from_row(raced, replayed=True)
            raise IdempotencyConflictError(
                f"a different result was already recorded for job {job_id}"
            ) from None

        row = (
            connection.execute(
                select(CRAWLER_AGENT_RESULTS_TABLE).where(
                    CRAWLER_AGENT_RESULTS_TABLE.c.id == result_id
                )
            )
            .mappings()
            .one()
        )
        return _submission_from_row(row, replayed=False)


    # ------------------------------------------------------------------
    # inbox processing (U7c)
    # ------------------------------------------------------------------

    def reclaim_expired_processing(self, *, now: datetime | None = None) -> int:
        """Return rows whose processor died mid-apply to the retry queue.

        Without this a consumer that crashes after setting ``processing`` strands
        its row forever: the drain query only looks at pending/failed.
        """

        moment = now or _now()
        with self._engine.begin() as connection:
            reclaimed = connection.execute(
                update(CRAWLER_AGENT_RESULTS_TABLE)
                .where(
                    and_(
                        CRAWLER_AGENT_RESULTS_TABLE.c.inbox_status
                        == AgentInboxStatus.PROCESSING.value,
                        CRAWLER_AGENT_RESULTS_TABLE.c.processing_expires_at.is_not(None),
                        CRAWLER_AGENT_RESULTS_TABLE.c.processing_expires_at <= moment,
                    )
                )
                .values(
                    inbox_status=AgentInboxStatus.PENDING.value,
                    processor_token=None,
                    processing_expires_at=None,
                    processing_heartbeat_at=None,
                    last_error_code=AgentInboxErrorCode.PROCESSOR_LEASE_LOST.value,
                    # Counts toward the retry budget on purpose. A "poison" row
                    # that hard-kills the process (OOM/SIGKILL) never reaches
                    # mark_result_retry, so without this it would cycle
                    # processing -> pending forever, hold its job in
                    # result_received, and — being the oldest due row — keep
                    # killing the executor before any later row is reached.
                    attempt_count=CRAWLER_AGENT_RESULTS_TABLE.c.attempt_count + 1,
                    updated_at=moment,
                )
            )
        return int(reclaimed.rowcount or 0)

    def claim_next_result(
        self,
        *,
        processor_token: str,
        lease_seconds: float = 300.0,
    ) -> InboxRecord | None:
        """Take ownership of one due inbox row under a processor lease.

        Select-then-CAS rather than ``FOR UPDATE SKIP LOCKED`` so the same code
        path works on the SQLite bootstrap used by tests; the repeated predicates
        in the UPDATE are what actually guarantee exclusivity.
        """

        now = _now()
        expires_at = now + timedelta(seconds=max(0.01, float(lease_seconds)))
        attempted: set[str] = set()
        drainable = (
            AgentInboxStatus.PENDING.value,
            AgentInboxStatus.FAILED.value,
        )

        with self._engine.begin() as connection:
            for _ in range(_CLAIM_CONTENTION_RETRIES):
                conditions = [
                    CRAWLER_AGENT_RESULTS_TABLE.c.inbox_status.in_(drainable),
                    CRAWLER_AGENT_RESULTS_TABLE.c.next_attempt_at <= now,
                ]
                if attempted:
                    conditions.append(
                        CRAWLER_AGENT_RESULTS_TABLE.c.id.not_in(attempted)
                    )
                candidate = (
                    connection.execute(
                        select(CRAWLER_AGENT_RESULTS_TABLE)
                        .where(and_(*conditions))
                        .order_by(
                            CRAWLER_AGENT_RESULTS_TABLE.c.next_attempt_at,
                            CRAWLER_AGENT_RESULTS_TABLE.c.received_at,
                            CRAWLER_AGENT_RESULTS_TABLE.c.id,
                        )
                        .limit(1)
                    )
                    .mappings()
                    .first()
                )
                if candidate is None:
                    return None

                taken = connection.execute(
                    update(CRAWLER_AGENT_RESULTS_TABLE)
                    .where(
                        and_(
                            CRAWLER_AGENT_RESULTS_TABLE.c.id == candidate["id"],
                            CRAWLER_AGENT_RESULTS_TABLE.c.inbox_status.in_(drainable),
                            CRAWLER_AGENT_RESULTS_TABLE.c.next_attempt_at <= now,
                        )
                    )
                    .values(
                        inbox_status=AgentInboxStatus.PROCESSING.value,
                        processor_token=processor_token,
                        processing_expires_at=expires_at,
                        processing_heartbeat_at=now,
                        updated_at=now,
                    )
                )
                if not taken.rowcount:
                    attempted.add(str(candidate["id"]))
                    continue

                row = (
                    connection.execute(
                        select(CRAWLER_AGENT_RESULTS_TABLE).where(
                            CRAWLER_AGENT_RESULTS_TABLE.c.id == candidate["id"]
                        )
                    )
                    .mappings()
                    .one()
                )
                return _inbox_record_from_row(row)
        return None

    def mark_result_applied(
        self,
        *,
        result_id: str,
        processor_token: str,
    ) -> bool:
        """Terminal success: the row is applied and its job leaves in-flight.

        The job transition matters as much as the inbox one: a job left in
        ``result_received`` counts as in-flight forever, so its tenant's dedupe
        and quota paths would never free it.
        """

        now = _now()
        with self._engine.begin() as connection:
            applied = connection.execute(
                update(CRAWLER_AGENT_RESULTS_TABLE)
                .where(
                    and_(
                        CRAWLER_AGENT_RESULTS_TABLE.c.id == normalize_uuid_string(result_id),
                        CRAWLER_AGENT_RESULTS_TABLE.c.processor_token
                        == normalize_uuid_string(processor_token),
                        CRAWLER_AGENT_RESULTS_TABLE.c.inbox_status
                        == AgentInboxStatus.PROCESSING.value,
                        # The lease must still be LIVE. Matching the token is not
                        # enough: between expiry and reclaim the old owner still
                        # holds a matching token and could terminalize a row it no
                        # longer owns.
                        CRAWLER_AGENT_RESULTS_TABLE.c.processing_expires_at.is_not(None),
                        CRAWLER_AGENT_RESULTS_TABLE.c.processing_expires_at > now,
                    )
                )
                .values(
                    inbox_status=AgentInboxStatus.APPLIED.value,
                    processor_token=None,
                    processing_expires_at=None,
                    last_error_code=None,
                    applied_at=now,
                    updated_at=now,
                )
            )
            if not applied.rowcount:
                return False
            row = (
                connection.execute(
                    select(CRAWLER_AGENT_RESULTS_TABLE).where(
                        CRAWLER_AGENT_RESULTS_TABLE.c.id
                        == normalize_uuid_string(result_id)
                    )
                )
                .mappings()
                .one()
            )
            released = connection.execute(
                update(DISCOVERY_JOBS_TABLE)
                .where(
                    and_(
                        DISCOVERY_JOBS_TABLE.c.tenant_id == row["tenant_id"],
                        DISCOVERY_JOBS_TABLE.c.id == row["job_id"],
                        DISCOVERY_JOBS_TABLE.c.job_status
                        == DiscoveryJobStatus.RESULT_RECEIVED.value,
                    )
                )
                .values(
                    job_status=DiscoveryJobStatus.DISPATCHED.value,
                    dispatched_at=now,
                    updated_at=now,
                )
            )
            if not released.rowcount:
                # Never leave a terminal inbox row whose job is still in-flight:
                # that job would count as in-flight forever.
                raise JobReleaseFailedError(
                    f"inbox row {result_id} applied but job {row['job_id']} "
                    "was not in result_received"
                )
        return True

    def mark_result_retry(
        self,
        *,
        result_id: str,
        processor_token: str,
        error_code: str,
        backoff_seconds: float,
    ) -> bool:
        """Transient failure: back to the queue with a future retry time."""

        now = _now()
        with self._engine.begin() as connection:
            updated = connection.execute(
                update(CRAWLER_AGENT_RESULTS_TABLE)
                .where(
                    and_(
                        CRAWLER_AGENT_RESULTS_TABLE.c.id == normalize_uuid_string(result_id),
                        CRAWLER_AGENT_RESULTS_TABLE.c.processor_token
                        == normalize_uuid_string(processor_token),
                        CRAWLER_AGENT_RESULTS_TABLE.c.inbox_status
                        == AgentInboxStatus.PROCESSING.value,
                        # The lease must still be LIVE. Matching the token is not
                        # enough: between expiry and reclaim the old owner still
                        # holds a matching token and could terminalize a row it no
                        # longer owns.
                        CRAWLER_AGENT_RESULTS_TABLE.c.processing_expires_at.is_not(None),
                        CRAWLER_AGENT_RESULTS_TABLE.c.processing_expires_at > now,
                    )
                )
                .values(
                    inbox_status=AgentInboxStatus.FAILED.value,
                    attempt_count=CRAWLER_AGENT_RESULTS_TABLE.c.attempt_count + 1,
                    next_attempt_at=now
                    + timedelta(seconds=max(0.01, float(backoff_seconds))),
                    last_error_code=error_code,
                    processor_token=None,
                    processing_expires_at=None,
                    updated_at=now,
                )
            )
        return bool(updated.rowcount)

    def mark_result_rejected(
        self,
        *,
        result_id: str,
        processor_token: str,
        error_code: str,
    ) -> bool:
        """Terminal failure: never retried, and the job is closed as failed."""

        now = _now()
        with self._engine.begin() as connection:
            rejected = connection.execute(
                update(CRAWLER_AGENT_RESULTS_TABLE)
                .where(
                    and_(
                        CRAWLER_AGENT_RESULTS_TABLE.c.id == normalize_uuid_string(result_id),
                        CRAWLER_AGENT_RESULTS_TABLE.c.processor_token
                        == normalize_uuid_string(processor_token),
                        CRAWLER_AGENT_RESULTS_TABLE.c.inbox_status
                        == AgentInboxStatus.PROCESSING.value,
                        # The lease must still be LIVE. Matching the token is not
                        # enough: between expiry and reclaim the old owner still
                        # holds a matching token and could terminalize a row it no
                        # longer owns.
                        CRAWLER_AGENT_RESULTS_TABLE.c.processing_expires_at.is_not(None),
                        CRAWLER_AGENT_RESULTS_TABLE.c.processing_expires_at > now,
                    )
                )
                .values(
                    inbox_status=AgentInboxStatus.REJECTED.value,
                    last_error_code=error_code,
                    processor_token=None,
                    processing_expires_at=None,
                    updated_at=now,
                )
            )
            if not rejected.rowcount:
                return False
            row = (
                connection.execute(
                    select(CRAWLER_AGENT_RESULTS_TABLE).where(
                        CRAWLER_AGENT_RESULTS_TABLE.c.id
                        == normalize_uuid_string(result_id)
                    )
                )
                .mappings()
                .one()
            )
            released = connection.execute(
                update(DISCOVERY_JOBS_TABLE)
                .where(
                    and_(
                        DISCOVERY_JOBS_TABLE.c.tenant_id == row["tenant_id"],
                        DISCOVERY_JOBS_TABLE.c.id == row["job_id"],
                        DISCOVERY_JOBS_TABLE.c.job_status
                        == DiscoveryJobStatus.RESULT_RECEIVED.value,
                    )
                )
                .values(
                    job_status=DiscoveryJobStatus.FAILED.value,
                    last_error_code=DiscoveryFailureCode.WORKER_RESULT_INVALID.value,
                    updated_at=now,
                )
            )
            if not released.rowcount:
                raise JobReleaseFailedError(
                    f"inbox row {result_id} rejected but job {row['job_id']} "
                    "was not in result_received"
                )
        return True

    def mark_shadow_compared(
        self,
        *,
        result_id: str,
        processor_token: str,
        parity_verdict: str,
        parity_detail: dict[str, Any] | None = None,
    ) -> bool:
        """Terminate a SHADOW row with its verdict, mutating no product state.

        Deliberately NOT ``mark_result_applied``: that also transitions the job out
        of ``result_received``, and a shadow row's job was never in that state — it
        is still being executed by the legacy path that owns the claim. Calling the
        primary terminal here would raise ``JobReleaseFailedError`` at best, and
        corrupt a live job's state at worst.
        """

        now = _now()
        with self._engine.begin() as connection:
            updated = connection.execute(
                update(CRAWLER_AGENT_RESULTS_TABLE)
                .where(
                    and_(
                        CRAWLER_AGENT_RESULTS_TABLE.c.id
                        == normalize_uuid_string(result_id),
                        CRAWLER_AGENT_RESULTS_TABLE.c.processor_token
                        == normalize_uuid_string(processor_token),
                        CRAWLER_AGENT_RESULTS_TABLE.c.inbox_status
                        == AgentInboxStatus.PROCESSING.value,
                        CRAWLER_AGENT_RESULTS_TABLE.c.delivery_mode
                        == AgentDeliveryMode.SHADOW.value,
                        # Lease liveness, same rule as the primary terminals: a
                        # matching token is not enough between expiry and reclaim.
                        CRAWLER_AGENT_RESULTS_TABLE.c.processing_expires_at.is_not(None),
                        CRAWLER_AGENT_RESULTS_TABLE.c.processing_expires_at > now,
                    )
                )
                .values(
                    inbox_status=AgentInboxStatus.APPLIED.value,
                    parity_verdict=AgentParityVerdict(parity_verdict).value,
                    parity_detail=parity_detail,
                    processor_token=None,
                    processing_expires_at=None,
                    applied_at=now,
                    updated_at=now,
                )
            )
        return bool(updated.rowcount)

    def list_run_discovered_project_identities(
        self,
        *,
        tenant_id: str,
        run_id: str,
    ) -> set[str]:
        """Canonical project identities a discovery run DURABLY recorded.

        This is the shadow-parity oracle, and the two tempting shortcuts are both
        wrong:

        * ``project_status_events.run_id`` is incomplete — an unchanged status
          signature suppresses the event entirely (``project_aliases.py``), so a
          re-discovered project leaves no row.
        * ``projects.last_run_id`` is latest-writer state, overwritten by any later
          run. It is not a historical ledger.

        The durable evidence is the per-project ``crawl_tasks`` row the discovery
        workflow writes on success, whose ``result_json`` carries the project id.
        Note ``crawl_tasks.project_id`` is NOT populated by ``mark_task_finished``,
        so the id must come from ``result_json``.
        """

        from egp_db.repositories.project_schema import PROJECTS_TABLE
        from egp_db.repositories.run_repo import CRAWL_RUNS_TABLE, CRAWL_TASKS_TABLE

        normalized_tenant_id = normalize_uuid_string(tenant_id)
        normalized_run_id = normalize_uuid_string(run_id)
        with self._engine.connect() as connection:
            rows = (
                connection.execute(
                    select(CRAWL_TASKS_TABLE.c.result_json)
                    .select_from(
                        CRAWL_TASKS_TABLE.join(
                            CRAWL_RUNS_TABLE,
                            CRAWL_RUNS_TABLE.c.id == CRAWL_TASKS_TABLE.c.run_id,
                        )
                    )
                    .where(
                        and_(
                            # Tenant scoping comes from the RUN, which owns it;
                            # crawl_tasks has no tenant column.
                            CRAWL_RUNS_TABLE.c.tenant_id == normalized_tenant_id,
                            CRAWL_RUNS_TABLE.c.id == normalized_run_id,
                            CRAWL_TASKS_TABLE.c.task_type == "discover",
                            CRAWL_TASKS_TABLE.c.status == "succeeded",
                        )
                    )
                )
                .mappings()
                .all()
            )

        project_ids: set[str] = set()
        for row in rows:
            payload = row["result_json"]
            if isinstance(payload, str):  # SQLite JSON round-trips as text
                payload = json.loads(payload)
            if not isinstance(payload, dict):
                continue
            project_id = payload.get("project_id")
            if project_id:
                project_ids.add(normalize_uuid_string(str(project_id)))
        if not project_ids:
            return set()

        with self._engine.connect() as connection:
            identities = (
                connection.execute(
                    select(PROJECTS_TABLE.c.canonical_project_id).where(
                        and_(
                            PROJECTS_TABLE.c.tenant_id == normalized_tenant_id,
                            PROJECTS_TABLE.c.id.in_(project_ids),
                        )
                    )
                )
                .scalars()
                .all()
            )
        return {str(value) for value in identities}

    # ------------------------------------------------------------------
    # liveness and health (U8b)
    # ------------------------------------------------------------------

    def record_inbox_heartbeat(
        self,
        *,
        processor_id: str,
        status: str,
        backlog_depth: int,
        last_outcome: str,
        now: datetime | None = None,
    ) -> None:
        """Report one drain iteration. UPSERT on ``processor_id``.

        `now` is injectable so tests can age a heartbeat without sleeping; nothing
        in production passes it.
        """

        resolved_now = _as_utc(now or _now())
        values = {
            "processor_id": str(processor_id),
            "status": AgentInboxProcessorStatus(status).value,
            "backlog_depth": max(0, int(backlog_depth)),
            "last_outcome": AgentInboxDrainOutcome(last_outcome).value,
            "reported_at": resolved_now,
            "updated_at": resolved_now,
        }
        with self._engine.begin() as connection:
            # A genuine atomic upsert. UPDATE-then-INSERT-if-zero-rows looks
            # equivalent but is not: two replicas writing their FIRST heartbeat
            # under the same processor id both see zero rows and then race on the
            # primary key, so one of them raises.
            statement = _dialect_insert(
                CRAWLER_AGENT_INBOX_HEARTBEATS_TABLE, connection
            ).values(**values)
            connection.execute(
                statement.on_conflict_do_update(
                    index_elements=[
                        CRAWLER_AGENT_INBOX_HEARTBEATS_TABLE.c.processor_id
                    ],
                    set_={
                        "status": values["status"],
                        "backlog_depth": values["backlog_depth"],
                        "last_outcome": values["last_outcome"],
                        "reported_at": values["reported_at"],
                        "updated_at": values["updated_at"],
                    },
                )
            )

    def count_queued_results(self, *, now: datetime | None = None) -> int:
        """Cheap backlog count for the heartbeat path.

        Deliberately NOT ``get_inbox_health()``: this runs on every drain
        iteration, and the health aggregate spans the whole table. This predicate
        matches ``idx_crawler_agent_results_drain``.
        """

        del now  # accepted for symmetry with the other probes
        with self._engine.connect() as connection:
            return int(
                connection.execute(
                    select(func.count())
                    .select_from(CRAWLER_AGENT_RESULTS_TABLE)
                    .where(
                        CRAWLER_AGENT_RESULTS_TABLE.c.inbox_status.in_(
                            (
                                AgentInboxStatus.PENDING.value,
                                AgentInboxStatus.FAILED.value,
                            )
                        )
                    )
                ).scalar()
                or 0
            )

    def get_inbox_health(
        self,
        *,
        stale_after_seconds: float = 120.0,
        now: datetime | None = None,
    ) -> InboxHealthSnapshot:
        """Answer "can the processor drain?" from durable state alone.

        See ``AgentInboxDrainStatus`` for the precedence, which is total: every
        input maps to exactly one status. The two rules worth restating here
        because they are the non-obvious ones:

        * ``idle`` requires a FRESH heartbeat. An empty queue is not evidence of
          health — a dead processor looks exactly the same from the queue side,
          and that is the case this whole table exists to detect.
        * Health aggregates on the FRESHEST heartbeat across processors. Taking
          the oldest would leave the fleet permanently ``wedged`` after a replica
          is scaled down and its final heartbeat is left behind.
        """

        if stale_after_seconds <= 0:
            raise ValueError("stale_after_seconds must be positive")

        resolved_now = _as_utc(now or _now())
        queued = CRAWLER_AGENT_RESULTS_TABLE.c.inbox_status.in_(
            (AgentInboxStatus.PENDING.value, AgentInboxStatus.FAILED.value)
        )
        stuck = and_(
            CRAWLER_AGENT_RESULTS_TABLE.c.inbox_status
            == AgentInboxStatus.PROCESSING.value,
            or_(
                CRAWLER_AGENT_RESULTS_TABLE.c.processing_expires_at.is_(None),
                CRAWLER_AGENT_RESULTS_TABLE.c.processing_expires_at <= resolved_now,
            ),
        )
        with self._engine.connect() as connection:
            counts = (
                connection.execute(
                    select(
                        func.sum(case((queued, 1), else_=0)).label("backlog"),
                        func.sum(
                            case(
                                (
                                    and_(
                                        queued,
                                        CRAWLER_AGENT_RESULTS_TABLE.c.next_attempt_at
                                        <= resolved_now,
                                    ),
                                    1,
                                ),
                                else_=0,
                            )
                        ).label("due_backlog"),
                        func.sum(case((stuck, 1), else_=0)).label("stuck"),
                        func.min(
                            case(
                                (queued, CRAWLER_AGENT_RESULTS_TABLE.c.received_at),
                                else_=None,
                            )
                        ).label("oldest_queued_at"),
                        func.max(CRAWLER_AGENT_RESULTS_TABLE.c.applied_at).label(
                            "last_applied_at"
                        ),
                    )
                )
                .mappings()
                .one()
            )
            heartbeats = (
                connection.execute(
                    select(CRAWLER_AGENT_INBOX_HEARTBEATS_TABLE).order_by(
                        CRAWLER_AGENT_INBOX_HEARTBEATS_TABLE.c.reported_at.desc()
                    )
                )
                .mappings()
                .all()
            )
        heartbeat = _select_fleet_heartbeat(
            heartbeats,
            now=resolved_now,
            stale_after_seconds=float(stale_after_seconds),
        )

        backlog_depth = int(counts["backlog"] or 0)
        due_backlog_depth = int(counts["due_backlog"] or 0)
        stuck_processing_count = int(counts["stuck"] or 0)
        oldest_queued_at = counts["oldest_queued_at"]
        oldest_pending_age_seconds = (
            max(0, int((resolved_now - _as_utc(oldest_queued_at)).total_seconds()))
            if oldest_queued_at is not None
            else None
        )

        heartbeat_age_seconds: int | None = None
        if heartbeat is not None:
            heartbeat_age_seconds = max(
                0,
                int(
                    (resolved_now - _as_utc(heartbeat["reported_at"])).total_seconds()
                ),
            )

        heartbeat_usable = heartbeat is not None and _heartbeat_is_usable(
            heartbeat, now=resolved_now, stale_after_seconds=float(stale_after_seconds)
        )
        drain_status = _derive_drain_status(
            stuck_processing_count=stuck_processing_count,
            heartbeat=heartbeat,
            heartbeat_age_seconds=heartbeat_age_seconds,
            heartbeat_usable=heartbeat_usable,
            # DUE work, not total. A backlog whose retries are all scheduled far
            # in the future is not being actively drained, and calling it
            # `draining` while `last_outcome=idle` contradicted itself — and hid
            # an accidentally far-future retry schedule.
            due_backlog_depth=due_backlog_depth,
        )

        return InboxHealthSnapshot(
            backlog_depth=backlog_depth,
            due_backlog_depth=due_backlog_depth,
            stuck_processing_count=stuck_processing_count,
            oldest_pending_age_seconds=oldest_pending_age_seconds,
            last_applied_at=_iso_or_none(counts["last_applied_at"]),
            heartbeat_processor_id=(
                str(heartbeat["processor_id"]) if heartbeat is not None else None
            ),
            heartbeat_status=(
                str(heartbeat["status"]) if heartbeat is not None else None
            ),
            heartbeat_last_outcome=(
                str(heartbeat["last_outcome"]) if heartbeat is not None else None
            ),
            heartbeat_reported_at=(
                _iso_or_none(heartbeat["reported_at"]) if heartbeat is not None else None
            ),
            heartbeat_age_seconds=heartbeat_age_seconds,
            drain_status=drain_status,
        )

    def get_agent_queue_snapshot(
        self,
        *,
        now: datetime | None = None,
    ) -> DiscoveryQueueSnapshot:
        """Agent-queue counts, the mirror of the legacy queue snapshot.

        A separate method rather than a widened one: ``get_discovery_queue_snapshot``
        is scoped to ``execution_backend='legacy'`` deliberately, because the
        bounded one-shot crawl derives its terminal contract from those counts.
        Counting agent rows there would make it loop forever (U7a Tier-1 HIGH).
        """

        resolved_now = _as_utc(now or _now())
        pending = and_(
            DISCOVERY_JOBS_TABLE.c.job_status == DiscoveryJobStatus.PENDING.value,
            DISCOVERY_JOBS_TABLE.c.execution_backend == ExecutionBackend.AGENT.value,
        )
        claimable = and_(
            pending,
            DISCOVERY_JOBS_TABLE.c.next_attempt_at <= resolved_now,
            _lease_is_free(resolved_now),
        )
        leased = and_(
            pending,
            DISCOVERY_JOBS_TABLE.c.claim_token.is_not(None),
            DISCOVERY_JOBS_TABLE.c.lease_expires_at > resolved_now,
        )
        retry_scheduled = and_(
            pending,
            DISCOVERY_JOBS_TABLE.c.next_attempt_at > resolved_now,
        )
        with self._engine.connect() as connection:
            row = (
                connection.execute(
                    select(
                        func.sum(case((pending, 1), else_=0)).label("pending_count"),
                        func.sum(case((claimable, 1), else_=0)).label("claimable_count"),
                        func.sum(case((leased, 1), else_=0)).label("leased_count"),
                        func.sum(case((retry_scheduled, 1), else_=0)).label(
                            "retry_scheduled_count"
                        ),
                    )
                )
                .mappings()
                .one()
            )
        return DiscoveryQueueSnapshot(
            pending_count=int(row["pending_count"] or 0),
            claimable_count=int(row["claimable_count"] or 0),
            leased_count=int(row["leased_count"] or 0),
            retry_scheduled_count=int(row["retry_scheduled_count"] or 0),
        )


_MAX_FUTURE_HEARTBEAT_SKEW_SECONDS = 60.0


def _heartbeat_is_usable(row, *, now: datetime, stale_after_seconds: float) -> bool:
    """Fresh, not implausibly future-dated, and self-reporting as running.

    The future-dating guard matters: the executor writes its own application
    clock and the API compares against its own. A heartbeat stamped an hour ahead
    would otherwise stay "fresh" for an hour AND sort first, masking every
    genuinely dead processor behind it.
    """

    reported_at = _as_utc(row["reported_at"])
    delta_seconds = (now - reported_at).total_seconds()
    if delta_seconds < -_MAX_FUTURE_HEARTBEAT_SKEW_SECONDS:
        return False
    if delta_seconds > stale_after_seconds:
        return False
    return str(row["status"]) == AgentInboxProcessorStatus.RUNNING.value


def _select_fleet_heartbeat(rows, *, now: datetime, stale_after_seconds: float):
    """Pick the row that represents the fleet.

    Availability means "at least one fresh running processor", not "the single
    newest row is running". Taking the newest row outright reported the fleet
    wedged when a replica that was shutting down happened to heartbeat one second
    after a healthy one.

    Falls back to the newest row when nothing is usable, so the response still
    carries something for the operator to look at.
    """

    ordered = list(rows)
    if not ordered:
        return None
    for row in ordered:
        if _heartbeat_is_usable(
            row, now=now, stale_after_seconds=stale_after_seconds
        ):
            return row
    return ordered[0]


def _derive_drain_status(
    *,
    stuck_processing_count: int,
    heartbeat,
    heartbeat_age_seconds: int | None,
    heartbeat_usable: bool,
    due_backlog_depth: int,
) -> str:
    """Total function over the health inputs — see ``AgentInboxDrainStatus``."""

    # 1. A stranded `processing` row means work is already lost to a dead
    #    processor, regardless of what any live replica reports.
    if stuck_processing_count > 0:
        return AgentInboxDrainStatus.WEDGED.value
    # 2. Never observed. Distinct from wedged: nothing is known either way.
    if heartbeat is None or heartbeat_age_seconds is None:
        return AgentInboxDrainStatus.UNKNOWN.value
    # 3. `heartbeat` is the fleet representative chosen by
    #    `_select_fleet_heartbeat`, so if it is not usable then NO processor is:
    #    stale, future-dated beyond the skew allowance, or self-reporting
    #    error/stopping.
    if not heartbeat_usable:
        return AgentInboxDrainStatus.WEDGED.value
    # 4/5. At least one fresh running processor.
    return (
        AgentInboxDrainStatus.DRAINING.value
        if due_backlog_depth > 0
        else AgentInboxDrainStatus.IDLE.value
    )


def _iso_or_none(value: datetime | None) -> str | None:
    return _iso(value) if value is not None else None



def _dialect_insert(table, connection):
    """PostgreSQL/SQLite-aware INSERT supporting ON CONFLICT.

    Same idiom as `project_aliases.py`; both dialects implement
    `on_conflict_do_update`, so the atomic upsert works on the SQLite bootstrap
    used by tests as well as in production.
    """

    if connection.dialect.name == "postgresql":
        from sqlalchemy.dialects.postgresql import insert as postgresql_insert

        return postgresql_insert(table)
    from sqlalchemy.dialects.sqlite import insert as sqlite_insert

    return sqlite_insert(table)


def _lease_is_free(now: datetime):
    """A lease is free when unclaimed, unbounded, or expired."""

    return or_(
        DISCOVERY_JOBS_TABLE.c.claim_token.is_(None),
        DISCOVERY_JOBS_TABLE.c.lease_expires_at.is_(None),
        DISCOVERY_JOBS_TABLE.c.lease_expires_at <= now,
    )


def _select_inbox_row(connection, *, tenant_id: str, job_id: str, claim_token: str):
    return (
        connection.execute(
            select(CRAWLER_AGENT_RESULTS_TABLE).where(
                and_(
                    CRAWLER_AGENT_RESULTS_TABLE.c.tenant_id == tenant_id,
                    CRAWLER_AGENT_RESULTS_TABLE.c.job_id == job_id,
                    CRAWLER_AGENT_RESULTS_TABLE.c.claim_token == claim_token,
                )
            )
        )
        .mappings()
        .first()
    )


def _inbox_record_from_row(row) -> InboxRecord:
    envelope = row["envelope"]
    if isinstance(envelope, str):  # SQLite JSON round-trips as text
        envelope = json.loads(envelope)
    return InboxRecord(
        result_id=str(row["id"]),
        tenant_id=str(row["tenant_id"]),
        job_id=str(row["job_id"]),
        claim_token=str(row["claim_token"]),
        contract_version=str(row["contract_version"]),
        idempotency_key=str(row["idempotency_key"]),
        envelope=envelope or {},
        envelope_sha256=str(row["envelope_sha256"]),
        attempt_count=int(row["attempt_count"]),
        processor_token=str(row["processor_token"]),
        delivery_mode=str(row["delivery_mode"]),
    )


def _submission_from_row(row, *, replayed: bool) -> InboxSubmission:
    return InboxSubmission(
        result_id=str(row["id"]),
        job_id=str(row["job_id"]),
        tenant_id=str(row["tenant_id"]),
        inbox_status=str(row["inbox_status"]),
        replayed=replayed,
        received_at=_iso(row["received_at"]),
    )


def _claim_from_row(row, *, claim_token: str) -> AgentClaim:
    return AgentClaim(
        contract_version=AgentContractVersion.V1.value,
        job_id=str(row["id"]),
        tenant_id=str(row["tenant_id"]),
        profile_id=str(row["profile_id"]),
        profile_type=str(row["profile_type"]),
        keyword=str(row["keyword"]),
        trigger_type=str(row["trigger_type"]),
        live=bool(row["live"]),
        recrawl_request_id=(
            str(row["recrawl_request_id"])
            if row.get("recrawl_request_id") is not None
            else None
        ),
        claim_token=claim_token,
        lease_expires_at=_iso(row["lease_expires_at"]),
        attempt_count=int(row["attempt_count"]),
    )


def create_crawler_agent_repository(
    *,
    database_url: str | None = None,
    engine: Engine | None = None,
    bootstrap_schema: bool = False,
) -> SqlCrawlerAgentRepository:
    return SqlCrawlerAgentRepository(
        database_url=database_url,
        engine=engine,
        bootstrap_schema=bootstrap_schema,
    )
