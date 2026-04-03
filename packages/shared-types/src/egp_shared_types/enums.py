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
