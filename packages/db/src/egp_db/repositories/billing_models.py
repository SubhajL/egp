"""Billing repository record types."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from egp_shared_types.enums import (
    BillingEventType,
    BillingPaymentMethod,
    BillingPaymentProvider,
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
    is_stale_unpaid: bool
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
    current_subscription: BillingSubscriptionRecord | None
    summary: BillingSummary


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
