"""Shared enums for the e-GP Intelligence Platform."""

from enum import StrEnum


class ProjectState(StrEnum):
    DISCOVERED = "discovered"
    OPEN_INVITATION = "open_invitation"
    OPEN_CONSULTING = "open_consulting"
    OPEN_PUBLIC_HEARING = "open_public_hearing"
    TOR_DOWNLOADED = "tor_downloaded"
    PRELIM_PRICING_SEEN = "prelim_pricing_seen"
    WINNER_ANNOUNCED = "winner_announced"
    CONTRACT_SIGNED = "contract_signed"
    CLOSED_TIMEOUT_CONSULTING = "closed_timeout_consulting"
    CLOSED_STALE_NO_TOR = "closed_stale_no_tor"
    CLOSED_MANUAL = "closed_manual"
    ERROR = "error"


class ClosedReason(StrEnum):
    WINNER_ANNOUNCED = "winner_announced"
    CONTRACT_SIGNED = "contract_signed"
    CONSULTING_TIMEOUT_30D = "consulting_timeout_30d"
    PRELIM_PRICING = "prelim_pricing"
    STALE_NO_TOR = "stale_no_tor"
    MANUAL = "manual"
    MERGED_DUPLICATE = "merged_duplicate"


class ProcurementType(StrEnum):
    GOODS = "goods"
    SERVICES = "services"
    CONSULTING = "consulting"
    UNKNOWN = "unknown"


class DocumentType(StrEnum):
    INVITATION = "invitation"
    MID_PRICE = "mid_price"
    TOR = "tor"
    OTHER = "other"


class DocumentPhase(StrEnum):
    PUBLIC_HEARING = "public_hearing"
    FINAL = "final"
    UNKNOWN = "unknown"


class DocumentCaptureAttemptStatus(StrEnum):
    ENQUEUED = "enqueued"
    SUCCEEDED = "succeeded"
    NO_DOCUMENTS = "no_documents"
    FAILED = "failed"
    TIMEOUT = "timeout"
    SKIPPED = "skipped"


class DocumentCaptureReason(StrEnum):
    """Structured reason codes for `document_capture_attempts.reason`.

    Replaces free-text reason strings (WS3 arch#3) with a low-cardinality,
    queryable vocabulary aligned with WS2's `CrawlOutcomeReason`. Stored as the
    enum's string value in the existing TEXT column (no migration).
    """

    LIVE_DISCOVERY_METADATA_FIRST = "live_discovery_metadata_first"
    BACKFILL_JOB_CREATED = "backfill_job_created"
    BACKFILL_PROJECT_NOT_REDISCOVERED = "backfill_project_not_rediscovered"
    NO_DOCUMENTS = "no_documents"
    TIMEOUT = "timeout"
    FAILED = "failed"
    PROPOSAL_DEADLINE_PASSED = "proposal_deadline_passed"
    RETRY_EXHAUSTED = "retry_exhausted"


class ArtifactBucket(StrEnum):
    PRICING_ONLY = "pricing_only"
    INVITATION_PLUS_PRICING = "invitation_plus_pricing"
    DRAFT_PLUS_PRICING = "draft_plus_pricing"
    FINAL_TOR_DOWNLOADED = "final_tor_downloaded"
    NO_ARTIFACT_EVIDENCE = "no_artifact_evidence"


class DocumentReviewStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class DocumentReviewAction(StrEnum):
    APPROVE = "approve"
    REJECT = "reject"
    REOPEN = "reopen"


class DocumentReviewEventType(StrEnum):
    CREATED = "created"
    APPROVED = "approved"
    REJECTED = "rejected"
    REOPENED = "reopened"


class CrawlRunStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    PARTIAL = "partial"
    FAILED = "failed"
    CANCELLED = "cancelled"


class CrawlTaskType(StrEnum):
    DISCOVER = "discover"
    UPDATE = "update"
    CLOSE_CHECK = "close_check"
    DOWNLOAD = "download"


