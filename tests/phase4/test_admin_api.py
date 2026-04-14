from __future__ import annotations

import base64
from datetime import UTC, date, datetime, timedelta
from uuid import uuid4

from fastapi.testclient import TestClient
from jose import jwt
from sqlalchemy import text

from egp_api.main import create_app
from egp_db.repositories.project_repo import build_project_upsert_record
from egp_shared_types.enums import ProcurementType, ProjectState

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
            storage_credentials_secret="phase4-storage-secret",
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


def _seed_future_upgrade_chain(
    client: TestClient, *, tenant_id: str = TENANT_ID
) -> None:
    source_record_id = str(uuid4())
    source_subscription_id = str(uuid4())
    upgrade_record_id = str(uuid4())
    upgrade_subscription_id = str(uuid4())
    today = date.today()
    future_start = today + timedelta(days=5)
    future_end = future_start + timedelta(days=29)
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
                    upgrade_from_subscription_id,
                    upgrade_mode,
                    created_at,
                    updated_at
                ) VALUES (
                    :id,
                    :tenant_id,
                    :record_number,
                    'one_time_search_pack',
                    'paid',
                    :billing_period_start,
                    :billing_period_end,
                    'THB',
                    '300.00',
                    NULL,
                    'none',
                    :created_at,
                    :updated_at
                )
                """
            ),
            {
                "id": source_record_id,
                "tenant_id": tenant_id,
                "record_number": "INV-CHAIN-0001",
                "billing_period_start": today.isoformat(),
                "billing_period_end": (today + timedelta(days=2)).isoformat(),
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
                    'one_time_search_pack',
                    'active',
                    :billing_period_start,
                    :billing_period_end,
                    1,
                    :activated_at,
                    :created_at,
                    :updated_at
                )
                """
            ),
            {
                "id": source_subscription_id,
                "tenant_id": tenant_id,
                "billing_record_id": source_record_id,
                "billing_period_start": today.isoformat(),
                "billing_period_end": (today + timedelta(days=2)).isoformat(),
                "activated_at": now,
                "created_at": now,
                "updated_at": now,
            },
        )
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
                    paid_at,
                    upgrade_from_subscription_id,
                    upgrade_mode,
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
                    :paid_at,
                    :upgrade_from_subscription_id,
                    'replace_on_activation',
                    :created_at,
                    :updated_at
                )
                """
            ),
            {
                "id": upgrade_record_id,
                "tenant_id": tenant_id,
                "record_number": "UPG-MONTHLY-CHAIN",
                "billing_period_start": future_start.isoformat(),
                "billing_period_end": future_end.isoformat(),
                "paid_at": now,
                "upgrade_from_subscription_id": source_subscription_id,
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
                "id": upgrade_subscription_id,
                "tenant_id": tenant_id,
                "billing_record_id": upgrade_record_id,
                "billing_period_start": future_start.isoformat(),
                "billing_period_end": future_end.isoformat(),
                "activated_at": now,
                "created_at": now,
                "updated_at": now,
            },
        )


def _seed_project(
    client: TestClient,
    *,
    tenant_id: str = TENANT_ID,
    project_number: str = "EGP-2026-4301",
    project_name: str = "ระบบจัดการข้อมูล",
    observed_at: str = "2026-04-05T09:00:00+00:00",
):
    repository = client.app.state.project_repository
    return repository.upsert_project(
        build_project_upsert_record(
            tenant_id=tenant_id,
            project_number=project_number,
            search_name=project_name,
            detail_name=project_name,
            project_name=project_name,
            organization_name="กรมตัวอย่าง",
            proposal_submission_date="2026-05-01",
            budget_amount="1000000",
            procurement_type=ProcurementType.SERVICES,
            project_state=ProjectState.OPEN_INVITATION,
        ),
        source_status_text="ประกาศเชิญชวน",
        observed_at=observed_at,
    )


def _ingest_document(
    client: TestClient,
    *,
    tenant_id: str = TENANT_ID,
    project_id: str,
    file_name: str,
    content: bytes,
) -> dict[str, object]:
    response = client.post(
        "/v1/documents/ingest",
        json={
            "tenant_id": tenant_id,
            "project_id": project_id,
            "file_name": file_name,
            "content_base64": base64.b64encode(content).decode("ascii"),
            "source_label": "เอกสารประกวดราคา",
            "source_status_text": "ประกาศเชิญชวน",
        },
    )
    assert response.status_code in {200, 201}
    return response.json()


def _create_billing_record(
    client: TestClient,
    *,
    tenant_id: str = TENANT_ID,
    record_number: str = "INV-2026-4301",
) -> dict[str, object]:
    response = client.post(
        "/v1/billing/records",
        json={
            "tenant_id": tenant_id,
            "record_number": record_number,
            "plan_code": "monthly_membership",
            "status": "awaiting_payment",
            "billing_period_start": "2026-04-01",
            "billing_period_end": "2026-04-30",
            "amount_due": "1500.00",
            "currency": "THB",
        },
    )
    assert response.status_code == 201
    return response.json()


def test_owner_can_start_free_trial_once_for_tenant(tmp_path) -> None:
    client = _create_client(tmp_path, auth_required=True)
    _seed_tenant(client)

    started = client.post(
        "/v1/billing/trial/start",
        json={"tenant_id": TENANT_ID},
        headers=_auth_headers(role="owner"),
    )

    assert started.status_code == 201
    body = started.json()
    assert body["plan_code"] == "free_trial"
    assert body["subscription_status"] == "active"
    assert body["keyword_limit"] == 1

    listing = client.get("/v1/billing/records", headers=_auth_headers(role="owner"))
    assert listing.status_code == 200
    assert listing.json()["records"][0]["record"]["plan_code"] == "free_trial"
    assert listing.json()["records"][0]["record"]["amount_due"] == "0.00"

    duplicate = client.post(
        "/v1/billing/trial/start",
        json={"tenant_id": TENANT_ID},
        headers=_auth_headers(role="owner"),
    )

    assert duplicate.status_code == 400
    assert duplicate.json()["detail"] == "free trial already used for tenant"


def _create_failed_run(client: TestClient, *, tenant_id: str = TENANT_ID) -> str:
    repository = client.app.state.run_repository
    created = repository.create_run(tenant_id=tenant_id, trigger_type="manual")
    repository.mark_run_started(created.id)
    task = repository.create_task(
        run_id=created.id,
        task_type="discover",
        keyword="ระบบ",
        payload={"page": 1},
    )
    repository.mark_task_started(task.id)
    repository.mark_task_finished(
        task.id, status="failed", result_json={"reason": "timeout"}
    )
    repository.mark_run_finished(
        created.id,
        status="failed",
        summary_json={"projects_seen": 0},
        error_count=2,
    )
    return created.id


def _seed_webhook_delivery_failure(
    client: TestClient,
    *,
    tenant_id: str = TENANT_ID,
    notification_id: str,
) -> str:
    subscription_id = str(uuid4())
    delivery_id = str(uuid4())
    now = datetime.now(UTC).isoformat()
    with client.app.state.db_engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO webhook_subscriptions (
                    id,
                    tenant_id,
                    name,
                    url,
                    signing_secret,
                    notification_types,
                    is_active,
                    created_at,
                    updated_at,
                    deleted_at
                ) VALUES (
                    :id,
                    :tenant_id,
                    'Support endpoint',
                    'https://example.com/hooks/support',
                    'secret-123',
                    '["run_failed"]',
                    1,
                    :created_at,
                    :updated_at,
                    NULL
                )
                """
            ),
            {
                "id": subscription_id,
                "tenant_id": tenant_id,
                "created_at": now,
                "updated_at": now,
            },
        )
        connection.execute(
            text(
                """
                INSERT INTO webhook_deliveries (
                    id,
                    tenant_id,
                    webhook_subscription_id,
                    notification_id,
                    event_id,
                    notification_type,
                    project_id,
                    payload,
                    attempt_count,
                    delivery_status,
                    last_response_status_code,
                    last_response_body,
                    created_at,
                    updated_at,
                    last_attempted_at,
                    delivered_at
                ) VALUES (
                    :id,
                    :tenant_id,
                    :webhook_subscription_id,
                    :notification_id,
                    'evt-support-1',
                    'run_failed',
                    NULL,
                    '{"summary":"failure"}',
                    2,
                    'failed',
                    500,
                    'internal error',
                    :created_at,
                    :updated_at,
                    :last_attempted_at,
                    NULL
                )
                """
            ),
            {
                "id": delivery_id,
                "tenant_id": tenant_id,
                "webhook_subscription_id": subscription_id,
                "notification_id": notification_id,
                "created_at": now,
                "updated_at": now,
                "last_attempted_at": now,
            },
        )
    return delivery_id


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
        "crawl_interval_hours": None,
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


