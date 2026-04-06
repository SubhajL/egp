from __future__ import annotations

import base64
from datetime import UTC, date, datetime, timedelta
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import text

from egp_api.main import create_app
from egp_db.repositories.project_repo import build_project_upsert_record
from egp_shared_types.enums import ProcurementType, ProjectState, UserRole

TENANT_ID = "11111111-1111-1111-1111-111111111111"


def _create_client(tmp_path, *, email_sender=None) -> TestClient:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'phase4-entitlements.sqlite3'}"
    return TestClient(
        create_app(
            artifact_root=tmp_path,
            database_url=database_url,
            auth_required=False,
            notification_email_sender=email_sender,
        )
    )


def _seed_subscription(
    client: TestClient,
    *,
    tenant_id: str = TENANT_ID,
    plan_code: str,
    keyword_limit: int,
    billing_period_start: date,
    billing_period_end: date,
    status: str = "active",
) -> None:
    record_id = str(uuid4())
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
                    :plan_code,
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
                "plan_code": plan_code,
                "billing_period_start": billing_period_start.isoformat(),
                "billing_period_end": billing_period_end.isoformat(),
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
                    :plan_code,
                    :status,
                    :billing_period_start,
                    :billing_period_end,
                    :keyword_limit,
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
                "plan_code": plan_code,
                "status": status,
                "billing_period_start": billing_period_start.isoformat(),
                "billing_period_end": billing_period_end.isoformat(),
                "keyword_limit": keyword_limit,
                "activated_at": now,
                "created_at": now,
                "updated_at": now,
            },
        )


