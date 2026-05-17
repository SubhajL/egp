"""Billing payment recording and reconciliation operations."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import insert, select, update

from egp_db.db_utils import normalize_uuid_string
from egp_shared_types.billing_plans import get_billing_plan_definition
from egp_shared_types.enums import (
    BillingEventType,
    BillingPaymentMethod,
    BillingPaymentStatus,
    BillingRecordStatus,
    BillingSubscriptionStatus,
)

from .billing_models import BillingPaymentRecord, BillingRecordDetail
from .billing_schema import (
    BILLING_PAYMENTS_TABLE,
    BILLING_RECORDS_TABLE,
    BILLING_SUBSCRIPTIONS_TABLE,
)
from .profile_repo import CRAWL_PROFILES_TABLE
from .billing_utils import (
    _normalize_amount,
    _normalize_datetime,
    _normalize_payment_method,
    _normalize_payment_status,
    _now,
    _payment_from_mapping,
    _reconciled_total_for_payments,
    _subscription_status_for_period,
)


class BillingPaymentMixin:
    def _deactivate_profiles_for_one_time_renewal(
        self,
        *,
        connection,
        tenant_id: str,
        source_subscription_id: str | None,
        target_plan_code: str,
        new_subscription_status: BillingSubscriptionStatus,
        now,
    ) -> None:
        if (
            source_subscription_id is None
            or target_plan_code != "one_time_search_pack"
            or new_subscription_status is not BillingSubscriptionStatus.ACTIVE
        ):
            return
        source_subscription_row = (
            connection.execute(
                select(BILLING_SUBSCRIPTIONS_TABLE.c.plan_code)
                .where(
                    BILLING_SUBSCRIPTIONS_TABLE.c.id
                    == normalize_uuid_string(source_subscription_id)
                )
                .limit(1)
            )
            .mappings()
            .one_or_none()
        )
        if (
            source_subscription_row is None
            or str(source_subscription_row["plan_code"]) != "one_time_search_pack"
        ):
            return
        connection.execute(
            update(CRAWL_PROFILES_TABLE)
            .where(
                CRAWL_PROFILES_TABLE.c.tenant_id == normalize_uuid_string(tenant_id),
                CRAWL_PROFILES_TABLE.c.is_active.is_(True),
            )
            .values(is_active=False, updated_at=now)
        )

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
                    self._deactivate_profiles_for_one_time_renewal(
                        connection=connection,
                        tenant_id=tenant_id,
                        source_subscription_id=record_before.upgrade_from_subscription_id,
                        target_plan_code=record_before.plan_code,
                        new_subscription_status=subscription_status,
                        now=now,
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
