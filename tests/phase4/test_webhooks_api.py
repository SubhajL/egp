from __future__ import annotations

from datetime import UTC, datetime

from fastapi.testclient import TestClient
from jose import jwt
from sqlalchemy import text

from egp_api.main import create_app

TENANT_ID = "11111111-1111-1111-1111-111111111111"
OTHER_TENANT_ID = "22222222-2222-2222-2222-222222222222"
JWT_SECRET = "phase4-webhook-secret"


def _create_client(tmp_path, *, auth_required: bool = False) -> TestClient:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'phase4-webhooks.sqlite3'}"
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


def test_create_and_list_webhooks_returns_tenant_scoped_configuration(tmp_path) -> None:
    client = _create_client(tmp_path)
    _seed_tenant(client)
    _seed_tenant(
        client,
        tenant_id=OTHER_TENANT_ID,
        name="Other Tenant",
        slug="other-tenant",
        plan_code="free",
    )

    created = client.post(
        "/v1/webhooks",
        json={
            "tenant_id": TENANT_ID,
            "name": "Ops Receiver",
            "url": "https://hooks.example.com/egp",
            "notification_types": ["new_project", "run_failed"],
            "signing_secret": "super-secret",
        },
    )
    listed = client.get("/v1/webhooks", params={"tenant_id": TENANT_ID})
    foreign = client.get("/v1/webhooks", params={"tenant_id": OTHER_TENANT_ID})

    assert created.status_code == 201
    assert created.json()["name"] == "Ops Receiver"
    assert created.json()["url"] == "https://hooks.example.com/egp"
    assert created.json()["notification_types"] == ["new_project", "run_failed"]
    assert created.json()["last_delivery_status"] is None
    assert listed.status_code == 200
    assert len(listed.json()["webhooks"]) == 1
    assert listed.json()["webhooks"][0]["id"] == created.json()["id"]
    assert foreign.status_code == 200
    assert foreign.json()["webhooks"] == []


def test_delete_webhook_soft_disables_subscription(tmp_path) -> None:
    client = _create_client(tmp_path)
    _seed_tenant(client)

    created = client.post(
        "/v1/webhooks",
        json={
            "tenant_id": TENANT_ID,
            "name": "Ops Receiver",
            "url": "https://hooks.example.com/egp",
            "notification_types": ["export_ready"],
            "signing_secret": "super-secret",
        },
    )
    deleted = client.delete(
        f"/v1/webhooks/{created.json()['id']}",
        params={"tenant_id": TENANT_ID},
    )
    listed = client.get("/v1/webhooks", params={"tenant_id": TENANT_ID})

    assert created.status_code == 201
    assert deleted.status_code == 204
    assert listed.status_code == 200
    assert listed.json()["webhooks"] == []


def test_webhook_routes_require_admin_role(tmp_path) -> None:
    client = _create_client(tmp_path, auth_required=True)
    _seed_tenant(client)

    viewer_response = client.get(
        "/v1/webhooks",
        headers=_auth_headers(role="viewer"),
    )
    admin_response = client.get(
        "/v1/webhooks",
        headers=_auth_headers(role="admin"),
    )

    assert viewer_response.status_code == 403
    assert viewer_response.json()["detail"] == "admin role required"
    assert admin_response.status_code == 200


def test_webhook_routes_reject_invalid_notification_types_and_bad_urls(tmp_path) -> None:
    client = _create_client(tmp_path)
    _seed_tenant(client)

    invalid_type = client.post(
        "/v1/webhooks",
        json={
            "tenant_id": TENANT_ID,
            "name": "Ops Receiver",
            "url": "https://hooks.example.com/egp",
            "notification_types": ["not-a-real-type"],
            "signing_secret": "super-secret",
        },
    )
    invalid_url = client.post(
        "/v1/webhooks",
        json={
            "tenant_id": TENANT_ID,
            "name": "Ops Receiver",
            "url": "ftp://hooks.example.com/egp",
            "notification_types": ["run_failed"],
            "signing_secret": "super-secret",
        },
    )

    assert invalid_type.status_code == 422
    assert invalid_url.status_code == 422


def test_webhook_routes_reject_cross_tenant_delete_attempt(tmp_path) -> None:
    client = _create_client(tmp_path, auth_required=True)
    _seed_tenant(client, tenant_id=TENANT_ID, slug="tenant-one")
    _seed_tenant(
        client,
        tenant_id=OTHER_TENANT_ID,
        name="Other Tenant",
        slug="tenant-two",
        plan_code="free",
    )

    created = client.post(
        "/v1/webhooks",
        json={
            "name": "Ops Receiver",
            "url": "https://hooks.example.com/egp",
            "notification_types": ["run_failed"],
            "signing_secret": "super-secret",
        },
        headers=_auth_headers(tenant_id=TENANT_ID, role="admin"),
    )
    deleted = client.delete(
        f"/v1/webhooks/{created.json()['id']}",
        headers=_auth_headers(tenant_id=OTHER_TENANT_ID, role="admin"),
    )

    assert created.status_code == 201
    assert deleted.status_code == 404