def test_admin_snapshot_exposes_upgrade_chain_and_upcoming_subscription(
    tmp_path,
) -> None:
    client = _create_client(tmp_path)
    _seed_tenant(client)
    _seed_future_upgrade_chain(client)

    response = client.get("/v1/admin", params={"tenant_id": TENANT_ID})

    assert response.status_code == 200
    body = response.json()
    assert (
        body["billing"]["current_subscription"]["plan_code"] == "one_time_search_pack"
    )
    assert body["billing"]["current_subscription"]["subscription_status"] == "active"
    assert body["billing"]["upcoming_subscription"]["plan_code"] == "monthly_membership"
    assert (
        body["billing"]["upcoming_subscription"]["subscription_status"]
        == "pending_activation"
    )
    upgrade_record = next(
        record
        for record in body["billing"]["records"]
        if record["record_number"] == "UPG-MONTHLY-CHAIN"
    )
    assert upgrade_record["upgrade_mode"] == "replace_on_activation"
    assert upgrade_record["upgrade_from_subscription_id"] is not None


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
            "crawl_interval_hours": 24,
        },
    )
    assert settings.status_code == 200
    assert settings.json()["support_email"] == "support@example.com"
    assert settings.json()["daily_digest_enabled"] is False
    assert settings.json()["crawl_interval_hours"] == 24

    snapshot = client.get("/v1/admin", params={"tenant_id": TENANT_ID})
    assert snapshot.status_code == 200
    assert snapshot.json()["settings"]["billing_contact_email"] == "billing@example.com"
    assert snapshot.json()["settings"]["crawl_interval_hours"] == 24
    assert snapshot.json()["users"][0]["notification_preferences"]["run_failed"] is True


