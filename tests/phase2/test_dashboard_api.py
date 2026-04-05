from __future__ import annotations

import base64
from datetime import UTC, date, datetime, timedelta
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import text

from egp_api.main import create_app
from egp_db.repositories.project_repo import build_project_upsert_record
from egp_shared_types.enums import (
    ClosedReason,
    CrawlRunStatus,
    ProcurementType,
    ProjectState,
)

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


def _seed_project(
    client: TestClient,
    *,
    project_number: str,
    project_name: str,
    project_state: ProjectState,
    observed_at: datetime,
    procurement_type: ProcurementType = ProcurementType.SERVICES,
    closed_reason: ClosedReason | None = None,
):
    repository = client.app.state.project_repository
    return repository.upsert_project(
        build_project_upsert_record(
            tenant_id=TENANT_ID,
            project_number=project_number,
            search_name=project_name,
            detail_name=project_name,
            project_name=project_name,
            organization_name="กรมตัวอย่าง",
            proposal_submission_date="2026-05-01",
            budget_amount="1000000",
            procurement_type=procurement_type,
            project_state=project_state,
            closed_reason=closed_reason,
        ),
        source_status_text=project_name,
        observed_at=observed_at.isoformat(),
    )


def _ingest_document(
    client: TestClient,
    *,
    project_id: str,
    file_name: str,
    content: bytes,
) -> None:
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
    assert response.status_code == 201


def _create_run(
    client: TestClient,
    *,
    trigger_type: str,
    status: CrawlRunStatus,
    projects_seen: int,
    profile_id: str | None = None,
) -> dict[str, object]:
    created = client.post(
        "/v1/runs",
        json={
            "tenant_id": TENANT_ID,
            "trigger_type": trigger_type,
            "profile_id": profile_id,
        },
    )
    assert created.status_code == 201
    run_id = created.json()["run"]["id"]
    task = client.post(
        f"/v1/runs/{run_id}/tasks",
        params={"tenant_id": TENANT_ID},
        json={
            "task_type": "discover",
            "keyword": "สุขภาพ",
            "payload": {"page": 1},
        },
    )
    assert task.status_code == 201
    finished = client.post(
        f"/v1/runs/{run_id}/finish",
        params={"tenant_id": TENANT_ID},
        json={
            "status": status.value,
            "summary_json": {"projects_seen": projects_seen},
            "error_count": 1 if status is CrawlRunStatus.FAILED else 0,
        },
    )
    assert finished.status_code == 200
    return finished.json()


