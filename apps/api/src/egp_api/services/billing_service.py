"""Billing service for invoice lifecycle, payment requests, and reconciliation."""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import date
from decimal import Decimal, InvalidOperation

from egp_db.db_utils import normalize_uuid_string
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
    BillingSubscriptionStatus,
)

logger = logging.getLogger(__name__)


_TEST_CHARGED_PLAN_AMOUNTS = {
    "one_time_search_pack": "20.00",
    "monthly_membership": "25.00",
}


class BillingService:
    def __init__(
        self,
        repository: SqlBillingRepository,
        *,
        payment_provider: PaymentProvider | None = None,
        subscription_activated_notifier: Callable[..., object] | None = None,
    ) -> None:
        self._repository = repository
        self._payment_provider = payment_provider
        self._subscription_activated_notifier = subscription_activated_notifier

    def set_subscription_activated_notifier(self, notifier: Callable[..., object] | None) -> None:
        """Late-bind the activation notifier (avoids a construction-order cycle
        with LineSlipService, which itself depends on this service)."""
        self._subscription_activated_notifier = notifier

    def list_plans(self) -> list[BillingPlanDefinition]:
        return list_billing_plan_definitions()

    @staticmethod
    def _charged_plan_amount(plan_code: str, default_amount: str) -> str:
        return _TEST_CHARGED_PLAN_AMOUNTS.get(str(plan_code).strip(), default_amount)

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

    def list_snapshot(
        self,
        *,
        tenant_id: str,
        limit: int = 50,
        offset: int = 0,
        include_stale_unpaid: bool = False,
        stale_unpaid_only: bool = False,
    ) -> BillingPage:
        return self._repository.list_billing_records(
            tenant_id=tenant_id,
            limit=limit,
            offset=offset,
            include_stale_unpaid=include_stale_unpaid,
            stale_unpaid_only=stale_unpaid_only,
        )

    def has_overdue_records(self, *, tenant_id: str) -> bool:
        return self._repository.has_overdue_billing_records(tenant_id=tenant_id)

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
            charged_amount = self._charged_plan_amount(
                plan_definition.code,
                plan_definition.amount_due,
            )
            if resolved_amount is None:
                resolved_amount = charged_amount
            elif str(resolved_amount).strip() not in {
                plan_definition.amount_due,
                charged_amount,
            }:
                raise ValueError(
                    f"{plan_definition.code} must be billed at {charged_amount} {plan_definition.currency}"
                )
            else:
                resolved_amount = charged_amount
            if resolved_currency is None:
                resolved_currency = plan_definition.currency
            elif resolved_currency != plan_definition.currency:
                raise ValueError(
                    f"{plan_definition.code} must use currency {plan_definition.currency}"
                )
        else:
            raise ValueError("unsupported billing plan")

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
        target_plan_definition = get_billing_plan_definition(normalized_target_plan_code)
        if target_plan_definition is None:
            raise ValueError("unsupported subscription upgrade")
        resolved_record_number = (record_number or "").strip()
        if not resolved_record_number:
            resolved_record_number = (
                f"UPG-{normalized_target_plan_code.upper()}-{normalized_start.replace('-', '')}"
            )
        resolved_notes = notes
        if resolved_notes is None:
            resolved_notes = f"Upgrade to {normalized_target_plan_code} starting {normalized_start}"
        return self._repository.create_upgrade_billing_record(
            tenant_id=tenant_id,
            target_plan_code=normalized_target_plan_code,
            billing_period_start=normalized_start,
            amount_due=self._charged_plan_amount(
                normalized_target_plan_code,
                target_plan_definition.amount_due,
            ),
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
        if detail.record.is_stale_unpaid:
            raise ValueError("stale unpaid billing record is not payable")
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
        except RuntimeError:
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

        # Validate the callback BEFORE any DB mutation. If amount/currency
        # don't match, raise so nothing is persisted; the provider will retry
        # and the same validation will fail again — no silent half-state.
        # See QCHECK PR-G #1: previously the event row + status update landed
        # BEFORE validation, so a retry hit the UNIQUE constraint and
        # short-circuited without recording payment.
        if callback.status is BillingPaymentRequestStatus.SETTLED and (
            payment_request.status is not BillingPaymentRequestStatus.SETTLED
        ):
            if callback.currency != payment_request.currency:
                raise ValueError("callback currency does not match payment request")
            try:
                callback_amount = Decimal(callback.amount)
                request_amount = Decimal(payment_request.amount)
            except (InvalidOperation, ValueError) as exc:
                raise ValueError("invalid callback amount") from exc
            if callback_amount != request_amount:
                raise ValueError("callback amount does not match payment request")

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
        # Capture the pre-state so we notify ONLY on the real pending->reconciled
        # transition — an idempotent re-reconcile of an already-settled payment
        # must not push a second activation message to the customer.
        was_pending = self._payment_pending_reconciliation(
            tenant_id=tenant_id, payment_id=payment_id
        )
        detail = self._repository.reconcile_payment(
            tenant_id=tenant_id,
            payment_id=payment_id,
            status=status,
            note=note,
            actor_subject=actor_subject,
        )
        if was_pending:
            self._notify_if_subscription_activated(
                tenant_id=tenant_id, payment_id=payment_id, detail=detail
            )
        return detail

    def _payment_pending_reconciliation(self, *, tenant_id: str, payment_id: str) -> bool:
        try:
            payment = self._repository.get_billing_payment(
                tenant_id=tenant_id, payment_id=payment_id
            )
        except Exception:
            return False
        return payment.payment_status is BillingPaymentStatus.PENDING_RECONCILIATION

    def _notify_if_subscription_activated(
        self, *, tenant_id: str, payment_id: str, detail: BillingRecordDetail
    ) -> None:
        notifier = self._subscription_activated_notifier
        if notifier is None:
            return
        subscription = detail.subscription
        if (
            subscription is None
            or subscription.subscription_status is not BillingSubscriptionStatus.ACTIVE
        ):
            return
        # Notify ONLY when THIS payment is the one that activated the subscription.
        # A second payment reconciled on an already-active record (e.g. a duplicate
        # bank transfer) leaves the existing subscription untouched — it must stay
        # silent rather than push a second activation notice.
        activated_by = subscription.activated_by_payment_id
        if activated_by is None or normalize_uuid_string(activated_by) != normalize_uuid_string(
            payment_id
        ):
            return
        try:
            notifier(tenant_id=tenant_id, plan_code=subscription.plan_code)
        except Exception:  # pragma: no cover - notifier is best-effort
            logger.exception("subscription-activated notifier failed for tenant %s", tenant_id)

    def verify_manual_payment(
        self,
        *,
        tenant_id: str,
        billing_record_id: str,
        received_at: str,
        amount: str | None = None,
        payment_request_id: str | None = None,
        note: str | None = None,
        actor_subject: str | None = None,
        idempotency_key: str | None = None,
    ) -> BillingRecordDetail:
        """Settle a manual PromptPay record after an admin verifies the LINE slip.

        There is no provider webhook for ``promptpay_manual``; settlement is an
        explicit human action. Records a reconciled ``promptpay_qr`` payment and
        settles the linked manual payment request when supplied.

        ``amount`` is the value the admin reads off the slip image. When given,
        exactly that amount is recorded (so an under-payment leaves the record
        short of PAID — and the subscription un-activated — rather than silently
        normalising to the full balance). When omitted, the record's outstanding
        balance is used.

        ``idempotency_key`` (the slip id) makes settlement safe to retry: if a
        payment carrying this key already exists for the record, no second
        payment is recorded. This closes the crash-recovery window even for an
        under-payment (which leaves the record in ``payment_detected``, not
        ``paid``), where a status check alone would re-record.
        """
        detail = self._repository.require_billing_record_detail(
            tenant_id=tenant_id,
            record_id=billing_record_id,
        )
        if idempotency_key:
            marker = f"[slip:{idempotency_key}]"
            for existing in detail.payments:
                if existing.note and marker in existing.note:
                    # This slip already produced a payment — never double-record.
                    if existing.payment_status is BillingPaymentStatus.PENDING_RECONCILIATION:
                        return self._repository.reconcile_payment(
                            tenant_id=tenant_id,
                            payment_id=existing.id,
                            status=BillingPaymentStatus.RECONCILED,
                            # note=None preserves the existing "[slip:...]" marker
                            # so the idempotency scan keeps matching it.
                            note=None,
                            actor_subject=actor_subject,
                        )
                    refreshed = self._repository.get_billing_record_detail(
                        tenant_id=tenant_id, record_id=billing_record_id
                    )
                    if refreshed is None:
                        raise KeyError(billing_record_id)
                    return refreshed
        if detail.record.status in {
            BillingRecordStatus.PAID,
            BillingRecordStatus.CANCELLED,
            BillingRecordStatus.REFUNDED,
        }:
            raise ValueError("billing record is not payable")
        outstanding = Decimal(detail.record.outstanding_balance)
        if outstanding <= Decimal("0.00"):
            raise ValueError("billing record has no outstanding balance")
        if amount is not None:
            try:
                recorded_amount = Decimal(str(amount))
            except (InvalidOperation, ValueError) as exc:
                raise ValueError("invalid payment amount") from exc
            if recorded_amount <= Decimal("0.00"):
                raise ValueError("invalid payment amount")
        else:
            recorded_amount = outstanding
        reference = detail.record.record_number
        if payment_request_id:
            try:
                self._repository.update_payment_request_status(
                    tenant_id=tenant_id,
                    payment_request_id=payment_request_id,
                    status=BillingPaymentRequestStatus.SETTLED,
                    settled_at=received_at,
                    actor_subject=actor_subject,
                    note=reference,
                )
            except (KeyError, PermissionError):
                # The request may belong to another record or be missing; the
                # payment recording below is the source of truth for activation.
                pass
        recorded_note = note or reference
        if idempotency_key:
            recorded_note = f"{recorded_note} [slip:{idempotency_key}]"
        payment = self._repository.record_payment(
            tenant_id=tenant_id,
            billing_record_id=billing_record_id,
            payment_method=BillingPaymentMethod.PROMPTPAY_QR,
            amount=f"{recorded_amount:.2f}",
            currency=detail.record.currency,
            reference_code=reference,
            received_at=received_at,
            note=recorded_note,
            actor_subject=actor_subject,
        )
        return self._repository.reconcile_payment(
            tenant_id=tenant_id,
            payment_id=payment.id,
            status=BillingPaymentStatus.RECONCILED,
            # note=None preserves the recorded note (which carries the
            # "[slip:...]" idempotency marker) so recovery can dedupe.
            note=None,
            actor_subject=actor_subject,
        )