def test_storage_settings_default_to_managed_storage(tmp_path) -> None:
    client = _create_client(tmp_path)
    _seed_tenant(client)

    response = client.get("/v1/admin/storage", params={"tenant_id": TENANT_ID})

    assert response.status_code == 200
    body = response.json()
    assert body["provider"] == "managed"
    assert body["connection_status"] == "managed"
    assert body["account_email"] is None
    assert body["folder_label"] is None
    assert body["folder_path_hint"] is None
    assert body["managed_fallback_enabled"] is False
    assert body["last_validated_at"] is None
    assert body["last_validation_error"] is None


def test_storage_settings_can_be_updated_and_written_to_audit_log(tmp_path) -> None:
    client = _create_client(tmp_path, auth_required=True)
    _seed_tenant(client)

    updated = client.patch(
        "/v1/admin/storage",
        headers=_auth_headers(role="owner"),
        json={
            "tenant_id": TENANT_ID,
            "provider": "google_drive",
            "connection_status": "pending_setup",
            "account_email": "ops@example.com",
            "folder_label": "Acme Procurement TOR",
            "folder_path_hint": "Google Drive/Acme Procurement TOR",
            "managed_fallback_enabled": True,
            "last_validation_error": "OAuth connection required",
        },
    )

    assert updated.status_code == 200
    body = updated.json()
    assert body["provider"] == "google_drive"
    assert body["connection_status"] == "pending_setup"
    assert body["account_email"] == "ops@example.com"
    assert body["folder_label"] == "Acme Procurement TOR"
    assert body["folder_path_hint"] == "Google Drive/Acme Procurement TOR"
    assert body["managed_fallback_enabled"] is True
    assert body["last_validation_error"] == "OAuth connection required"

    fetched = client.get(
        "/v1/admin/storage",
        headers=_auth_headers(role="owner"),
        params={"tenant_id": TENANT_ID},
    )
    assert fetched.status_code == 200
    assert fetched.json()["provider"] == "google_drive"

    audit = client.get(
        "/v1/admin/audit-log",
        headers=_auth_headers(role="owner"),
        params={"tenant_id": TENANT_ID, "source": "admin"},
    )
    assert audit.status_code == 200
    assert any(
        item["event_type"] == "tenant.storage_settings_updated"
        for item in audit.json()["items"]
    )


