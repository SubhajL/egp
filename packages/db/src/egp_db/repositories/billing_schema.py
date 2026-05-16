"""Billing repository SQLAlchemy schema definitions."""

from __future__ import annotations

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
    text,
)
from sqlalchemy import Column

from egp_db.connection import DB_METADATA
from egp_db.db_utils import UUID_SQL_TYPE
from egp_shared_types.enums import (
    BillingEventType,
    BillingPaymentMethod,
    BillingPaymentProvider,
    BillingPaymentRequestStatus,
    BillingPaymentStatus,
    BillingRecordStatus,
    BillingSubscriptionStatus,
)


METADATA = DB_METADATA
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
