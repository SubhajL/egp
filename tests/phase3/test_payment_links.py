from __future__ import annotations

import base64
import hashlib
import hmac
import time
from datetime import UTC, date, datetime, timedelta
import pytest
from fastapi.testclient import TestClient

from egp_api.main import create_app
from egp_api.services.payment_provider import (
    CreatedPaymentRequest,
    OpnProvider,
    ParsedPaymentCallback,
    ProviderPaymentRequest,
    StripeProvider,
)
from egp_shared_types.enums import (
    BillingPaymentMethod,
    BillingPaymentProvider,
    BillingPaymentRequestStatus,
)

TENANT_ID = "11111111-1111-1111-1111-111111111111"
OTHER_TENANT_ID = "22222222-2222-2222-2222-222222222222"


def _utc_today() -> date:
    return datetime.now(UTC).date()


class FailingPaymentProvider:
    def create_payment_request(self, **kwargs):
        raise RuntimeError("provider unavailable")

    def parse_callback(self, **kwargs):
        raise RuntimeError("provider unavailable")


class StubOpnProvider:
    def __init__(self) -> None:
        self.created_requests: list[object] = []
        self.last_amount = "25.00"

    def create_payment_request(self, *, request):
        self.created_requests.append(request)
        self.last_amount = str(request.amount)
        if request.payment_method is BillingPaymentMethod.CARD:
            return CreatedPaymentRequest(
                provider=BillingPaymentProvider.OPN,
                payment_method=BillingPaymentMethod.CARD,
                status=BillingPaymentRequestStatus.PENDING,
                provider_reference="link_test_card_001",
                payment_url="https://link.omise.co/card-001",
                qr_payload="",
                qr_svg="",
                amount=request.amount,
                currency=request.currency,
                expires_at="2026-04-05T05:30:00+00:00",
            )
        return CreatedPaymentRequest(
            provider=BillingPaymentProvider.OPN,
            payment_method=BillingPaymentMethod.PROMPTPAY_QR,
            status=BillingPaymentRequestStatus.PENDING,
            provider_reference="chrg_test_promptpay_001",
            payment_url="https://api.omise.co/charges/chrg_test_promptpay_001/qrcode.svg",
            qr_payload="0002010102121234",
            qr_svg="<svg></svg>",
            amount=request.amount,
            currency=request.currency,
            expires_at="2026-04-05T05:30:00+00:00",
        )

    def parse_callback(self, *, payload, headers=None, raw_body=None):
        signature = str((headers or {}).get("x-opn-signature") or "").strip()
        if not signature or raw_body is None:
            raise ValueError("invalid opn webhook signature")
        expected = _opn_signature("skey_test_opn", raw_body)
        if signature != expected:
            raise ValueError("invalid opn webhook signature")
        kind = str(payload.get("kind") or "promptpay").strip()
        if kind == "card":
            return ParsedPaymentCallback(
                provider_event_id="evnt_test_card_001",
                provider_reference="link_test_card_001",
                status=BillingPaymentRequestStatus.SETTLED,
                amount=self.last_amount,
                currency="THB",
                occurred_at="2026-04-05T05:30:00+00:00",
                reference_code="chrg_test_card_charge_001",
                payload_json='{"kind":"card"}',
            )
        return ParsedPaymentCallback(
            provider_event_id="evnt_test_promptpay_001",
            provider_reference="chrg_test_promptpay_001",
            status=BillingPaymentRequestStatus.SETTLED,
            amount=self.last_amount,
            currency="THB",
            occurred_at="2026-04-05T05:30:00+00:00",
            reference_code="chrg_test_promptpay_001",
            payload_json='{"kind":"promptpay"}',
        )


def _create_client(
    tmp_path, payment_provider=None, callback_secret: str | None = "top-secret"
) -> TestClient:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'phase3-payment-links.sqlite3'}"
    return TestClient(
        create_app(
            artifact_root=tmp_path,
            database_url=database_url,
            auth_required=False,
            payment_provider=payment_provider,
            payment_base_url="https://pay.egp.test",
            promptpay_proxy_id="0801234567",
            payment_callback_secret=callback_secret,
            opn_secret_key="skey_test_opn",
        )
    )


def _opn_signature(secret: str, raw_body: str) -> str:
    digest = hmac.new(
        secret.encode("utf-8"),
        raw_body.encode("utf-8"),
        hashlib.sha256,
    ).digest()
    return base64.b64encode(digest).decode("ascii")


def _omise_signature(webhook_secret: str, timestamp: str, raw_body: str) -> str:
    decoded_secret = base64.b64decode(webhook_secret, validate=True)
    signed_payload = f"{timestamp}.{raw_body}".encode("utf-8")
    return hmac.new(decoded_secret, signed_payload, hashlib.sha256).hexdigest()


