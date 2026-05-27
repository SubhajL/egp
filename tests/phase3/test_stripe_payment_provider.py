"""Unit tests for ``StripeProvider`` in payment_provider.py.

Stripe REST API is accessed via stdlib ``urllib`` (no ``stripe`` SDK)
mirroring the existing ``OpnProvider`` pattern. Tests stub ``_request``
directly via instance method override so they never touch the network.

The webhook signature scheme follows Stripe's documented format:
    Stripe-Signature: t=<unix-timestamp>,v1=<hex-hmac>
where the hmac is HMAC-SHA256(secret, f"{t}.{raw_body}") and at least
one v1 must match within ``_signature_tolerance_seconds`` (±5 min).
"""

from __future__ import annotations

import hashlib
import hmac
import time
from collections.abc import Mapping

import pytest

from egp_api.services.payment_provider import (
    ProviderPaymentRequest,
    StripeProvider,
    build_payment_provider,
)
from egp_shared_types.enums import (
    BillingPaymentMethod,
    BillingPaymentProvider,
    BillingPaymentRequestStatus,
)

WEBHOOK_SECRET = "whsec_test_secret_value_dont_use_in_prod"
SECRET_KEY = "sk_test_example_dont_use_in_prod"


def _stripe_signature(secret: str, timestamp: int, raw_body: str) -> str:
    digest = hmac.new(
        secret.encode("utf-8"),
        f"{timestamp}.{raw_body}".encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return f"t={timestamp},v1={digest}"


def _request_template(
    *,
    tenant_id: str = "11111111-1111-1111-1111-111111111111",
    billing_record_id: str = "22222222-2222-2222-2222-222222222222",
    record_number: str = "INV-2026-0001",
    amount: str = "1500.00",
    currency: str = "THB",
    method: BillingPaymentMethod = BillingPaymentMethod.PROMPTPAY_QR,
) -> ProviderPaymentRequest:
    return ProviderPaymentRequest(
        provider=BillingPaymentProvider.STRIPE,
        payment_method=method,
        tenant_id=tenant_id,
        billing_record_id=billing_record_id,
        record_number=record_number,
        amount=amount,
        currency=currency,
        expires_in_minutes=30,
    )


# ---------------------------------------------------------------------------
# Constructor + factory
# ---------------------------------------------------------------------------


def test_stripe_provider_constructor_normalizes_keys() -> None:
    provider = StripeProvider(
        secret_key="  " + SECRET_KEY + "  ",
        webhook_secret="  " + WEBHOOK_SECRET + "  ",
    )
    assert provider._secret_key == SECRET_KEY
    assert provider._webhook_secret == WEBHOOK_SECRET


def test_stripe_provider_constructor_rejects_empty_secret_key() -> None:
    with pytest.raises(ValueError, match="secret_key"):
        StripeProvider(secret_key="   ", webhook_secret=WEBHOOK_SECRET)


def test_factory_returns_none_without_stripe_secret_key() -> None:
    provider = build_payment_provider(
        provider_name="stripe",
        base_url="https://api.example.com",
        promptpay_proxy_id=None,
        stripe_secret_key=None,
        stripe_webhook_secret=WEBHOOK_SECRET,
    )
    assert provider is None


def test_factory_builds_stripe_when_provider_name_is_stripe() -> None:
    provider = build_payment_provider(
        provider_name="stripe",
        base_url="https://api.example.com",
        promptpay_proxy_id=None,
        stripe_secret_key=SECRET_KEY,
        stripe_webhook_secret=WEBHOOK_SECRET,
    )
    assert isinstance(provider, StripeProvider)


# ---------------------------------------------------------------------------
# Signature verification
# ---------------------------------------------------------------------------


def test_verify_signature_accepts_well_formed_stripe_header() -> None:
    provider = StripeProvider(secret_key=SECRET_KEY, webhook_secret=WEBHOOK_SECRET)
    raw_body = '{"id":"evt_test","type":"payment_intent.succeeded"}'
    timestamp = int(time.time())
    signature = _stripe_signature(WEBHOOK_SECRET, timestamp, raw_body)
    # Should not raise
    provider._verify_webhook_signature(
        headers={"Stripe-Signature": signature}, raw_body=raw_body
    )


def test_verify_signature_rejects_tampered_body() -> None:
    provider = StripeProvider(secret_key=SECRET_KEY, webhook_secret=WEBHOOK_SECRET)
    raw_body = '{"id":"evt_test","type":"payment_intent.succeeded"}'
    timestamp = int(time.time())
    signature = _stripe_signature(WEBHOOK_SECRET, timestamp, raw_body)
    with pytest.raises(ValueError, match="invalid stripe webhook signature"):
        provider._verify_webhook_signature(
            headers={"Stripe-Signature": signature},
            raw_body=raw_body + " tampered",
        )


def test_verify_signature_rejects_timestamp_beyond_tolerance() -> None:
    provider = StripeProvider(secret_key=SECRET_KEY, webhook_secret=WEBHOOK_SECRET)
    raw_body = '{"id":"evt_test"}'
    stale_timestamp = int(time.time()) - 60 * 60  # 1 hour old
    signature = _stripe_signature(WEBHOOK_SECRET, stale_timestamp, raw_body)
    with pytest.raises(ValueError, match="signature"):
        provider._verify_webhook_signature(
            headers={"Stripe-Signature": signature}, raw_body=raw_body
        )


def test_verify_signature_rejects_missing_stripe_signature_header() -> None:
    provider = StripeProvider(secret_key=SECRET_KEY, webhook_secret=WEBHOOK_SECRET)
    with pytest.raises(ValueError, match="signature"):
        provider._verify_webhook_signature(headers={}, raw_body='{"id":"evt_test"}')


def test_verify_signature_rejects_malformed_header() -> None:
    provider = StripeProvider(secret_key=SECRET_KEY, webhook_secret=WEBHOOK_SECRET)
    with pytest.raises(ValueError, match="signature"):
        provider._verify_webhook_signature(
            headers={"Stripe-Signature": "not-a-valid-format"},
            raw_body='{"id":"evt_test"}',
        )


def test_verify_signature_accepts_multiple_v1_signatures() -> None:
    """Stripe sometimes sends multiple v1=... values during key rotation.
    The verifier must accept the message if ANY v1 matches."""
    provider = StripeProvider(secret_key=SECRET_KEY, webhook_secret=WEBHOOK_SECRET)
    raw_body = '{"id":"evt_test"}'
    timestamp = int(time.time())
    valid = hmac.new(
        WEBHOOK_SECRET.encode("utf-8"),
        f"{timestamp}.{raw_body}".encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    header = f"t={timestamp},v1=deadbeef{'0' * 56},v1={valid}"
    provider._verify_webhook_signature(
        headers={"Stripe-Signature": header}, raw_body=raw_body
    )


def test_verify_signature_requires_webhook_secret_configured() -> None:
    provider = StripeProvider(secret_key=SECRET_KEY, webhook_secret=None)
    raw_body = '{"id":"evt_test"}'
    timestamp = int(time.time())
    signature = _stripe_signature(WEBHOOK_SECRET, timestamp, raw_body)
    with pytest.raises(ValueError, match="webhook"):
        provider._verify_webhook_signature(
            headers={"Stripe-Signature": signature}, raw_body=raw_body
        )


# ---------------------------------------------------------------------------
# Status normalization
# ---------------------------------------------------------------------------


def test_normalize_status_maps_succeeded_to_settled() -> None:
    assert (
        StripeProvider._normalize_status("succeeded", event_type=None)
        is BillingPaymentRequestStatus.SETTLED
    )


def test_normalize_status_maps_payment_failed_to_failed() -> None:
    assert (
        StripeProvider._normalize_status(
            "requires_payment_method", event_type="payment_intent.payment_failed"
        )
        is BillingPaymentRequestStatus.FAILED
    )


def test_normalize_status_maps_canceled_to_cancelled() -> None:
    assert (
        StripeProvider._normalize_status("canceled", event_type=None)
        is BillingPaymentRequestStatus.CANCELLED
    )


def test_normalize_status_unknown_defaults_to_pending() -> None:
    assert (
        StripeProvider._normalize_status("unknown_value", event_type=None)
        is BillingPaymentRequestStatus.PENDING
    )


# ---------------------------------------------------------------------------
# create_payment_request — PromptPay
# ---------------------------------------------------------------------------


def test_create_request_promptpay_posts_payment_intent_with_promptpay_method() -> None:
    provider = StripeProvider(secret_key=SECRET_KEY, webhook_secret=WEBHOOK_SECRET)
    captured: dict[str, object] = {}

    def fake_request(
        *, method: str, path: str, payload: Mapping[str, object] | None = None
    ):
        captured["method"] = method
        captured["path"] = path
        captured["payload"] = dict(payload or {})
        return {
            "id": "pi_test_promptpay_001",
            "amount": 150000,
            "currency": "thb",
            "status": "requires_action",
            "next_action": {
                "promptpay_display_qr_code": {
                    "data": "0002010102121234",
                    "image_url_svg": "https://files.stripe.com/qr.svg",
                },
            },
        }

    provider._request = fake_request  # type: ignore[method-assign]

    result = provider.create_payment_request(request=_request_template())

    assert captured["method"] == "POST"
    assert captured["path"] == "/v1/payment_intents"
    payload = captured["payload"]
    assert payload["currency"] == "thb"
    assert payload["amount"] == 150000
    assert payload["payment_method_types[]"] == "promptpay"
    assert result.provider is BillingPaymentProvider.STRIPE
    assert result.payment_method is BillingPaymentMethod.PROMPTPAY_QR
    assert result.qr_payload == "0002010102121234"
    assert result.provider_reference == "pi_test_promptpay_001"


def test_create_request_promptpay_fails_closed_without_qr_data() -> None:
    """Stripe MUST return next_action.promptpay_display_qr_code for the
    UI to render the code; absent that, fail rather than persist an
    unusable PaymentIntent."""
    provider = StripeProvider(secret_key=SECRET_KEY, webhook_secret=WEBHOOK_SECRET)

    def fake_request(*, method, path, payload=None):
        return {
            "id": "pi_test_no_qr",
            "amount": 150000,
            "currency": "thb",
            "status": "requires_action",
            # next_action absent
        }

    provider._request = fake_request  # type: ignore[method-assign]

    with pytest.raises(RuntimeError, match="promptpay"):
        provider.create_payment_request(request=_request_template())


def test_create_request_promptpay_rejects_amount_below_minimum() -> None:
    """Stripe Thailand minimum PromptPay charge is 10.00 THB."""
    provider = StripeProvider(secret_key=SECRET_KEY, webhook_secret=WEBHOOK_SECRET)
    with pytest.raises(ValueError, match="minimum"):
        provider.create_payment_request(
            request=_request_template(amount="5.00"),
        )


def test_create_request_promptpay_rejects_non_thb_currency() -> None:
    provider = StripeProvider(secret_key=SECRET_KEY, webhook_secret=WEBHOOK_SECRET)
    with pytest.raises(ValueError, match="THB"):
        provider.create_payment_request(
            request=_request_template(currency="USD"),
        )


# ---------------------------------------------------------------------------
# create_payment_request — Card (Payment Link)
# ---------------------------------------------------------------------------


def test_create_request_card_creates_payment_link() -> None:
    provider = StripeProvider(
        secret_key=SECRET_KEY,
        webhook_secret=WEBHOOK_SECRET,
        base_url="https://api.example.com",
    )
    captured: dict[str, object] = {}

    def fake_request(*, method, path, payload=None):
        captured["path"] = path
        captured["payload"] = dict(payload or {})
        return {
            "id": "plink_test_card_001",
            "url": "https://buy.stripe.com/test_link_001",
            "active": True,
        }

    provider._request = fake_request  # type: ignore[method-assign]

    result = provider.create_payment_request(
        request=_request_template(method=BillingPaymentMethod.CARD),
    )

    assert captured["path"] == "/v1/payment_links"
    assert result.payment_url == "https://buy.stripe.com/test_link_001"
    assert result.provider_reference == "plink_test_card_001"
    assert result.payment_method is BillingPaymentMethod.CARD


def test_create_request_card_includes_billing_metadata() -> None:
    provider = StripeProvider(secret_key=SECRET_KEY, webhook_secret=WEBHOOK_SECRET)
    captured: dict[str, object] = {}

    def fake_request(*, method, path, payload=None):
        captured["payload"] = dict(payload or {})
        return {"id": "plink_x", "url": "https://buy.stripe.com/x", "active": True}

    provider._request = fake_request  # type: ignore[method-assign]
    provider.create_payment_request(
        request=_request_template(
            method=BillingPaymentMethod.CARD,
            billing_record_id="bil-123",
            record_number="INV-2026-9999",
        ),
    )

    payload = captured["payload"]
    # `_request` is stubbed before form-encoding; metadata is still nested
    metadata = payload.get("metadata")
    assert isinstance(metadata, dict)
    assert metadata.get("billing_record_id") == "bil-123"
    assert metadata.get("record_number") == "INV-2026-9999"


def test_create_request_card_payment_link_is_restricted_to_single_use() -> None:
    """CRITICAL: without `restrictions[completed_sessions][limit]=1`, one
    invoice's Payment Link could be paid multiple times (double-charge).
    """
    provider = StripeProvider(secret_key=SECRET_KEY, webhook_secret=WEBHOOK_SECRET)
    captured: dict[str, object] = {}

    def fake_request(*, method, path, payload=None):
        captured["payload"] = dict(payload or {})
        return {"id": "plink_x", "url": "https://buy.stripe.com/x", "active": True}

    provider._request = fake_request  # type: ignore[method-assign]
    provider.create_payment_request(
        request=_request_template(method=BillingPaymentMethod.CARD),
    )

    payload = captured["payload"]
    assert (
        payload.get("restrictions[completed_sessions][limit]") == "1"
    ), "Payment Link must be single-use to prevent repeat charges per invoice"


def test_create_request_promptpay_passes_confirm_and_payment_method_data() -> None:
    """HIGH: Stripe returns `next_action.promptpay_display_qr_code` only
    after confirmation. Create must include `confirm=true` plus
    `payment_method_data[type]=promptpay`.
    """
    provider = StripeProvider(secret_key=SECRET_KEY, webhook_secret=WEBHOOK_SECRET)
    captured: dict[str, object] = {}

    def fake_request(*, method, path, payload=None):
        captured["payload"] = dict(payload or {})
        return {
            "id": "pi_test",
            "amount": 150000,
            "currency": "thb",
            "status": "requires_action",
            "next_action": {
                "promptpay_display_qr_code": {
                    "data": "0002010102121234",
                    "image_url_svg": "https://files.stripe.com/qr.svg",
                },
            },
        }

    provider._request = fake_request  # type: ignore[method-assign]
    provider.create_payment_request(request=_request_template())

    payload = captured["payload"]
    assert payload.get("confirm") == "true"
    assert payload.get("payment_method_data[type]") == "promptpay"


def test_create_request_rejects_wrong_provider() -> None:
    provider = StripeProvider(secret_key=SECRET_KEY, webhook_secret=WEBHOOK_SECRET)
    bad = ProviderPaymentRequest(
        provider=BillingPaymentProvider.OPN,  # wrong
        payment_method=BillingPaymentMethod.CARD,
        tenant_id="t",
        billing_record_id="b",
        record_number="r",
        amount="100.00",
        currency="THB",
        expires_in_minutes=30,
    )
    with pytest.raises(ValueError, match="provider"):
        provider.create_payment_request(request=bad)


# ---------------------------------------------------------------------------
# parse_callback
# ---------------------------------------------------------------------------


def _signed(provider: StripeProvider, raw_body: str) -> dict[str, str]:
    timestamp = int(time.time())
    sig = _stripe_signature(WEBHOOK_SECRET, timestamp, raw_body)
    return {"Stripe-Signature": sig}


def test_parse_callback_handles_payment_intent_succeeded() -> None:
    provider = StripeProvider(secret_key=SECRET_KEY, webhook_secret=WEBHOOK_SECRET)
    raw_body = (
        '{"id":"evt_001","type":"payment_intent.succeeded",'
        '"data":{"object":{"id":"pi_001","amount":150000,"currency":"thb",'
        '"status":"succeeded","created":1758696391}}}'
    )
    payload = {
        "id": "evt_001",
        "type": "payment_intent.succeeded",
        "created": 1758696391,
        "data": {
            "object": {
                "id": "pi_001",
                "amount": 150000,
                "currency": "thb",
                "status": "succeeded",
                "created": 1758696391,
            }
        },
    }
    parsed = provider.parse_callback(
        payload=payload, headers=_signed(provider, raw_body), raw_body=raw_body
    )
    assert parsed.provider_event_id == "evt_001"
    assert parsed.provider_reference == "pi_001"
    assert parsed.amount == "1500.00"
    assert parsed.status is BillingPaymentRequestStatus.SETTLED


def test_parse_callback_handles_payment_intent_failed() -> None:
    provider = StripeProvider(secret_key=SECRET_KEY, webhook_secret=WEBHOOK_SECRET)
    raw_body = (
        '{"id":"evt_002","type":"payment_intent.payment_failed",'
        '"data":{"object":{"id":"pi_002","amount":150000,"currency":"thb",'
        '"status":"requires_payment_method","created":1758696391}}}'
    )
    payload = {
        "id": "evt_002",
        "type": "payment_intent.payment_failed",
        "created": 1758696391,
        "data": {
            "object": {
                "id": "pi_002",
                "amount": 150000,
                "currency": "thb",
                "status": "requires_payment_method",
                "created": 1758696391,
            }
        },
    }
    parsed = provider.parse_callback(
        payload=payload, headers=_signed(provider, raw_body), raw_body=raw_body
    )
    assert parsed.status is BillingPaymentRequestStatus.FAILED


def test_parse_callback_handles_payment_intent_canceled() -> None:
    provider = StripeProvider(secret_key=SECRET_KEY, webhook_secret=WEBHOOK_SECRET)
    raw_body = (
        '{"id":"evt_003","type":"payment_intent.canceled",'
        '"data":{"object":{"id":"pi_003","amount":150000,"currency":"thb",'
        '"status":"canceled","created":1758696391}}}'
    )
    payload = {
        "id": "evt_003",
        "type": "payment_intent.canceled",
        "created": 1758696391,
        "data": {
            "object": {
                "id": "pi_003",
                "amount": 150000,
                "currency": "thb",
                "status": "canceled",
                "created": 1758696391,
            }
        },
    }
    parsed = provider.parse_callback(
        payload=payload, headers=_signed(provider, raw_body), raw_body=raw_body
    )
    assert parsed.status is BillingPaymentRequestStatus.CANCELLED


def test_parse_callback_handles_checkout_session_completed() -> None:
    """HIGH: For `checkout.session.*` events, the stored
    provider_reference is the `plink_*` Payment Link id (set at create
    time), NOT the session id `cs_*`. parse_callback must return the
    payment_link as provider_reference, with session id as reference_code.
    """
    provider = StripeProvider(secret_key=SECRET_KEY, webhook_secret=WEBHOOK_SECRET)
    raw_body = (
        '{"id":"evt_004","type":"checkout.session.completed",'
        '"data":{"object":{"id":"cs_004","payment_link":"plink_x",'
        '"amount_total":150000,"currency":"thb","payment_status":"paid",'
        '"created":1758696391}}}'
    )
    payload = {
        "id": "evt_004",
        "type": "checkout.session.completed",
        "created": 1758696391,
        "data": {
            "object": {
                "id": "cs_004",
                "payment_link": "plink_x",
                "amount_total": 150000,
                "currency": "thb",
                "payment_status": "paid",
                "created": 1758696391,
            }
        },
    }
    parsed = provider.parse_callback(
        payload=payload, headers=_signed(provider, raw_body), raw_body=raw_body
    )
    assert parsed.status is BillingPaymentRequestStatus.SETTLED
    # CRITICAL: provider_reference MUST be the Payment Link id, not the session id
    assert parsed.provider_reference == "plink_x"
    assert parsed.reference_code == "cs_004"


def test_parse_callback_checkout_session_without_payment_link_raises() -> None:
    """If a checkout.session.* event arrives with no `payment_link` field,
    we cannot match it to a stored request — fail closed rather than persist
    an event that the billing service can never reconcile.
    """
    provider = StripeProvider(secret_key=SECRET_KEY, webhook_secret=WEBHOOK_SECRET)
    raw_body = (
        '{"id":"evt_x","type":"checkout.session.completed",'
        '"data":{"object":{"id":"cs_orphan","amount_total":150000,'
        '"currency":"thb","payment_status":"paid","created":1758696391}}}'
    )
    payload = {
        "id": "evt_x",
        "type": "checkout.session.completed",
        "created": 1758696391,
        "data": {
            "object": {
                "id": "cs_orphan",
                # payment_link intentionally absent
                "amount_total": 150000,
                "currency": "thb",
                "payment_status": "paid",
                "created": 1758696391,
            }
        },
    }
    with pytest.raises(ValueError, match="payment_link"):
        provider.parse_callback(
            payload=payload, headers=_signed(provider, raw_body), raw_body=raw_body
        )


def test_parse_callback_raises_on_unsupported_event_type() -> None:
    provider = StripeProvider(secret_key=SECRET_KEY, webhook_secret=WEBHOOK_SECRET)
    raw_body = (
        '{"id":"evt_x","type":"customer.subscription.created",'
        '"data":{"object":{"id":"sub_x"}}}'
    )
    payload = {
        "id": "evt_x",
        "type": "customer.subscription.created",
        "data": {"object": {"id": "sub_x"}},
    }
    with pytest.raises(ValueError, match="unsupported"):
        provider.parse_callback(
            payload=payload, headers=_signed(provider, raw_body), raw_body=raw_body
        )


def test_parse_callback_verifies_signature_before_processing() -> None:
    provider = StripeProvider(secret_key=SECRET_KEY, webhook_secret=WEBHOOK_SECRET)
    raw_body = '{"id":"evt_x","type":"payment_intent.succeeded"}'
    with pytest.raises(ValueError, match="signature"):
        provider.parse_callback(
            payload={"id": "evt_x", "type": "payment_intent.succeeded"},
            headers={"Stripe-Signature": "t=1,v1=deadbeef"},
            raw_body=raw_body,
        )


# ---------------------------------------------------------------------------
# Subunits + error handling
# ---------------------------------------------------------------------------


def test_to_subunits_handles_thb_precision() -> None:
    assert StripeProvider._to_subunits("1500.00") == 150000
    assert StripeProvider._to_subunits("0.50") == 50
    assert StripeProvider._to_subunits("1234.56") == 123456


def test_from_subunits_renders_two_decimal_places() -> None:
    assert StripeProvider._from_subunits(150000) == "1500.00"
    assert StripeProvider._from_subunits(50) == "0.50"
    assert StripeProvider._from_subunits(0) == "0.00"


# ---------------------------------------------------------------------------
# API version pin
# ---------------------------------------------------------------------------


def test_api_version_header_is_pinned() -> None:
    """Every Stripe API call MUST send the pinned `Stripe-Version`
    header. This locks behavior across Stripe's monthly API updates."""
    # Verified through the constant on the class
    assert hasattr(StripeProvider, "_api_version")
    assert StripeProvider._api_version == "2026-04-22.dahlia"
