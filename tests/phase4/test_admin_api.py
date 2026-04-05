from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from uuid import uuid4

from fastapi.testclient import TestClient
from jose import jwt
from sqlalchemy import text

from egp_api.main import create_app

TENANT_ID = "11111111-1111-1111-1111-111111111111"
OTHER_TENANT_ID = "22222222-2222-2222-2222-222222222222"
JWT_SECRET = "phase4-admin-secret"


def _create_client(tmp_path, *, auth_required: bool = False) -> TestClient:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'phase4-admin.sqlite3'}"
    return TestClient(
        create_app(
            artifact_root=tmp_path,
            database_url=database_url,
            auth_required=auth_required,
            jwt_secret=JWT_SECRET if auth_required else None,
        )
    )


def _seed_tenant(
    client: TestClient,
    *,
    tenant_id: str = TENANT_ID,
    name: str = "Acme Intelligence",
    slug: str = "acme-intelligence",
    plan_code: str = "monthly_membership",
) -> None:
    now = datetime.now(UTC).isoformat()
    with client.app.state.db_engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO tenants (
                    id,
                    name,
                    slug,
                    plan_code,
                    is_active,
                    created_at,
                    updated_at
                ) VALUES (
                    :id,
                    :name,
                    :slug,
                    :plan_code,
                    1,
                    :created_at,
                    :updated_at
                )
                """
            ),
            {
                "id": tenant_id,
                "name": name,
                "slug": slug,
                "plan_code": plan_code,
                "created_at": now,
                "updated_at": now,
            },
        )


def _seed_subscription(client: TestClient, *, tenant_id: str = TENANT_ID) -> None:
    record_id = str(uuid4())
    today = date.today()
    now = datetime.now(UTC).isoformat()
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
                    'monthly_membership',
                    'paid',
                    :billing_period_start,
                    :billing_period_end,
                    'THB',
                    '1500.00',
                    :created_at,
                    :updated_at
                )
                """
            ),
            {
                "id": record_id,
                "tenant_id": tenant_id,
                "record_number": f"INV-{record_id[:8]}",
                "billing_period_start": (today - timedelta(days=1)).isoformat(),
                "billing_period_end": (today + timedelta(days=29)).isoformat(),
                "created_at": now,
                "updated_at": now,
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
                    'monthly_membership',
                    'active',
                    :billing_period_start,
                    :billing_period_end,
                    5,
                    :activated_at,
                    :created_at,
                    :updated_at
                )
                """
            ),
            {
                "id": str(uuid4()),
                "tenant_id": tenant_id,
                "billing_record_id": record_id,
                "billing_period_start": (today - timedelta(days=1)).isoformat(),
                "billing_period_end": (today + timedelta(days=29)).isoformat(),
                "activated_at": now,
                "created_at": now,
                "updated_at": now,
            },
        )


def _auth_headers(*, tenant_id: str = TENANT_ID, role: str) -> dict[str, str]:
    token = jwt.encode(
        {
            "sub": "user-123",
            "tenant_id": tenant_id,
            "role": role,
        },
        JWT_SECRET,
        algorithm="HS256",
    )
    return {"Authorization": f"Bearer {token}"}


def test_admin_snapshot_returns_tenant_users_settings_and_billing(tmp_path) -> None:
    client = _create_client(tmp_path)
    _seed_tenant(client)
    _seed_subscription(client)

    owner = client.app.state.notification_repository.create_user(
        tenant_id=TENANT_ID,
        email="owner@example.com",
        role="owner",
        full_name="Owner User",
    )
    viewer = client.app.state.notification_repository.create_user(
        tenant_id=TENANT_ID,
        email="viewer@example.com",
        role="viewer",
        full_name="Viewer User",
    )
    client.app.state.notification_repository.set_email_preference(
        tenant_id=TENANT_ID,
        user_id=viewer["id"],
        notification_type="run_failed",
        enabled=True,
    )
    client.app.state.notification_repository.set_email_preference(
        tenant_id=TENANT_ID,
        user_id=owner["id"],
        notification_type="export_ready",
        enabled=False,
    )

    response = client.get("/v1/admin", params={"tenant_id": TENANT_ID})

    assert response.status_code == 200
    body = response.json()
    assert body["tenant"]["id"] == TENANT_ID
    assert body["tenant"]["name"] == "Acme Intelligence"
    assert body["tenant"]["slug"] == "acme-intelligence"
    assert body["settings"] == {
        "support_email": None,
        "billing_contact_email": None,
        "timezone": "Asia/Bangkok",
        "locale": "th-TH",
        "daily_digest_enabled": True,
        "weekly_digest_enabled": False,
        "created_at": None,
        "updated_at": None,
    }
    assert [user["email"] for user in body["users"]] == [
        "owner@example.com",
        "viewer@example.com",
    ]
    assert body["users"][0]["notification_preferences"]["run_failed"] is True
    assert body["users"][0]["notification_preferences"]["export_ready"] is False
    assert body["users"][1]["notification_preferences"]["run_failed"] is True
    assert body["users"][1]["notification_preferences"]["new_project"] is False
    assert body["billing"]["summary"]["collected_amount"] == "0.00"
    assert body["billing"]["current_subscription"]["plan_code"] == "monthly_membership"
    assert body["billing"]["records"][0]["record_number"].startswith("INV-")


def test_admin_routes_can_create_users_update_preferences_and_patch_settings(
    tmp_path,
) -> None:
    client = _create_client(tmp_path)
    _seed_tenant(client)

    created = client.post(
        "/v1/admin/users",
        json={
            "tenant_id": TENANT_ID,
            "email": "analyst@example.com",
            "full_name": "Analyst User",
            "role": "analyst",
        },
    )
    assert created.status_code == 201
    user_id = created.json()["id"]

    updated = client.patch(
        f"/v1/admin/users/{user_id}",
        json={
            "tenant_id": TENANT_ID,
            "role": "admin",
            "status": "suspended",
            "full_name": "Admin Analyst",
        },
    )
    assert updated.status_code == 200
    assert updated.json()["role"] == "admin"
    assert updated.json()["status"] == "suspended"

    preferences = client.put(
        f"/v1/admin/users/{user_id}/notification-preferences",
        json={
            "tenant_id": TENANT_ID,
            "email_preferences": {
                "run_failed": True,
                "tor_changed": False,
            },
        },
    )
    assert preferences.status_code == 200
    assert preferences.json()["notification_preferences"]["run_failed"] is True
    assert preferences.json()["notification_preferences"]["tor_changed"] is False

    settings = client.patch(
        "/v1/admin/settings",
        json={
            "tenant_id": TENANT_ID,
            "support_email": "support@example.com",
            "billing_contact_email": "billing@example.com",
            "timezone": "Asia/Bangkok",
            "locale": "th-TH",
            "daily_digest_enabled": False,
            "weekly_digest_enabled": True,
        },
    )
    assert settings.status_code == 200
    assert settings.json()["support_email"] == "support@example.com"
    assert settings.json()["daily_digest_enabled"] is False

    snapshot = client.get("/v1/admin", params={"tenant_id": TENANT_ID})
    assert snapshot.status_code == 200
    assert snapshot.json()["settings"]["billing_contact_email"] == "billing@example.com"
    assert snapshot.json()["users"][0]["notification_preferences"]["run_failed"] is True


def test_admin_routes_are_tenant_scoped(tmp_path) -> None:
    client = _create_client(tmp_path)
    _seed_tenant(client, tenant_id=TENANT_ID, slug="tenant-one")
    _seed_tenant(
        client,
        tenant_id=OTHER_TENANT_ID,
        name="Other Tenant",
        slug="tenant-two",
        plan_code="free",
    )

    created = client.post(
        "/v1/admin/users",
        json={
            "tenant_id": TENANT_ID,
            "email": "owner@example.com",
            "role": "owner",
        },
    )
    assert created.status_code == 201
    user_id = created.json()["id"]

    foreign_update = client.patch(
        f"/v1/admin/users/{user_id}",
        json={"tenant_id": OTHER_TENANT_ID, "role": "viewer"},
    )
    assert foreign_update.status_code == 403

    foreign_snapshot = client.get("/v1/admin", params={"tenant_id": OTHER_TENANT_ID})
    assert foreign_snapshot.status_code == 200
    assert foreign_snapshot.json()["users"] == []


def test_admin_routes_require_owner_or_admin_role_when_auth_enabled(tmp_path) -> None:
    client = _create_client(tmp_path, auth_required=True)
    _seed_tenant(client)

    viewer_response = client.get(
        "/v1/admin",
        headers=_auth_headers(role="viewer"),
    )
    admin_response = client.get(
        "/v1/admin",
        headers=_auth_headers(role="admin"),
    )

    assert viewer_response.status_code == 403
    assert viewer_response.json()["detail"] == "admin role required"
    assert admin_response.status_code == 200
    assert admin_response.json()["tenant"]["id"] == TENANT_ID