def test_dashboard_summary_endpoint_returns_repository_backed_metrics(tmp_path) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'phase2-dashboard.sqlite3'}"
    client = TestClient(
        create_app(
            artifact_root=tmp_path, database_url=database_url, auth_required=False
        )
    )
    _seed_active_subscription(client)
    _seed_active_profile_keyword(client, keyword="สุขภาพ")

    now = datetime.now(UTC).replace(microsecond=0)
    today_open = _seed_project(
        client,
        project_number="EGP-2026-4001",
        project_name="ระบบข้อมูลสุขภาพ",
        project_state=ProjectState.OPEN_INVITATION,
        observed_at=now - timedelta(hours=1),
    )
    today_closed = _seed_project(
        client,
        project_number="EGP-2026-4002",
        project_name="โครงการปิดวันนี้",
        project_state=ProjectState.CLOSED_MANUAL,
        observed_at=now - timedelta(hours=2),
        closed_reason=ClosedReason.MANUAL,
    )
    weekly_winner = _seed_project(
        client,
        project_number="EGP-2026-4003",
        project_name="ประกาศผู้ชนะระบบกลาง",
        project_state=ProjectState.WINNER_ANNOUNCED,
        observed_at=now - timedelta(days=2),
        procurement_type=ProcurementType.CONSULTING,
        closed_reason=ClosedReason.WINNER_ANNOUNCED,
    )
    consulting = _seed_project(
        client,
        project_number="EGP-2026-4004",
        project_name="ที่ปรึกษาระบบข้อมูลภาครัฐ",
        project_state=ProjectState.OPEN_CONSULTING,
        observed_at=now - timedelta(days=6),
        procurement_type=ProcurementType.CONSULTING,
    )
    _seed_project(
        client,
        project_number="EGP-2026-4005",
        project_name="โครงการค้นพบย้อนหลัง",
        project_state=ProjectState.DISCOVERED,
        observed_at=now - timedelta(days=12),
    )
    _seed_project(
        client,
        project_number="EGP-2026-4006",
        project_name="ผู้ชนะเก่าเกินสัปดาห์",
        project_state=ProjectState.WINNER_ANNOUNCED,
        observed_at=now - timedelta(days=10),
        closed_reason=ClosedReason.WINNER_ANNOUNCED,
    )

    _ingest_document(
        client, project_id=weekly_winner.id, file_name="tor-v1.pdf", content=b"tor-v1"
    )
    _ingest_document(
        client, project_id=weekly_winner.id, file_name="tor-v2.pdf", content=b"tor-v2"
    )

    _create_run(
        client,
        trigger_type="schedule",
        status=CrawlRunStatus.SUCCEEDED,
        projects_seen=12,
        profile_id="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
    )
    _create_run(
        client,
        trigger_type="manual",
        status=CrawlRunStatus.FAILED,
        projects_seen=0,
        profile_id="bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
    )
    _create_run(
        client,
        trigger_type="retry",
        status=CrawlRunStatus.PARTIAL,
        projects_seen=3,
    )
    latest_succeeded = _create_run(
        client,
        trigger_type="schedule",
        status=CrawlRunStatus.SUCCEEDED,
        projects_seen=8,
    )

    response = client.get("/v1/dashboard/summary", params={"tenant_id": TENANT_ID})

    assert response.status_code == 200
    body = response.json()
    assert body["kpis"]["active_projects"] == 5
    assert body["kpis"]["discovered_today"] == 2
    assert body["kpis"]["winner_projects_this_week"] == 1
    assert body["kpis"]["closed_today"] == 1
    assert body["kpis"]["changed_tor_projects"] == 1
    assert body["kpis"]["crawl_success_rate_percent"] == 50.0
    assert body["kpis"]["failed_runs_recent"] == 1
    assert body["kpis"]["crawl_success_window_runs"] == 4

    assert len(body["recent_runs"]) == 4
    assert body["recent_runs"][0]["id"] == latest_succeeded["run"]["id"]
    assert body["recent_runs"][0]["discovered_projects"] == 8

    assert [item["project_name"] for item in body["recent_changes"]] == [
        today_open.project_name,
        today_closed.project_name,
        weekly_winner.project_name,
        consulting.project_name,
        "ผู้ชนะเก่าเกินสัปดาห์",
    ]
    assert [item["project_name"] for item in body["winner_projects"]] == [
        weekly_winner.project_name
    ]

    series = {point["date"]: point["count"] for point in body["daily_discovery"]}
    assert len(body["daily_discovery"]) == 14
    assert series[now.date().isoformat()] == 2
    assert series[(now - timedelta(days=2)).date().isoformat()] == 1
    assert series[(now - timedelta(days=6)).date().isoformat()] == 1
    assert series[(now - timedelta(days=10)).date().isoformat()] == 1
    assert series[(now - timedelta(days=12)).date().isoformat()] == 1

    breakdown = {
        item["bucket"]: item["count"] for item in body["project_state_breakdown"]
    }
    assert breakdown == {
        "discovered": 1,
        "open_invitation": 1,
        "open_consulting": 1,
        "tor_downloaded": 0,
        "winner": 2,
        "closed": 1,
    }


def test_dashboard_summary_endpoint_returns_zero_safe_defaults_for_empty_tenant(
    tmp_path,
) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'phase2-dashboard-empty.sqlite3'}"
    client = TestClient(
        create_app(
            artifact_root=tmp_path, database_url=database_url, auth_required=False
        )
    )

    response = client.get("/v1/dashboard/summary", params={"tenant_id": TENANT_ID})

    assert response.status_code == 200
    body = response.json()
    assert body["kpis"] == {
        "active_projects": 0,
        "discovered_today": 0,
        "winner_projects_this_week": 0,
        "closed_today": 0,
        "changed_tor_projects": 0,
        "crawl_success_rate_percent": 0.0,
        "failed_runs_recent": 0,
        "crawl_success_window_runs": 0,
    }
    assert body["recent_runs"] == []
    assert body["recent_changes"] == []
    assert body["winner_projects"] == []
    assert len(body["daily_discovery"]) == 14
    assert all(point["count"] == 0 for point in body["daily_discovery"])
    assert body["project_state_breakdown"] == [
        {"bucket": "discovered", "count": 0},
        {"bucket": "open_invitation", "count": 0},
        {"bucket": "open_consulting", "count": 0},
        {"bucket": "tor_downloaded", "count": 0},
        {"bucket": "winner", "count": 0},
        {"bucket": "closed", "count": 0},
    ]
