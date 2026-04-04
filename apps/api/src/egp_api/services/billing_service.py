"""Billing service for manual records and bank-transfer reconciliation."""

from __future__ import annotations

from datetime import date

from egp_db.repositories.billing_repo import (
    BillingPage,
    BillingPaymentRecord,
    BillingRecordDetail,
    SqlBillingRepository,
)
from egp_shared_types.billing_plans import (
    BillingPlanDefinition,
    derive_plan_period_end,
    get_billing_plan_definition,
    list_billing_plan_definitions,
)
from egp_shared_types.enums import BillingPaymentMethod, BillingPaymentStatus, BillingRecordStatus


class BillingService:
    def __init__(self, repository: SqlBillingRepository) -> None:
        self._repository = repository

    def list_plans(self) -> list[BillingPlanDefinition]:
        return list_billing_plan_definitions()

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
        billing_period_end: str | None = None,
        amount_due: str | None = None,
        currency: str | None = None,
        due_at: str | None = None,
        issued_at: str | None = None,
        notes: str | None = None,
        actor_subject: str | None = None,
    ) -> BillingRecordDetail:
        plan_definition = get_billing_plan_definition(plan_code)
        resolved_end = billing_period_end
        resolved_amount = amount_due
        resolved_currency = (currency or "").strip() or None
        if plan_definition is not None:
            try:
                period_start = date.fromisoformat(str(billing_period_start).strip())
            except ValueError as exc:
                raise ValueError("invalid billing date") from exc
            expected_end = derive_plan_period_end(
                plan_definition,
                billing_period_start=period_start,
            ).isoformat()
            if resolved_end is None:
                resolved_end = expected_end
            elif str(resolved_end).strip() != expected_end:
                raise ValueError(f"{plan_definition.code} must end on {expected_end}")
            if resolved_amount is None:
                resolved_amount = plan_definition.amount_due
            elif str(resolved_amount).strip() != plan_definition.amount_due:
                raise ValueError(
                    f"{plan_definition.code} must be billed at {plan_definition.amount_due} {plan_definition.currency}"
                )
            if resolved_currency is None:
                resolved_currency = plan_definition.currency
            elif resolved_currency != plan_definition.currency:
                raise ValueError(
                    f"{plan_definition.code} must use currency {plan_definition.currency}"
                )
        else:
            if resolved_end is None:
                raise ValueError("billing_period_end is required for custom plans")
            if resolved_amount is None:
                raise ValueError("amount_due is required for custom plans")
            if resolved_currency is None:
                resolved_currency = "THB"

        return self._repository.create_billing_record(
            tenant_id=tenant_id,
            record_number=record_number,
            plan_code=plan_code,
            status=status,
            billing_period_start=billing_period_start,
            billing_period_end=resolved_end,
            amount_due=resolved_amount,
            currency=resolved_currency,
            due_at=due_at,
            issued_at=issued_at,
            notes=notes,
            actor_subject=actor_subject,
        )

    def transition_record(
        self,
        *,
        tenant_id: str,
        billing_record_id: str,
        status: BillingRecordStatus,
        note: str | None = None,
        actor_subject: str | None = None,
    ) -> BillingRecordDetail:
        return self._repository.transition_billing_record_status(
            tenant_id=tenant_id,
            billing_record_id=billing_record_id,
            status=status,
            note=note,
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