def test_create_app_requires_payment_callback_secret(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'phase3-payment-links.sqlite3'}"
    monkeypatch.delenv("EGP_PAYMENT_CALLBACK_SECRET", raising=False)

    try:
        create_app(
            artifact_root=tmp_path,
            database_url=database_url,
            auth_required=False,
            payment_base_url="https://pay.egp.test",
            promptpay_proxy_id="0801234567",
            payment_callback_secret="",
        )
    except RuntimeError as exc:
        assert str(exc) == "payment callback secret is required"
    else:
        raise AssertionError("expected create_app to require payment callback secret")


def _create_billing_record(
    client: TestClient, *, tenant_id: str = TENANT_ID
) -> dict[str, object]:
    billing_period_start = _utc_today()
    response = client.post(
        "/v1/billing/records",
        json={
            "tenant_id": tenant_id,
            "record_number": "INV-2026-3001",
            "plan_code": "monthly_membership",
            "status": "awaiting_payment",
            "billing_period_start": billing_period_start.isoformat(),
        },
    )
    assert response.status_code == 201
    return response.json()


def _create_payment_request(
    client: TestClient,
    *,
    record_id: str,
    tenant_id: str = TENANT_ID,
    provider: str = "mock_promptpay",
    payment_method: str = "promptpay_qr",
) -> dict[str, object]:
    response = client.post(
        f"/v1/billing/records/{record_id}/payment-requests",
        json={
            "tenant_id": tenant_id,
            "provider": provider,
            "payment_method": payment_method,
            "expires_in_minutes": 30,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _settle_request(
    client: TestClient,
    *,
    request_id: str,
    tenant_id: str = TENANT_ID,
    provider_event_id: str = "evt-settled-001",
    callback_secret: str | None = "top-secret",
) -> dict[str, object]:
    response = client.post(
        f"/v1/billing/payment-requests/{request_id}/callbacks",
        json={
            "tenant_id": tenant_id,
            "provider_event_id": provider_event_id,
            "status": "settled",
            "amount": "25.00",
            "currency": "THB",
            "occurred_at": f"{_utc_today().isoformat()}T05:30:00+00:00",
            "reference_code": "PROMPTPAY-3001",
        },
        headers=(
            {"x-egp-payment-callback-secret": callback_secret}
            if callback_secret is not None
            else None
        ),
    )
    assert response.status_code == 200
    return response.json()


def test_create_payment_request_returns_promptpay_qr_and_payment_link(tmp_path) -> None:
    client = _create_client(tmp_path)
    created = _create_billing_record(client)

    detail = _create_payment_request(client, record_id=str(created["record"]["id"]))

    request = detail["payment_requests"][0]
    assert detail["record"]["id"] == created["record"]["id"]
    assert request["provider"] == "mock_promptpay"
    assert request["status"] == "pending"
    assert request["payment_method"] == "promptpay_qr"
    assert request["payment_url"].startswith("https://pay.egp.test/checkout/")
    assert request["amount"] == "25.00"
    assert request["qr_payload"]
    assert request["qr_svg"].startswith("<svg")
    assert request["expires_at"] is not None


def test_create_payment_request_supports_opn_promptpay_qr(tmp_path) -> None:
    provider = StubOpnProvider()
    client = _create_client(tmp_path, payment_provider=provider)
    created = _create_billing_record(client)

    detail = _create_payment_request(
        client,
        record_id=str(created["record"]["id"]),
        provider="opn",
        payment_method="promptpay_qr",
    )

    request = detail["payment_requests"][0]
    assert request["provider"] == "opn"
    assert request["payment_method"] == "promptpay_qr"
    assert request["provider_reference"] == "chrg_test_promptpay_001"
    assert (
        request["payment_url"]
        == "https://api.omise.co/charges/chrg_test_promptpay_001/qrcode.svg"
    )
    assert request["qr_payload"] == "0002010102121234"
    assert request["qr_svg"].startswith("<svg")


def test_create_payment_request_supports_opn_card_checkout(tmp_path) -> None:
    provider = StubOpnProvider()
    client = _create_client(tmp_path, payment_provider=provider)
    created = _create_billing_record(client)

    detail = _create_payment_request(
        client,
        record_id=str(created["record"]["id"]),
        provider="opn",
        payment_method="card",
    )

    request = detail["payment_requests"][0]
    assert request["provider"] == "opn"
    assert request["payment_method"] == "card"
    assert request["provider_reference"] == "link_test_card_001"
    assert request["payment_url"] == "https://link.omise.co/card-001"
    assert request["qr_payload"] == ""
    assert request["qr_svg"] == ""


def test_create_payment_request_rejects_terminal_billing_record(tmp_path) -> None:
    client = _create_client(tmp_path)
    created = _create_billing_record(client)
    record_id = str(created["record"]["id"])
    request_detail = _create_payment_request(client, record_id=record_id)
    request_id = str(request_detail["payment_requests"][0]["id"])
    _settle_request(client, request_id=request_id)

    response = client.post(
        f"/v1/billing/records/{record_id}/payment-requests",
        json={
            "tenant_id": TENANT_ID,
            "provider": "mock_promptpay",
        },
    )
    assert response.status_code == 400


def test_create_payment_request_rejects_stale_unpaid_record(tmp_path) -> None:
    client = _create_client(tmp_path)
    stale_start = _utc_today() - timedelta(days=40)
    trial_response = client.post(
        "/v1/billing/trial/start",
        json={"tenant_id": TENANT_ID},
    )
    assert trial_response.status_code == 201
    response = client.post(
        "/v1/billing/upgrades",
        json={
            "tenant_id": TENANT_ID,
            "record_number": "INV-STALE-PAY-0001",
            "target_plan_code": "one_time_search_pack",
            "billing_period_start": stale_start.isoformat(),
        },
    )
    assert response.status_code == 201

    payment_response = client.post(
        f"/v1/billing/records/{response.json()['record']['id']}/payment-requests",
        json={
            "tenant_id": TENANT_ID,
            "provider": "mock_promptpay",
        },
    )

    assert payment_response.status_code == 400
    assert (
        payment_response.json()["detail"]
        == "stale unpaid billing record is not payable"
    )


def test_callback_settles_invoice_and_activates_subscription_once(tmp_path) -> None:
    client = _create_client(tmp_path)
    created = _create_billing_record(client)
    request_detail = _create_payment_request(
        client, record_id=str(created["record"]["id"])
    )
    request_id = str(request_detail["payment_requests"][0]["id"])

    first = _settle_request(
        client, request_id=request_id, provider_event_id="evt-settled-002"
    )
    second = _settle_request(
        client, request_id=request_id, provider_event_id="evt-settled-002"
    )

    assert first["record"]["status"] == "paid"
    assert first["subscription"]["subscription_status"] == "active"
    assert [payment["payment_method"] for payment in first["payments"]] == [
        "promptpay_qr"
    ]
    assert [payment["payment_status"] for payment in first["payments"]] == [
        "reconciled"
    ]
    assert first["payment_requests"][0]["status"] == "settled"
    assert second["subscription"]["id"] == first["subscription"]["id"]
    assert len(second["payments"]) == 1
    assert [entry["event_type"] for entry in second["events"]].count(
        "subscription_activated"
    ) == 1


def test_payment_request_and_callback_are_tenant_scoped(tmp_path) -> None:
    client = _create_client(tmp_path)
    created = _create_billing_record(client)
    request_detail = _create_payment_request(
        client, record_id=str(created["record"]["id"])
    )
    request_id = str(request_detail["payment_requests"][0]["id"])

    foreign_create = client.post(
        f"/v1/billing/records/{created['record']['id']}/payment-requests",
        json={
            "tenant_id": OTHER_TENANT_ID,
            "provider": "mock_promptpay",
        },
    )
    assert foreign_create.status_code == 403

    foreign_callback = client.post(
        f"/v1/billing/payment-requests/{request_id}/callbacks",
        json={
            "tenant_id": OTHER_TENANT_ID,
            "provider_event_id": "evt-foreign-001",
            "status": "settled",
            "amount": "25.00",
            "currency": "THB",
            "occurred_at": "2026-04-05T05:30:00+00:00",
        },
        headers={"x-egp-payment-callback-secret": "top-secret"},
    )
    assert foreign_callback.status_code == 403


def test_provider_creation_failure_returns_502_without_persisting_request(
    tmp_path,
) -> None:
    client = _create_client(tmp_path, payment_provider=FailingPaymentProvider())
    created = _create_billing_record(client)
    record_id = str(created["record"]["id"])

    response = client.post(
        f"/v1/billing/records/{record_id}/payment-requests",
        json={
            "tenant_id": TENANT_ID,
            "provider": "mock_promptpay",
        },
    )
    assert response.status_code == 502

    listed = client.get("/v1/billing/records", params={"tenant_id": TENANT_ID})
    assert listed.status_code == 200
    assert listed.json()["records"][0]["payment_requests"] == []


def test_callback_requires_configured_secret(tmp_path) -> None:
    client = _create_client(tmp_path, callback_secret="top-secret")
    created = _create_billing_record(client)
    request_detail = _create_payment_request(
        client, record_id=str(created["record"]["id"])
    )
    request_id = str(request_detail["payment_requests"][0]["id"])

    unauthorized = client.post(
        f"/v1/billing/payment-requests/{request_id}/callbacks",
        json={
            "tenant_id": TENANT_ID,
            "provider_event_id": "evt-secret-001",
            "status": "settled",
            "amount": "25.00",
            "currency": "THB",
            "occurred_at": "2026-04-05T05:30:00+00:00",
        },
    )
    assert unauthorized.status_code == 401

    settled = _settle_request(
        client,
        request_id=request_id,
        provider_event_id="evt-secret-002",
        callback_secret="top-secret",
    )
    assert settled["record"]["status"] == "paid"


def test_opn_webhook_settles_promptpay_request_without_shared_secret(tmp_path) -> None:
    provider = StubOpnProvider()
    client = _create_client(tmp_path, payment_provider=provider)
    created = _create_billing_record(client)
    request_detail = _create_payment_request(
        client,
        record_id=str(created["record"]["id"]),
        provider="opn",
        payment_method="promptpay_qr",
    )

    raw_body = '{"kind":"promptpay"}'
    response = client.post(
        "/v1/billing/providers/opn/webhooks",
        content=raw_body,
        headers={
            "content-type": "application/json",
            "x-opn-signature": _opn_signature("skey_test_opn", raw_body),
        },
    )

    assert response.status_code == 200
    settled = response.json()
    assert settled["record"]["status"] == "paid"
    assert (
        settled["payment_requests"][0]["id"]
        == request_detail["payment_requests"][0]["id"]
    )
    assert [payment["payment_method"] for payment in settled["payments"]] == [
        "promptpay_qr"
    ]


def test_opn_webhook_settles_card_request_without_shared_secret(tmp_path) -> None:
    provider = StubOpnProvider()
    client = _create_client(tmp_path, payment_provider=provider)
    created = _create_billing_record(client)
    request_detail = _create_payment_request(
        client,
        record_id=str(created["record"]["id"]),
        provider="opn",
        payment_method="card",
    )

    raw_body = '{"kind":"card"}'
    response = client.post(
        "/v1/billing/providers/opn/webhooks",
        content=raw_body,
        headers={
            "content-type": "application/json",
            "x-opn-signature": _opn_signature("skey_test_opn", raw_body),
        },
    )

    assert response.status_code == 200
    settled = response.json()
    assert settled["record"]["status"] == "paid"
    assert (
        settled["payment_requests"][0]["id"]
        == request_detail["payment_requests"][0]["id"]
    )
    assert [payment["payment_method"] for payment in settled["payments"]] == ["card"]


def test_opn_webhook_rejects_missing_signature(tmp_path) -> None:
    provider = StubOpnProvider()
    client = _create_client(tmp_path, payment_provider=provider)
    created = _create_billing_record(client)
    _create_payment_request(
        client,
        record_id=str(created["record"]["id"]),
        provider="opn",
        payment_method="promptpay_qr",
    )

    response = client.post(
        "/v1/billing/providers/opn/webhooks",
        json={"kind": "promptpay"},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "invalid opn webhook signature"


def test_one_time_opn_promptpay_webhook_settles_and_activates_subscription(
    tmp_path,
) -> None:
    provider = StubOpnProvider()
    client = _create_client(tmp_path, payment_provider=provider)
    future_start = _utc_today() + timedelta(days=1)
    created_response = client.post(
        "/v1/billing/records",
        json={
            "tenant_id": TENANT_ID,
            "record_number": "INV-2026-3002",
            "plan_code": "one_time_search_pack",
            "status": "awaiting_payment",
            "billing_period_start": future_start.isoformat(),
        },
    )
    assert created_response.status_code == 201
    created = created_response.json()
    request_detail = _create_payment_request(
        client,
        record_id=str(created["record"]["id"]),
        provider="opn",
        payment_method="promptpay_qr",
    )

    raw_body = '{"kind":"promptpay"}'
    response = client.post(
        "/v1/billing/providers/opn/webhooks",
        content=raw_body,
        headers={
            "content-type": "application/json",
            "x-opn-signature": _opn_signature("skey_test_opn", raw_body),
        },
    )

    assert response.status_code == 200
    settled = response.json()
    assert settled["record"]["id"] == created["record"]["id"]
    assert settled["record"]["status"] == "paid"
    assert (
        settled["payment_requests"][0]["id"]
        == request_detail["payment_requests"][0]["id"]
    )
    assert settled["subscription"]["plan_code"] == "one_time_search_pack"
    assert settled["subscription"]["subscription_status"] == "pending_activation"
    assert settled["subscription"]["keyword_limit"] == 1


def test_opn_webhook_settles_upgrade_record_and_supersedes_trial(tmp_path) -> None:
    provider = StubOpnProvider()
    client = _create_client(tmp_path, payment_provider=provider)
    today = _utc_today()

    trial_response = client.post(
        "/v1/billing/trial/start",
        json={"tenant_id": TENANT_ID},
    )
    assert trial_response.status_code == 201
    trial_subscription_id = trial_response.json()["id"]

    upgrade_response = client.post(
        "/v1/billing/upgrades",
        json={
            "tenant_id": TENANT_ID,
            "target_plan_code": "monthly_membership",
            "billing_period_start": today.isoformat(),
        },
    )
    assert upgrade_response.status_code == 201
    upgrade = upgrade_response.json()

    request_detail = _create_payment_request(
        client,
        record_id=str(upgrade["record"]["id"]),
        provider="opn",
        payment_method="promptpay_qr",
    )

    raw_body = '{"kind":"promptpay"}'
    response = client.post(
        "/v1/billing/providers/opn/webhooks",
        content=raw_body,
        headers={
            "content-type": "application/json",
            "x-opn-signature": _opn_signature("skey_test_opn", raw_body),
        },
    )

    assert response.status_code == 200
    settled = response.json()
    assert (
        settled["payment_requests"][0]["id"]
        == request_detail["payment_requests"][0]["id"]
    )
    assert settled["subscription"]["plan_code"] == "monthly_membership"
    assert settled["subscription"]["keyword_limit"] is None

    listed = client.get("/v1/billing/records", params={"tenant_id": TENANT_ID})
    assert listed.status_code == 200
    trial_record = next(
        detail
        for detail in listed.json()["records"]
        if detail["subscription"] is not None
        and detail["subscription"]["id"] == trial_subscription_id
    )
    assert trial_record["subscription"]["subscription_status"] == "cancelled"


def test_opn_charge_callback_uses_link_reference_for_card_requests() -> None:
    provider = OpnProvider(secret_key="skey_test_example")

    def fake_request(*, method: str, path: str, payload=None):
        assert method == "GET"
        assert path == "/charges/chrg_test_card_001"
        assert payload is None
        return {
            "id": "chrg_test_card_001",
            "link": "link_test_card_001",
            "amount": 150000,
            "currency": "thb",
            "status": "successful",
            "paid_at": "2026-04-05T05:30:00+00:00",
        }

    provider._request = fake_request  # type: ignore[method-assign]

    raw_body = (
        '{"id":"evt_test_card_001","key":"charge.complete",'
        '"data":{"object":"charge","id":"chrg_test_card_001"}}'
    )
    parsed = provider.parse_callback(
        headers={"x-opn-signature": _opn_signature("skey_test_example", raw_body)},
        raw_body=raw_body,
        payload={
            "id": "evt_test_card_001",
            "key": "charge.complete",
            "data": {
                "object": "charge",
                "id": "chrg_test_card_001",
            },
        },
    )

    assert parsed.provider_event_id == "evt_test_card_001"
    assert parsed.provider_reference == "link_test_card_001"
    assert parsed.reference_code == "chrg_test_card_001"
    assert parsed.status is BillingPaymentRequestStatus.SETTLED


def test_opn_charge_callback_accepts_omise_signature_headers() -> None:
    webhook_secret = base64.b64encode(b"test-webhook-secret").decode("ascii")
    provider = OpnProvider(
        secret_key="skey_test_example",
        webhook_secret=webhook_secret,
    )

    def fake_request(*, method: str, path: str, payload=None):
        assert method == "GET"
        assert path == "/charges/chrg_test_card_002"
        assert payload is None
        return {
            "id": "chrg_test_card_002",
            "link": "link_test_card_002",
            "amount": 150000,
            "currency": "thb",
            "status": "successful",
            "paid_at": "2026-04-05T05:30:00+00:00",
        }

    provider._request = fake_request  # type: ignore[method-assign]

    timestamp = "1758696391"
    raw_body = (
        '{"id":"evt_test_card_002","key":"charge.complete",'
        '"data":{"object":"charge","id":"chrg_test_card_002"}}'
    )
    parsed = provider.parse_callback(
        headers={
            "omise-signature": _omise_signature(webhook_secret, timestamp, raw_body),
            "omise-signature-timestamp": timestamp,
        },
        raw_body=raw_body,
        payload={
            "id": "evt_test_card_002",
            "key": "charge.complete",
            "data": {
                "object": "charge",
                "id": "chrg_test_card_002",
            },
        },
    )

    assert parsed.provider_event_id == "evt_test_card_002"
    assert parsed.provider_reference == "link_test_card_002"
    assert parsed.reference_code == "chrg_test_card_002"
    assert parsed.status is BillingPaymentRequestStatus.SETTLED


def test_opn_promptpay_request_prefers_authorize_uri_and_sets_return_and_webhook_urls() -> (
    None
):
    provider = OpnProvider(
        secret_key="skey_test_example",
        base_url="https://api.egp.test",
        web_base_url="https://app.egp.test",
    )
    captured_requests: list[tuple[str, str, dict[str, object] | None]] = []

    def fake_request(*, method: str, path: str, payload=None):
        captured_requests.append((method, path, payload))
        if path == "/sources":
            return {
                "id": "src_test_promptpay_001",
                "scannable_code": {
                    "value": "0002010102121234",
                    "image": {
                        "download_uri": "https://api.omise.co/charges/chrg_test_promptpay_001/qrcode.svg",
                    },
                },
                "expires_at": "2026-04-05T05:30:00+00:00",
            }
        if path == "/charges":
            return {
                "id": "chrg_test_promptpay_001",
                "status": "pending",
                "authorize_uri": "https://pay.omise.co/payments/pay2_test_promptpay_001/authorize",
                "expires_at": "2026-04-05T05:30:00+00:00",
                "source": {
                    "scannable_code": {
                        "value": "0002010102121234",
                        "image": {
                            "download_uri": "https://api.omise.co/charges/chrg_test_promptpay_001/qrcode.svg",
                        },
                    },
                },
            }
        raise AssertionError(f"unexpected path: {path}")

    provider._request = fake_request  # type: ignore[method-assign]

    created = provider.create_payment_request(
        request=ProviderPaymentRequest(
            provider=BillingPaymentProvider.OPN,
            payment_method=BillingPaymentMethod.PROMPTPAY_QR,
            tenant_id=TENANT_ID,
            billing_record_id="record-123",
            record_number="INV-123",
            amount="25.00",
            currency="THB",
            expires_in_minutes=30,
        )
    )

    assert (
        created.payment_url
        == "https://pay.omise.co/payments/pay2_test_promptpay_001/authorize"
    )
    assert created.provider_reference == "chrg_test_promptpay_001"
    assert captured_requests == [
        (
            "POST",
            "/sources",
            {
                "amount": 2500,
                "currency": "thb",
                "type": "promptpay",
            },
        ),
        (
            "POST",
            "/charges",
            {
                "amount": 2500,
                "currency": "thb",
                "source": "src_test_promptpay_001",
                "description": "Billing record INV-123",
                "metadata": {
                    "billing_record_id": "record-123",
                    "record_number": "INV-123",
                },
                "return_uri": "https://app.egp.test/billing?record_id=record-123&payment_return=opn",
                "webhook_endpoints": [
                    "https://api.egp.test/v1/billing/providers/opn/webhooks"
                ],
            },
        ),
    ]


def test_opn_request_encoding_flattens_nested_metadata() -> None:
    payload = OpnProvider._flatten_payload(
        {
            "amount": 150000,
            "metadata": {
                "billing_record_id": "record-123",
                "record_number": "INV-123",
            },
            "webhook_endpoints": [
                "https://api.egp.test/v1/billing/providers/opn/webhooks"
            ],
        }
    )

    assert payload == [
        ("amount", "150000"),
        ("metadata[billing_record_id]", "record-123"),
        ("metadata[record_number]", "INV-123"),
        (
            "webhook_endpoints[]",
            "https://api.egp.test/v1/billing/providers/opn/webhooks",
        ),
    ]


# ============================================================================
# Stripe webhook route integration tests (PR-G)
# ============================================================================
#
# These tests use the REAL `StripeProvider` with `_request` stubbed only for
# payment-request creation, so webhook signature verification + parse_callback
# remain real. The webhook endpoint at `/v1/billing/providers/stripe/webhooks`
# must mirror OPN's behavior (raw body required, 400 on signature mismatch,
# 404 on unknown payment reference) and bypass the auth middleware.

STRIPE_SECRET_KEY = "sk_test_egp_pr_g_dont_use_in_prod"
STRIPE_WEBHOOK_SECRET = "whsec_egp_pr_g_dont_use_in_prod"


def _stripe_signature_header(secret: str, timestamp: int, raw_body: str) -> str:
    digest = hmac.new(
        secret.encode("utf-8"),
        f"{timestamp}.{raw_body}".encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return f"t={timestamp},v1={digest}"


def _build_stripe_provider() -> StripeProvider:
    """Build a real StripeProvider; tests stub `_request` per scenario."""
    return StripeProvider(
        secret_key=STRIPE_SECRET_KEY,
        webhook_secret=STRIPE_WEBHOOK_SECRET,
        base_url="https://api.egp.test",
    )


def _stub_promptpay_create(provider: StripeProvider) -> None:
    """Stub Stripe API for PaymentIntent create — returns a real-shaped
    response so create_payment_request returns successfully."""

    def fake_request(*, method, path, payload=None):
        assert method == "POST"
        assert path == "/v1/payment_intents"
        return {
            "id": "pi_test_promptpay_g1",
            "amount": payload["amount"] if payload else 2500,
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


def _stub_card_create(provider: StripeProvider) -> None:
    """Stub Stripe API for Payment Link create."""

    def fake_request(*, method, path, payload=None):
        assert method == "POST"
        assert path == "/v1/payment_links"
        return {
            "id": "plink_test_card_g1",
            "url": "https://buy.stripe.com/test_card_g1",
            "active": True,
        }

    provider._request = fake_request  # type: ignore[method-assign]


def test_stripe_webhook_settles_promptpay_request(tmp_path) -> None:
    provider = _build_stripe_provider()
    _stub_promptpay_create(provider)
    client = _create_client(tmp_path, payment_provider=provider)
    created = _create_billing_record(client)
    request_detail = _create_payment_request(
        client,
        record_id=str(created["record"]["id"]),
        provider="stripe",
        payment_method="promptpay_qr",
    )

    # Real webhook payload + real signature
    raw_body = (
        '{"id":"evt_test_g1","type":"payment_intent.succeeded","created":1758696391,'
        '"data":{"object":{"id":"pi_test_promptpay_g1","amount":2500,"currency":"thb",'
        '"status":"succeeded","created":1758696391}}}'
    )
    timestamp = int(time.time())
    response = client.post(
        "/v1/billing/providers/stripe/webhooks",
        content=raw_body,
        headers={
            "content-type": "application/json",
            "stripe-signature": _stripe_signature_header(
                STRIPE_WEBHOOK_SECRET, timestamp, raw_body
            ),
        },
    )

    assert response.status_code == 200, response.text
    settled = response.json()
    assert settled["record"]["status"] == "paid"
    assert (
        settled["payment_requests"][0]["id"]
        == request_detail["payment_requests"][0]["id"]
    )


def test_stripe_webhook_settles_card_payment_link_session(tmp_path) -> None:
    """For checkout.session.* events, the route must locate the request by
    `payment_link` (not session id) — PR-F's parse_callback fix.
    """
    provider = _build_stripe_provider()
    _stub_card_create(provider)
    client = _create_client(tmp_path, payment_provider=provider)
    created = _create_billing_record(client)
    request_detail = _create_payment_request(
        client,
        record_id=str(created["record"]["id"]),
        provider="stripe",
        payment_method="card",
    )

    raw_body = (
        '{"id":"evt_test_g2","type":"checkout.session.completed","created":1758696400,'
        '"data":{"object":{"id":"cs_test_session_g1","payment_link":"plink_test_card_g1",'
        '"amount_total":2500,"currency":"thb","payment_status":"paid","created":1758696400}}}'
    )
    timestamp = int(time.time())
    response = client.post(
        "/v1/billing/providers/stripe/webhooks",
        content=raw_body,
        headers={
            "content-type": "application/json",
            "stripe-signature": _stripe_signature_header(
                STRIPE_WEBHOOK_SECRET, timestamp, raw_body
            ),
        },
    )

    assert response.status_code == 200, response.text
    settled = response.json()
    assert settled["record"]["status"] == "paid"
    assert (
        settled["payment_requests"][0]["id"]
        == request_detail["payment_requests"][0]["id"]
    )


def test_stripe_webhook_rejects_invalid_signature(tmp_path) -> None:
    provider = _build_stripe_provider()
    _stub_promptpay_create(provider)
    client = _create_client(tmp_path, payment_provider=provider)
    created = _create_billing_record(client)
    _create_payment_request(
        client,
        record_id=str(created["record"]["id"]),
        provider="stripe",
        payment_method="promptpay_qr",
    )

    raw_body = (
        '{"id":"evt_bad","type":"payment_intent.succeeded","created":1758696391,'
        '"data":{"object":{"id":"pi_test_promptpay_g1","amount":2500,"currency":"thb",'
        '"status":"succeeded","created":1758696391}}}'
    )
    response = client.post(
        "/v1/billing/providers/stripe/webhooks",
        content=raw_body,
        headers={
            "content-type": "application/json",
            "stripe-signature": "t=1,v1=deadbeef",
        },
    )

    assert response.status_code == 400
    assert "signature" in response.json()["detail"].lower()


def test_stripe_webhook_returns_404_for_unknown_payment_reference(tmp_path) -> None:
    """Stripe stops retrying on 4xx; an unknown payment_intent id should
    return 404 rather than 5xx (matches OPN behavior)."""
    provider = _build_stripe_provider()
    client = _create_client(tmp_path, payment_provider=provider)
    # Note: no payment request created — webhook references something unknown

    raw_body = (
        '{"id":"evt_unknown","type":"payment_intent.succeeded","created":1758696391,'
        '"data":{"object":{"id":"pi_unknown_ref","amount":2500,"currency":"thb",'
        '"status":"succeeded","created":1758696391}}}'
    )
    timestamp = int(time.time())
    response = client.post(
        "/v1/billing/providers/stripe/webhooks",
        content=raw_body,
        headers={
            "content-type": "application/json",
            "stripe-signature": _stripe_signature_header(
                STRIPE_WEBHOOK_SECRET, timestamp, raw_body
            ),
        },
    )

    assert response.status_code == 404


def test_stripe_webhook_rejects_malformed_json(tmp_path) -> None:
    provider = _build_stripe_provider()
    client = _create_client(tmp_path, payment_provider=provider)

    response = client.post(
        "/v1/billing/providers/stripe/webhooks",
        content="not valid json {{{",
        headers={"content-type": "application/json"},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "invalid json payload"


def test_stripe_webhook_endpoint_bypasses_auth_when_required(tmp_path) -> None:
    """Even with auth_required=True, the Stripe webhook endpoint must
    accept unauthenticated requests (Stripe doesn't send Authorization).
    """
    provider = _build_stripe_provider()
    _stub_promptpay_create(provider)
    client = _create_client(tmp_path, payment_provider=provider)
    created = _create_billing_record(client)
    _create_payment_request(
        client,
        record_id=str(created["record"]["id"]),
        provider="stripe",
        payment_method="promptpay_qr",
    )
    # Flip auth on AFTER seeding so the webhook test exercises the bypass
    client.app.state.auth_required = True

    raw_body = (
        '{"id":"evt_auth_test","type":"payment_intent.succeeded","created":1758696391,'
        '"data":{"object":{"id":"pi_test_promptpay_g1","amount":2500,"currency":"thb",'
        '"status":"succeeded","created":1758696391}}}'
    )
    timestamp = int(time.time())
    response = client.post(
        "/v1/billing/providers/stripe/webhooks",
        content=raw_body,
        headers={
            "content-type": "application/json",
            "stripe-signature": _stripe_signature_header(
                STRIPE_WEBHOOK_SECRET, timestamp, raw_body
            ),
            # No Authorization header — proves middleware bypass
        },
    )

    # Auth bypass works → status is NOT 401/403; webhook either settles or
    # returns a domain error (200 expected for happy path)
    assert response.status_code == 200, (
        f"middleware bypass broken: {response.status_code} {response.text}"
    )


def test_stripe_webhook_settles_idempotently_on_duplicate_event(tmp_path) -> None:
    """Stripe retries webhooks on non-2xx delivery. If a duplicate event
    arrives, the second call must still return 2xx (DB UNIQUE on
    billing_provider_events(provider, provider_event_id) makes it
    idempotent at the service layer)."""
    provider = _build_stripe_provider()
    _stub_promptpay_create(provider)
    client = _create_client(tmp_path, payment_provider=provider)
    created = _create_billing_record(client)
    _create_payment_request(
        client,
        record_id=str(created["record"]["id"]),
        provider="stripe",
        payment_method="promptpay_qr",
    )

    raw_body = (
        '{"id":"evt_dup_001","type":"payment_intent.succeeded","created":1758696391,'
        '"data":{"object":{"id":"pi_test_promptpay_g1","amount":2500,"currency":"thb",'
        '"status":"succeeded","created":1758696391}}}'
    )
    timestamp = int(time.time())
    headers = {
        "content-type": "application/json",
        "stripe-signature": _stripe_signature_header(
            STRIPE_WEBHOOK_SECRET, timestamp, raw_body
        ),
    }

    first = client.post(
        "/v1/billing/providers/stripe/webhooks", content=raw_body, headers=headers
    )
    second = client.post(
        "/v1/billing/providers/stripe/webhooks", content=raw_body, headers=headers
    )

    assert first.status_code == 200
    # Duplicate must not error; record stays paid
    assert second.status_code == 200
    assert second.json()["record"]["status"] == "paid"


def test_stripe_webhook_amount_mismatch_fails_atomically_and_allows_retry(
    tmp_path,
) -> None:
    """QCHECK PR-G #1 regression: a Stripe webhook with the wrong amount
    must fail BEFORE any DB mutation. Without that ordering fix, the
    first delivery would land the event row + mark the request settled,
    then a Stripe retry would hit the UNIQUE constraint, short-circuit,
    and return 200 without recording payment — silent corruption.

    This test verifies the fix: mismatched amount returns 400 cleanly,
    no mutation happens, AND a subsequent CORRECT webhook delivery (with
    a fresh event_id, as Stripe would send after the operator fixes the
    mismatch) settles the request properly.
    """
    provider = _build_stripe_provider()
    _stub_promptpay_create(provider)
    client = _create_client(tmp_path, payment_provider=provider)
    created = _create_billing_record(client)
    _create_payment_request(
        client,
        record_id=str(created["record"]["id"]),
        provider="stripe",
        payment_method="promptpay_qr",
    )

    # First delivery: amount is WRONG (Stripe sent 9900 satang = ฿99,
    # not ฿25 like the request).
    bad_body = (
        '{"id":"evt_mismatch","type":"payment_intent.succeeded","created":1758696391,'
        '"data":{"object":{"id":"pi_test_promptpay_g1","amount":9900,"currency":"thb",'
        '"status":"succeeded","created":1758696391}}}'
    )
    timestamp = int(time.time())
    response = client.post(
        "/v1/billing/providers/stripe/webhooks",
        content=bad_body,
        headers={
            "content-type": "application/json",
            "stripe-signature": _stripe_signature_header(
                STRIPE_WEBHOOK_SECRET, timestamp, bad_body
            ),
        },
    )
    assert response.status_code == 400
    assert "amount" in response.json()["detail"].lower()

    # The bad delivery MUST NOT have mutated state. Re-deliver the SAME
    # bad event (same event_id) and verify it still returns 400 — proves
    # the event row was never inserted (otherwise UNIQUE constraint
    # would silently short-circuit with 200).
    timestamp_retry = int(time.time())
    retry_response = client.post(
        "/v1/billing/providers/stripe/webhooks",
        content=bad_body,
        headers={
            "content-type": "application/json",
            "stripe-signature": _stripe_signature_header(
                STRIPE_WEBHOOK_SECRET, timestamp_retry, bad_body
            ),
        },
    )
    assert retry_response.status_code == 400, (
        f"retry of bad webhook must re-fail with 400; got "
        f"{retry_response.status_code} {retry_response.text}. "
        "If 200: validation runs AFTER mutation (QCHECK PR-G regression)."
    )

    # Now a CORRECT delivery (different event_id, right amount) succeeds.
    good_body = (
        '{"id":"evt_correct","type":"payment_intent.succeeded","created":1758696400,'
        '"data":{"object":{"id":"pi_test_promptpay_g1","amount":2500,"currency":"thb",'
        '"status":"succeeded","created":1758696400}}}'
    )
    timestamp2 = int(time.time())
    response2 = client.post(
        "/v1/billing/providers/stripe/webhooks",
        content=good_body,
        headers={
            "content-type": "application/json",
            "stripe-signature": _stripe_signature_header(
                STRIPE_WEBHOOK_SECRET, timestamp2, good_body
            ),
        },
    )
    assert response2.status_code == 200, response2.text
    assert response2.json()["record"]["status"] == "paid"
