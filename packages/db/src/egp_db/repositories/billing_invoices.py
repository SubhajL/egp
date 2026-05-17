"""Billing invoice and record lifecycle operations."""

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from uuid import uuid4

from sqlalchemy import desc, insert, select, update
from sqlalchemy.exc import IntegrityError

from egp_db.db_utils import normalize_uuid_string
from egp_shared_types.enums import (
    BillingEventType,
    BillingPaymentStatus,
    BillingRecordStatus,
)

from .billing_models import (
    BillingPage,
    BillingRecordDetail,
    BillingSummary,
    _BillingRecordRow,
)
from .billing_schema import BILLING_RECORDS_TABLE
from .billing_utils import (
    _billing_record_from_mapping,
    _decimal_to_str,
    _detail_from_row,
    _group_events,
    _group_payment_requests,
    _group_payments,
    _group_subscriptions,
    _MONEY_QUANTUM,
    _normalize_amount,
    _normalize_date,
    _normalize_datetime,
    _normalize_record_status,
    _normalize_upgrade_mode,
    _now,
    _reconciled_total_for_payments,
    _TERMINAL_BILLING_STATUSES,
)


class BillingInvoiceMixin:
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

    def _require_record_for_tenant(
        self, *, tenant_id: str, record_id: str
    ) -> _BillingRecordRow:
        row = self._get_record_row_by_id(record_id)
        if row is None:
            raise KeyError(record_id)
        if row.tenant_id != normalize_uuid_string(tenant_id):
            raise PermissionError(record_id)
        return row

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
            current_subscription=self.get_effective_subscription_for_tenant(
                tenant_id=tenant_id
            ),
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
            row = connection.execute(
                select(BILLING_RECORDS_TABLE.c.id)
                .where(
                    BILLING_RECORDS_TABLE.c.tenant_id == normalized_tenant_id,
                    BILLING_RECORDS_TABLE.c.status == BillingRecordStatus.OVERDUE.value,
                )
                .limit(1)
            ).first()
        return row is not None

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