class CrawlOutcomeReason(StrEnum):
    """Structured reason codes for a keyword discovery scan outcome.

    Persisted in ``crawl_runs.summary_json`` / ``crawl_tasks.result_json`` and
    used by the WS2 discovery anomaly canary so silent misses cannot hide as a
    plain ``succeeded`` run. Shared vocabulary for telemetry + Prometheus labels.
    """

    OK = "ok"
    KEYWORD_NO_RESULTS = "keyword_no_results"
    NO_ELIGIBLE_ROWS = "no_eligible_rows"
    HEADER_SIGNATURE_DRIFT = "header_signature_drift"
    PROJECT_DETAIL_INVALID = "project_detail_invalid"
    PROJECT_DETAIL_MISSING_REQUIRED_FIELDS = "project_detail_missing_required_fields"


class DiscoveryFailureCode(StrEnum):
    """Stable low-cardinality reasons for discovery dispatch failures."""

    KEYWORD_NO_RESULTS = "keyword_no_results"
    NO_ELIGIBLE_ROWS = "no_eligible_rows"
    PROJECT_DETAIL_INVALID = "project_detail_invalid"
    PROJECT_DETAIL_MISSING_REQUIRED_FIELDS = "project_detail_missing_required_fields"
    LIVE_DISCOVERY_PARTIAL = "live_discovery_partial"
    SEARCH_PAGE_STATE_ERROR = "search_page_state_error"
    WORKER_REPORTED_FAILURE = "worker_reported_failure"
    WORKER_RESULT_INVALID = "worker_result_invalid"
    WORKER_RESULT_MISSING = "worker_result_missing"
    WORKER_EXIT_NONZERO = "worker_exit_nonzero"
    WORKER_TIMEOUT = "worker_timeout"
    WORKER_TERMINATED = "worker_terminated"
    ENTITLEMENT_DENIED = "entitlement_denied"
    DISPATCH_EXCEPTION = "dispatch_exception"
    LEASE_LOST = "lease_lost"


class CrawlerBlockerCode(StrEnum):
    """Shared crawler conditions that stop dispatch before a job claim."""

    AGENT_OFFLINE = "agent_offline"
    DATABASE_UNREACHABLE = "database_unreachable"
    CORRELATION_MISMATCH = "correlation_mismatch"
    CIRCUIT_OPEN = "circuit_open"
    PROFILE_BUSY = "profile_busy"
    PROFILE_WARM_RETRY = "profile_warm_retry"
    PROFILE_OPERATOR_ACTION_REQUIRED = "profile_operator_action_required"


class UserRole(StrEnum):
    OWNER = "owner"
    ADMIN = "admin"
    ANALYST = "analyst"
    VIEWER = "viewer"


class NotificationType(StrEnum):
    NEW_PROJECT = "new_project"
    WINNER_ANNOUNCED = "winner_announced"
    CONTRACT_SIGNED = "contract_signed"
    TOR_CHANGED = "tor_changed"
    RUN_FAILED = "run_failed"
    EXPORT_READY = "export_ready"


class BillingRecordStatus(StrEnum):
    DRAFT = "draft"
    ISSUED = "issued"
    AWAITING_PAYMENT = "awaiting_payment"
    PAYMENT_DETECTED = "payment_detected"
    PAID = "paid"
    FAILED = "failed"
    OVERDUE = "overdue"
    CANCELLED = "cancelled"
    REFUNDED = "refunded"


class BillingPaymentMethod(StrEnum):
    BANK_TRANSFER = "bank_transfer"
    PROMPTPAY_QR = "promptpay_qr"
    CARD = "card"


class BillingPaymentStatus(StrEnum):
    PENDING_RECONCILIATION = "pending_reconciliation"
    RECONCILED = "reconciled"
    REJECTED = "rejected"


class BillingEventType(StrEnum):
    BILLING_RECORD_CREATED = "billing_record_created"
    BILLING_RECORD_STATUS_CHANGED = "billing_record_status_changed"
    PAYMENT_REQUEST_CREATED = "payment_request_created"
    PAYMENT_REQUEST_SETTLED = "payment_request_settled"
    PAYMENT_RECORDED = "payment_recorded"
    PAYMENT_RECONCILED = "payment_reconciled"
    PAYMENT_REJECTED = "payment_rejected"
    SUBSCRIPTION_ACTIVATED = "subscription_activated"


