"""Billing service for manual records and bank-transfer reconciliation."""

from __future__ import annotations

from egp_db.repositories.billing_repo import (
    BillingPage,
    BillingPaymentRecord,
    BillingRecordDetail,
    SqlBillingRepository,
)
from egp_shared_types.enums import BillingPaymentMethod, BillingPaymentStatus, BillingRecordStatus


class BillingService:
    def __init__(self, repository: SqlBillingRepository) -> None:
        self._repository = repository

    def list_snapshot(self, *, tenant_id: str, limit: int = 50, offset: int = 0) -> BillingPage:
        return self._repository.list_billing_records(
            tenant_id=tenant_id,
            limit=limit,
            offset=offset,
        )

    def create_record(
        self,
        *,
        tenant_id: str,
        record_number: str,
        plan_code: str,
        status: BillingRecordStatus,
        billing_period_start: str,
        billing_period_end: str,
        amount_due: str,
        currency: str = "THB",
        due_at: str | None = None,
        issued_at: str | None = None,
        notes: str | None = None,
        actor_subject: str | None = None,
    ) -> BillingRecordDetail:
        return self._repository.create_billing_record(
            tenant_id=tenant_id,
            record_number=record_number,
            plan_code=plan_code,
            status=status,
            billing_period_start=billing_period_start,
            billing_period_end=billing_period_end,
            amount_due=amount_due,
            currency=currency,
            due_at=due_at,
            issued_at=issued_at,
            notes=notes,
            actor_subject=actor_subject,
        )

    def record_payment(
        self,
        *,
        tenant_id: str,
        billing_record_id: str,
        payment_method: BillingPaymentMethod,
        amount: str,
        currency: str = "THB",
        reference_code: str | None = None,
        received_at: str,
        note: str | None = None,
        actor_subject: str | None = None,
    ) -> BillingPaymentRecord:
        return self._repository.record_bank_transfer_payment(
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
        status: BillingPaymentStatus,
        note: str | None = None,
        actor_subject: str | None = None,
    ) -> BillingRecordDetail:
        return self._repository.reconcile_payment(
            tenant_id=tenant_id,
            payment_id=payment_id,
            status=status,
            note=note,
            actor_subject=actor_subject,
        )
