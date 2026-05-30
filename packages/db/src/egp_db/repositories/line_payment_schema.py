"""SQLAlchemy schema for LINE-mediated manual PromptPay slip verification.

These tables back the ฿0-fee bootstrap flow where a customer pays a personal
PromptPay QR and forwards the slip image via LINE OA for a human to verify.

- ``payment_slips``        — slip images received over LINE (the operator inbox).
- ``line_payment_contexts``— reference codes parsed from LINE text messages, so a
                             slip image arriving in a *separate* webhook event can
                             still be matched to a billing record.
- ``line_admin_subscribers``— LINE userIds that receive admin push notifications.

``payment_slips.tenant_id`` is intentionally NULLable: a slip can arrive before
it is matched to any tenant (operator inbox). It is populated the moment the
slip is matched to a billing record, and all tenant-scoped admin listings filter
on it once set.
"""

from __future__ import annotations

from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    Index,
    String,
    Table,
    text,
)

from egp_db.connection import DB_METADATA
from egp_db.db_utils import UUID_SQL_TYPE

METADATA = DB_METADATA

_SLIP_VERIFICATION_STATUSES = ("pending", "matched", "verified", "rejected")


PAYMENT_SLIPS_TABLE = Table(
    "payment_slips",
    METADATA,
    Column("id", UUID_SQL_TYPE, primary_key=True),
    Column("tenant_id", UUID_SQL_TYPE, nullable=True),
    Column(
        "billing_record_id",
        UUID_SQL_TYPE,
        ForeignKey("billing_records.id", ondelete="SET NULL"),
        nullable=True,
    ),
    Column(
        "payment_request_id",
        UUID_SQL_TYPE,
        ForeignKey("billing_payment_requests.id", ondelete="SET NULL"),
        nullable=True,
    ),
    Column("line_user_id", String, nullable=False),
    Column("line_message_id", String, nullable=False, unique=True),
    Column("reference_code_match", String, nullable=True),
    Column("image_object_key", String, nullable=True),
    Column("image_content_type", String, nullable=True),
    Column("image_sha256", String, nullable=True),
    Column(
        "verification_status",
        String,
        nullable=False,
        default="pending",
        server_default=text("'pending'"),
    ),
    Column("verified_by_user_id", UUID_SQL_TYPE, nullable=True),
    Column("verified_at", DateTime(timezone=True), nullable=True),
    Column("verification_notes", String, nullable=True),
    Column("received_at", DateTime(timezone=True), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
)

LINE_PAYMENT_CONTEXTS_TABLE = Table(
    "line_payment_contexts",
    METADATA,
    Column("id", UUID_SQL_TYPE, primary_key=True),
    Column("line_user_id", String, nullable=False),
    Column("reference_code", String, nullable=False),
    Column("tenant_id", UUID_SQL_TYPE, nullable=True),
    Column(
        "billing_record_id",
        UUID_SQL_TYPE,
        ForeignKey("billing_records.id", ondelete="SET NULL"),
        nullable=True,
    ),
    Column("plan_code", String, nullable=True),
    Column("source_message_id", String, nullable=False, unique=True),
    Column("expires_at", DateTime(timezone=True), nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False),
)

LINE_ADMIN_SUBSCRIBERS_TABLE = Table(
    "line_admin_subscribers",
    METADATA,
    Column("id", UUID_SQL_TYPE, primary_key=True),
    Column("line_user_id", String, nullable=False, unique=True),
    Column("tenant_id", UUID_SQL_TYPE, nullable=True),
    Column("display_name", String, nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False),
)

Index(
    "idx_payment_slips_status_received",
    PAYMENT_SLIPS_TABLE.c.verification_status,
    PAYMENT_SLIPS_TABLE.c.received_at,
)
Index(
    "idx_payment_slips_tenant_status",
    PAYMENT_SLIPS_TABLE.c.tenant_id,
    PAYMENT_SLIPS_TABLE.c.verification_status,
)
Index(
    "idx_payment_slips_reference",
    PAYMENT_SLIPS_TABLE.c.reference_code_match,
)
Index(
    "idx_line_payment_contexts_user_created",
    LINE_PAYMENT_CONTEXTS_TABLE.c.line_user_id,
    LINE_PAYMENT_CONTEXTS_TABLE.c.created_at,
)
