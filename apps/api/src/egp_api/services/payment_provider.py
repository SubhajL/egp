"""Provider-agnostic payment initiation helpers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Protocol
from uuid import uuid4

from egp_api.services.promptpay import build_promptpay_payload, render_promptpay_qr_svg
from egp_shared_types.enums import (
    BillingPaymentMethod,
    BillingPaymentProvider,
    BillingPaymentRequestStatus,
)


@dataclass(frozen=True, slots=True)
class ProviderPaymentRequest:
    tenant_id: str
    billing_record_id: str
    record_number: str
    amount: str
    currency: str
    expires_in_minutes: int


@dataclass(frozen=True, slots=True)
class CreatedPaymentRequest:
    provider: BillingPaymentProvider
    payment_method: BillingPaymentMethod
    status: BillingPaymentRequestStatus
    provider_reference: str
    payment_url: str
    qr_payload: str
    qr_svg: str
    amount: str
    currency: str
    expires_at: str


@dataclass(frozen=True, slots=True)
class ParsedPaymentCallback:
    provider_event_id: str
    status: BillingPaymentRequestStatus
    amount: str
    currency: str
    occurred_at: str
    reference_code: str | None
    payload_json: str


class PaymentProvider(Protocol):
    def create_payment_request(
        self, *, request: ProviderPaymentRequest
    ) -> CreatedPaymentRequest: ...

    def parse_callback(
        self,
        *,
        payload: dict[str, object],
    ) -> ParsedPaymentCallback: ...


class MockPromptPayProvider:
    def __init__(self, *, base_url: str, promptpay_proxy_id: str) -> None:
        self._base_url = base_url.rstrip("/")
        self._promptpay_proxy_id = promptpay_proxy_id

    def create_payment_request(self, *, request: ProviderPaymentRequest) -> CreatedPaymentRequest:
        if request.currency != "THB":
            raise ValueError("PromptPay only supports THB")
        provider_reference = f"mockpp_{uuid4().hex[:20]}"
        qr_payload = build_promptpay_payload(
            self._promptpay_proxy_id,
            amount=request.amount,
            reference=request.record_number,
        )
        expires_at = (
            datetime.now(UTC) + timedelta(minutes=max(1, int(request.expires_in_minutes)))
        ).isoformat()
        return CreatedPaymentRequest(
            provider=BillingPaymentProvider.MOCK_PROMPTPAY,
            payment_method=BillingPaymentMethod.PROMPTPAY_QR,
            status=BillingPaymentRequestStatus.PENDING,
            provider_reference=provider_reference,
            payment_url=f"{self._base_url}/checkout/{provider_reference}",
            qr_payload=qr_payload,
            qr_svg=render_promptpay_qr_svg(qr_payload),
            amount=request.amount,
            currency=request.currency,
            expires_at=expires_at,
        )

    def parse_callback(
        self,
        *,
        payload: dict[str, object],
    ) -> ParsedPaymentCallback:
        provider_event_id = str(payload.get("provider_event_id") or "").strip()
        occurred_at = str(payload.get("occurred_at") or "").strip()
        if not provider_event_id:
            raise ValueError("provider_event_id is required")
        if not occurred_at:
            raise ValueError("occurred_at is required")
        status = BillingPaymentRequestStatus(str(payload.get("status") or "").strip())
        amount = f"{Decimal(str(payload.get('amount') or '0')).quantize(Decimal('0.01')):.2f}"
        currency = str(payload.get("currency") or "").strip() or "THB"
        reference_code = (
            str(payload.get("reference_code")).strip() if payload.get("reference_code") else None
        )
        return ParsedPaymentCallback(
            provider_event_id=provider_event_id,
            status=status,
            amount=amount,
            currency=currency,
            occurred_at=occurred_at,
            reference_code=reference_code,
            payload_json=str(payload),
        )


def build_payment_provider(
    *,
    provider_name: str,
    base_url: str,
    promptpay_proxy_id: str | None,
) -> PaymentProvider | None:
    provider = BillingPaymentProvider(str(provider_name).strip())
    if provider is BillingPaymentProvider.MOCK_PROMPTPAY:
        if not promptpay_proxy_id:
            return None
        return MockPromptPayProvider(base_url=base_url, promptpay_proxy_id=promptpay_proxy_id)
    return None
