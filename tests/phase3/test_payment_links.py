from __future__ import annotations

import base64
import hashlib
import hmac
from datetime import UTC, date, datetime, timedelta
import pytest
from fastapi.testclient import TestClient

from egp_api.main import create_app
from egp_api.services.payment_provider import (
    CreatedPaymentRequest,
    OpnProvider,
    ParsedPaymentCallback,
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
    response = client.post(
        "/v1/billing/records",
        json={
            "tenant_id": tenant_id,
            "record_number": "INV-2026-3001",
            "plan_code": "monthly_membership",
            "status": "awaiting_payment",
            "billing_period_start": "2026-04-01",
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
    assert response.status_code == 201
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
            "occurred_at": "2026-04-05T05:30:00+00:00",
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


def test_one_time_opn_promptpay_webhook_settles_and_activates_subscription(tmp_path) -> None:
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
    assert settled["payment_requests"][0]["id"] == request_detail["payment_requests"][0]["id"]
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
    assert settled["payment_requests"][0]["id"] == request_detail["payment_requests"][0]["id"]
    assert settled["subscription"]["plan_code"] == "monthly_membership"
    assert settled["subscription"]["keyword_limit"] == 5

    listed = client.get("/v1/billing/records", params={"tenant_id": TENANT_ID})
    assert listed.status_code == 200
    trial_record = next(
        detail
        for detail in listed.json()["records"]
        if detail["subscription"] is not None and detail["subscription"]["id"] == trial_subscription_id
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

    parsed = provider.parse_callback(
        headers={"x-opn-signature": _opn_signature("skey_test_example", '{"id":"evt_test_card_001","key":"charge.complete","data":{"object":"charge","id":"chrg_test_card_001"}}')},
        raw_body='{"id":"evt_test_card_001","key":"charge.complete","data":{"object":"charge","id":"chrg_test_card_001"}}',
        payload={
            "id": "evt_test_card_001",
            "key": "charge.complete",
            "data": {
                "object": "charge",
                "id": "chrg_test_card_001",
            },
        }
    )

    assert parsed.provider_event_id == "evt_test_card_001"
    assert parsed.provider_reference == "link_test_card_001"
    assert parsed.reference_code == "chrg_test_card_001"
    assert parsed.status is BillingPaymentRequestStatus.SETTLED


def test_opn_request_encoding_flattens_nested_metadata() -> None:
    payload = OpnProvider._flatten_payload(
        {
            "amount": 150000,
            "metadata": {
                "billing_record_id": "record-123",
                "record_number": "INV-123",
            },
        }
    )

    assert payload == [
        ("amount", "150000"),
        ("metadata[billing_record_id]", "record-123"),
        ("metadata[record_number]", "INV-123"),
    ]
