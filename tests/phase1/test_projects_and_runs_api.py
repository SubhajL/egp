from __future__ import annotations

from fastapi.testclient import TestClient

from egp_api.main import create_app
from egp_shared_types.enums import NotificationType
from egp_db.repositories.project_repo import build_project_upsert_record
from egp_shared_types.enums import CrawlRunStatus, ProcurementType, ProjectState

TENANT_ID = "11111111-1111-1111-1111-111111111111"


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
