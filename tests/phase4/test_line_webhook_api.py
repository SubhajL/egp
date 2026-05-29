"""Integration tests for the LINE webhook + admin slip verification flow.

Builds the API app on SQLite (the billing test pattern) and injects a fake LINE
messaging client + in-memory artifact store so no network or LINE credentials
are needed.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
from datetime import date

import pytest
from fastapi.testclient import TestClient
from jose import jwt

from egp_api.main import create_app
from egp_api.services.line_slip_service import LineSlipService
from egp_db.repositories.line_payment_repo import LinePaymentRepository

TENANT_ID = "11111111-1111-1111-1111-111111111111"
OTHER_TENANT_ID = "22222222-2222-2222-2222-222222222222"
CHANNEL_SECRET = "line-webhook-secret"
ADMIN_LINE_ID = "Uadmin"
JWT_SECRET = "line-test-jwt-secret"


def _auth_headers(tenant_id: str, *, role: str = "admin") -> dict[str, str]:
    token = jwt.encode(
        {"sub": "00000000-0000-0000-0000-0000000000aa", "tenant_id": tenant_id, "role": role},
        JWT_SECRET,
        algorithm="HS256",
    )
    return {"Authorization": f"Bearer {token}"}


class FakeMessaging:
    def __init__(self) -> None:
        self.pushed: list[tuple[str, str]] = []
        self.content = b"\xff\xd8\xff\xe0fake-jpeg-bytes"

    def get_message_content(self, message_id: str) -> tuple[bytes, str | None]:
        return self.content, "image/jpeg"

    def push_message(self, *, to: str, text: str) -> None:
        self.pushed.append((to, text))


class FakeArtifactStore:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    def put_bytes(self, *, key: str, data: bytes, content_type: str | None = None) -> str:
        self.objects[key] = data
        return key

    def get_bytes(self, key: str) -> bytes:
        return self.objects[key]

    def delete(self, key: str) -> None:
        self.objects.pop(key, None)

    def download_url(self, key: str, *, expires_in: int = 300) -> str:
        return f"mem://{key}"


@pytest.fixture()
def harness(tmp_path, monkeypatch):
    monkeypatch.setenv("EGP_LINE_CHANNEL_SECRET", CHANNEL_SECRET)
    database_url = f"sqlite+pysqlite:///{tmp_path / 'line-api.sqlite3'}"
    app = create_app(
        artifact_root=tmp_path,
        database_url=database_url,
        auth_required=False,
        payment_callback_secret="top-secret",
    )
    fake_messaging = FakeMessaging()
    fake_store = FakeArtifactStore()
    line_repo = LinePaymentRepository(engine=app.state.db_engine)
    app.state.line_slip_service = LineSlipService(
        line_repository=line_repo,
        billing_repository=app.state.billing_repository,
        billing_service=app.state.billing_service,
        artifact_store=fake_store,
        messaging_client=fake_messaging,
        admin_user_ids=(ADMIN_LINE_ID,),
        admin_console_base_url="https://admin.example.com",
    )
    client = TestClient(app)
    return client, fake_messaging, fake_store, line_repo


def _sign(body: bytes) -> str:
    return base64.b64encode(
        hmac.new(CHANNEL_SECRET.encode(), body, hashlib.sha256).digest()
    ).decode()


def _post_webhook(client, payload: dict):
    body = json.dumps(payload).encode("utf-8")
    return client.post(
        "/v1/integrations/line/webhook",
        content=body,
        headers={"X-Line-Signature": _sign(body), "Content-Type": "application/json"},
    )


def _create_record(client, *, record_number="INV-2026-0001") -> dict:
    start = date(2026, 5, 1)
    response = client.post(
        "/v1/billing/records",
        json={
            "tenant_id": TENANT_ID,
            "record_number": record_number,
            "plan_code": "monthly_membership",
            "status": "awaiting_payment",
            "billing_period_start": start.isoformat(),
            "due_at": f"{start.isoformat()}T09:00:00+00:00",
            "amount_due": "1500.00",
            "currency": "THB",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _text_event(text: str, message_id: str, user_id: str = "Ucustomer") -> dict:
    return {
        "type": "message",
        "timestamp": 1700000000000,
        "source": {"userId": user_id},
        "message": {"type": "text", "id": message_id, "text": text},
    }


def _image_event(message_id: str, user_id: str = "Ucustomer") -> dict:
    return {
        "type": "message",
        "timestamp": 1700000005000,
        "source": {"userId": user_id},
        "message": {"type": "image", "id": message_id},
    }


def test_webhook_rejects_invalid_signature(harness) -> None:
    client, *_ = harness
    response = client.post(
        "/v1/integrations/line/webhook",
        content=b'{"events":[]}',
        headers={"X-Line-Signature": "not-valid", "Content-Type": "application/json"},
    )
    assert response.status_code == 400


def test_webhook_image_stores_and_matches_then_admin_verifies(harness) -> None:
    client, fake_messaging, fake_store, _ = harness
    _create_record(client)

    # 1. Customer sends the reference text -> context recorded + resolved.
    text_resp = _post_webhook(client, {"events": [_text_event("Reference: INV-2026-0001", "m-text")]})
    assert text_resp.status_code == 200
    assert text_resp.json()["text_events"] == 1

    # 2. Customer sends the slip image -> slip created, stored, matched, admin notified.
    image_resp = _post_webhook(client, {"events": [_image_event("m-image")]})
    body = image_resp.json()
    assert body["image_events"] == 1
    assert body["slips_created"] == 1
    assert body["slips_matched"] == 1
    assert len(fake_store.objects) == 1
    assert any(to == ADMIN_LINE_ID for to, _ in fake_messaging.pushed)

    # 3. Admin sees the matched slip.
    listed = client.get("/v1/billing/slips", params={"status": "matched"})
    assert listed.status_code == 200
    slips = listed.json()["slips"]
    assert len(slips) == 1
    slip_id = slips[0]["id"]
    assert slips[0]["reference_code_match"] == "INV-2026-0001"
    assert slips[0]["tenant_id"] == TENANT_ID

    # 4. Admin verifies -> subscription activated (record becomes paid).
    verify = client.post(f"/v1/billing/slips/{slip_id}/verify", json={"note": "ok"})
    assert verify.status_code == 200, verify.text
    assert verify.json()["verification_status"] == "verified"

    records = client.get("/v1/billing/records", params={"tenant_id": TENANT_ID})
    assert records.status_code == 200
    detail = records.json()["records"][0]
    assert detail["record"]["status"] == "paid"
    assert detail["subscription"] is not None
    assert detail["subscription"]["subscription_status"] == "active"

    # Customer received a confirmation push.
    assert any(to == "Ucustomer" for to, _ in fake_messaging.pushed)


def test_webhook_image_before_text_is_rematched_when_reference_arrives(harness) -> None:
    client, fake_messaging, _, _ = harness
    _create_record(client)

    # Image arrives FIRST (no reference context yet) -> slip pending/unmatched.
    img = _post_webhook(client, {"events": [_image_event("m-img-first")]})
    assert img.json()["slips_created"] == 1
    assert img.json()["slips_matched"] == 0
    pending = client.get("/v1/billing/slips", params={"status": "pending"})
    assert len(pending.json()["slips"]) == 1

    # Reference text arrives AFTER -> the pending slip is rematched.
    txt = _post_webhook(
        client, {"events": [_text_event("Reference: INV-2026-0001", "m-txt-after")]}
    )
    assert txt.status_code == 200
    matched = client.get("/v1/billing/slips", params={"status": "matched"})
    slips = matched.json()["slips"]
    assert len(slips) == 1
    assert slips[0]["reference_code_match"] == "INV-2026-0001"
    assert slips[0]["tenant_id"] == TENANT_ID


def test_webhook_does_not_auto_match_paid_or_ambiguous_reference(harness) -> None:
    client, _, _, _ = harness
    billing = client.app.state.billing_repository

    def _make(tenant_id: str, number: str) -> str:
        detail = billing.create_billing_record(
            tenant_id=tenant_id,
            record_number=number,
            plan_code="monthly_membership",
            status="awaiting_payment",
            billing_period_start="2026-05-01",
            billing_period_end="2026-05-31",
            amount_due="1500.00",
            currency="THB",
        )
        return detail.record.id

    # Lone record but already PAID -> must NOT auto-match (no dead-end at verify).
    paid_id = _make(TENANT_ID, "INV-2026-0950")
    payment = billing.record_payment(
        tenant_id=TENANT_ID,
        billing_record_id=paid_id,
        payment_method="promptpay_qr",
        amount="1500.00",
        currency="THB",
        received_at="2026-05-29T10:00:00+00:00",
    )
    billing.reconcile_payment(tenant_id=TENANT_ID, payment_id=payment.id, status="reconciled")

    # Same number under two tenants, ONE already paid -> still ambiguous; the
    # paid duplicate must NOT collapse this into a false unique match on the
    # other tenant (the cross-tenant mis-credit guard).
    dup_a = _make(TENANT_ID, "INV-2026-0960")
    _make(OTHER_TENANT_ID, "INV-2026-0960")
    dup_pay = billing.record_payment(
        tenant_id=TENANT_ID,
        billing_record_id=dup_a,
        payment_method="promptpay_qr",
        amount="1500.00",
        currency="THB",
        received_at="2026-05-29T10:00:00+00:00",
    )
    billing.reconcile_payment(tenant_id=TENANT_ID, payment_id=dup_pay.id, status="reconciled")

    _post_webhook(client, {"events": [_text_event("INV-2026-0950", "t-paid", "Upaid")]})
    _post_webhook(client, {"events": [_image_event("i-paid", "Upaid")]})
    _post_webhook(client, {"events": [_text_event("INV-2026-0960", "t-amb", "Uamb")]})
    _post_webhook(client, {"events": [_image_event("i-amb", "Uamb")]})

    matched = client.get("/v1/billing/slips", params={"status": "matched"}).json()["slips"]
    assert matched == []
    pending = client.get("/v1/billing/slips", params={"status": "pending"}).json()["slips"]
    assert len(pending) == 2


def test_webhook_image_is_idempotent_by_message_id(harness) -> None:
    client, _, fake_store, _ = harness
    first = _post_webhook(client, {"events": [_image_event("dup-image")]})
    second = _post_webhook(client, {"events": [_image_event("dup-image")]})
    assert first.json()["slips_created"] == 1
    assert second.json()["slips_created"] == 0
    assert len(fake_store.objects) == 1


def test_verify_unmatched_slip_returns_conflict(harness) -> None:
    client, _, _, _ = harness
    # Image with no prior reference text -> slip stays pending/unmatched.
    _post_webhook(client, {"events": [_image_event("lonely-image")]})
    listed = client.get("/v1/billing/slips", params={"status": "pending"})
    slip_id = listed.json()["slips"][0]["id"]
    verify = client.post(f"/v1/billing/slips/{slip_id}/verify", json={})
    assert verify.status_code == 409


def test_payment_config_exposes_provider(harness) -> None:
    client, *_ = harness
    response = client.get("/v1/billing/payment-config")
    assert response.status_code == 200
    assert "provider" in response.json()


def _auth_harness(tmp_path, monkeypatch):
    """Auth-enabled app (JWT) with injected fakes, for tenant-scoping tests."""
    monkeypatch.setenv("EGP_LINE_CHANNEL_SECRET", CHANNEL_SECRET)
    database_url = f"sqlite+pysqlite:///{tmp_path / 'line-auth.sqlite3'}"
    app = create_app(
        artifact_root=tmp_path,
        database_url=database_url,
        jwt_secret=JWT_SECRET,
        payment_callback_secret="top-secret",
    )
    line_repo = LinePaymentRepository(engine=app.state.db_engine)
    app.state.line_slip_service = LineSlipService(
        line_repository=line_repo,
        billing_repository=app.state.billing_repository,
        billing_service=app.state.billing_service,
        artifact_store=FakeArtifactStore(),
        messaging_client=FakeMessaging(),
        admin_user_ids=(ADMIN_LINE_ID,),
        admin_console_base_url="https://admin.example.com",
    )
    return TestClient(app)


def test_slip_routes_are_tenant_scoped_for_non_operator_admins(tmp_path, monkeypatch) -> None:
    client = _auth_harness(tmp_path, monkeypatch)

    # Tenant A admin creates a record; the public webhook matches a slip to it.
    start = date(2026, 5, 1)
    created = client.post(
        "/v1/billing/records",
        json={
            "tenant_id": TENANT_ID,
            "record_number": "INV-2026-0777",
            "plan_code": "monthly_membership",
            "status": "awaiting_payment",
            "billing_period_start": start.isoformat(),
            "due_at": f"{start.isoformat()}T09:00:00+00:00",
            "amount_due": "1500.00",
            "currency": "THB",
        },
        headers=_auth_headers(TENANT_ID),
    )
    assert created.status_code == 201, created.text

    _post_webhook(client, {"events": [_text_event("Reference: INV-2026-0777", "m-t")]})
    _post_webhook(client, {"events": [_image_event("m-i")]})

    # Tenant A admin sees the matched slip.
    own = client.get("/v1/billing/slips", headers=_auth_headers(TENANT_ID))
    assert own.status_code == 200
    own_slips = own.json()["slips"]
    assert len(own_slips) == 1
    slip_id = own_slips[0]["id"]

    # Tenant B admin must NOT see tenant A's slip, nor verify it.
    others = client.get("/v1/billing/slips", headers=_auth_headers(OTHER_TENANT_ID))
    assert others.status_code == 200
    assert others.json()["slips"] == []

    forbidden = client.post(
        f"/v1/billing/slips/{slip_id}/verify",
        json={},
        headers=_auth_headers(OTHER_TENANT_ID),
    )
    assert forbidden.status_code == 403

    forbidden_image = client.get(
        f"/v1/billing/slips/{slip_id}/image", headers=_auth_headers(OTHER_TENANT_ID)
    )
    assert forbidden_image.status_code == 403