def _seed_profile(
    client: TestClient,
    *,
    profile_id: str,
    name: str,
    is_active: bool,
    keywords: list[str],
    tenant_id: str = TENANT_ID,
) -> None:
    with client.app.state.db_engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO crawl_profiles (
                    id,
                    tenant_id,
                    name,
                    profile_type,
                    is_active,
                    max_pages_per_keyword,
                    close_consulting_after_days,
                    close_stale_after_days,
                    created_at,
                    updated_at
                ) VALUES (
                    :id,
                    :tenant_id,
                    :name,
                    'tor',
                    :is_active,
                    15,
                    30,
                    45,
                    :created_at,
                    :updated_at
                )
                """
            ),
            {
                "id": profile_id,
                "tenant_id": tenant_id,
                "name": name,
                "is_active": is_active,
                "created_at": "2026-04-05T00:00:00+00:00",
                "updated_at": "2026-04-05T00:00:00+00:00",
            },
        )
        for position, keyword in enumerate(keywords, start=1):
            connection.execute(
                text(
                    """
                    INSERT INTO crawl_profile_keywords (
                        id,
                        profile_id,
                        keyword,
                        position,
                        created_at
                    ) VALUES (
                        :id,
                        :profile_id,
                        :keyword,
                        :position,
                        :created_at
                    )
                    """
                ),
                {
                    "id": str(uuid4()),
                    "profile_id": profile_id,
                    "keyword": keyword,
                    "position": position,
                    "created_at": "2026-04-05T00:00:00+00:00",
                },
            )


def _seed_project(client: TestClient, *, tenant_id: str = TENANT_ID):
    return client.app.state.project_repository.upsert_project(
        build_project_upsert_record(
            tenant_id=tenant_id,
            project_number=f"EGP-2026-{uuid4().hex[:6]}",
            search_name="ระบบข้อมูลกลาง",
            detail_name="ระบบข้อมูลกลาง",
            project_name="ระบบข้อมูลกลาง",
            organization_name="กรมตัวอย่าง",
            proposal_submission_date="2026-05-01",
            budget_amount="1500000.00",
            procurement_type=ProcurementType.SERVICES,
            project_state=ProjectState.OPEN_INVITATION,
        ),
        source_status_text="ประกาศเชิญชวน",
    )


def _ingest_document(
    client: TestClient,
    *,
    project_id: str,
    content: bytes,
    file_name: str = "tor.pdf",
) -> dict[str, object]:
    response = client.post(
        "/v1/documents/ingest",
        json={
            "tenant_id": TENANT_ID,
            "project_id": project_id,
            "file_name": file_name,
            "content_base64": base64.b64encode(content).decode("ascii"),
            "source_label": "เอกสารประกวดราคา",
            "source_status_text": "ประกาศเชิญชวน",
        },
    )
    assert response.status_code in {200, 201}
    return response.json()


def test_rules_snapshot_includes_subscription_and_keyword_usage(tmp_path) -> None:
    client = _create_client(tmp_path)
    today = date.today()
    _seed_subscription(
        client,
        plan_code="monthly_membership",
        keyword_limit=5,
        billing_period_start=today - timedelta(days=1),
        billing_period_end=today + timedelta(days=29),
    )
    _seed_profile(
        client,
        profile_id="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        name="TOR",
        is_active=True,
        keywords=["ระบบข้อมูล", "สุขภาพ"],
    )
    _seed_profile(
        client,
        profile_id="bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
        name="Inactive",
        is_active=False,
        keywords=["ไม่ควรถูกนับ"],
    )

    response = client.get("/v1/rules", params={"tenant_id": TENANT_ID})

    assert response.status_code == 200
    body = response.json()
    assert body["entitlements"]["plan_code"] == "monthly_membership"
    assert body["entitlements"]["subscription_status"] == "active"
    assert body["entitlements"]["has_active_subscription"] is True
    assert body["entitlements"]["keyword_limit"] == 5
    assert body["entitlements"]["active_keyword_count"] == 2
    assert body["entitlements"]["remaining_keyword_slots"] == 3
    assert body["entitlements"]["over_keyword_limit"] is False
    assert body["entitlements"]["active_keywords"] == ["ระบบข้อมูล", "สุขภาพ"]
    assert body["entitlements"]["runs_allowed"] is True
    assert body["entitlements"]["exports_allowed"] is True
    assert body["entitlements"]["document_download_allowed"] is True
    assert body["entitlements"]["notifications_allowed"] is True


def test_free_trial_snapshot_limits_exports_downloads_and_notifications(tmp_path) -> None:
    client = _create_client(tmp_path)
    today = date.today()
    _seed_subscription(
        client,
        plan_code="free_trial",
        keyword_limit=1,
        billing_period_start=today - timedelta(days=1),
        billing_period_end=today + timedelta(days=5),
    )
    _seed_profile(
        client,
        profile_id="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        name="TOR",
        is_active=True,
        keywords=["ระบบข้อมูล"],
    )

    response = client.get("/v1/rules", params={"tenant_id": TENANT_ID})

    assert response.status_code == 200
    body = response.json()
    assert body["entitlements"]["plan_code"] == "free_trial"
    assert body["entitlements"]["plan_label"] == "Free Trial"
    assert body["entitlements"]["keyword_limit"] == 1
    assert body["entitlements"]["runs_allowed"] is True
    assert body["entitlements"]["exports_allowed"] is False
    assert body["entitlements"]["document_download_allowed"] is False
    assert body["entitlements"]["notifications_allowed"] is False


def test_run_creation_requires_active_subscription(tmp_path) -> None:
    client = _create_client(tmp_path)

    response = client.post(
        "/v1/runs",
        json={"tenant_id": TENANT_ID, "trigger_type": "manual"},
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "active subscription required for runs"


def test_discover_task_keyword_must_be_entitled(tmp_path) -> None:
    client = _create_client(tmp_path)
    today = date.today()
    _seed_subscription(
        client,
        plan_code="monthly_membership",
        keyword_limit=5,
        billing_period_start=today - timedelta(days=1),
        billing_period_end=today + timedelta(days=29),
    )
    _seed_profile(
        client,
        profile_id="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        name="TOR",
        is_active=True,
        keywords=["โรงพยาบาล"],
    )

    created = client.post(
        "/v1/runs",
        json={"tenant_id": TENANT_ID, "trigger_type": "manual"},
    )
    assert created.status_code == 201
    run_id = created.json()["run"]["id"]

    allowed = client.post(
        f"/v1/runs/{run_id}/tasks",
        params={"tenant_id": TENANT_ID},
        json={"task_type": "discover", "keyword": "โรงพยาบาล", "payload": {"page": 1}},
    )
    denied = client.post(
        f"/v1/runs/{run_id}/tasks",
        params={"tenant_id": TENANT_ID},
        json={"task_type": "discover", "keyword": "รถดับเพลิง", "payload": {"page": 1}},
    )

    assert allowed.status_code == 201
    assert denied.status_code == 403
    assert denied.json()["detail"] == "discover keyword is not entitled for tenant"


def test_over_limit_profiles_block_new_discover_tasks(tmp_path) -> None:
    client = _create_client(tmp_path)
    today = date.today()
    _seed_subscription(
        client,
        plan_code="monthly_membership",
        keyword_limit=5,
        billing_period_start=today - timedelta(days=1),
        billing_period_end=today + timedelta(days=29),
    )
    _seed_profile(
        client,
        profile_id="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        name="TOR-A",
        is_active=True,
        keywords=["kw1", "kw2", "kw3"],
    )
    _seed_profile(
        client,
        profile_id="bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
        name="TOR-B",
        is_active=True,
        keywords=["kw4", "kw5", "kw6"],
    )

    created = client.post(
        "/v1/runs",
        json={"tenant_id": TENANT_ID, "trigger_type": "manual"},
    )
    assert created.status_code == 201
    run_id = created.json()["run"]["id"]

    response = client.post(
        f"/v1/runs/{run_id}/tasks",
        params={"tenant_id": TENANT_ID},
        json={"task_type": "discover", "keyword": "kw1", "payload": {"page": 1}},
    )

    assert response.status_code == 403
    assert (
        response.json()["detail"] == "active keyword configuration exceeds plan limit"
    )


def test_export_requires_active_subscription(tmp_path) -> None:
    client = _create_client(tmp_path)
    _seed_project(client)

    response = client.get("/v1/exports/excel", params={"tenant_id": TENANT_ID})

    assert response.status_code == 403
    assert response.json()["detail"] == "active subscription required for exports"


def test_document_download_requires_active_subscription(tmp_path) -> None:
    client = _create_client(tmp_path)
    project = _seed_project(client)
    created = _ingest_document(client, project_id=project.id, content=b"tor-v1")
    document_id = created["document"]["id"]

    response = client.get(
        f"/v1/documents/{document_id}/download",
        params={"tenant_id": TENANT_ID},
    )

    assert response.status_code == 403
    assert (
        response.json()["detail"]
        == "active subscription required for document downloads"
    )


def test_notifications_are_suppressed_when_entitlement_inactive(tmp_path) -> None:
    sent: list[str] = []
    client = _create_client(
        tmp_path, email_sender=lambda *, to, subject, body: sent.append(to)
    )
    client.app.state.notification_repository.create_user(
        tenant_id=TENANT_ID,
        email="ops@example.com",
        role=UserRole.OWNER,
    )
    project = _seed_project(client)

    first = _ingest_document(
        client, project_id=project.id, content=b"tor-v1", file_name="tor-v1.pdf"
    )
    second = _ingest_document(
        client, project_id=project.id, content=b"tor-v2", file_name="tor-v2.pdf"
    )

    notifications = client.app.state.notification_repository.list_for_tenant(TENANT_ID)

    assert first["created"] is True
    assert second["created"] is True
    assert notifications == []
    assert sent == []
