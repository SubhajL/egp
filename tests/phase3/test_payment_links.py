from __future__ import annotations

from fastapi.testclient import TestClient

from egp_api.main import create_app

TENANT_ID = "11111111-1111-1111-1111-111111111111"
OTHER_TENANT_ID = "22222222-2222-2222-2222-222222222222"


class FailingPaymentProvider:
    def create_payment_request(self, **kwargs):
        raise RuntimeError("provider unavailable")

    def parse_callback(self, **kwargs):
        raise RuntimeError("provider unavailable")


def _create_client(
    tmp_path, payment_provider=None, callback_secret: str | None = None
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
        )
    )


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
) -> dict[str, object]:
    response = client.post(
        f"/v1/billing/records/{record_id}/payment-requests",
        json={
            "tenant_id": tenant_id,
            "provider": "mock_promptpay",
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
    callback_secret: str | None = None,
) -> dict[str, object]:
    response = client.post(
        f"/v1/billing/payment-requests/{request_id}/callbacks",
        json={
            "tenant_id": tenant_id,
            "provider_event_id": provider_event_id,
            "status": "settled",
            "amount": "1500.00",
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
    assert request["qr_payload"]
    assert request["qr_svg"].startswith("<svg")
    assert request["expires_at"] is not None


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
            "amount": "1500.00",
            "currency": "THB",
            "occurred_at": "2026-04-05T05:30:00+00:00",
        },
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
            "amount": "1500.00",
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
