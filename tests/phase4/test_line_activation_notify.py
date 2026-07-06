"""Admin/manual activation notifies the customer over LINE.

A LINE slip verification already pushes a confirmation to the customer. This
covers the OTHER activation path — an admin reconciling a payment in the console
(e.g. a bank transfer) — which must reuse the LINE contact learned from the
tenant's slip history and push a subscription-activated notice exactly once.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from egp_api.main import create_app
from egp_api.services.line_slip_service import LineSlipService
from egp_db.repositories.line_payment_repo import LinePaymentRepository

TENANT_ID = "11111111-1111-1111-1111-111111111111"
CUSTOMER_LINE_ID = "Ucustomer-manual"


class FakeMessaging:
    def __init__(self) -> None:
        self.pushed: list[tuple[str, str]] = []

    def get_message_content(self, message_id: str) -> tuple[bytes, str | None]:
        return b"", None

    def push_message(self, *, to: str, text: str) -> None:
        self.pushed.append((to, text))


class FakeArtifactStore:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    def put_bytes(
        self, *, key: str, data: bytes, content_type: str | None = None
    ) -> str:
        self.objects[key] = data
        return key

    def get_bytes(self, key: str) -> bytes:
        return self.objects[key]


@pytest.fixture()
def harness(tmp_path):
    database_url = f"sqlite+pysqlite:///{tmp_path / 'line-activation.sqlite3'}"
    app = create_app(
        artifact_root=tmp_path, database_url=database_url, auth_required=False
    )
    fake_messaging = FakeMessaging()
    line_repo = LinePaymentRepository(engine=app.state.db_engine)
    app.state.line_slip_service = LineSlipService(
        line_repository=line_repo,
        billing_repository=app.state.billing_repository,
        billing_service=app.state.billing_service,
        artifact_store=FakeArtifactStore(),
        messaging_client=fake_messaging,
        admin_user_ids=(),
        admin_console_base_url="https://admin.example.com",
    )
    return TestClient(app), fake_messaging, line_repo


def _create_paid_record_and_pending_payment(client: TestClient) -> tuple[str, str]:
    """Create a monthly record starting today with a pending payment; return (record_id, payment_id)."""
    today = datetime.now(UTC).date()
    created = client.post(
        "/v1/billing/records",
        json={
            "tenant_id": TENANT_ID,
            "record_number": f"INV-ACT-{today.isoformat()}",
            "plan_code": "monthly_membership",
            "status": "awaiting_payment",
            "billing_period_start": today.isoformat(),
            "amount_due": "1500.00",
            "currency": "THB",
        },
    )
    assert created.status_code == 201, created.text
    record_id = created.json()["record"]["id"]
    payment = client.post(
        f"/v1/billing/records/{record_id}/payments",
        json={
            "tenant_id": TENANT_ID,
            "payment_method": "bank_transfer",
            "amount": "1500.00",
            "currency": "THB",
            "reference_code": "KBANK-ACT-1",
            "received_at": f"{today.isoformat()}T03:30:00+00:00",
        },
    )
    assert payment.status_code == 201, payment.text
    return record_id, payment.json()["id"]


def _link_line_contact(line_repo: LinePaymentRepository, *, record_id: str) -> None:
    """Simulate the tenant having previously paid via LINE (learns the contact)."""
    slip, _ = line_repo.create_slip(
        line_user_id=CUSTOMER_LINE_ID,
        line_message_id="m-earlier-slip",
        received_at=datetime.now(UTC).isoformat(),
    )
    line_repo.match_slip(
        slip_id=slip.id,
        tenant_id=TENANT_ID,
        billing_record_id=record_id,
        reference_code_match="INV-EARLIER",
    )


def test_admin_reconcile_pushes_activation_notice_to_customer(harness) -> None:
    client, fake_messaging, line_repo = harness
    record_id, payment_id = _create_paid_record_and_pending_payment(client)
    _link_line_contact(line_repo, record_id=record_id)

    reconciled = client.post(
        f"/v1/billing/payments/{payment_id}/reconcile",
        json={"tenant_id": TENANT_ID, "status": "reconciled"},
    )
    assert reconciled.status_code == 200, reconciled.text
    assert reconciled.json()["subscription"]["subscription_status"] == "active"

    activation_pushes = [
        (to, text) for to, text in fake_messaging.pushed if to == CUSTOMER_LINE_ID
    ]
    assert len(activation_pushes) == 1
    assert "เปิดใช้งานสมาชิก" in activation_pushes[0][1]
    # The friendly plan label is included.
    assert "Monthly Membership" in activation_pushes[0][1]


def test_reconcile_does_not_notify_when_no_line_contact(harness) -> None:
    client, fake_messaging, _ = harness
    _, payment_id = _create_paid_record_and_pending_payment(client)
    # No LINE contact linked for this tenant.
    reconciled = client.post(
        f"/v1/billing/payments/{payment_id}/reconcile",
        json={"tenant_id": TENANT_ID, "status": "reconciled"},
    )
    assert reconciled.status_code == 200, reconciled.text
    assert reconciled.json()["subscription"]["subscription_status"] == "active"
    assert fake_messaging.pushed == []


def test_repeated_reconcile_notifies_customer_only_once(harness) -> None:
    client, fake_messaging, line_repo = harness
    record_id, payment_id = _create_paid_record_and_pending_payment(client)
    _link_line_contact(line_repo, record_id=record_id)

    first = client.post(
        f"/v1/billing/payments/{payment_id}/reconcile",
        json={"tenant_id": TENANT_ID, "status": "reconciled"},
    )
    assert first.status_code == 200, first.text
    # Idempotent re-reconcile of the already-settled payment must not re-notify.
    second = client.post(
        f"/v1/billing/payments/{payment_id}/reconcile",
        json={"tenant_id": TENANT_ID, "status": "reconciled"},
    )
    assert second.status_code == 200, second.text

    activation_pushes = [
        to for to, _ in fake_messaging.pushed if to == CUSTOMER_LINE_ID
    ]
    assert len(activation_pushes) == 1


def test_second_payment_on_active_record_does_not_renotify(harness) -> None:
    client, fake_messaging, line_repo = harness
    record_id, payment_id = _create_paid_record_and_pending_payment(client)
    _link_line_contact(line_repo, record_id=record_id)

    first = client.post(
        f"/v1/billing/payments/{payment_id}/reconcile",
        json={"tenant_id": TENANT_ID, "status": "reconciled"},
    )
    assert first.status_code == 200, first.text

    # A duplicate/correcting bank transfer recorded + reconciled on the already
    # PAID+ACTIVE record must NOT push a second activation notice.
    today = datetime.now(UTC).date()
    second_payment = client.post(
        f"/v1/billing/records/{record_id}/payments",
        json={
            "tenant_id": TENANT_ID,
            "payment_method": "bank_transfer",
            "amount": "1500.00",
            "currency": "THB",
            "reference_code": "KBANK-ACT-2",
            "received_at": f"{today.isoformat()}T05:30:00+00:00",
        },
    )
    assert second_payment.status_code == 201, second_payment.text
    second = client.post(
        f"/v1/billing/payments/{second_payment.json()['id']}/reconcile",
        json={"tenant_id": TENANT_ID, "status": "reconciled"},
    )
    assert second.status_code == 200, second.text

    activation_pushes = [to for to, _ in fake_messaging.pushed if to == CUSTOMER_LINE_ID]
    assert len(activation_pushes) == 1


def test_underpayment_does_not_notify(harness) -> None:
    client, fake_messaging, line_repo = harness
    today = datetime.now(UTC).date()
    created = client.post(
        "/v1/billing/records",
        json={
            "tenant_id": TENANT_ID,
            "record_number": "INV-UNDERPAY-1",
            "plan_code": "monthly_membership",
            "status": "awaiting_payment",
            "billing_period_start": today.isoformat(),
            "amount_due": "1500.00",
            "currency": "THB",
        },
    )
    assert created.status_code == 201, created.text
    record_id = created.json()["record"]["id"]
    _link_line_contact(line_repo, record_id=record_id)

    # The test env charges 25.00 for monthly (_TEST_CHARGED_PLAN_AMOUNTS), so pay
    # under that to force PAYMENT_DETECTED (no activation).
    partial = client.post(
        f"/v1/billing/records/{record_id}/payments",
        json={
            "tenant_id": TENANT_ID,
            "payment_method": "bank_transfer",
            "amount": "1.00",
            "currency": "THB",
            "reference_code": "KBANK-PARTIAL",
            "received_at": f"{today.isoformat()}T03:30:00+00:00",
        },
    )
    assert partial.status_code == 201, partial.text
    reconciled = client.post(
        f"/v1/billing/payments/{partial.json()['id']}/reconcile",
        json={"tenant_id": TENANT_ID, "status": "reconciled"},
    )
    assert reconciled.status_code == 200, reconciled.text
    # Under-payment: record is payment_detected, no active subscription -> no push,
    # even though a LINE contact exists for the tenant.
    assert reconciled.json()["subscription"] is None
    assert fake_messaging.pushed == []
