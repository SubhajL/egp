from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from fastapi.testclient import TestClient

from egp_api.main import create_app

TENANT_ID = "11111111-1111-1111-1111-111111111111"
OTHER_TENANT_ID = "22222222-2222-2222-2222-222222222222"


def _utc_today() -> date:
    return datetime.now(UTC).date()


def _create_client(tmp_path) -> TestClient:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'phase2-billing.sqlite3'}"
    return TestClient(
        create_app(
            artifact_root=tmp_path,
            database_url=database_url,
            auth_required=False,
            payment_callback_secret="top-secret",
        )
    )


def _create_billing_record(
    client: TestClient, *, tenant_id: str = TENANT_ID
) -> dict[str, object]:
    billing_period_start = _utc_today() - timedelta(days=1)
    response = client.post(
        "/v1/billing/records",
        json={
            "tenant_id": tenant_id,
            "record_number": "INV-2026-0001",
            "plan_code": "monthly_membership",
            "status": "awaiting_payment",
            "billing_period_start": billing_period_start.isoformat(),
            "due_at": f"{billing_period_start.isoformat()}T09:00:00+00:00",
            "amount_due": "1500.00",
            "currency": "THB",
            "notes": "Internal beta invoice",
        },
    )
    assert response.status_code == 201
    return response.json()


def _record_payment(
    client: TestClient,
    *,
    record_id: str,
    tenant_id: str = TENANT_ID,
    amount: str,
    reference_code: str,
    payment_method: str = "bank_transfer",
) -> dict[str, object]:
    response = client.post(
        f"/v1/billing/records/{record_id}/payments",
        json={
            "tenant_id": tenant_id,
            "payment_method": payment_method,
            "amount": amount,
            "currency": "THB",
            "reference_code": reference_code,
            "received_at": f"{_utc_today().isoformat()}T03:30:00+00:00",
            "note": "Customer transfer recorded by ops",
        },
    )
    assert response.status_code == 201
    return response.json()


def _reconcile_payment(
    client: TestClient,
    *,
    payment_id: str,
    tenant_id: str = TENANT_ID,
    status: str = "reconciled",
) -> dict[str, object]:
    response = client.post(
        f"/v1/billing/payments/{payment_id}/reconcile",
        json={
            "tenant_id": tenant_id,
            "status": status,
            "note": "Matched against bank transfer statement",
        },
    )
    assert response.status_code == 200
    return response.json()


def test_billing_snapshot_supports_create_record_payment_and_reconcile(
    tmp_path,
) -> None:
    client = _create_client(tmp_path)

    created = _create_billing_record(client)
    record_id = created["record"]["id"]
    assert created["record"]["status"] == "awaiting_payment"
    assert created["record"]["amount_due"] == "25.00"
    assert created["payments"] == []
    assert created["events"][0]["event_type"] == "billing_record_created"

    listed_before_payment = client.get(
        "/v1/billing/records", params={"tenant_id": TENANT_ID}
    )
    assert listed_before_payment.status_code == 200
    listed_before_body = listed_before_payment.json()
    assert listed_before_body["total"] == 1
    assert listed_before_body["summary"] == {
        "open_records": 1,
        "awaiting_reconciliation": 0,
        "outstanding_amount": "25.00",
        "collected_amount": "0.00",
    }

    payment = _record_payment(
        client,
        record_id=record_id,
        amount="25.00",
        reference_code="KBANK-0001",
    )
    payment_id = payment["id"]
    assert payment["payment_status"] == "pending_reconciliation"

    reconciled = _reconcile_payment(client, payment_id=payment_id)
    assert reconciled["record"]["status"] == "paid"
    assert reconciled["record"]["reconciled_total"] == "25.00"
    assert reconciled["record"]["outstanding_balance"] == "0.00"
    assert reconciled["subscription"]["plan_code"] == "monthly_membership"
    assert reconciled["subscription"]["subscription_status"] == "active"
    assert reconciled["subscription"]["keyword_limit"] == 5
    assert [entry["payment_status"] for entry in reconciled["payments"]] == [
        "reconciled"
    ]
    assert [entry["event_type"] for entry in reconciled["events"]] == [
        "billing_record_created",
        "payment_recorded",
        "payment_reconciled",
        "subscription_activated",
    ]

    listed_after_payment = client.get(
        "/v1/billing/records", params={"tenant_id": TENANT_ID}
    )
    assert listed_after_payment.status_code == 200
    listed_after_body = listed_after_payment.json()
    assert listed_after_body["summary"] == {
        "open_records": 0,
        "awaiting_reconciliation": 0,
        "outstanding_amount": "0.00",
        "collected_amount": "25.00",
    }
    assert listed_after_body["records"][0]["record"]["status"] == "paid"


