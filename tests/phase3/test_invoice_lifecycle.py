from __future__ import annotations

from datetime import date, timedelta

from fastapi.testclient import TestClient

from egp_api.main import create_app

TENANT_ID = "11111111-1111-1111-1111-111111111111"
OTHER_TENANT_ID = "22222222-2222-2222-2222-222222222222"


def _create_client(tmp_path) -> TestClient:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'phase3-invoice.sqlite3'}"
    return TestClient(
        create_app(
            artifact_root=tmp_path,
            database_url=database_url,
            auth_required=False,
        )
    )


def test_invoice_lifecycle_uses_pricing_defaults_and_activates_one_time_subscription(
    tmp_path,
) -> None:
    client = _create_client(tmp_path)
    future_start = date.today() + timedelta(days=5)
    future_end = future_start + timedelta(days=2)

    plans_response = client.get("/v1/billing/plans")
    assert plans_response.status_code == 200
    plans_body = plans_response.json()
    assert [plan["code"] for plan in plans_body["plans"]] == [
        "free_trial",
        "one_time_search_pack",
        "monthly_membership",
    ]

    created_response = client.post(
        "/v1/billing/records",
        json={
            "tenant_id": TENANT_ID,
            "record_number": "INV-2026-1001",
            "plan_code": "one_time_search_pack",
            "status": "draft",
            "billing_period_start": future_start.isoformat(),
        },
    )
    assert created_response.status_code == 201
    created = created_response.json()
    assert created["record"]["status"] == "draft"
    assert created["record"]["billing_period_end"] == future_end.isoformat()
    assert created["record"]["amount_due"] == "300.00"
    assert created["subscription"] is None

    record_id = created["record"]["id"]
    issued_response = client.post(
        f"/v1/billing/records/{record_id}/transition",
        json={
            "tenant_id": TENANT_ID,
            "status": "issued",
            "note": "Issued to customer",
        },
    )
    assert issued_response.status_code == 200
    issued = issued_response.json()
    assert issued["record"]["status"] == "issued"
    assert issued["record"]["issued_at"] is not None

    awaiting_response = client.post(
        f"/v1/billing/records/{record_id}/transition",
        json={
            "tenant_id": TENANT_ID,
            "status": "awaiting_payment",
            "note": "Sent payment instructions",
        },
    )
    assert awaiting_response.status_code == 200
    awaiting = awaiting_response.json()
    assert awaiting["record"]["status"] == "awaiting_payment"

    payment_response = client.post(
        f"/v1/billing/records/{record_id}/payments",
        json={
            "tenant_id": TENANT_ID,
            "payment_method": "bank_transfer",
            "amount": "300.00",
            "currency": "THB",
            "reference_code": "KBANK-OT-001",
            "received_at": f"{future_start.isoformat()}T03:30:00+00:00",
            "note": "Customer transfer",
        },
    )
    assert payment_response.status_code == 201
    payment = payment_response.json()

    reconciled_response = client.post(
        f"/v1/billing/payments/{payment['id']}/reconcile",
        json={
            "tenant_id": TENANT_ID,
            "status": "reconciled",
            "note": "Matched against statement",
        },
    )
    assert reconciled_response.status_code == 200
    reconciled = reconciled_response.json()
    assert reconciled["record"]["status"] == "paid"
    assert reconciled["subscription"]["subscription_status"] == "pending_activation"
    assert reconciled["subscription"]["plan_code"] == "one_time_search_pack"
    assert reconciled["subscription"]["keyword_limit"] == 1
    assert (
        reconciled["subscription"]["billing_period_start"] == future_start.isoformat()
    )
    assert reconciled["subscription"]["billing_period_end"] == future_end.isoformat()
    assert [entry["event_type"] for entry in reconciled["events"]] == [
        "billing_record_created",
        "billing_record_status_changed",
        "billing_record_status_changed",
        "payment_recorded",
        "payment_reconciled",
        "subscription_activated",
    ]


def test_monthly_membership_partial_payment_does_not_activate_subscription(
    tmp_path,
) -> None:
    client = _create_client(tmp_path)

    created_response = client.post(
        "/v1/billing/records",
        json={
            "tenant_id": TENANT_ID,
            "record_number": "INV-2026-1002",
            "plan_code": "monthly_membership",
            "status": "awaiting_payment",
            "billing_period_start": "2026-04-01",
        },
    )
    assert created_response.status_code == 201
    created = created_response.json()
    assert created["record"]["billing_period_end"] == "2026-04-30"
    assert created["record"]["amount_due"] == "1500.00"

    payment_response = client.post(
        f"/v1/billing/records/{created['record']['id']}/payments",
        json={
            "tenant_id": TENANT_ID,
            "payment_method": "bank_transfer",
            "amount": "500.00",
            "currency": "THB",
            "reference_code": "KBANK-MM-001",
            "received_at": "2026-04-02T03:30:00+00:00",
        },
    )
    assert payment_response.status_code == 201
    payment = payment_response.json()

    reconciled_response = client.post(
        f"/v1/billing/payments/{payment['id']}/reconcile",
        json={
            "tenant_id": TENANT_ID,
            "status": "reconciled",
            "note": "Partial settlement",
        },
    )
    assert reconciled_response.status_code == 200
    reconciled = reconciled_response.json()
    assert reconciled["record"]["status"] == "payment_detected"
    assert reconciled["record"]["outstanding_balance"] == "1000.00"
    assert reconciled["subscription"] is None


def test_invoice_transitions_and_activation_remain_tenant_scoped(tmp_path) -> None:
    client = _create_client(tmp_path)
    future_start = date.today() + timedelta(days=10)

    created_response = client.post(
        "/v1/billing/records",
        json={
            "tenant_id": TENANT_ID,
            "record_number": "INV-2026-1003",
            "plan_code": "one_time_search_pack",
            "status": "draft",
            "billing_period_start": future_start.isoformat(),
        },
    )
    assert created_response.status_code == 201
    record_id = created_response.json()["record"]["id"]

    foreign_transition = client.post(
        f"/v1/billing/records/{record_id}/transition",
        json={
            "tenant_id": OTHER_TENANT_ID,
            "status": "issued",
        },
    )
    assert foreign_transition.status_code == 403