def test_storage_settings_switching_back_to_managed_clears_provider_metadata(
    tmp_path,
) -> None:
    client = _create_client(tmp_path, auth_required=True)
    _seed_tenant(client)

    first_update = client.patch(
        "/v1/admin/storage",
        headers=_auth_headers(role="owner"),
        json={
            "tenant_id": TENANT_ID,
            "provider": "google_drive",
            "connection_status": "pending_setup",
            "account_email": "ops@example.com",
            "folder_label": "Acme Procurement TOR",
            "folder_path_hint": "Google Drive/Acme Procurement TOR",
            "managed_fallback_enabled": True,
            "last_validation_error": "OAuth connection required",
        },
    )
    assert first_update.status_code == 200

    managed_update = client.patch(
        "/v1/admin/storage",
        headers=_auth_headers(role="owner"),
        json={
            "tenant_id": TENANT_ID,
            "provider": "managed",
            "connection_status": "managed",
            "account_email": "stale@example.com",
            "folder_label": "Should be cleared",
            "folder_path_hint": "Should be cleared",
            "managed_fallback_enabled": True,
            "last_validation_error": "Should be cleared",
        },
    )

    assert managed_update.status_code == 200
    body = managed_update.json()
    assert body["provider"] == "managed"
    assert body["connection_status"] == "managed"
    assert body["account_email"] is None
    assert body["folder_label"] is None
    assert body["folder_path_hint"] is None
    assert body["managed_fallback_enabled"] is False
    assert body["last_validated_at"] is None
    assert body["last_validation_error"] is None


def test_storage_settings_reject_connected_status_before_real_validation_exists(
    tmp_path,
) -> None:
    client = _create_client(tmp_path, auth_required=True)
    _seed_tenant(client)

    response = client.patch(
        "/v1/admin/storage",
        headers=_auth_headers(role="owner"),
        json={
            "tenant_id": TENANT_ID,
            "provider": "google_drive",
            "connection_status": "connected",
        },
    )

    assert response.status_code == 422
    assert "reserved" in response.json()["detail"]


def test_storage_connect_stores_encrypted_credentials_and_masks_response(
    tmp_path,
) -> None:
    client = _create_client(tmp_path, auth_required=True)
    _seed_tenant(client)

    config_response = client.patch(
        "/v1/admin/storage",
        headers=_auth_headers(role="owner"),
        json={
            "tenant_id": TENANT_ID,
            "provider": "google_drive",
            "connection_status": "pending_setup",
            "account_email": "ops@example.com",
            "folder_label": "Acme Procurement TOR",
            "folder_path_hint": "Google Drive/Acme Procurement TOR",
        },
    )
    assert config_response.status_code == 200

    connect_response = client.post(
        "/v1/admin/storage/connect",
        headers=_auth_headers(role="owner"),
        json={
            "tenant_id": TENANT_ID,
            "provider": "google_drive",
            "credential_type": "oauth_tokens",
            "credentials": {
                "access_token": "access-token-value",
                "refresh_token": "refresh-token-value",
            },
        },
    )

    assert connect_response.status_code == 200
    body = connect_response.json()
    assert body["provider"] == "google_drive"
    assert body["has_credentials"] is True
    assert body["credential_type"] == "oauth_tokens"
    assert body["credential_updated_at"] is not None
    assert "credentials" not in body

    with client.app.state.db_engine.connect() as connection:
        row = (
            connection.execute(
                text(
                    """
                    SELECT encrypted_payload
                    FROM tenant_storage_credentials
                    WHERE tenant_id = :tenant_id AND provider = 'google_drive'
                    """
                ),
                {"tenant_id": TENANT_ID},
            )
            .mappings()
            .one()
        )
    encrypted_payload = row["encrypted_payload"]
    assert "access-token-value" not in encrypted_payload
    assert "refresh-token-value" not in encrypted_payload