def test_billing_snapshot_keeps_partial_payment_in_payment_detected_status(
    tmp_path,
) -> None:
    client = _create_client(tmp_path)

    created = _create_billing_record(client)
    record_id = created["record"]["id"]
    payment = _record_payment(
        client,
        record_id=record_id,
        amount="5.00",
        reference_code="KBANK-0002",
    )

    reconciled = _reconcile_payment(client, payment_id=payment["id"])

    assert reconciled["record"]["status"] == "payment_detected"
    assert reconciled["record"]["reconciled_total"] == "5.00"
    assert reconciled["record"]["outstanding_balance"] == "20.00"
    assert reconciled["payments"][0]["amount"] == "5.00"
    assert reconciled["payments"][0]["payment_status"] == "reconciled"
    assert reconciled["subscription"] is None


def test_billing_reconcile_is_idempotent_for_already_reconciled_payment(
    tmp_path,
) -> None:
    client = _create_client(tmp_path)

    created = _create_billing_record(client)
    record_id = created["record"]["id"]
    payment = _record_payment(
        client,
        record_id=record_id,
        amount="25.00",
        reference_code="KBANK-0002B",
    )

    first = _reconcile_payment(client, payment_id=payment["id"])
    second_response = client.post(
        f"/v1/billing/payments/{payment['id']}/reconcile",
        json={
            "tenant_id": TENANT_ID,
            "status": "reconciled",
            "note": "Retry webhook delivery",
        },
    )

    assert second_response.status_code == 200
    second = second_response.json()
    assert second["record"]["status"] == "paid"
    assert second["subscription"]["id"] == first["subscription"]["id"]
    assert [entry["event_type"] for entry in second["events"]].count(
        "subscription_activated"
    ) == 1


def test_billing_endpoints_are_tenant_scoped(tmp_path) -> None:
    client = _create_client(tmp_path)

    created = _create_billing_record(client)
    record_id = created["record"]["id"]

    foreign_list = client.get(
        "/v1/billing/records", params={"tenant_id": OTHER_TENANT_ID}
    )
    assert foreign_list.status_code == 200
    assert foreign_list.json()["records"] == []

    foreign_payment = client.post(
        f"/v1/billing/records/{record_id}/payments",
        json={
            "tenant_id": OTHER_TENANT_ID,
            "payment_method": "bank_transfer",
            "amount": "15000.00",
            "currency": "THB",
            "reference_code": "KBANK-0003",
            "received_at": "2026-04-16T03:30:00+00:00",
        },
    )
    assert foreign_payment.status_code == 403


def test_billing_payment_recording_rejects_non_bank_transfer_method(tmp_path) -> None:
    client = _create_client(tmp_path)

    created = _create_billing_record(client)
    record_id = created["record"]["id"]

    invalid_payment = client.post(
        f"/v1/billing/records/{record_id}/payments",
        json={
            "tenant_id": TENANT_ID,
            "payment_method": "promptpay_qr",
            "amount": "15000.00",
            "currency": "THB",
            "reference_code": "QR-0001",
            "received_at": "2026-04-16T03:30:00+00:00",
        },
    )
    assert invalid_payment.status_code == 400
    assert (
        invalid_payment.json()["detail"]
        == "manual payment endpoint only accepts bank_transfer"
    )
