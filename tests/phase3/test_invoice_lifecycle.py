from __future__ import annotations

from datetime import date, timedelta
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import text

from egp_api.main import create_app
from egp_db.repositories.billing_repo import create_billing_repository

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


def _seed_subscription(
    client: TestClient,
    *,
    plan_code: str,
    billing_period_start: date,
    billing_period_end: date,
    keyword_limit: int,
    status: str = "active",
) -> str:
    record_id = str(uuid4())
    subscription_id = str(uuid4())
    with client.app.state.db_engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO billing_records (
                    id,
                    tenant_id,
                    record_number,
                    plan_code,
                    status,
                    billing_period_start,
                    billing_period_end,
                    currency,
                    amount_due,
                    created_at,
                    updated_at
                ) VALUES (
                    :id,
                    :tenant_id,
                    :record_number,
                    :plan_code,
                    'paid',
                    :billing_period_start,
                    :billing_period_end,
                    'THB',
                    '0.00',
                    '2026-04-08T00:00:00+00:00',
                    '2026-04-08T00:00:00+00:00'
                )
                """
            ),
            {
                "id": record_id,
                "tenant_id": TENANT_ID,
                "record_number": f"SEED-{record_id[:8]}",
                "plan_code": plan_code,
                "billing_period_start": billing_period_start.isoformat(),
                "billing_period_end": billing_period_end.isoformat(),
            },
        )
        connection.execute(
            text(
                """
                INSERT INTO billing_subscriptions (
                    id,
                    tenant_id,
                    billing_record_id,
                    plan_code,
                    status,
                    billing_period_start,
                    billing_period_end,
                    keyword_limit,
                    activated_at,
                    created_at,
                    updated_at
                ) VALUES (
                    :id,
                    :tenant_id,
                    :billing_record_id,
                    :plan_code,
                    :status,
                    :billing_period_start,
                    :billing_period_end,
                    :keyword_limit,
                    '2026-04-08T00:00:00+00:00',
                    '2026-04-08T00:00:00+00:00',
                    '2026-04-08T00:00:00+00:00'
                )
                """
            ),
            {
                "id": subscription_id,
                "tenant_id": TENANT_ID,
                "billing_record_id": record_id,
                "plan_code": plan_code,
                "status": status,
                "billing_period_start": billing_period_start.isoformat(),
                "billing_period_end": billing_period_end.isoformat(),
                "keyword_limit": keyword_limit,
            },
        )
    return subscription_id


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
    assert created["record"]["amount_due"] == "20.00"
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
            "amount": "20.00",
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
    assert created["record"]["amount_due"] == "25.00"

    payment_response = client.post(
        f"/v1/billing/records/{created['record']['id']}/payments",
        json={
            "tenant_id": TENANT_ID,
            "payment_method": "bank_transfer",
            "amount": "5.00",
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
    assert reconciled["record"]["outstanding_balance"] == "20.00"
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


def test_free_trial_can_request_upgrade_to_one_time_search_pack(tmp_path) -> None:
    client = _create_client(tmp_path)
    today = date.today()
    trial_subscription_id = _seed_subscription(
        client,
        plan_code="free_trial",
        billing_period_start=today,
        billing_period_end=today + timedelta(days=6),
        keyword_limit=1,
    )

    response = client.post(
        "/v1/billing/upgrades",
        json={
            "tenant_id": TENANT_ID,
            "target_plan_code": "one_time_search_pack",
            "billing_period_start": today.isoformat(),
        },
    )

    assert response.status_code == 201
    detail = response.json()
    assert detail["record"]["plan_code"] == "one_time_search_pack"
    assert detail["record"]["amount_due"] == "20.00"
    assert detail["record"]["upgrade_from_subscription_id"] == trial_subscription_id
    assert detail["record"]["upgrade_mode"] == "replace_now"


def test_one_time_can_request_upgrade_to_monthly_membership(tmp_path) -> None:
    client = _create_client(tmp_path)
    today = date.today()
    one_time_subscription_id = _seed_subscription(
        client,
        plan_code="one_time_search_pack",
        billing_period_start=today,
        billing_period_end=today + timedelta(days=2),
        keyword_limit=1,
    )

    response = client.post(
        "/v1/billing/upgrades",
        json={
            "tenant_id": TENANT_ID,
            "target_plan_code": "monthly_membership",
            "billing_period_start": today.isoformat(),
        },
    )

    assert response.status_code == 201
    detail = response.json()
    assert detail["record"]["plan_code"] == "monthly_membership"
    assert detail["record"]["amount_due"] == "25.00"
    assert detail["record"]["upgrade_from_subscription_id"] == one_time_subscription_id
    assert detail["record"]["upgrade_mode"] == "replace_now"


def test_monthly_membership_cannot_downgrade_via_upgrade_api(tmp_path) -> None:
    client = _create_client(tmp_path)
    today = date.today()
    _seed_subscription(
        client,
        plan_code="monthly_membership",
        billing_period_start=today,
        billing_period_end=today + timedelta(days=29),
        keyword_limit=5,
    )

    response = client.post(
        "/v1/billing/upgrades",
        json={
            "tenant_id": TENANT_ID,
            "target_plan_code": "one_time_search_pack",
            "billing_period_start": today.isoformat(),
        },
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "unsupported subscription upgrade"


def test_duplicate_in_flight_upgrade_is_rejected(tmp_path) -> None:
    client = _create_client(tmp_path)
    today = date.today()
    _seed_subscription(
        client,
        plan_code="free_trial",
        billing_period_start=today,
        billing_period_end=today + timedelta(days=6),
        keyword_limit=1,
    )

    first_response = client.post(
        "/v1/billing/upgrades",
        json={
            "tenant_id": TENANT_ID,
            "target_plan_code": "monthly_membership",
            "billing_period_start": today.isoformat(),
        },
    )
    assert first_response.status_code == 201

    second_response = client.post(
        "/v1/billing/upgrades",
        json={
            "tenant_id": TENANT_ID,
            "target_plan_code": "monthly_membership",
            "billing_period_start": today.isoformat(),
        },
    )

    assert second_response.status_code == 400
    assert (
        second_response.json()["detail"]
        == "upgrade already in progress for subscription"
    )


def test_upgrade_with_unknown_target_plan_returns_unsupported_upgrade(tmp_path) -> None:
    client = _create_client(tmp_path)
    today = date.today()
    _seed_subscription(
        client,
        plan_code="free_trial",
        billing_period_start=today,
        billing_period_end=today + timedelta(days=6),
        keyword_limit=1,
    )

    response = client.post(
        "/v1/billing/upgrades",
        json={
            "tenant_id": TENANT_ID,
            "target_plan_code": "enterprise_membership",
            "billing_period_start": today.isoformat(),
        },
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "unsupported subscription upgrade"


def test_future_start_upgrade_creates_replace_on_activation_record(tmp_path) -> None:
    client = _create_client(tmp_path)
    today = date.today()
    source_subscription_id = _seed_subscription(
        client,
        plan_code="one_time_search_pack",
        billing_period_start=today,
        billing_period_end=today + timedelta(days=2),
        keyword_limit=1,
    )

    response = client.post(
        "/v1/billing/upgrades",
        json={
            "tenant_id": TENANT_ID,
            "target_plan_code": "monthly_membership",
            "billing_period_start": (today + timedelta(days=1)).isoformat(),
        },
    )

    assert response.status_code == 201
    detail = response.json()
    assert detail["record"]["amount_due"] == "25.00"
    assert detail["record"]["upgrade_from_subscription_id"] == source_subscription_id
    assert detail["record"]["upgrade_mode"] == "replace_on_activation"


def test_future_start_upgrade_settlement_preserves_current_active_subscription(
    tmp_path,
) -> None:
    client = _create_client(tmp_path)
    today = date.today()
    source_subscription_id = _seed_subscription(
        client,
        plan_code="one_time_search_pack",
        billing_period_start=today,
        billing_period_end=today + timedelta(days=2),
        keyword_limit=1,
    )
    future_start = today + timedelta(days=5)

    upgrade_response = client.post(
        "/v1/billing/upgrades",
        json={
            "tenant_id": TENANT_ID,
            "target_plan_code": "monthly_membership",
            "billing_period_start": future_start.isoformat(),
        },
    )
    assert upgrade_response.status_code == 201
    upgrade_detail = upgrade_response.json()

    payment_response = client.post(
        f"/v1/billing/records/{upgrade_detail['record']['id']}/payments",
        json={
            "tenant_id": TENANT_ID,
            "payment_method": "bank_transfer",
            "amount": "25.00",
            "currency": "THB",
            "reference_code": "KBANK-UPG-FUTURE-001",
            "received_at": f"{today.isoformat()}T03:30:00+00:00",
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
    assert reconciled["record"]["upgrade_mode"] == "replace_on_activation"
    assert reconciled["subscription"]["subscription_status"] == "pending_activation"
    assert reconciled["subscription"]["plan_code"] == "monthly_membership"

    listed = client.get("/v1/billing/records", params={"tenant_id": TENANT_ID})
    assert listed.status_code == 200
    source_record = next(
        detail
        for detail in listed.json()["records"]
        if detail["subscription"] is not None
        and detail["subscription"]["id"] == source_subscription_id
    )
    assert source_record["subscription"]["subscription_status"] == "active"


def test_repository_rejects_duplicate_open_upgrade_insert_even_without_precheck(
    tmp_path,
) -> None:
    client = _create_client(tmp_path)
    today = date.today()
    source_subscription_id = _seed_subscription(
        client,
        plan_code="free_trial",
        billing_period_start=today,
        billing_period_end=today + timedelta(days=6),
        keyword_limit=1,
    )
    repository = create_billing_repository(
        engine=client.app.state.db_engine,
        bootstrap_schema=False,
    )

    repository.create_billing_record(
        tenant_id=TENANT_ID,
        record_number="UPG-DB-1",
        plan_code="monthly_membership",
        status="awaiting_payment",
        billing_period_start=today.isoformat(),
        billing_period_end=(today + timedelta(days=29)).isoformat(),
        amount_due="1500.00",
        upgrade_from_subscription_id=source_subscription_id,
        upgrade_mode="replace_now",
    )

    try:
        repository.create_billing_record(
            tenant_id=TENANT_ID,
            record_number="UPG-DB-2",
            plan_code="monthly_membership",
            status="awaiting_payment",
            billing_period_start=today.isoformat(),
            billing_period_end=(today + timedelta(days=29)).isoformat(),
            amount_due="1500.00",
            upgrade_from_subscription_id=source_subscription_id,
            upgrade_mode="replace_now",
        )
    except ValueError as exc:
        assert str(exc) == "upgrade already in progress for subscription"
    else:
        raise AssertionError("expected duplicate open upgrade insert to be rejected")