def test_storage_disconnect_clears_credentials_and_marks_disconnected(tmp_path) -> None:
    client = _create_client(tmp_path, auth_required=True)
    _seed_tenant(client)

    client.patch(
        "/v1/admin/storage",
        headers=_auth_headers(role="owner"),
        json={
            "tenant_id": TENANT_ID,
            "provider": "google_drive",
            "connection_status": "pending_setup",
            "account_email": "ops@example.com",
            "folder_label": "Acme Procurement TOR",
            "folder_path_hint": "Google Drive/Acme Procurement TOR",
        },
    )
    client.post(
        "/v1/admin/storage/connect",
        headers=_auth_headers(role="owner"),
        json={
            "tenant_id": TENANT_ID,
            "provider": "google_drive",
            "credential_type": "oauth_tokens",
            "credentials": {
                "refresh_token": "refresh-token-value",
            },
        },
    )

    response = client.post(
        "/v1/admin/storage/disconnect",
        headers=_auth_headers(role="owner"),
        json={"tenant_id": TENANT_ID, "provider": "google_drive"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["provider"] == "google_drive"
    assert body["connection_status"] == "disconnected"
    assert body["has_credentials"] is False
    assert body["credential_type"] is None
    assert body["credential_updated_at"] is None

    with client.app.state.db_engine.connect() as connection:
        count = connection.execute(
            text(
                """
                SELECT COUNT(*) AS value
                FROM tenant_storage_credentials
                WHERE tenant_id = :tenant_id AND provider = 'google_drive'
                """
            ),
            {"tenant_id": TENANT_ID},
        ).scalar_one()
    assert count == 0


def test_storage_disconnect_rejects_provider_mismatch(tmp_path) -> None:
    client = _create_client(tmp_path, auth_required=True)
    _seed_tenant(client)

    configured = client.patch(
        "/v1/admin/storage",
        headers=_auth_headers(role="owner"),
        json={
            "tenant_id": TENANT_ID,
            "provider": "google_drive",
            "connection_status": "pending_setup",
            "account_email": "ops@example.com",
            "folder_label": "Acme Procurement TOR",
            "folder_path_hint": "Google Drive/Acme Procurement TOR",
        },
    )
    assert configured.status_code == 200

    response = client.post(
        "/v1/admin/storage/disconnect",
        headers=_auth_headers(role="owner"),
        json={"tenant_id": TENANT_ID, "provider": "onedrive"},
    )

    assert response.status_code == 422
    assert "mismatch" in response.json()["detail"]

    current = client.get(
        "/v1/admin/storage",
        headers=_auth_headers(role="owner"),
        params={"tenant_id": TENANT_ID},
    )
    assert current.status_code == 200
    assert current.json()["provider"] == "google_drive"
    assert current.json()["connection_status"] == "pending_setup"


def test_storage_test_write_marks_pending_config_as_connected_when_inputs_complete(
    tmp_path,
) -> None:
    client = _create_client(tmp_path, auth_required=True)
    _seed_tenant(client)

    client.patch(
        "/v1/admin/storage",
        headers=_auth_headers(role="owner"),
        json={
            "tenant_id": TENANT_ID,
            "provider": "google_drive",
            "connection_status": "pending_setup",
            "account_email": "ops@example.com",
            "folder_label": "Acme Procurement TOR",
            "folder_path_hint": "Google Drive/Acme Procurement TOR",
        },
    )
    client.post(
        "/v1/admin/storage/connect",
        headers=_auth_headers(role="owner"),
        json={
            "tenant_id": TENANT_ID,
            "provider": "google_drive",
            "credential_type": "oauth_tokens",
            "credentials": {
                "refresh_token": "refresh-token-value",
            },
        },
    )

    response = client.post(
        "/v1/admin/storage/test-write",
        headers=_auth_headers(role="owner"),
        json={"tenant_id": TENANT_ID},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["connection_status"] == "connected"
    assert body["last_validated_at"] is not None
    assert body["last_validation_error"] is None


def test_storage_test_write_marks_error_when_credentials_missing(tmp_path) -> None:
    client = _create_client(tmp_path, auth_required=True)
    _seed_tenant(client)

    client.patch(
        "/v1/admin/storage",
        headers=_auth_headers(role="owner"),
        json={
            "tenant_id": TENANT_ID,
            "provider": "google_drive",
            "connection_status": "pending_setup",
            "account_email": "ops@example.com",
            "folder_label": "Acme Procurement TOR",
            "folder_path_hint": "Google Drive/Acme Procurement TOR",
        },
    )

    response = client.post(
        "/v1/admin/storage/test-write",
        headers=_auth_headers(role="owner"),
        json={"tenant_id": TENANT_ID},
    )

    assert response.status_code == 422
    assert "credentials" in response.json()["detail"]

    current = client.get(
        "/v1/admin/storage",
        headers=_auth_headers(role="owner"),
        params={"tenant_id": TENANT_ID},
    )
    assert current.status_code == 200
    assert current.json()["connection_status"] == "error"
    assert current.json()["last_validation_error"] is not None
    assert "credentials" in current.json()["last_validation_error"]


def test_create_user_with_password_can_subsequently_login(tmp_path) -> None:
    client = _create_client(tmp_path, auth_required=True)
    _seed_tenant(client)

    created = client.post(
        "/v1/admin/users",
        headers=_auth_headers(role="owner"),
        json={
            "tenant_id": TENANT_ID,
            "email": "loginable@example.com",
            "full_name": "Login Ready",
            "role": "analyst",
            "password": "correct horse battery staple",
        },
    )

    assert created.status_code == 201

    login = client.post(
        "/v1/auth/login",
        json={
            "tenant_slug": "acme-intelligence",
            "email": "loginable@example.com",
            "password": "correct horse battery staple",
        },
    )

    assert login.status_code == 200
    assert login.json()["user"]["email"] == "loginable@example.com"


def test_update_user_password_rotates_credentials(tmp_path) -> None:
    client = _create_client(tmp_path, auth_required=True)
    _seed_tenant(client)

    created = client.post(
        "/v1/admin/users",
        headers=_auth_headers(role="owner"),
        json={
            "tenant_id": TENANT_ID,
            "email": "rotate@example.com",
            "role": "viewer",
            "password": "correct horse battery staple",
        },
    )
    assert created.status_code == 201
    user_id = created.json()["id"]

    rotated = client.patch(
        f"/v1/admin/users/{user_id}",
        headers=_auth_headers(role="owner"),
        json={
            "tenant_id": TENANT_ID,
            "password": "new secure passphrase",
        },
    )
    assert rotated.status_code == 200

    old_login = client.post(
        "/v1/auth/login",
        json={
            "tenant_slug": "acme-intelligence",
            "email": "rotate@example.com",
            "password": "correct horse battery staple",
        },
    )
    new_login = client.post(
        "/v1/auth/login",
        json={
            "tenant_slug": "acme-intelligence",
            "email": "rotate@example.com",
            "password": "new secure passphrase",
        },
    )

    assert old_login.status_code == 401
    assert new_login.status_code == 200


def test_admin_can_issue_invite_for_existing_user(tmp_path) -> None:
    sent: list[dict[str, str]] = []
    client = _create_client(
        tmp_path,
        auth_required=True,
    )
    client.app.state.notification_service._email_sender = lambda *, to, subject, body: (
        sent.append({"to": to, "subject": subject, "body": body})
    )
    _seed_tenant(client)

    created = client.post(
        "/v1/admin/users",
        headers=_auth_headers(role="owner"),
        json={
            "email": "invite-admin@example.com",
            "role": "viewer",
        },
    )
    assert created.status_code == 201
    user_id = created.json()["id"]

    invited = client.post(
        f"/v1/admin/users/{user_id}/invite",
        headers=_auth_headers(role="owner"),
        json={},
    )

    assert invited.status_code == 202
    assert sent
    assert sent[-1]["to"] == "invite-admin@example.com"


def test_admin_routes_use_session_tenant_when_tenant_id_is_omitted(tmp_path) -> None:
    client = _create_client(tmp_path, auth_required=True)
    _seed_tenant(client)

    created = client.post(
        "/v1/admin/users",
        headers=_auth_headers(role="owner"),
        json={
            "email": "implicit-tenant@example.com",
            "role": "viewer",
        },
    )

    assert created.status_code == 201
    assert created.json()["email"] == "implicit-tenant@example.com"


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


def test_admin_support_search_matches_name_slug_and_contact_email(tmp_path) -> None:
    client = _create_client(tmp_path)
    _seed_tenant(client)
    client.patch(
        "/v1/admin/settings",
        json={
            "tenant_id": TENANT_ID,
            "support_email": "support@acme.example",
            "billing_contact_email": "billing@acme.example",
        },
    )
    client.post(
        "/v1/admin/users",
        json={
            "tenant_id": TENANT_ID,
            "email": "owner@acme.example",
            "role": "owner",
        },
    )

    by_slug = client.get(
        "/v1/admin/support/tenants", params={"query": "acme-intelligence"}
    )
    by_support_email = client.get(
        "/v1/admin/support/tenants", params={"query": "support@acme.example"}
    )
    by_user_email = client.get(
        "/v1/admin/support/tenants", params={"query": "owner@acme.example"}
    )

    assert by_slug.status_code == 200
    assert by_support_email.status_code == 200
    assert by_user_email.status_code == 200
    assert by_slug.json()["tenants"][0]["id"] == TENANT_ID
    assert by_slug.json()["tenants"][0]["support_email"] == "support@acme.example"
    assert (
        by_support_email.json()["tenants"][0]["billing_contact_email"]
        == "billing@acme.example"
    )
    assert by_user_email.json()["tenants"][0]["active_user_count"] == 1


def test_admin_support_summary_returns_triage_and_cost_report(tmp_path) -> None:
    client = _create_client(tmp_path)
    _seed_tenant(client)
    project = _seed_project(client)
    _create_failed_run(client)
    billing_detail = _create_billing_record(client)

    notification_id = str(uuid4())
    now = datetime.now(UTC).isoformat()
    with client.app.state.db_engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO notifications (
                    id,
                    tenant_id,
                    project_id,
                    notification_type,
                    channel,
                    status,
                    payload,
                    created_at,
                    sent_at
                ) VALUES (
                    :id,
                    :tenant_id,
                    NULL,
                    'run_failed',
                    'email',
                    'sent',
                    '{"subject":"Run failed","body":"Support investigate"}',
                    :created_at,
                    :sent_at
                )
                """
            ),
            {
                "id": notification_id,
                "tenant_id": TENANT_ID,
                "created_at": now,
                "sent_at": now,
            },
        )
    webhook_delivery_id = _seed_webhook_delivery_failure(
        client,
        notification_id=notification_id,
    )

    _ingest_document(
        client,
        project_id=project.id,
        file_name="tor-v1.pdf",
        content=b"draft-v1",
    )
    _ingest_document(
        client,
        project_id=project.id,
        file_name="tor-v2.pdf",
        content=b"draft-v2",
    )

    summary = client.get(
        f"/v1/admin/support/tenants/{TENANT_ID}/summary",
    )

    assert summary.status_code == 200
    body = summary.json()
    assert body["tenant"]["id"] == TENANT_ID
    assert body["triage"] == {
        "failed_runs_recent": 1,
        "pending_document_reviews": 1,
        "failed_webhook_deliveries": 1,
        "outstanding_billing_records": 1,
    }
    assert body["cost_summary"] == {
        "window_days": 30,
        "currency": "THB",
        "estimated_total_thb": "1.87",
        "crawl": {
            "estimated_cost_thb": "0.35",
            "run_count": 1,
            "task_count": 1,
            "failed_run_count": 1,
        },
        "storage": {
            "estimated_cost_thb": "0.06",
            "document_count": 2,
            "total_bytes": 16,
        },
        "notifications": {
            "estimated_cost_thb": "0.21",
            "sent_count": 1,
            "failed_webhook_delivery_count": 1,
        },
        "payments": {
            "estimated_cost_thb": "1.25",
            "billing_record_count": 1,
            "payment_request_count": 0,
            "collected_amount_thb": "0.00",
        },
    }
    assert body["recent_failed_runs"][0]["status"] == "failed"
    assert body["pending_reviews"][0]["status"] == "pending"
    assert body["failed_webhooks"][0]["id"] == webhook_delivery_id
    assert (
        body["billing_issues"][0]["record_number"]
        == billing_detail["record"]["record_number"]
    )


def test_support_role_can_access_selected_tenant_context(tmp_path) -> None:
    client = _create_client(tmp_path, auth_required=True)
    _seed_tenant(client, tenant_id=TENANT_ID, slug="tenant-one")
    _seed_tenant(
        client, tenant_id=OTHER_TENANT_ID, slug="tenant-two", name="Other Tenant"
    )

    support_snapshot = client.get(
        "/v1/admin",
        params={"tenant_id": OTHER_TENANT_ID},
        headers=_auth_headers(role="support"),
    )
    support_settings = client.patch(
        "/v1/admin/settings",
        json={
            "tenant_id": OTHER_TENANT_ID,
            "support_email": "support@other.example",
        },
        headers=_auth_headers(role="support"),
    )
    admin_lookup = client.get(
        "/v1/admin/support/tenants",
        params={"query": "tenant-two"},
        headers=_auth_headers(role="admin"),
    )

    assert support_snapshot.status_code == 200
    assert support_snapshot.json()["tenant"]["id"] == OTHER_TENANT_ID
    assert support_settings.status_code == 200
    assert support_settings.json()["support_email"] == "support@other.example"
    assert admin_lookup.status_code == 403
    assert admin_lookup.json()["detail"] == "support role required"


def test_non_support_roles_cannot_cross_tenant_or_use_support_lookup(tmp_path) -> None:
    client = _create_client(tmp_path, auth_required=True)
    _seed_tenant(client, tenant_id=TENANT_ID, slug="tenant-one")
    _seed_tenant(
        client, tenant_id=OTHER_TENANT_ID, slug="tenant-two", name="Other Tenant"
    )

    foreign_snapshot = client.get(
        "/v1/admin",
        params={"tenant_id": OTHER_TENANT_ID},
        headers=_auth_headers(role="admin"),
    )
    support_lookup = client.get(
        "/v1/admin/support/tenants",
        params={"query": "tenant-two"},
        headers=_auth_headers(role="viewer"),
    )

    assert foreign_snapshot.status_code == 403
    assert foreign_snapshot.json()["detail"] == "tenant mismatch"
    assert support_lookup.status_code == 403
    assert support_lookup.json()["detail"] == "support role required"


def test_support_role_remains_tenant_scoped_on_non_support_routes(tmp_path) -> None:
    client = _create_client(tmp_path, auth_required=True)
    _seed_tenant(client, tenant_id=TENANT_ID, slug="tenant-one")
    _seed_tenant(
        client, tenant_id=OTHER_TENANT_ID, slug="tenant-two", name="Other Tenant"
    )

    response = client.get(
        "/v1/projects",
        params={"tenant_id": OTHER_TENANT_ID},
        headers=_auth_headers(role="support"),
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "tenant mismatch"


def test_admin_audit_log_returns_cross_domain_feed_and_filters(tmp_path) -> None:
    client = _create_client(tmp_path)
    _seed_tenant(client)
    project = _seed_project(client)

    _create_billing_record(client)
    _ingest_document(
        client,
        project_id=project.id,
        file_name="tor-v1.pdf",
        content=b"draft-tor-v1",
    )
    _ingest_document(
        client,
        project_id=project.id,
        file_name="tor-v2.pdf",
        content=b"draft-tor-v2",
    )

    reviews = client.get(
        f"/v1/documents/projects/{project.id}/reviews",
        params={"tenant_id": TENANT_ID},
    )
    assert reviews.status_code == 200
    review_id = reviews.json()["reviews"][0]["id"]

    review_action = client.post(
        f"/v1/documents/reviews/{review_id}/actions",
        json={
            "tenant_id": TENANT_ID,
            "action": "approve",
            "note": "Reviewed by ops",
        },
    )
    assert review_action.status_code == 200

    created_user = client.post(
        "/v1/admin/users",
        json={
            "tenant_id": TENANT_ID,
            "email": "auditor@example.com",
            "role": "admin",
        },
    )
    assert created_user.status_code == 201

    settings = client.patch(
        "/v1/admin/settings",
        json={
            "tenant_id": TENANT_ID,
            "support_email": "support@example.com",
        },
    )
    assert settings.status_code == 200

    response = client.get("/v1/admin/audit-log", params={"tenant_id": TENANT_ID})

    assert response.status_code == 200
    body = response.json()
    assert body["limit"] == 50
    assert body["offset"] == 0
    assert body["total"] >= 6
    assert {"project", "billing", "review", "document", "admin"} <= {
        item["source"] for item in body["items"]
    }

    filtered = client.get(
        "/v1/admin/audit-log",
        params={
            "tenant_id": TENANT_ID,
            "source": "admin",
            "entity_type": "user",
        },
    )

    assert filtered.status_code == 200
    filtered_body = filtered.json()
    assert filtered_body["total"] >= 1
    assert {item["source"] for item in filtered_body["items"]} == {"admin"}
    assert {item["entity_type"] for item in filtered_body["items"]} == {"user"}


def test_admin_audit_log_is_tenant_scoped(tmp_path) -> None:
    client = _create_client(tmp_path)
    _seed_tenant(client, tenant_id=TENANT_ID, slug="tenant-one")
    _seed_tenant(
        client,
        tenant_id=OTHER_TENANT_ID,
        name="Other Tenant",
        slug="tenant-two",
    )

    client.post(
        "/v1/admin/users",
        json={
            "tenant_id": TENANT_ID,
            "email": "tenant-one@example.com",
            "role": "admin",
        },
    )
    client.post(
        "/v1/admin/users",
        json={
            "tenant_id": OTHER_TENANT_ID,
            "email": "tenant-two@example.com",
            "role": "admin",
        },
    )

    response = client.get("/v1/admin/audit-log", params={"tenant_id": TENANT_ID})

    assert response.status_code == 200
    body = response.json()
    assert body["total"] >= 1
    assert all(item["tenant_id"] == TENANT_ID for item in body["items"])
    assert all(item["summary"] != "tenant-two@example.com" for item in body["items"])
