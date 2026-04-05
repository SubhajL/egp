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


class BillingPaymentProvider(StrEnum):
    MOCK_PROMPTPAY = "mock_promptpay"


class BillingPaymentRequestStatus(StrEnum):
    PENDING = "pending"
    SETTLED = "settled"
    EXPIRED = "expired"
    FAILED = "failed"
    CANCELLED = "cancelled"
