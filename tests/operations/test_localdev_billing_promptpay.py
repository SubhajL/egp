"""Localhost billing: the mock PromptPay provider must be fully configured for
local dev so the "Create PromptPay QR" step works without external services.

Regression guard: docker-compose-localdev.yml shipped
``EGP_PAYMENT_PROVIDER=mock_promptpay`` but never wired ``EGP_PROMPTPAY_PROXY_ID``,
so ``build_payment_provider()`` returned ``None`` and the upgrade/billing flow
raised "payment provider is not configured" at the QR step.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from egp_api.services.payment_provider import (
    ProviderPaymentRequest,
    build_payment_provider,
)
from egp_shared_types.enums import BillingPaymentMethod, BillingPaymentProvider

REPO_ROOT = Path(__file__).resolve().parents[2]
LOCALDEV_COMPOSE = REPO_ROOT / "docker-compose-localdev.yml"


def _localdev_api_env() -> dict:
    compose = yaml.safe_load(LOCALDEV_COMPOSE.read_text(encoding="utf-8"))
    return compose["services"]["api"]["environment"]


def test_localdev_api_defaults_to_mock_promptpay_provider() -> None:
    env = _localdev_api_env()
    assert env.get("EGP_PAYMENT_PROVIDER") == "${EGP_PAYMENT_PROVIDER:-mock_promptpay}"


def test_localdev_api_wires_nonempty_promptpay_proxy_id() -> None:
    raw = _localdev_api_env().get("EGP_PROMPTPAY_PROXY_ID")
    assert raw is not None, (
        "localdev api must wire EGP_PROMPTPAY_PROXY_ID, or the mock_promptpay "
        "provider resolves to None and billing raises 'payment provider is not "
        "configured' at the Create-PromptPay-QR step"
    )
    # Must carry a NON-EMPTY default (${VAR:-<value>}), not the empty :- form,
    # so a plain local boot self-configures the PromptPay QR.
    assert raw.startswith("${EGP_PROMPTPAY_PROXY_ID:-") and not raw.endswith(":-}"), (
        f"EGP_PROMPTPAY_PROXY_ID must default to a non-empty dev proxy id, got {raw!r}"
    )


def test_mock_promptpay_builds_qr_with_a_proxy_id() -> None:
    provider = build_payment_provider(
        provider_name="mock_promptpay",
        base_url="http://localhost:8000",
        promptpay_proxy_id="0899999999",
    )
    assert provider is not None
    created = provider.create_payment_request(
        request=ProviderPaymentRequest(
            provider=BillingPaymentProvider.MOCK_PROMPTPAY,
            payment_method=BillingPaymentMethod.PROMPTPAY_QR,
            tenant_id="tenant",
            billing_record_id="record",
            record_number="UPG-TEST-0001",
            amount="25.00",
            currency="THB",
            expires_in_minutes=30,
        )
    )
    assert created.qr_payload, "mock PromptPay must return an EMVCo QR payload"
    assert created.qr_svg.startswith("<svg"), (
        "mock PromptPay must return a rendered QR SVG"
    )


def test_mock_promptpay_without_proxy_id_is_unconfigured() -> None:
    # Documents the exact failure mode the localdev wiring must avoid.
    assert (
        build_payment_provider(
            provider_name="mock_promptpay",
            base_url="http://localhost:8000",
            promptpay_proxy_id=None,
        )
        is None
    )
