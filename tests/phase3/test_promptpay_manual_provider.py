"""Unit tests for ``PromptpayManualProvider`` in payment_provider.py.

The manual PromptPay provider is the ฿0-fee bootstrap path used before the
operator can onboard a registered acquirer (Stripe/OPN). It generates a
dynamic EMVCo PromptPay payload locally from the operator's PERSONAL proxy id
(no network call, no acquirer) and is reconciled by a human verifying the LINE
slip — there is no provider-pushed webhook. ``parse_callback`` therefore only
needs to echo the admin-synthesised settled payload so the existing
``BillingService`` settle/activate path can be reused on manual verification.
"""

from __future__ import annotations

import pytest

from egp_api.services.payment_provider import (
    CreatedPaymentRequest,
    PromptpayManualProvider,
    ProviderPaymentRequest,
    build_payment_provider,
)
from egp_api.services.promptpay import build_promptpay_payload
from egp_shared_types.enums import (
    BillingPaymentMethod,
    BillingPaymentProvider,
    BillingPaymentRequestStatus,
)

PROXY_ID = "0812345678"


def _request_template(
    *,
    record_number: str = "INV-2026-0001",
    amount: str = "1500.00",
    currency: str = "THB",
    method: BillingPaymentMethod = BillingPaymentMethod.PROMPTPAY_QR,
) -> ProviderPaymentRequest:
    return ProviderPaymentRequest(
        provider=BillingPaymentProvider.PROMPTPAY_MANUAL,
        payment_method=method,
        tenant_id="11111111-1111-1111-1111-111111111111",
        billing_record_id="22222222-2222-2222-2222-222222222222",
        record_number=record_number,
        amount=amount,
        currency=currency,
        expires_in_minutes=1440,
    )


def test_enum_has_promptpay_manual_value() -> None:
    assert BillingPaymentProvider.PROMPTPAY_MANUAL.value == "promptpay_manual"


def test_create_request_builds_valid_emvco_payload_from_proxy_and_reference() -> None:
    provider = PromptpayManualProvider(base_url="https://api.example.com", promptpay_proxy_id=PROXY_ID)
    created = provider.create_payment_request(request=_request_template())
    assert isinstance(created, CreatedPaymentRequest)
    assert created.provider is BillingPaymentProvider.PROMPTPAY_MANUAL
    assert created.payment_method is BillingPaymentMethod.PROMPTPAY_QR
    assert created.status is BillingPaymentRequestStatus.PENDING
    # The payload must equal the canonical PromptPay payload for proxy+amount+ref.
    assert created.qr_payload == build_promptpay_payload(
        PROXY_ID, amount="1500.00", reference="INV-2026-0001"
    )
    assert created.qr_svg.startswith("<svg")
    assert created.amount == "1500.00"
    assert created.currency == "THB"


def test_create_request_provider_reference_is_unique_per_call() -> None:
    provider = PromptpayManualProvider(base_url="https://api.example.com", promptpay_proxy_id=PROXY_ID)
    first = provider.create_payment_request(request=_request_template())
    second = provider.create_payment_request(request=_request_template())
    assert first.provider_reference != second.provider_reference
    assert first.provider_reference.startswith("ppm_")


def test_create_request_rejects_non_promptpay_method() -> None:
    provider = PromptpayManualProvider(base_url="https://api.example.com", promptpay_proxy_id=PROXY_ID)
    with pytest.raises(ValueError):
        provider.create_payment_request(
            request=_request_template(method=BillingPaymentMethod.CARD)
        )


def test_create_request_rejects_non_thb_currency() -> None:
    provider = PromptpayManualProvider(base_url="https://api.example.com", promptpay_proxy_id=PROXY_ID)
    with pytest.raises(ValueError):
        provider.create_payment_request(request=_request_template(currency="USD"))


def test_create_request_rejects_wrong_provider() -> None:
    provider = PromptpayManualProvider(base_url="https://api.example.com", promptpay_proxy_id=PROXY_ID)
    bad = ProviderPaymentRequest(
        provider=BillingPaymentProvider.STRIPE,
        payment_method=BillingPaymentMethod.PROMPTPAY_QR,
        tenant_id="11111111-1111-1111-1111-111111111111",
        billing_record_id="22222222-2222-2222-2222-222222222222",
        record_number="INV-2026-0001",
        amount="1500.00",
        currency="THB",
        expires_in_minutes=1440,
    )
    with pytest.raises(ValueError):
        provider.create_payment_request(request=bad)


def test_parse_callback_fails_closed_no_provider_webhook() -> None:
    # Manual PromptPay has no acquirer; a provider callback must never settle
    # a request. Settlement only happens via admin slip verification.
    provider = PromptpayManualProvider(base_url="https://api.example.com", promptpay_proxy_id=PROXY_ID)
    with pytest.raises(ValueError):
        provider.parse_callback(
            payload={
                "provider_event_id": "manual-verify-abc",
                "provider_reference": "ppm_deadbeef",
                "status": "settled",
                "amount": "1500.00",
                "currency": "THB",
                "occurred_at": "2026-05-29T10:00:00+00:00",
                "reference_code": "INV-2026-0001",
            }
        )


def test_factory_returns_manual_provider_when_configured() -> None:
    provider = build_payment_provider(
        provider_name="promptpay_manual",
        base_url="https://api.example.com",
        promptpay_proxy_id=PROXY_ID,
    )
    assert isinstance(provider, PromptpayManualProvider)


def test_factory_returns_none_without_proxy_id() -> None:
    provider = build_payment_provider(
        provider_name="promptpay_manual",
        base_url="https://api.example.com",
        promptpay_proxy_id=None,
    )
    assert provider is None
