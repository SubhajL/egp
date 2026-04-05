from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import text

from egp_api.main import create_app
from egp_shared_types.enums import NotificationType
from egp_db.repositories.project_repo import build_project_upsert_record
from egp_shared_types.enums import CrawlRunStatus, ProcurementType, ProjectState

TENANT_ID = "11111111-1111-1111-1111-111111111111"


def _seed_active_subscription(client: TestClient) -> None:
    today = date.today()
    now = datetime.now(UTC).isoformat()
    record_id = str(uuid4())
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
                "tenant_id": TENANT_ID,
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
                "tenant_id": TENANT_ID,
                "billing_record_id": record_id,
                "billing_period_start": (today - timedelta(days=1)).isoformat(),
                "billing_period_end": (today + timedelta(days=29)).isoformat(),
                "activated_at": now,
                "created_at": now,
                "updated_at": now,
            },
        )


def _seed_active_profile_keyword(client: TestClient, *, keyword: str) -> None:
    profile_id = str(uuid4())
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
                    'TOR',
                    'tor',
                    1,
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
                "tenant_id": TENANT_ID,
                "created_at": "2026-04-05T00:00:00+00:00",
                "updated_at": "2026-04-05T00:00:00+00:00",
            },
        )
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
                    1,
                    :created_at
                )
                """
            ),
            {
                "id": str(uuid4()),
                "profile_id": profile_id,
                "keyword": keyword,
                "created_at": "2026-04-05T00:00:00+00:00",
            },
        )


def test_projects_endpoints_list_and_detail_repository_backed(tmp_path) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'phase1.sqlite3'}"
    client = TestClient(
        create_app(
            artifact_root=tmp_path, database_url=database_url, auth_required=False
        )
    )
    repository = client.app.state.project_repository
    project = repository.upsert_project(
        build_project_upsert_record(
            tenant_id=TENANT_ID,
            project_number="EGP-2026-1001",
            search_name="ระบบข้อมูลกลาง",
            detail_name="โครงการระบบข้อมูลกลาง",
            project_name="โครงการระบบข้อมูลกลาง",
            organization_name="กรมตัวอย่าง",
            proposal_submission_date="2026-05-01",
            budget_amount="1500000.00",
            procurement_type=ProcurementType.SERVICES,
            project_state=ProjectState.OPEN_INVITATION,
        ),
        source_status_text="ประกาศเชิญชวน",
    )

    listed = client.get("/v1/projects", params={"tenant_id": TENANT_ID})
    detail = client.get(f"/v1/projects/{project.id}", params={"tenant_id": TENANT_ID})

    assert listed.status_code == 200
    assert (
        listed.json()["projects"][0]["canonical_project_id"]
        == "project-number:EGP-2026-1001"
    )
    assert listed.json()["total"] == 1
    assert listed.json()["limit"] == 50
    assert listed.json()["offset"] == 0
    assert detail.status_code == 200
    assert detail.json()["project"]["id"] == project.id
    assert detail.json()["aliases"][0]["alias_type"] == "project_number"


def test_runs_endpoints_create_list_and_return_tasks(tmp_path) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'phase1.sqlite3'}"
    client = TestClient(
        create_app(
            artifact_root=tmp_path, database_url=database_url, auth_required=False
        )
    )
    _seed_active_subscription(client)
    _seed_active_profile_keyword(client, keyword="โรงพยาบาล")

    created = client.post(
        "/v1/runs", json={"tenant_id": TENANT_ID, "trigger_type": "manual"}
    )
    run_id = created.json()["run"]["id"]
    task = client.post(
        f"/v1/runs/{run_id}/tasks",
        params={"tenant_id": TENANT_ID},
        json={"task_type": "discover", "keyword": "โรงพยาบาล", "payload": {"page": 1}},
    )
    client.post(
        f"/v1/runs/{run_id}/finish",
        params={"tenant_id": TENANT_ID},
        json={
            "status": CrawlRunStatus.SUCCEEDED.value,
            "summary_json": {"projects_seen": 1},
        },
    )
    listed = client.get("/v1/runs", params={"tenant_id": TENANT_ID})

    assert created.status_code == 201
    assert task.status_code == 201
    assert listed.status_code == 200
    assert listed.json()["total"] == 1
    assert listed.json()["limit"] == 50
    assert listed.json()["offset"] == 0
    assert listed.json()["runs"][0]["run"]["status"] == CrawlRunStatus.SUCCEEDED.value
    assert listed.json()["runs"][0]["tasks"][0]["task_type"] == "discover"


def test_projects_and_runs_endpoints_accept_limit_and_offset(tmp_path) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'phase1.sqlite3'}"
    client = TestClient(
        create_app(
            artifact_root=tmp_path, database_url=database_url, auth_required=False
        )
    )
    _seed_active_subscription(client)
    repository = client.app.state.project_repository

    for project_number in ("EGP-2026-1101", "EGP-2026-1102"):
        repository.upsert_project(
            build_project_upsert_record(
                tenant_id=TENANT_ID,
                project_number=project_number,
                search_name=project_number,
                detail_name=project_number,
                project_name=project_number,
                organization_name="กรมตัวอย่าง",
                proposal_submission_date="2026-05-01",
                budget_amount="1500000.00",
                procurement_type=ProcurementType.SERVICES,
                project_state=ProjectState.OPEN_INVITATION,
            ),
            source_status_text="ประกาศเชิญชวน",
        )

    first_run = client.post(
        "/v1/runs", json={"tenant_id": TENANT_ID, "trigger_type": "manual"}
    ).json()
    second_run = client.post(
        "/v1/runs", json={"tenant_id": TENANT_ID, "trigger_type": "retry"}
    ).json()

    projects_page = client.get(
        "/v1/projects", params={"tenant_id": TENANT_ID, "limit": 1, "offset": 1}
    )
    runs_page = client.get(
        "/v1/runs", params={"tenant_id": TENANT_ID, "limit": 1, "offset": 1}
    )

    assert projects_page.status_code == 200
    assert projects_page.json()["total"] == 2
    assert projects_page.json()["limit"] == 1
    assert projects_page.json()["offset"] == 1
    assert len(projects_page.json()["projects"]) == 1

    assert runs_page.status_code == 200
    assert runs_page.json()["total"] == 2
    assert runs_page.json()["limit"] == 1
    assert runs_page.json()["offset"] == 1
    assert len(runs_page.json()["runs"]) == 1
    assert runs_page.json()["runs"][0]["run"]["id"] == first_run["run"]["id"]
    assert second_run["run"]["id"] != first_run["run"]["id"]


def test_finish_run_failed_emits_run_failed_notification(tmp_path) -> None:
    sent: list[str] = []
    database_url = f"sqlite+pysqlite:///{tmp_path / 'phase1.sqlite3'}"
    client = TestClient(
        create_app(
            artifact_root=tmp_path,
            database_url=database_url,
            auth_required=False,
            notification_email_sender=lambda *, to, subject, body: sent.append(to),
        )
    )
    client.app.state.notification_repository.create_user(
        tenant_id=TENANT_ID,
        email="ops@example.com",
        role="owner",
    )
    _seed_active_subscription(client)

    created = client.post(
        "/v1/runs", json={"tenant_id": TENANT_ID, "trigger_type": "manual"}
    )
    run_id = created.json()["run"]["id"]
    finished = client.post(
        f"/v1/runs/{run_id}/finish",
        params={"tenant_id": TENANT_ID},
        json={
            "status": CrawlRunStatus.FAILED.value,
            "summary_json": {"projects_seen": 0},
            "error_count": 3,
        },
    )

    notifications = client.app.state.notification_repository.list_for_tenant(TENANT_ID)

    assert finished.status_code == 200
    assert sent == ["ops@example.com"]
    assert notifications[0].notification_type is NotificationType.RUN_FAILED
