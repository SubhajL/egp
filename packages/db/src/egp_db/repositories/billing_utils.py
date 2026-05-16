"""Shared billing repository normalization and mapping helpers."""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from sqlalchemy.engine import RowMapping

from egp_shared_types.enums import (
    BillingEventType,
    BillingPaymentMethod,
    BillingPaymentProvider,
    BillingPaymentRequestStatus,
    BillingPaymentStatus,
    BillingRecordStatus,
    BillingSubscriptionStatus,
)

from .billing_models import (
    BillingEventRecord,
    BillingPaymentRecord,
    BillingPaymentRequestRecord,
    BillingRecordDetail,
    BillingRecordRecord,
    BillingSubscriptionRecord,
    _BillingRecordRow,
)


_MONEY_QUANTUM = Decimal("0.01")
_TERMINAL_BILLING_STATUSES = {
    BillingRecordStatus.PAID,
    BillingRecordStatus.CANCELLED,
    BillingRecordStatus.REFUNDED,
}


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
