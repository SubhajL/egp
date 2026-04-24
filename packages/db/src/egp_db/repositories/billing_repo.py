"""Tenant-scoped billing records and manual bank-transfer reconciliation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from uuid import uuid4

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Index,
    Numeric,
    String,
    Table,
    desc,
    text,
)
from sqlalchemy import Column, insert, select, update
from sqlalchemy.engine import Engine, RowMapping
from sqlalchemy.exc import IntegrityError

from egp_db.connection import DB_METADATA, create_shared_engine
from egp_db.db_utils import UUID_SQL_TYPE, normalize_database_url, normalize_uuid_string
from egp_shared_types.billing_plans import (
    derive_plan_period_end,
    get_billing_plan_definition,
)
from egp_shared_types.enums import (
    BillingEventType,
    BillingPaymentProvider,
    BillingPaymentMethod,
    BillingPaymentRequestStatus,
    BillingPaymentStatus,
    BillingRecordStatus,
    BillingSubscriptionStatus,
)


@dataclass(frozen=True, slots=True)
class BillingRecordRecord:
    id: str
    tenant_id: str
    record_number: str
    plan_code: str
    status: BillingRecordStatus
    billing_period_start: str
    billing_period_end: str
    due_at: str | None
    issued_at: str | None
    paid_at: str | None
    currency: str
    amount_due: str
    reconciled_total: str
    outstanding_balance: str
    upgrade_from_subscription_id: str | None
    upgrade_mode: str
    notes: str | None
    created_at: str
    updated_at: str


@dataclass(frozen=True, slots=True)
class BillingPaymentRecord:
    id: str
    billing_record_id: str
    payment_method: BillingPaymentMethod
    payment_status: BillingPaymentStatus
    amount: str
    currency: str
    reference_code: str | None
    received_at: str
    recorded_at: str
    reconciled_at: str | None
    note: str | None
    recorded_by: str | None
    reconciled_by: str | None


@dataclass(frozen=True, slots=True)
class BillingPaymentRequestRecord:
    id: str
    tenant_id: str
    billing_record_id: str
    provider: BillingPaymentProvider
    payment_method: BillingPaymentMethod
    status: BillingPaymentRequestStatus
    provider_reference: str
    payment_url: str
    qr_payload: str
    qr_svg: str
    amount: str
    currency: str
    expires_at: str | None
    settled_at: str | None
    created_at: str
    updated_at: str


@dataclass(frozen=True, slots=True)
class BillingEventRecord:
    id: str
    billing_record_id: str
    payment_id: str | None
    event_type: BillingEventType
    actor_subject: str | None
    note: str | None
    from_status: str | None
    to_status: str | None
    created_at: str


@dataclass(frozen=True, slots=True)
class BillingSubscriptionRecord:
    id: str
    tenant_id: str
    billing_record_id: str
    plan_code: str
    subscription_status: BillingSubscriptionStatus
    billing_period_start: str
    billing_period_end: str
    keyword_limit: int | None
    activated_at: str
    activated_by_payment_id: str | None
    created_at: str
    updated_at: str


@dataclass(frozen=True, slots=True)
class BillingRecordDetail:
    record: BillingRecordRecord
    payment_requests: list[BillingPaymentRequestRecord]
    payments: list[BillingPaymentRecord]
    events: list[BillingEventRecord]
    subscription: BillingSubscriptionRecord | None


@dataclass(frozen=True, slots=True)
class BillingSummary:
    open_records: int
    awaiting_reconciliation: int
    outstanding_amount: str
    collected_amount: str


@dataclass(frozen=True, slots=True)
class BillingPage:
    items: list[BillingRecordDetail]
    total: int
    limit: int
    offset: int
    summary: BillingSummary


METADATA = DB_METADATA
_MONEY_QUANTUM = Decimal("0.01")
_TERMINAL_BILLING_STATUSES = {
    BillingRecordStatus.PAID,
    BillingRecordStatus.CANCELLED,
    BillingRecordStatus.REFUNDED,
}
_OPEN_UPGRADE_RECORDS_WHERE = text(
    "upgrade_from_subscription_id IS NOT NULL "
    "AND status NOT IN ('paid', 'cancelled', 'refunded')"
)


def _enum_values(enum_type: type) -> str:
    return ", ".join(f"'{member.value}'" for member in enum_type)


BILLING_RECORDS_TABLE = Table(
    "billing_records",
    METADATA,
    Column("id", UUID_SQL_TYPE, primary_key=True),
    Column("tenant_id", UUID_SQL_TYPE, nullable=False),
    Column("record_number", String, nullable=False),
    Column("plan_code", String, nullable=False),
    Column("status", String, nullable=False),
    Column("billing_period_start", Date, nullable=False),
    Column("billing_period_end", Date, nullable=False),
    Column("due_at", DateTime(timezone=True), nullable=True),
    Column("issued_at", DateTime(timezone=True), nullable=True),
    Column("paid_at", DateTime(timezone=True), nullable=True),
    Column("currency", String, nullable=False, default="THB"),
    Column("amount_due", Numeric(18, 2), nullable=False),
    Column("upgrade_from_subscription_id", UUID_SQL_TYPE, nullable=True),
    Column(
        "upgrade_mode",
        String,
        nullable=False,
        default="none",
        server_default=text("'none'"),
    ),
    Column("notes", String, nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
    CheckConstraint(
        f"status IN ({_enum_values(BillingRecordStatus)})",
        name="billing_records_status_check",
    ),
    CheckConstraint(
        "upgrade_mode IN ('none', 'replace_now', 'replace_on_activation')",
        name="billing_records_upgrade_mode_check",
    ),
)

BILLING_PAYMENTS_TABLE = Table(
    "billing_payments",
    METADATA,
    Column("id", UUID_SQL_TYPE, primary_key=True),
    Column("tenant_id", UUID_SQL_TYPE, nullable=False),
    Column(
        "billing_record_id",
        UUID_SQL_TYPE,
        ForeignKey("billing_records.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("payment_method", String, nullable=False),
    Column("payment_status", String, nullable=False),
    Column("amount", Numeric(18, 2), nullable=False),
    Column("currency", String, nullable=False, default="THB"),
    Column("reference_code", String, nullable=True),
    Column("received_at", DateTime(timezone=True), nullable=False),
    Column("recorded_at", DateTime(timezone=True), nullable=False),
    Column("reconciled_at", DateTime(timezone=True), nullable=True),
    Column("note", String, nullable=True),
    Column("recorded_by", String, nullable=True),
    Column("reconciled_by", String, nullable=True),
    Column("updated_at", DateTime(timezone=True), nullable=False),
    CheckConstraint(
        f"payment_method IN ({_enum_values(BillingPaymentMethod)})",
        name="billing_payments_method_check",
    ),
    CheckConstraint(
        f"payment_status IN ({_enum_values(BillingPaymentStatus)})",
        name="billing_payments_status_check",
    ),
)

BILLING_PAYMENT_REQUESTS_TABLE = Table(
    "billing_payment_requests",
    METADATA,
    Column("id", UUID_SQL_TYPE, primary_key=True),
    Column("tenant_id", UUID_SQL_TYPE, nullable=False),
    Column(
        "billing_record_id",
        UUID_SQL_TYPE,
        ForeignKey("billing_records.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("provider", String, nullable=False),
    Column("payment_method", String, nullable=False),
    Column("status", String, nullable=False),
    Column("provider_reference", String, nullable=False),
    Column("payment_url", String, nullable=False),
    Column("qr_payload", String, nullable=False),
    Column("qr_svg", String, nullable=False),
    Column("amount", Numeric(18, 2), nullable=False),
    Column("currency", String, nullable=False, default="THB"),
    Column("expires_at", DateTime(timezone=True), nullable=True),
    Column("settled_at", DateTime(timezone=True), nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
    CheckConstraint(
        f"provider IN ({_enum_values(BillingPaymentProvider)})",
        name="billing_payment_requests_provider_check",
    ),
    CheckConstraint(
        f"payment_method IN ({_enum_values(BillingPaymentMethod)})",
        name="billing_payment_requests_method_check",
    ),
    CheckConstraint(
        f"status IN ({_enum_values(BillingPaymentRequestStatus)})",
        name="billing_payment_requests_status_check",
    ),
    CheckConstraint("amount > 0", name="billing_payment_requests_amount_check"),
)

BILLING_EVENTS_TABLE = Table(
    "billing_events",
    METADATA,
    Column("id", UUID_SQL_TYPE, primary_key=True),
    Column("tenant_id", UUID_SQL_TYPE, nullable=False),
    Column(
        "billing_record_id",
        UUID_SQL_TYPE,
        ForeignKey("billing_records.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column(
        "payment_id",
        UUID_SQL_TYPE,
        ForeignKey("billing_payments.id", ondelete="SET NULL"),
        nullable=True,
    ),
    Column("event_type", String, nullable=False),
    Column("actor_subject", String, nullable=True),
    Column("note", String, nullable=True),
    Column("from_status", String, nullable=True),
    Column("to_status", String, nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False),
    CheckConstraint(
        f"event_type IN ({_enum_values(BillingEventType)})",
        name="billing_events_type_check",
    ),
)

BILLING_PROVIDER_EVENTS_TABLE = Table(
    "billing_provider_events",
    METADATA,
    Column("id", UUID_SQL_TYPE, primary_key=True),
    Column("tenant_id", UUID_SQL_TYPE, nullable=False),
    Column(
        "payment_request_id",
        UUID_SQL_TYPE,
        ForeignKey("billing_payment_requests.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("provider", String, nullable=False),
    Column("provider_event_id", String, nullable=False),
    Column("event_type", String, nullable=False),
    Column("payload_json", String, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    CheckConstraint(
        f"provider IN ({_enum_values(BillingPaymentProvider)})",
        name="billing_provider_events_provider_check",
    ),
)

BILLING_SUBSCRIPTIONS_TABLE = Table(
    "billing_subscriptions",
    METADATA,
    Column("id", UUID_SQL_TYPE, primary_key=True),
    Column("tenant_id", UUID_SQL_TYPE, nullable=False),
    Column(
        "billing_record_id",
        UUID_SQL_TYPE,
        ForeignKey("billing_records.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    ),
    Column("plan_code", String, nullable=False),
    Column("status", String, nullable=False),
    Column("billing_period_start", Date, nullable=False),
    Column("billing_period_end", Date, nullable=False),
    Column("keyword_limit", Integer, nullable=True),
    Column("activated_at", DateTime(timezone=True), nullable=False),
    Column(
        "activated_by_payment_id",
        UUID_SQL_TYPE,
        ForeignKey("billing_payments.id", ondelete="SET NULL"),
        nullable=True,
    ),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
    CheckConstraint(
        "billing_period_end >= billing_period_start",
        name="billing_subscriptions_period_order_check",
    ),
    CheckConstraint(
        f"status IN ({_enum_values(BillingSubscriptionStatus)})",
        name="billing_subscriptions_status_check",
    ),
)

Index(
    "idx_billing_records_tenant_created",
    BILLING_RECORDS_TABLE.c.tenant_id,
    BILLING_RECORDS_TABLE.c.created_at,
)
Index(
    "idx_billing_records_tenant_due_at",
    BILLING_RECORDS_TABLE.c.tenant_id,
    BILLING_RECORDS_TABLE.c.due_at,
)
Index(
    "idx_billing_records_upgrade_from_subscription",
    BILLING_RECORDS_TABLE.c.upgrade_from_subscription_id,
)
Index(
    "uq_billing_records_open_upgrade_per_subscription",
    BILLING_RECORDS_TABLE.c.tenant_id,
    BILLING_RECORDS_TABLE.c.upgrade_from_subscription_id,
    unique=True,
    sqlite_where=_OPEN_UPGRADE_RECORDS_WHERE,
    postgresql_where=_OPEN_UPGRADE_RECORDS_WHERE,
)
Index(
    "idx_billing_payments_tenant_recorded",
    BILLING_PAYMENTS_TABLE.c.tenant_id,
    BILLING_PAYMENTS_TABLE.c.recorded_at,
)
Index(
    "idx_billing_payments_record",
    BILLING_PAYMENTS_TABLE.c.billing_record_id,
    BILLING_PAYMENTS_TABLE.c.payment_status,
)
Index(
    "idx_billing_payment_requests_tenant_created",
    BILLING_PAYMENT_REQUESTS_TABLE.c.tenant_id,
    BILLING_PAYMENT_REQUESTS_TABLE.c.created_at,
)
Index(
    "idx_billing_payment_requests_record",
    BILLING_PAYMENT_REQUESTS_TABLE.c.billing_record_id,
    BILLING_PAYMENT_REQUESTS_TABLE.c.status,
    BILLING_PAYMENT_REQUESTS_TABLE.c.created_at,
)
Index(
    "idx_billing_events_record_created",
    BILLING_EVENTS_TABLE.c.billing_record_id,
    BILLING_EVENTS_TABLE.c.created_at,
)
Index(
    "idx_billing_provider_events_request_created",
    BILLING_PROVIDER_EVENTS_TABLE.c.payment_request_id,
    BILLING_PROVIDER_EVENTS_TABLE.c.created_at,
)
Index(
    "uq_billing_provider_events_provider_event",
    BILLING_PROVIDER_EVENTS_TABLE.c.provider,
    BILLING_PROVIDER_EVENTS_TABLE.c.provider_event_id,
    unique=True,
)
Index(
    "idx_billing_subscriptions_tenant_status",
    BILLING_SUBSCRIPTIONS_TABLE.c.tenant_id,
    BILLING_SUBSCRIPTIONS_TABLE.c.status,
    BILLING_SUBSCRIPTIONS_TABLE.c.billing_period_end,
)
Index(
    "idx_billing_subscriptions_record",
    BILLING_SUBSCRIPTIONS_TABLE.c.billing_record_id,
)


@dataclass(frozen=True, slots=True)
class _BillingRecordRow:
    id: str
    tenant_id: str
    record_number: str
    plan_code: str
    status: BillingRecordStatus
    billing_period_start: str
    billing_period_end: str
    due_at: str | None
    issued_at: str | None
    paid_at: str | None
    currency: str
    amount_due: Decimal
    upgrade_from_subscription_id: str | None
    upgrade_mode: str
    notes: str | None
    created_at: str
    updated_at: str


@dataclass(frozen=True, slots=True)
class _BillingPaymentRequestRow:
    id: str
    tenant_id: str
    billing_record_id: str
    provider: BillingPaymentProvider
    payment_method: BillingPaymentMethod
    status: BillingPaymentRequestStatus
    provider_reference: str
    payment_url: str
    qr_payload: str
    qr_svg: str
    amount: Decimal
    currency: str
    expires_at: str | None
    settled_at: str | None
    created_at: str
    updated_at: str


@dataclass(frozen=True, slots=True)
class _BillingSubscriptionRow:
    id: str
    tenant_id: str
    billing_record_id: str
    plan_code: str
    status: BillingSubscriptionStatus
    billing_period_start: str
    billing_period_end: str
    keyword_limit: int | None
    activated_at: str
    activated_by_payment_id: str | None
    created_at: str
    updated_at: str


def _now() -> datetime:
    return datetime.now(UTC)


def _dt_to_iso(value: datetime | date | None) -> str | None:
    if value is None:
        return None
    return value.isoformat()


def _normalize_amount(value: Decimal | str | float | int) -> Decimal:
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError("invalid billing amount") from exc
    amount = amount.quantize(_MONEY_QUANTUM, rounding=ROUND_HALF_UP)
    if amount < Decimal("0.00"):
        raise ValueError("billing amount must not be negative")
    return amount


def _decimal_to_str(value: Decimal) -> str:
    return f"{value.quantize(_MONEY_QUANTUM, rounding=ROUND_HALF_UP):.2f}"


def _normalize_date(value: str) -> date:
    try:
        return date.fromisoformat(str(value).strip())
    except ValueError as exc:
        raise ValueError("invalid billing date") from exc


def _normalize_datetime(value: str | None) -> datetime | None:
    if value is None:
        return None
    try:
        return datetime.fromisoformat(str(value).strip())
    except ValueError as exc:
        raise ValueError("invalid billing timestamp") from exc


def _subscription_status_for_period(
    *, now: datetime, period_start: date, period_end: date
) -> BillingSubscriptionStatus:
    today = now.date()
    if today < period_start:
        return BillingSubscriptionStatus.PENDING_ACTIVATION
    if today > period_end:
        return BillingSubscriptionStatus.EXPIRED
    return BillingSubscriptionStatus.ACTIVE


def _normalize_record_status(value: BillingRecordStatus | str) -> BillingRecordStatus:
    try:
        return (
            value
            if isinstance(value, BillingRecordStatus)
            else BillingRecordStatus(str(value).strip())
        )
    except ValueError as exc:
        raise ValueError("invalid billing record status") from exc


def _normalize_payment_method(
    value: BillingPaymentMethod | str,
) -> BillingPaymentMethod:
    try:
        return (
            value
            if isinstance(value, BillingPaymentMethod)
            else BillingPaymentMethod(str(value).strip())
        )
    except ValueError as exc:
        raise ValueError("invalid billing payment method") from exc


def _normalize_payment_provider(
    value: BillingPaymentProvider | str,
) -> BillingPaymentProvider:
    try:
        return (
            value
            if isinstance(value, BillingPaymentProvider)
            else BillingPaymentProvider(str(value).strip())
        )
    except ValueError as exc:
        raise ValueError("invalid billing payment provider") from exc


def _normalize_payment_request_status(
    value: BillingPaymentRequestStatus | str,
) -> BillingPaymentRequestStatus:
    try:
        return (
            value
            if isinstance(value, BillingPaymentRequestStatus)
            else BillingPaymentRequestStatus(str(value).strip())
        )
    except ValueError as exc:
        raise ValueError("invalid billing payment request status") from exc


def _normalize_payment_status(
    value: BillingPaymentStatus | str,
) -> BillingPaymentStatus:
    try:
        return (
            value
            if isinstance(value, BillingPaymentStatus)
            else BillingPaymentStatus(str(value).strip())
        )
    except ValueError as exc:
        raise ValueError("invalid billing payment status") from exc


def _normalize_upgrade_mode(value: str | None) -> str:
    normalized = str(value or "none").strip() or "none"
    if normalized not in {"none", "replace_now", "replace_on_activation"}:
        raise ValueError("invalid upgrade mode")
    return normalized


def _subscription_priority(status: BillingSubscriptionStatus) -> int:
    priorities = {
        BillingSubscriptionStatus.ACTIVE: 0,
        BillingSubscriptionStatus.PENDING_ACTIVATION: 1,
        BillingSubscriptionStatus.EXPIRED: 2,
        BillingSubscriptionStatus.CANCELLED: 3,
    }
    return priorities.get(status, 99)


def _select_effective_subscription(
    subscriptions: list[BillingSubscriptionRecord],
) -> BillingSubscriptionRecord | None:
    if not subscriptions:
        return None
    return min(
        subscriptions,
        key=lambda subscription: (
            _subscription_priority(subscription.subscription_status),
            0
            if subscription.subscription_status is BillingSubscriptionStatus.ACTIVE
            else 1,
            -date.fromisoformat(subscription.billing_period_end).toordinal(),
            -date.fromisoformat(subscription.billing_period_start).toordinal(),
            subscription.created_at,
        ),
    )


def _select_upcoming_subscription(
    subscriptions: list[BillingSubscriptionRecord],
) -> BillingSubscriptionRecord | None:
    pending = [
        subscription
        for subscription in subscriptions
        if subscription.subscription_status
        is BillingSubscriptionStatus.PENDING_ACTIVATION
    ]
    if not pending:
        return None
    return min(
        pending,
        key=lambda subscription: (
            date.fromisoformat(subscription.billing_period_start).toordinal(),
            -date.fromisoformat(subscription.billing_period_end).toordinal(),
            subscription.created_at,
        ),
    )


def _billing_record_from_mapping(row: RowMapping) -> _BillingRecordRow:
    return _BillingRecordRow(
        id=str(row["id"]),
        tenant_id=str(row["tenant_id"]),
        record_number=str(row["record_number"]),
        plan_code=str(row["plan_code"]),
        status=BillingRecordStatus(str(row["status"])),
        billing_period_start=_dt_to_iso(row["billing_period_start"]) or "",
        billing_period_end=_dt_to_iso(row["billing_period_end"]) or "",
        due_at=_dt_to_iso(row["due_at"]),
        issued_at=_dt_to_iso(row["issued_at"]),
        paid_at=_dt_to_iso(row["paid_at"]),
        currency=str(row["currency"]),
        amount_due=Decimal(str(row["amount_due"])).quantize(
            _MONEY_QUANTUM, rounding=ROUND_HALF_UP
        ),
        upgrade_from_subscription_id=(
            str(row["upgrade_from_subscription_id"])
            if row["upgrade_from_subscription_id"] is not None
            else None
        ),
        upgrade_mode=_normalize_upgrade_mode(row.get("upgrade_mode")),
        notes=str(row["notes"]) if row["notes"] is not None else None,
        created_at=_dt_to_iso(row["created_at"]) or "",
        updated_at=_dt_to_iso(row["updated_at"]) or "",
    )


def _payment_from_mapping(row: RowMapping) -> BillingPaymentRecord:
    return BillingPaymentRecord(
        id=str(row["id"]),
        billing_record_id=str(row["billing_record_id"]),
        payment_method=BillingPaymentMethod(str(row["payment_method"])),
        payment_status=BillingPaymentStatus(str(row["payment_status"])),
        amount=_decimal_to_str(Decimal(str(row["amount"]))),
        currency=str(row["currency"]),
        reference_code=str(row["reference_code"])
        if row["reference_code"] is not None
        else None,
        received_at=_dt_to_iso(row["received_at"]) or "",
        recorded_at=_dt_to_iso(row["recorded_at"]) or "",
        reconciled_at=_dt_to_iso(row["reconciled_at"]),
        note=str(row["note"]) if row["note"] is not None else None,
        recorded_by=str(row["recorded_by"]) if row["recorded_by"] is not None else None,
        reconciled_by=(
            str(row["reconciled_by"]) if row["reconciled_by"] is not None else None
        ),
    )


def _payment_request_from_mapping(row: RowMapping) -> BillingPaymentRequestRecord:
    return BillingPaymentRequestRecord(
        id=str(row["id"]),
        tenant_id=str(row["tenant_id"]),
        billing_record_id=str(row["billing_record_id"]),
        provider=BillingPaymentProvider(str(row["provider"])),
        payment_method=BillingPaymentMethod(str(row["payment_method"])),
        status=BillingPaymentRequestStatus(str(row["status"])),
        provider_reference=str(row["provider_reference"]),
        payment_url=str(row["payment_url"]),
        qr_payload=str(row["qr_payload"]),
        qr_svg=str(row["qr_svg"]),
        amount=_decimal_to_str(Decimal(str(row["amount"]))),
        currency=str(row["currency"]),
        expires_at=_dt_to_iso(row["expires_at"]),
        settled_at=_dt_to_iso(row["settled_at"]),
        created_at=_dt_to_iso(row["created_at"]) or "",
        updated_at=_dt_to_iso(row["updated_at"]) or "",
    )


def _event_from_mapping(row: RowMapping) -> BillingEventRecord:
    return BillingEventRecord(
        id=str(row["id"]),
        billing_record_id=str(row["billing_record_id"]),
        payment_id=str(row["payment_id"]) if row["payment_id"] is not None else None,
        event_type=BillingEventType(str(row["event_type"])),
        actor_subject=str(row["actor_subject"])
        if row["actor_subject"] is not None
        else None,
        note=str(row["note"]) if row["note"] is not None else None,
        from_status=str(row["from_status"]) if row["from_status"] is not None else None,
        to_status=str(row["to_status"]) if row["to_status"] is not None else None,
        created_at=_dt_to_iso(row["created_at"]) or "",
    )


def _subscription_from_mapping(row: RowMapping) -> BillingSubscriptionRecord:
    period_start = row["billing_period_start"]
    period_end = row["billing_period_end"]
    stored_status = BillingSubscriptionStatus(str(row["status"]))
    effective_status = (
        BillingSubscriptionStatus.CANCELLED
        if stored_status is BillingSubscriptionStatus.CANCELLED
        else _subscription_status_for_period(
            now=_now(),
            period_start=period_start,
            period_end=period_end,
        )
    )
    return BillingSubscriptionRecord(
        id=str(row["id"]),
        tenant_id=str(row["tenant_id"]),
        billing_record_id=str(row["billing_record_id"]),
        plan_code=str(row["plan_code"]),
        subscription_status=effective_status,
        billing_period_start=_dt_to_iso(period_start) or "",
        billing_period_end=_dt_to_iso(period_end) or "",
        keyword_limit=int(row["keyword_limit"])
        if row["keyword_limit"] is not None
        else None,
        activated_at=_dt_to_iso(row["activated_at"]) or "",
        activated_by_payment_id=(
            str(row["activated_by_payment_id"])
            if row["activated_by_payment_id"] is not None
            else None
        ),
        created_at=_dt_to_iso(row["created_at"]) or "",
        updated_at=_dt_to_iso(row["updated_at"]) or "",
    )


def _group_payments(
    payments: list[BillingPaymentRecord],
) -> dict[str, list[BillingPaymentRecord]]:
    grouped: dict[str, list[BillingPaymentRecord]] = {}
    for payment in payments:
        grouped.setdefault(payment.billing_record_id, []).append(payment)
    return grouped


def _group_payment_requests(
    requests: list[BillingPaymentRequestRecord],
) -> dict[str, list[BillingPaymentRequestRecord]]:
    grouped: dict[str, list[BillingPaymentRequestRecord]] = {}
    for request in requests:
        grouped.setdefault(request.billing_record_id, []).append(request)
    return grouped


def _group_events(
    events: list[BillingEventRecord],
) -> dict[str, list[BillingEventRecord]]:
    grouped: dict[str, list[BillingEventRecord]] = {}
    for event in events:
        grouped.setdefault(event.billing_record_id, []).append(event)
    return grouped


def _group_subscriptions(
    subscriptions: list[BillingSubscriptionRecord],
) -> dict[str, BillingSubscriptionRecord]:
    return {
        subscription.billing_record_id: subscription for subscription in subscriptions
    }


def _reconciled_total_for_payments(payments: list[BillingPaymentRecord]) -> Decimal:
    total = Decimal("0.00")
    for payment in payments:
        if payment.payment_status is BillingPaymentStatus.RECONCILED:
            total += Decimal(payment.amount)
    return total.quantize(_MONEY_QUANTUM, rounding=ROUND_HALF_UP)


def _detail_from_row(
    row: _BillingRecordRow,
    payment_requests: list[BillingPaymentRequestRecord],
    payments: list[BillingPaymentRecord],
    events: list[BillingEventRecord],
    subscription: BillingSubscriptionRecord | None,
) -> BillingRecordDetail:
    reconciled_total = _reconciled_total_for_payments(payments)
    outstanding = max(row.amount_due - reconciled_total, Decimal("0.00"))
    record = BillingRecordRecord(
        id=row.id,
        tenant_id=row.tenant_id,
        record_number=row.record_number,
        plan_code=row.plan_code,
        status=row.status,
        billing_period_start=row.billing_period_start,
        billing_period_end=row.billing_period_end,
        due_at=row.due_at,
        issued_at=row.issued_at,
        paid_at=row.paid_at,
        currency=row.currency,
        amount_due=_decimal_to_str(row.amount_due),
        reconciled_total=_decimal_to_str(reconciled_total),
        outstanding_balance=_decimal_to_str(outstanding),
        upgrade_from_subscription_id=row.upgrade_from_subscription_id,
        upgrade_mode=row.upgrade_mode,
        notes=row.notes,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )
    return BillingRecordDetail(
        record=record,
        payment_requests=payment_requests,
        payments=payments,
        events=events,
        subscription=subscription,
    )


class SqlBillingRepository:
    """Relational billing repository for Phase 2 manual reconciliation."""

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
        if bootstrap_schema:
            self._ensure_schema()

    def _ensure_schema(self) -> None:
        METADATA.create_all(self._engine)

    def _load_record_rows(self, *, tenant_id: str) -> list[_BillingRecordRow]:
        with self._engine.begin() as connection:
            rows = (
                connection.execute(
                    select(BILLING_RECORDS_TABLE)
                    .where(
                        BILLING_RECORDS_TABLE.c.tenant_id
                        == normalize_uuid_string(tenant_id)
                    )
                    .order_by(
                        desc(BILLING_RECORDS_TABLE.c.created_at),
                        desc(BILLING_RECORDS_TABLE.c.record_number),
                    )
                )
                .mappings()
                .all()
            )
        return [_billing_record_from_mapping(row) for row in rows]

    def _load_payments_for_records(
        self, record_ids: list[str]
    ) -> list[BillingPaymentRecord]:
        if not record_ids:
            return []
        normalized_ids = [normalize_uuid_string(record_id) for record_id in record_ids]
        with self._engine.begin() as connection:
            rows = (
                connection.execute(
                    select(BILLING_PAYMENTS_TABLE)
                    .where(
                        BILLING_PAYMENTS_TABLE.c.billing_record_id.in_(normalized_ids)
                    )
                    .order_by(BILLING_PAYMENTS_TABLE.c.recorded_at)
                )
                .mappings()
                .all()
            )
        return [_payment_from_mapping(row) for row in rows]

    def _load_payment_requests_for_records(
        self, record_ids: list[str]
    ) -> list[BillingPaymentRequestRecord]:
        if not record_ids:
            return []
        normalized_ids = [normalize_uuid_string(record_id) for record_id in record_ids]
        with self._engine.begin() as connection:
            rows = (
                connection.execute(
                    select(BILLING_PAYMENT_REQUESTS_TABLE)
                    .where(
                        BILLING_PAYMENT_REQUESTS_TABLE.c.billing_record_id.in_(
                            normalized_ids
                        )
                    )
                    .order_by(BILLING_PAYMENT_REQUESTS_TABLE.c.created_at.desc())
                )
                .mappings()
                .all()
            )
        return [_payment_request_from_mapping(row) for row in rows]

    def _load_events_for_records(
        self, record_ids: list[str]
    ) -> list[BillingEventRecord]:
        if not record_ids:
            return []
        normalized_ids = [normalize_uuid_string(record_id) for record_id in record_ids]
        with self._engine.begin() as connection:
            rows = (
                connection.execute(
                    select(BILLING_EVENTS_TABLE)
                    .where(BILLING_EVENTS_TABLE.c.billing_record_id.in_(normalized_ids))
                    .order_by(BILLING_EVENTS_TABLE.c.created_at)
                )
                .mappings()
                .all()
            )
        return [_event_from_mapping(row) for row in rows]

    def _load_subscriptions_for_records(
        self, record_ids: list[str]
    ) -> list[BillingSubscriptionRecord]:
        if not record_ids:
            return []
        normalized_ids = [normalize_uuid_string(record_id) for record_id in record_ids]
        with self._engine.begin() as connection:
            rows = (
                connection.execute(
                    select(BILLING_SUBSCRIPTIONS_TABLE)
                    .where(
                        BILLING_SUBSCRIPTIONS_TABLE.c.billing_record_id.in_(
                            normalized_ids
                        )
                    )
                    .order_by(BILLING_SUBSCRIPTIONS_TABLE.c.created_at.desc())
                )
                .mappings()
                .all()
            )
        return [_subscription_from_mapping(row) for row in rows]

    def _get_record_row_by_id(self, record_id: str) -> _BillingRecordRow | None:
        normalized_record_id = normalize_uuid_string(record_id)
        with self._engine.begin() as connection:
            row = (
                connection.execute(
                    select(BILLING_RECORDS_TABLE)
                    .where(BILLING_RECORDS_TABLE.c.id == normalized_record_id)
                    .limit(1)
                )
                .mappings()
                .one_or_none()
            )
        return _billing_record_from_mapping(row) if row is not None else None

    def _get_payment_request_by_id(
        self, request_id: str
    ) -> BillingPaymentRequestRecord | None:
        normalized_request_id = normalize_uuid_string(request_id)
        with self._engine.begin() as connection:
            row = (
                connection.execute(
                    select(BILLING_PAYMENT_REQUESTS_TABLE)
                    .where(BILLING_PAYMENT_REQUESTS_TABLE.c.id == normalized_request_id)
                    .limit(1)
                )
                .mappings()
                .one_or_none()
            )
        return _payment_request_from_mapping(row) if row is not None else None

    def _get_payment_request_by_provider_reference(
        self,
        *,
        provider: BillingPaymentProvider | str,
        provider_reference: str,
    ) -> BillingPaymentRequestRecord | None:
        normalized_provider = _normalize_payment_provider(provider)
        normalized_reference = str(provider_reference).strip()
        with self._engine.begin() as connection:
            row = (
                connection.execute(
                    select(BILLING_PAYMENT_REQUESTS_TABLE)
                    .where(
                        BILLING_PAYMENT_REQUESTS_TABLE.c.provider
                        == normalized_provider.value,
                        BILLING_PAYMENT_REQUESTS_TABLE.c.provider_reference
                        == normalized_reference,
                    )
                    .limit(1)
                )
                .mappings()
                .one_or_none()
            )
        return _payment_request_from_mapping(row) if row is not None else None

    def _require_record_for_tenant(
        self, *, tenant_id: str, record_id: str
    ) -> _BillingRecordRow:
        row = self._get_record_row_by_id(record_id)
        if row is None:
            raise KeyError(record_id)
        if row.tenant_id != normalize_uuid_string(tenant_id):
            raise PermissionError(record_id)
        return row

    def _require_payment_request_for_tenant(
        self, *, tenant_id: str, request_id: str
    ) -> BillingPaymentRequestRecord:
        request = self._get_payment_request_by_id(request_id)
        if request is None:
            raise KeyError(request_id)
        record = self._require_record_for_tenant(
            tenant_id=tenant_id,
            record_id=request.billing_record_id,
        )
        if record.tenant_id != normalize_uuid_string(tenant_id):
            raise PermissionError(request_id)
        return request

    def _require_payment_for_tenant(
        self, *, tenant_id: str, payment_id: str
    ) -> BillingPaymentRecord:
        normalized_payment_id = normalize_uuid_string(payment_id)
        with self._engine.begin() as connection:
            row = (
                connection.execute(
                    select(BILLING_PAYMENTS_TABLE)
                    .where(BILLING_PAYMENTS_TABLE.c.id == normalized_payment_id)
                    .limit(1)
                )
                .mappings()
                .one_or_none()
            )
        if row is None:
            raise KeyError(payment_id)
        payment = _payment_from_mapping(row)
        record = self._require_record_for_tenant(
            tenant_id=tenant_id, record_id=payment.billing_record_id
        )
        if record.tenant_id != normalize_uuid_string(tenant_id):
            raise PermissionError(payment_id)
        return payment

    def _append_event(
        self,
        connection,
        *,
        tenant_id: str,
        billing_record_id: str,
        payment_id: str | None,
        event_type: BillingEventType,
        actor_subject: str | None,
        note: str | None,
        from_status: str | None,
        to_status: str | None,
    ) -> None:
        connection.execute(
            insert(BILLING_EVENTS_TABLE).values(
                id=str(uuid4()),
                tenant_id=normalize_uuid_string(tenant_id),
                billing_record_id=normalize_uuid_string(billing_record_id),
                payment_id=normalize_uuid_string(payment_id)
                if payment_id is not None
                else None,
                event_type=event_type.value,
                actor_subject=actor_subject,
                note=note,
                from_status=from_status,
                to_status=to_status,
                created_at=_now(),
            )
        )

    def _record_provider_event(
        self,
        connection,
        *,
        tenant_id: str,
        payment_request_id: str,
        provider: BillingPaymentProvider,
        provider_event_id: str,
        event_type: str,
        payload_json: str,
    ) -> bool:
        try:
            connection.execute(
                insert(BILLING_PROVIDER_EVENTS_TABLE).values(
                    id=str(uuid4()),
                    tenant_id=normalize_uuid_string(tenant_id),
                    payment_request_id=normalize_uuid_string(payment_request_id),
                    provider=provider.value,
                    provider_event_id=str(provider_event_id).strip(),
                    event_type=str(event_type).strip(),
                    payload_json=str(payload_json),
                    created_at=_now(),
                )
            )
        except IntegrityError:
            return False
        return True

    def get_billing_record_detail(
        self, *, tenant_id: str, record_id: str
    ) -> BillingRecordDetail | None:
        row = self._get_record_row_by_id(record_id)
        if row is None or row.tenant_id != normalize_uuid_string(tenant_id):
            return None
        payment_requests = self._load_payment_requests_for_records([row.id])
        payments = self._load_payments_for_records([row.id])
        events = self._load_events_for_records([row.id])
        subscriptions = self._load_subscriptions_for_records([row.id])
        return _detail_from_row(
            row,
            payment_requests,
            payments,
            events,
            subscriptions[0] if subscriptions else None,
        )

    def get_payment_request_detail(
        self, *, tenant_id: str, request_id: str
    ) -> BillingPaymentRequestRecord | None:
        try:
            return self._require_payment_request_for_tenant(
                tenant_id=tenant_id,
                request_id=request_id,
            )
        except (KeyError, PermissionError):
            return None

    def require_billing_record_detail(
        self, *, tenant_id: str, record_id: str
    ) -> BillingRecordDetail:
        self._require_record_for_tenant(tenant_id=tenant_id, record_id=record_id)
        detail = self.get_billing_record_detail(
            tenant_id=tenant_id, record_id=record_id
        )
        if detail is None:
            raise KeyError(record_id)
        return detail

    def require_payment_request_detail(
        self, *, tenant_id: str, request_id: str
    ) -> BillingPaymentRequestRecord:
        return self._require_payment_request_for_tenant(
            tenant_id=tenant_id,
            request_id=request_id,
        )

    def get_payment_request_by_provider_reference(
        self,
        *,
        provider: BillingPaymentProvider | str,
        provider_reference: str,
    ) -> BillingPaymentRequestRecord | None:
        return self._get_payment_request_by_provider_reference(
            provider=provider,
            provider_reference=provider_reference,
        )

    def list_subscriptions_for_tenant(
        self, *, tenant_id: str
    ) -> list[BillingSubscriptionRecord]:
        normalized_tenant_id = normalize_uuid_string(tenant_id)
        with self._engine.connect() as connection:
            rows = (
                connection.execute(
                    select(BILLING_SUBSCRIPTIONS_TABLE)
                    .where(
                        BILLING_SUBSCRIPTIONS_TABLE.c.tenant_id == normalized_tenant_id
                    )
                    .order_by(
                        BILLING_SUBSCRIPTIONS_TABLE.c.billing_period_end.desc(),
                        BILLING_SUBSCRIPTIONS_TABLE.c.billing_period_start.desc(),
                        BILLING_SUBSCRIPTIONS_TABLE.c.created_at.desc(),
                    )
                )
                .mappings()
                .all()
            )
        return [_subscription_from_mapping(row) for row in rows]

    def get_effective_subscription_for_tenant(
        self, *, tenant_id: str
    ) -> BillingSubscriptionRecord | None:
        return _select_effective_subscription(
            self.list_subscriptions_for_tenant(tenant_id=tenant_id)
        )

    def _get_open_upgrade_record_id(
        self,
        *,
        tenant_id: str,
        subscription_id: str,
    ) -> str | None:
        with self._engine.begin() as connection:
            row = (
                connection.execute(
                    select(BILLING_RECORDS_TABLE.c.id)
                    .where(
                        BILLING_RECORDS_TABLE.c.tenant_id
                        == normalize_uuid_string(tenant_id),
                        BILLING_RECORDS_TABLE.c.upgrade_from_subscription_id
                        == normalize_uuid_string(subscription_id),
                        BILLING_RECORDS_TABLE.c.status.not_in(
                            [status.value for status in _TERMINAL_BILLING_STATUSES]
                        ),
                    )
                    .order_by(BILLING_RECORDS_TABLE.c.created_at.desc())
                    .limit(1)
                )
                .mappings()
                .one_or_none()
            )
        if row is None:
            return None
        return str(row["id"])

    def activate_free_trial_subscription(
        self,
        *,
        tenant_id: str,
        actor_subject: str | None = None,
        note: str | None = None,
    ) -> BillingSubscriptionRecord:
        normalized_tenant_id = normalize_uuid_string(tenant_id)
        plan_definition = get_billing_plan_definition("free_trial")
        if plan_definition is None:
            raise ValueError("free_trial plan is not configured")
        now = _now()
        period_start = now.date()
        period_end = period_start + timedelta(
            days=(plan_definition.duration_days or 1) - 1
        )
        with self._engine.begin() as connection:
            existing_rows = (
                connection.execute(
                    select(BILLING_SUBSCRIPTIONS_TABLE)
                    .where(
                        BILLING_SUBSCRIPTIONS_TABLE.c.tenant_id == normalized_tenant_id
                    )
                    .order_by(BILLING_SUBSCRIPTIONS_TABLE.c.created_at.desc())
                )
                .mappings()
                .all()
            )
            for row in existing_rows:
                subscription = _subscription_from_mapping(row)
                if subscription.plan_code == "free_trial":
                    raise ValueError("free trial already used for tenant")
                if subscription.subscription_status is BillingSubscriptionStatus.ACTIVE:
                    raise ValueError("tenant already has an active subscription")

            record_id = str(uuid4())
            subscription_id = str(uuid4())
            record_number = f"TRIAL-{record_id[:8].upper()}"
            connection.execute(
                insert(BILLING_RECORDS_TABLE).values(
                    id=record_id,
                    tenant_id=normalized_tenant_id,
                    record_number=record_number,
                    plan_code="free_trial",
                    status=BillingRecordStatus.PAID.value,
                    billing_period_start=period_start,
                    billing_period_end=period_end,
                    currency=plan_definition.currency,
                    amount_due=Decimal("0.00"),
                    due_at=None,
                    issued_at=now,
                    paid_at=now,
                    notes=note or "Free trial activation",
                    created_at=now,
                    updated_at=now,
                )
            )
            self._append_event(
                connection,
                tenant_id=tenant_id,
                billing_record_id=record_id,
                payment_id=None,
                event_type=BillingEventType.BILLING_RECORD_CREATED,
                actor_subject=actor_subject,
                note=note or "Free trial activation",
                from_status=None,
                to_status=BillingRecordStatus.PAID.value,
            )
            connection.execute(
                insert(BILLING_SUBSCRIPTIONS_TABLE).values(
                    id=subscription_id,
                    tenant_id=normalized_tenant_id,
                    billing_record_id=record_id,
                    plan_code="free_trial",
                    status=BillingSubscriptionStatus.ACTIVE.value,
                    billing_period_start=period_start,
                    billing_period_end=period_end,
                    keyword_limit=plan_definition.keyword_limit,
                    activated_at=now,
                    activated_by_payment_id=None,
                    created_at=now,
                    updated_at=now,
                )
            )
            self._append_event(
                connection,
                tenant_id=tenant_id,
                billing_record_id=record_id,
                payment_id=None,
                event_type=BillingEventType.SUBSCRIPTION_ACTIVATED,
                actor_subject=actor_subject,
                note=note or "Free trial activation",
                from_status=None,
                to_status=BillingSubscriptionStatus.ACTIVE.value,
            )

        detail = self.require_billing_record_detail(
            tenant_id=tenant_id, record_id=record_id
        )
        if detail.subscription is None:
            raise RuntimeError("free trial subscription activation failed")
        return detail.subscription

    def list_billing_records(
        self, *, tenant_id: str, limit: int = 50, offset: int = 0
    ) -> BillingPage:
        normalized_limit = max(1, min(int(limit), 200))
        normalized_offset = max(0, int(offset))
        all_rows = self._load_record_rows(tenant_id=tenant_id)
        all_record_ids = [row.id for row in all_rows]
        all_payments = self._load_payments_for_records(all_record_ids)
        all_payments_by_record = _group_payments(all_payments)

        collected_amount = sum(
            (
                Decimal(payment.amount)
                for payment in all_payments
                if payment.payment_status is BillingPaymentStatus.RECONCILED
            ),
            Decimal("0.00"),
        ).quantize(_MONEY_QUANTUM, rounding=ROUND_HALF_UP)
        awaiting_reconciliation = sum(
            1
            for payment in all_payments
            if payment.payment_status is BillingPaymentStatus.PENDING_RECONCILIATION
        )
        outstanding_amount = Decimal("0.00")
        open_records = 0
        for row in all_rows:
            reconciled_total = _reconciled_total_for_payments(
                all_payments_by_record.get(row.id, [])
            )
            outstanding_amount += max(
                row.amount_due - reconciled_total, Decimal("0.00")
            )
            if row.status not in _TERMINAL_BILLING_STATUSES:
                open_records += 1

        page_rows = all_rows[normalized_offset : normalized_offset + normalized_limit]
        page_ids = [row.id for row in page_rows]
        page_requests_by_record = _group_payment_requests(
            self._load_payment_requests_for_records(page_ids)
        )
        page_payments_by_record = _group_payments(
            self._load_payments_for_records(page_ids)
        )
        page_events_by_record = _group_events(self._load_events_for_records(page_ids))
        page_subscriptions_by_record = _group_subscriptions(
            self._load_subscriptions_for_records(page_ids)
        )
        details = [
            _detail_from_row(
                row,
                page_requests_by_record.get(row.id, []),
                page_payments_by_record.get(row.id, []),
                page_events_by_record.get(row.id, []),
                page_subscriptions_by_record.get(row.id),
            )
            for row in page_rows
        ]
        return BillingPage(
            items=details,
            total=len(all_rows),
            limit=normalized_limit,
            offset=normalized_offset,
            summary=BillingSummary(
                open_records=open_records,
                awaiting_reconciliation=awaiting_reconciliation,
                outstanding_amount=_decimal_to_str(outstanding_amount),
                collected_amount=_decimal_to_str(collected_amount),
            ),
        )

    def has_overdue_billing_records(self, *, tenant_id: str) -> bool:
        normalized_tenant_id = normalize_uuid_string(tenant_id)
        with self._engine.connect() as connection:
            row = (
                connection.execute(
                    select(BILLING_RECORDS_TABLE.c.id)
                    .where(
                        BILLING_RECORDS_TABLE.c.tenant_id == normalized_tenant_id,
                        BILLING_RECORDS_TABLE.c.status == BillingRecordStatus.OVERDUE.value,
                    )
                    .limit(1)
                )
                .first()
            )
        return row is not None

    def create_payment_request(
        self,
        *,
        tenant_id: str,
        billing_record_id: str,
        provider: BillingPaymentProvider | str,
        payment_method: BillingPaymentMethod | str,
        status: BillingPaymentRequestStatus | str,
        provider_reference: str,
        payment_url: str,
        qr_payload: str,
        qr_svg: str,
        amount: Decimal | str | float | int,
        currency: str,
        expires_at: str | None,
        actor_subject: str | None = None,
        note: str | None = None,
    ) -> BillingRecordDetail:
        record = self._require_record_for_tenant(
            tenant_id=tenant_id,
            record_id=billing_record_id,
        )
        normalized_provider = _normalize_payment_provider(provider)
        normalized_method = _normalize_payment_method(payment_method)
        normalized_status = _normalize_payment_request_status(status)
        normalized_amount = _normalize_amount(amount)
        normalized_expires_at = _normalize_datetime(expires_at)
        request_id = str(uuid4())
        now = _now()
        with self._engine.begin() as connection:
            connection.execute(
                insert(BILLING_PAYMENT_REQUESTS_TABLE).values(
                    id=request_id,
                    tenant_id=record.tenant_id,
                    billing_record_id=record.id,
                    provider=normalized_provider.value,
                    payment_method=normalized_method.value,
                    status=normalized_status.value,
                    provider_reference=str(provider_reference).strip(),
                    payment_url=str(payment_url).strip(),
                    qr_payload=str(qr_payload),
                    qr_svg=str(qr_svg),
                    amount=normalized_amount,
                    currency=str(currency).strip() or "THB",
                    expires_at=normalized_expires_at,
                    settled_at=None,
                    created_at=now,
                    updated_at=now,
                )
            )
            self._append_event(
                connection,
                tenant_id=tenant_id,
                billing_record_id=record.id,
                payment_id=None,
                event_type=BillingEventType.PAYMENT_REQUEST_CREATED,
                actor_subject=actor_subject,
                note=note,
                from_status=record.status.value,
                to_status=normalized_status.value,
            )

        detail = self.get_billing_record_detail(
            tenant_id=tenant_id,
            record_id=record.id,
        )
        if detail is None:
            raise KeyError(record.id)
        return detail

    def record_provider_callback(
        self,
        *,
        tenant_id: str,
        payment_request_id: str,
        provider: BillingPaymentProvider | str,
        provider_event_id: str,
        event_type: str,
        payload_json: str,
    ) -> bool:
        payment_request = self._require_payment_request_for_tenant(
            tenant_id=tenant_id,
            request_id=payment_request_id,
        )
        normalized_provider = _normalize_payment_provider(provider)
        with self._engine.begin() as connection:
            return self._record_provider_event(
                connection,
                tenant_id=tenant_id,
                payment_request_id=payment_request.id,
                provider=normalized_provider,
                provider_event_id=provider_event_id,
                event_type=event_type,
                payload_json=payload_json,
            )

    def create_billing_record(
        self,
        *,
        tenant_id: str,
        record_number: str,
        plan_code: str,
        status: BillingRecordStatus | str,
        billing_period_start: str,
        billing_period_end: str,
        amount_due: Decimal | str | float | int,
        currency: str = "THB",
        due_at: str | None = None,
        issued_at: str | None = None,
        upgrade_from_subscription_id: str | None = None,
        upgrade_mode: str = "none",
        notes: str | None = None,
        actor_subject: str | None = None,
    ) -> BillingRecordDetail:
        normalized_status = _normalize_record_status(status)
        normalized_start = _normalize_date(billing_period_start)
        normalized_end = _normalize_date(billing_period_end)
        if normalized_end < normalized_start:
            raise ValueError("billing period end must not be before start")
        normalized_amount = _normalize_amount(amount_due)
        normalized_due_at = _normalize_datetime(due_at)
        normalized_issued_at = _normalize_datetime(issued_at)
        normalized_upgrade_from_subscription_id = (
            normalize_uuid_string(upgrade_from_subscription_id)
            if upgrade_from_subscription_id is not None
            else None
        )
        normalized_upgrade_mode = _normalize_upgrade_mode(upgrade_mode)
        if (
            normalized_upgrade_mode == "none"
            and normalized_upgrade_from_subscription_id is not None
        ):
            raise ValueError("upgrade mode is required when upgrade source is provided")
        if (
            normalized_upgrade_mode != "none"
            and normalized_upgrade_from_subscription_id is None
        ):
            raise ValueError("upgrade source subscription is required")
        if (
            normalized_status
            in {
                BillingRecordStatus.ISSUED,
                BillingRecordStatus.AWAITING_PAYMENT,
            }
            and normalized_issued_at is None
        ):
            normalized_issued_at = _now()
        now = _now()
        record_id = str(uuid4())

        try:
            with self._engine.begin() as connection:
                connection.execute(
                    insert(BILLING_RECORDS_TABLE).values(
                        id=record_id,
                        tenant_id=normalize_uuid_string(tenant_id),
                        record_number=str(record_number).strip(),
                        plan_code=str(plan_code).strip(),
                        status=normalized_status.value,
                        billing_period_start=normalized_start,
                        billing_period_end=normalized_end,
                        due_at=normalized_due_at,
                        issued_at=normalized_issued_at,
                        paid_at=None,
                        currency=str(currency).strip() or "THB",
                        amount_due=normalized_amount,
                        upgrade_from_subscription_id=normalized_upgrade_from_subscription_id,
                        upgrade_mode=normalized_upgrade_mode,
                        notes=str(notes).strip() if notes else None,
                        created_at=now,
                        updated_at=now,
                    )
                )
                self._append_event(
                    connection,
                    tenant_id=tenant_id,
                    billing_record_id=record_id,
                    payment_id=None,
                    event_type=BillingEventType.BILLING_RECORD_CREATED,
                    actor_subject=actor_subject,
                    note=notes,
                    from_status=None,
                    to_status=normalized_status.value,
                )
        except IntegrityError as exc:
            if (
                normalized_upgrade_from_subscription_id is not None
                and normalized_status not in _TERMINAL_BILLING_STATUSES
                and self._get_open_upgrade_record_id(
                    tenant_id=tenant_id,
                    subscription_id=normalized_upgrade_from_subscription_id,
                )
                is not None
            ):
                raise ValueError(
                    "upgrade already in progress for subscription"
                ) from exc
            raise

        detail = self.get_billing_record_detail(
            tenant_id=tenant_id, record_id=record_id
        )
        if detail is None:
            raise KeyError(record_id)
        return detail

    def create_upgrade_billing_record(
        self,
        *,
        tenant_id: str,
        target_plan_code: str,
        billing_period_start: str,
        amount_due: Decimal | str | float | int | None = None,
        record_number: str,
        notes: str | None = None,
        actor_subject: str | None = None,
    ) -> BillingRecordDetail:
        current_subscription = self.get_effective_subscription_for_tenant(
            tenant_id=tenant_id
        )
        if current_subscription is None:
            raise ValueError("active or pending subscription required for upgrade")
        if current_subscription.subscription_status not in {
            BillingSubscriptionStatus.ACTIVE,
            BillingSubscriptionStatus.PENDING_ACTIVATION,
        }:
            raise ValueError("active or pending subscription required for upgrade")

        normalized_target_plan_code = str(target_plan_code).strip()
        allowed_transitions = {
            ("free_trial", "one_time_search_pack"),
            ("free_trial", "monthly_membership"),
            ("one_time_search_pack", "monthly_membership"),
        }
        if (
            current_subscription.plan_code,
            normalized_target_plan_code,
        ) not in allowed_transitions:
            raise ValueError("unsupported subscription upgrade")

        target_plan_definition = get_billing_plan_definition(
            normalized_target_plan_code
        )
        if target_plan_definition is None:
            raise ValueError("unsupported subscription upgrade")

        period_start = _normalize_date(billing_period_start)
        upgrade_mode = (
            "replace_on_activation" if period_start > _now().date() else "replace_now"
        )

        if (
            self._get_open_upgrade_record_id(
                tenant_id=tenant_id,
                subscription_id=current_subscription.id,
            )
            is not None
        ):
            raise ValueError("upgrade already in progress for subscription")

        period_end = derive_plan_period_end(
            target_plan_definition,
            billing_period_start=period_start,
        )
        return self.create_billing_record(
            tenant_id=tenant_id,
            record_number=record_number,
            plan_code=target_plan_definition.code,
            status=BillingRecordStatus.AWAITING_PAYMENT,
            billing_period_start=period_start.isoformat(),
            billing_period_end=period_end.isoformat(),
            amount_due=(
                target_plan_definition.amount_due if amount_due is None else amount_due
            ),
            currency=target_plan_definition.currency,
            due_at=None,
            issued_at=_now().isoformat(),
            upgrade_from_subscription_id=current_subscription.id,
            upgrade_mode=upgrade_mode,
            notes=notes,
            actor_subject=actor_subject,
        )

    def transition_billing_record_status(
        self,
        *,
        tenant_id: str,
        billing_record_id: str,
        status: BillingRecordStatus | str,
        note: str | None = None,
        actor_subject: str | None = None,
    ) -> BillingRecordDetail:
        record_before = self._require_record_for_tenant(
            tenant_id=tenant_id,
            record_id=billing_record_id,
        )
        target_status = _normalize_record_status(status)
        if target_status is record_before.status:
            detail = self.get_billing_record_detail(
                tenant_id=tenant_id,
                record_id=record_before.id,
            )
            if detail is None:
                raise KeyError(record_before.id)
            return detail

        allowed_transitions = {
            BillingRecordStatus.DRAFT: {
                BillingRecordStatus.ISSUED,
                BillingRecordStatus.CANCELLED,
            },
            BillingRecordStatus.ISSUED: {
                BillingRecordStatus.AWAITING_PAYMENT,
                BillingRecordStatus.CANCELLED,
            },
            BillingRecordStatus.AWAITING_PAYMENT: {
                BillingRecordStatus.OVERDUE,
                BillingRecordStatus.CANCELLED,
                BillingRecordStatus.FAILED,
            },
            BillingRecordStatus.OVERDUE: {
                BillingRecordStatus.AWAITING_PAYMENT,
                BillingRecordStatus.CANCELLED,
                BillingRecordStatus.FAILED,
            },
            BillingRecordStatus.FAILED: {
                BillingRecordStatus.AWAITING_PAYMENT,
                BillingRecordStatus.CANCELLED,
            },
            BillingRecordStatus.PAYMENT_DETECTED: {
                BillingRecordStatus.AWAITING_PAYMENT,
                BillingRecordStatus.CANCELLED,
            },
        }
        if target_status not in allowed_transitions.get(record_before.status, set()):
            raise ValueError(
                f"cannot transition billing record from {record_before.status.value} to {target_status.value}"
            )

        now = _now()
        issued_at = record_before.issued_at
        if (
            target_status
            in {
                BillingRecordStatus.ISSUED,
                BillingRecordStatus.AWAITING_PAYMENT,
            }
            and issued_at is None
        ):
            issued_at = now.isoformat()

        with self._engine.begin() as connection:
            connection.execute(
                update(BILLING_RECORDS_TABLE)
                .where(
                    BILLING_RECORDS_TABLE.c.id
                    == normalize_uuid_string(record_before.id)
                )
                .values(
                    status=target_status.value,
                    issued_at=_normalize_datetime(issued_at),
                    updated_at=now,
                )
            )
            self._append_event(
                connection,
                tenant_id=tenant_id,
                billing_record_id=record_before.id,
                payment_id=None,
                event_type=BillingEventType.BILLING_RECORD_STATUS_CHANGED,
                actor_subject=actor_subject,
                note=note,
                from_status=record_before.status.value,
                to_status=target_status.value,
            )

        detail = self.get_billing_record_detail(
            tenant_id=tenant_id,
            record_id=record_before.id,
        )
        if detail is None:
            raise KeyError(record_before.id)
        return detail

    def update_payment_request_status(
        self,
        *,
        tenant_id: str,
        payment_request_id: str,
        status: BillingPaymentRequestStatus | str,
        settled_at: str | None = None,
        actor_subject: str | None = None,
        note: str | None = None,
    ) -> BillingRecordDetail:
        request_before = self._require_payment_request_for_tenant(
            tenant_id=tenant_id,
            request_id=payment_request_id,
        )
        target_status = _normalize_payment_request_status(status)
        if request_before.status is target_status:
            detail = self.get_billing_record_detail(
                tenant_id=tenant_id,
                record_id=request_before.billing_record_id,
            )
            if detail is None:
                raise KeyError(request_before.billing_record_id)
            return detail
        record = self._require_record_for_tenant(
            tenant_id=tenant_id,
            record_id=request_before.billing_record_id,
        )
        now = _now()
        resolved_settled_at = _normalize_datetime(settled_at)
        with self._engine.begin() as connection:
            connection.execute(
                update(BILLING_PAYMENT_REQUESTS_TABLE)
                .where(
                    BILLING_PAYMENT_REQUESTS_TABLE.c.id
                    == normalize_uuid_string(payment_request_id)
                )
                .values(
                    status=target_status.value,
                    settled_at=resolved_settled_at,
                    updated_at=now,
                )
            )
            if target_status is BillingPaymentRequestStatus.SETTLED:
                self._append_event(
                    connection,
                    tenant_id=tenant_id,
                    billing_record_id=record.id,
                    payment_id=None,
                    event_type=BillingEventType.PAYMENT_REQUEST_SETTLED,
                    actor_subject=actor_subject,
                    note=note,
                    from_status=request_before.status.value,
                    to_status=target_status.value,
                )
        detail = self.get_billing_record_detail(
            tenant_id=tenant_id,
            record_id=request_before.billing_record_id,
        )
        if detail is None:
            raise KeyError(request_before.billing_record_id)
        return detail

    def record_payment(
        self,
        *,
        tenant_id: str,
        billing_record_id: str,
        payment_method: BillingPaymentMethod | str,
        amount: Decimal | str | float | int,
        currency: str = "THB",
        reference_code: str | None = None,
        received_at: str,
        note: str | None = None,
        actor_subject: str | None = None,
    ) -> BillingPaymentRecord:
        record = self._require_record_for_tenant(
            tenant_id=tenant_id, record_id=billing_record_id
        )
        normalized_method = _normalize_payment_method(payment_method)
        normalized_amount = _normalize_amount(amount)
        normalized_received_at = _normalize_datetime(received_at)
        if normalized_received_at is None:
            raise ValueError("received_at is required")
        now = _now()
        payment_id = str(uuid4())
        with self._engine.begin() as connection:
            connection.execute(
                insert(BILLING_PAYMENTS_TABLE).values(
                    id=payment_id,
                    tenant_id=record.tenant_id,
                    billing_record_id=record.id,
                    payment_method=normalized_method.value,
                    payment_status=BillingPaymentStatus.PENDING_RECONCILIATION.value,
                    amount=normalized_amount,
                    currency=str(currency).strip() or "THB",
                    reference_code=str(reference_code).strip()
                    if reference_code
                    else None,
                    received_at=normalized_received_at,
                    recorded_at=now,
                    reconciled_at=None,
                    note=str(note).strip() if note else None,
                    recorded_by=actor_subject,
                    reconciled_by=None,
                    updated_at=now,
                )
            )
            self._append_event(
                connection,
                tenant_id=tenant_id,
                billing_record_id=record.id,
                payment_id=payment_id,
                event_type=BillingEventType.PAYMENT_RECORDED,
                actor_subject=actor_subject,
                note=note,
                from_status=record.status.value,
                to_status=record.status.value,
            )
        payment = self._require_payment_for_tenant(
            tenant_id=tenant_id, payment_id=payment_id
        )
        return payment

    def record_bank_transfer_payment(
        self,
        *,
        tenant_id: str,
        billing_record_id: str,
        payment_method: BillingPaymentMethod | str,
        amount: Decimal | str | float | int,
        currency: str = "THB",
        reference_code: str | None = None,
        received_at: str,
        note: str | None = None,
        actor_subject: str | None = None,
    ) -> BillingPaymentRecord:
        return self.record_payment(
            tenant_id=tenant_id,
            billing_record_id=billing_record_id,
            payment_method=payment_method,
            amount=amount,
            currency=currency,
            reference_code=reference_code,
            received_at=received_at,
            note=note,
            actor_subject=actor_subject,
        )

    def reconcile_payment(
        self,
        *,
        tenant_id: str,
        payment_id: str,
        status: BillingPaymentStatus | str,
        note: str | None = None,
        actor_subject: str | None = None,
    ) -> BillingRecordDetail:
        normalized_payment = self._require_payment_for_tenant(
            tenant_id=tenant_id, payment_id=payment_id
        )
        target_status = _normalize_payment_status(status)
        if (
            normalized_payment.payment_status
            is not BillingPaymentStatus.PENDING_RECONCILIATION
        ):
            if normalized_payment.payment_status is target_status:
                detail = self.get_billing_record_detail(
                    tenant_id=tenant_id,
                    record_id=normalized_payment.billing_record_id,
                )
                if detail is None:
                    raise KeyError(normalized_payment.billing_record_id)
                return detail
            raise ValueError("payment is already reconciled")
        if target_status is BillingPaymentStatus.PENDING_RECONCILIATION:
            raise ValueError("payment reconciliation status must be final")

        record_before = self._require_record_for_tenant(
            tenant_id=tenant_id, record_id=normalized_payment.billing_record_id
        )
        now = _now()

        with self._engine.begin() as connection:
            connection.execute(
                update(BILLING_PAYMENTS_TABLE)
                .where(BILLING_PAYMENTS_TABLE.c.id == normalize_uuid_string(payment_id))
                .values(
                    payment_status=target_status.value,
                    reconciled_at=now,
                    reconciled_by=actor_subject,
                    note=str(note).strip() if note else normalized_payment.note,
                    updated_at=now,
                )
            )

            record_after_status = record_before.status
            paid_at = record_before.paid_at
            if target_status is BillingPaymentStatus.RECONCILED:
                payment_rows = (
                    connection.execute(
                        select(BILLING_PAYMENTS_TABLE)
                        .where(
                            BILLING_PAYMENTS_TABLE.c.billing_record_id
                            == normalize_uuid_string(record_before.id)
                        )
                        .order_by(BILLING_PAYMENTS_TABLE.c.recorded_at)
                    )
                    .mappings()
                    .all()
                )
                payments_after = [_payment_from_mapping(row) for row in payment_rows]
                reconciled_total = _reconciled_total_for_payments(payments_after)
                amount_due = record_before.amount_due
                record_after_status = (
                    BillingRecordStatus.PAID
                    if reconciled_total >= amount_due
                    else BillingRecordStatus.PAYMENT_DETECTED
                )
                paid_at = (
                    now.isoformat()
                    if record_after_status is BillingRecordStatus.PAID
                    else None
                )
                connection.execute(
                    update(BILLING_RECORDS_TABLE)
                    .where(
                        BILLING_RECORDS_TABLE.c.id
                        == normalize_uuid_string(record_before.id)
                    )
                    .values(
                        status=record_after_status.value,
                        paid_at=_normalize_datetime(paid_at),
                        updated_at=now,
                    )
                )
            self._append_event(
                connection,
                tenant_id=tenant_id,
                billing_record_id=record_before.id,
                payment_id=payment_id,
                event_type=(
                    BillingEventType.PAYMENT_RECONCILED
                    if target_status is BillingPaymentStatus.RECONCILED
                    else BillingEventType.PAYMENT_REJECTED
                ),
                actor_subject=actor_subject,
                note=note,
                from_status=record_before.status.value,
                to_status=record_after_status.value,
            )
            if (
                target_status is BillingPaymentStatus.RECONCILED
                and record_after_status is BillingRecordStatus.PAID
            ):
                existing_subscription_row = (
                    connection.execute(
                        select(BILLING_SUBSCRIPTIONS_TABLE)
                        .where(
                            BILLING_SUBSCRIPTIONS_TABLE.c.billing_record_id
                            == normalize_uuid_string(record_before.id)
                        )
                        .limit(1)
                    )
                    .mappings()
                    .one_or_none()
                )
                if existing_subscription_row is None:
                    plan_definition = get_billing_plan_definition(
                        record_before.plan_code
                    )
                    period_start = date.fromisoformat(
                        record_before.billing_period_start
                    )
                    period_end = date.fromisoformat(record_before.billing_period_end)
                    subscription_status = _subscription_status_for_period(
                        now=now,
                        period_start=period_start,
                        period_end=period_end,
                    )
                    subscription_id = str(uuid4())
                    connection.execute(
                        insert(BILLING_SUBSCRIPTIONS_TABLE).values(
                            id=subscription_id,
                            tenant_id=normalize_uuid_string(tenant_id),
                            billing_record_id=normalize_uuid_string(record_before.id),
                            plan_code=record_before.plan_code,
                            status=subscription_status.value,
                            billing_period_start=period_start,
                            billing_period_end=period_end,
                            keyword_limit=(
                                plan_definition.keyword_limit
                                if plan_definition is not None
                                else None
                            ),
                            activated_at=now,
                            activated_by_payment_id=normalize_uuid_string(payment_id),
                            created_at=now,
                            updated_at=now,
                        )
                    )
                    self._append_event(
                        connection,
                        tenant_id=tenant_id,
                        billing_record_id=record_before.id,
                        payment_id=payment_id,
                        event_type=BillingEventType.SUBSCRIPTION_ACTIVATED,
                        actor_subject=actor_subject,
                        note=note,
                        from_status=None,
                        to_status=subscription_status.value,
                    )
                    if (
                        record_before.upgrade_mode == "replace_now"
                        and record_before.upgrade_from_subscription_id is not None
                    ):
                        connection.execute(
                            update(BILLING_SUBSCRIPTIONS_TABLE)
                            .where(
                                BILLING_SUBSCRIPTIONS_TABLE.c.id
                                == normalize_uuid_string(
                                    record_before.upgrade_from_subscription_id
                                ),
                                BILLING_SUBSCRIPTIONS_TABLE.c.tenant_id
                                == normalize_uuid_string(tenant_id),
                            )
                            .values(
                                status=BillingSubscriptionStatus.CANCELLED.value,
                                updated_at=now,
                            )
                        )

        detail = self.get_billing_record_detail(
            tenant_id=tenant_id, record_id=record_before.id
        )
        if detail is None:
            raise KeyError(record_before.id)
        return detail

    def get_upcoming_subscription_for_tenant(
        self, *, tenant_id: str
    ) -> BillingSubscriptionRecord | None:
        return _select_upcoming_subscription(
            self.list_subscriptions_for_tenant(tenant_id=tenant_id)
        )


def create_billing_repository(
    *,
    database_url: str | None = None,
    engine: Engine | None = None,
    bootstrap_schema: bool = True,
) -> SqlBillingRepository:
    return SqlBillingRepository(
        database_url=database_url,
        engine=engine,
        bootstrap_schema=bootstrap_schema,
    )
