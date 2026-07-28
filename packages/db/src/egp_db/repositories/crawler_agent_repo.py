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
    insert,
    or_,
    select,
    update,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.types import JSON

from egp_db.connection import DB_METADATA, create_shared_engine
from egp_db.db_utils import UUID_SQL_TYPE, normalize_database_url, normalize_uuid_string
from egp_db.repositories.discovery_job_repo import DISCOVERY_JOBS_TABLE
from egp_shared_types.crawler_agent import (
    AgentClaim,
    InboxSubmission,
    canonical_envelope_sha256,
)
from egp_shared_types.enums import (
    AgentContractVersion,
    DiscoveryFailureCode,
    AgentInboxErrorCode,
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
    ) -> InboxSubmission:
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
                    return _submission_from_row(existing, replayed=True)
                # Same claim attempt, different body. Never overwrite: one claim
                # attempt yields exactly one terminal result.
                raise IdempotencyConflictError(
                    f"a different result was already recorded for job {job_id}"
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

            result_id = str(uuid4())
            values = {
                "id": result_id,
                "tenant_id": normalized_tenant_id,
                "job_id": normalized_job_id,
                "claim_token": normalized_claim_token,
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
                    tenant_id=normalized_tenant_id,
                    job_id=normalized_job_id,
                    claim_token=normalized_claim_token,
                )
                if raced is not None and raced["envelope_sha256"] == envelope_sha256:
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