class BillingSubscriptionStatus(StrEnum):
    PENDING_ACTIVATION = "pending_activation"
    ACTIVE = "active"
    EXPIRED = "expired"
    CANCELLED = "cancelled"


class KeywordGroupEffectiveStatus(StrEnum):
    RUNNING = "running"
    PAUSED_BY_USER = "paused_by_user"
    PAUSED_BY_PLAN = "paused_by_plan"
    BLOCKED_QUOTA = "blocked_quota"


class KeywordGroupStatusReason(StrEnum):
    SUBSCRIPTION_INACTIVE = "subscription_inactive"
    OUTSIDE_CURRENT_PLAN_CYCLE = "outside_current_plan_cycle"
    KEYWORD_LIMIT_EXCEEDED = "keyword_limit_exceeded"


class BillingPaymentProvider(StrEnum):
    MOCK_PROMPTPAY = "mock_promptpay"
    PROMPTPAY_MANUAL = "promptpay_manual"
    OPN = "opn"
    STRIPE = "stripe"


class BillingPaymentRequestStatus(StrEnum):
    PENDING = "pending"
    SETTLED = "settled"
    EXPIRED = "expired"
    FAILED = "failed"
    CANCELLED = "cancelled"


class DiscoveryJobStatus(StrEnum):
    """Discovery-job lifecycle states.

    Kept in sync with the ``discovery_jobs_status_check`` CHECK constraint
    (migrations 015 and 034). ``RESULT_RECEIVED`` is the non-claimable state a
    job enters once an agent result has been accepted, so that a lease which is
    later reclaimed cannot have a stale result applied on top of it.
    """

    PENDING = "pending"
    DISPATCHED = "dispatched"
    FAILED = "failed"
    RESULT_RECEIVED = "result_received"


# Discovery-job statuses that represent work still owned by the system: either
# waiting to be claimed/executed, or executed with a result awaiting application.
#
# Every site that answers "is there outstanding work for this tenant / profile /
# keyword?" must use this set rather than testing for PENDING alone. Counting only
# PENDING once RESULT_RECEIVED exists frees a tenant's concurrency budget early and
# lets dedupe paths enqueue a duplicate while the first result sits in the inbox.
IN_FLIGHT_DISCOVERY_JOB_STATUSES: frozenset[DiscoveryJobStatus] = frozenset(
    {DiscoveryJobStatus.PENDING, DiscoveryJobStatus.RESULT_RECEIVED}
)

IN_FLIGHT_DISCOVERY_JOB_STATUS_VALUES: tuple[str, ...] = tuple(
    sorted(status.value for status in IN_FLIGHT_DISCOVERY_JOB_STATUSES)
)


class ExecutionBackend(StrEnum):
    """Which consumer owns a discovery job.

    Partitions the job queue so the legacy external discovery executor and a
    crawler agent can never claim the same row. Defaults to ``LEGACY`` in the
    schema, so introducing the column changes no deployed behaviour.
    """

    LEGACY = "legacy"
    AGENT = "agent"


class AgentContractVersion(StrEnum):
    """Versioned crawler-agent wire contract."""

    V1 = "v1"


class AgentInboxStatus(StrEnum):
    """Durable result-inbox row lifecycle.

    Kept in sync with ``crawler_agent_results_status_check`` (migration 034).
    """

    PENDING = "pending"
    PROCESSING = "processing"
    APPLIED = "applied"
    FAILED = "failed"
    REJECTED = "rejected"


class AgentInboxErrorCode(StrEnum):
    """Typed inbox failure reasons.

    Kept in sync with ``crawler_agent_results_error_code_check`` (migration 034).
    Free-form errors are deliberately not stored here.
    """

    STALE_CLAIM_TOKEN = "stale_claim_token"
    ENVELOPE_INVALID = "envelope_invalid"
    ENVELOPE_CONFLICT = "envelope_conflict"
    CONTRACT_VERSION_UNSUPPORTED = "contract_version_unsupported"
    TENANT_MISMATCH = "tenant_mismatch"
    JOB_NOT_FOUND = "job_not_found"
    APPLY_FAILED_TRANSIENT = "apply_failed_transient"
    APPLY_FAILED_PERMANENT = "apply_failed_permanent"
    PROCESSOR_LEASE_LOST = "processor_lease_lost"
