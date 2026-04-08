"""Billing service for invoice lifecycle, payment requests, and reconciliation."""

from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation

from egp_db.repositories.billing_repo import (
    BillingPage,
    BillingPaymentRecord,
    BillingRecordDetail,
    SqlBillingRepository,
)
from egp_api.services.payment_provider import PaymentProvider, ProviderPaymentRequest
from egp_shared_types.billing_plans import (
    BillingPlanDefinition,
    derive_plan_period_end,
    get_billing_plan_definition,
    list_billing_plan_definitions,
)
from egp_shared_types.enums import (
    BillingPaymentMethod,
    BillingPaymentProvider,
    BillingPaymentRequestStatus,
    BillingPaymentStatus,
    BillingRecordStatus,
)


class BillingService:
    def __init__(
        self,
        repository: SqlBillingRepository,
        *,
        payment_provider: PaymentProvider | None = None,
    ) -> None:
        self._repository = repository
        self._payment_provider = payment_provider

    def list_plans(self) -> list[BillingPlanDefinition]:
        return list_billing_plan_definitions()

    def start_free_trial(
        self,
        *,
        tenant_id: str,
        actor_subject: str | None = None,
    ):
        return self._repository.activate_free_trial_subscription(
            tenant_id=tenant_id,
            actor_subject=actor_subject,
            note="Free trial activation",
        )

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

    def create_upgrade_record(
        self,
        *,
        tenant_id: str,
        target_plan_code: str,
        billing_period_start: str,
        record_number: str | None = None,
        notes: str | None = None,
        actor_subject: str | None = None,
    ) -> BillingRecordDetail:
        normalized_target_plan_code = str(target_plan_code).strip()
        normalized_start = str(billing_period_start).strip()
        resolved_record_number = (record_number or "").strip()
        if not resolved_record_number:
            resolved_record_number = (
                f"UPG-{normalized_target_plan_code.upper()}-{normalized_start.replace('-', '')}"
            )
        resolved_notes = notes
        if resolved_notes is None:
            resolved_notes = (
                f"Upgrade to {normalized_target_plan_code} starting {normalized_start}"
            )
        return self._repository.create_upgrade_billing_record(
            tenant_id=tenant_id,
            target_plan_code=normalized_target_plan_code,
            billing_period_start=normalized_start,
            record_number=resolved_record_number,
            notes=resolved_notes,
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
        if payment_method is not BillingPaymentMethod.BANK_TRANSFER:
            raise ValueError("manual payment endpoint only accepts bank_transfer")
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

    def create_payment_request(
        self,
        *,
        tenant_id: str,
        billing_record_id: str,
        provider: BillingPaymentProvider,
        payment_method: BillingPaymentMethod,
        expires_in_minutes: int = 30,
        actor_subject: str | None = None,
    ) -> BillingRecordDetail:
        if self._payment_provider is None:
            raise RuntimeError("payment provider is not configured")
        detail = self._repository.require_billing_record_detail(
            tenant_id=tenant_id,
            record_id=billing_record_id,
        )
        if detail.record.status in {
            BillingRecordStatus.PAID,
            BillingRecordStatus.CANCELLED,
            BillingRecordStatus.REFUNDED,
        }:
            raise ValueError("billing record is not payable")
        if Decimal(detail.record.outstanding_balance) <= Decimal("0.00"):
            raise ValueError("billing record has no outstanding balance")
        try:
            created_request = self._payment_provider.create_payment_request(
                request=ProviderPaymentRequest(
                    provider=provider,
                    payment_method=payment_method,
                    tenant_id=tenant_id,
                    billing_record_id=detail.record.id,
                    record_number=detail.record.record_number,
                    amount=detail.record.outstanding_balance,
                    currency=detail.record.currency,
                    expires_in_minutes=expires_in_minutes,
                )
            )
        except ValueError:
            raise
        except Exception as exc:
            raise RuntimeError("payment provider request failed") from exc
        return self._repository.create_payment_request(
            tenant_id=tenant_id,
            billing_record_id=detail.record.id,
            provider=created_request.provider,
            payment_method=created_request.payment_method,
            status=created_request.status,
            provider_reference=created_request.provider_reference,
            payment_url=created_request.payment_url,
            qr_payload=created_request.qr_payload,
            qr_svg=created_request.qr_svg,
            amount=created_request.amount,
            currency=created_request.currency,
            expires_at=created_request.expires_at,
            actor_subject=actor_subject,
            note=f"{created_request.provider.value} {created_request.payment_method.value} payment request created",
        )

    def _process_payment_callback(
        self,
        *,
        payment_request_id: str,
        payment_request_tenant_id: str,
        payload: dict[str, object],
        headers: dict[str, str] | None = None,
        raw_body: str | None = None,
        actor_subject: str | None = None,
    ) -> BillingRecordDetail:
        payment_request = self._repository.require_payment_request_detail(
            tenant_id=payment_request_tenant_id,
            request_id=payment_request_id,
        )
        callback = self._payment_provider.parse_callback(
            payload=payload,
            headers=headers,
            raw_body=raw_body,
        )
        inserted = self._repository.record_provider_callback(
            tenant_id=payment_request_tenant_id,
            payment_request_id=payment_request.id,
            provider=payment_request.provider,
            provider_event_id=callback.provider_event_id,
            event_type=callback.status.value,
            payload_json=callback.payload_json,
        )
        if not inserted:
            detail = self._repository.get_billing_record_detail(
                tenant_id=payment_request_tenant_id,
                record_id=payment_request.billing_record_id,
            )
            if detail is None:
                raise KeyError(payment_request.billing_record_id)
            return detail

        detail = self._repository.update_payment_request_status(
            tenant_id=payment_request_tenant_id,
            payment_request_id=payment_request.id,
            status=callback.status,
            settled_at=callback.occurred_at,
            actor_subject=actor_subject,
            note=callback.reference_code,
        )
        if callback.status is not BillingPaymentRequestStatus.SETTLED:
            return detail

        if payment_request.status is BillingPaymentRequestStatus.SETTLED:
            return detail
        if callback.currency != payment_request.currency:
            raise ValueError("callback currency does not match payment request")
        try:
            callback_amount = Decimal(callback.amount)
            request_amount = Decimal(payment_request.amount)
        except (InvalidOperation, ValueError) as exc:
            raise ValueError("invalid callback amount") from exc
        if callback_amount != request_amount:
            raise ValueError("callback amount does not match payment request")

        recorded_payment = self._repository.record_payment(
            tenant_id=payment_request_tenant_id,
            billing_record_id=payment_request.billing_record_id,
            payment_method=payment_request.payment_method,
            amount=callback.amount,
            currency=callback.currency,
            reference_code=callback.reference_code or payment_request.provider_reference,
            received_at=callback.occurred_at,
            note=callback.reference_code,
            actor_subject=actor_subject,
        )
        return self._repository.reconcile_payment(
            tenant_id=payment_request_tenant_id,
            payment_id=recorded_payment.id,
            status=BillingPaymentStatus.RECONCILED,
            note=callback.reference_code,
            actor_subject=actor_subject,
        )

    def handle_payment_request_callback(
        self,
        *,
        tenant_id: str,
        payment_request_id: str,
        payload: dict[str, object],
        headers: dict[str, str] | None = None,
        raw_body: str | None = None,
        actor_subject: str | None = None,
    ) -> BillingRecordDetail:
        if self._payment_provider is None:
            raise RuntimeError("payment provider is not configured")
        payment_request = self._repository.require_payment_request_detail(
            tenant_id=tenant_id,
            request_id=payment_request_id,
        )
        return self._process_payment_callback(
            payment_request_id=payment_request.id,
            payment_request_tenant_id=tenant_id,
            payload=payload,
            headers=headers,
            raw_body=raw_body,
            actor_subject=actor_subject,
        )

    def handle_provider_webhook(
        self,
        *,
        provider: BillingPaymentProvider,
        payload: dict[str, object],
        headers: dict[str, str] | None = None,
        raw_body: str | None = None,
        actor_subject: str | None = None,
    ) -> BillingRecordDetail:
        if self._payment_provider is None:
            raise RuntimeError("payment provider is not configured")
        callback = self._payment_provider.parse_callback(
            payload=payload,
            headers=headers,
            raw_body=raw_body,
        )
        payment_request = self._repository.get_payment_request_by_provider_reference(
            provider=provider,
            provider_reference=callback.provider_reference,
        )
        if payment_request is None:
            raise KeyError(callback.provider_reference)
        return self._process_payment_callback(
            payment_request_id=payment_request.id,
            payment_request_tenant_id=payment_request.tenant_id,
            payload=payload,
            headers=headers,
            raw_body=raw_body,
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
