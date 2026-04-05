from __future__ import annotations

from fastapi.testclient import TestClient

from egp_api.main import create_app
from egp_db.repositories.project_repo import build_project_upsert_record
from egp_shared_types.enums import CrawlRunStatus, ProcurementType, ProjectState

TENANT_ID = "11111111-1111-1111-1111-111111111111"


def test_project_crawl_evidence_endpoint_returns_project_scoped_run_tasks(
    tmp_path,
) -> None:
    database_url = (
        f"sqlite+pysqlite:///{tmp_path / 'phase2-project-crawl-evidence.sqlite3'}"
    )
    client = TestClient(
        create_app(
            artifact_root=tmp_path, database_url=database_url, auth_required=False
        )
    )
    project_repository = client.app.state.project_repository
    run_repository = client.app.state.run_repository

    target_project = project_repository.upsert_project(
        build_project_upsert_record(
            tenant_id=TENANT_ID,
            project_number="EGP-2026-3001",
            search_name="ระบบติดตามโครงการ",
            detail_name="ระบบติดตามโครงการ",
            project_name="ระบบติดตามโครงการ",
            organization_name="กรมตัวอย่าง",
            proposal_submission_date="2026-06-01",
            budget_amount="5000000",
            procurement_type=ProcurementType.SERVICES,
            project_state=ProjectState.OPEN_INVITATION,
        ),
        source_status_text="ประกาศเชิญชวน",
    )
    other_project = project_repository.upsert_project(
        build_project_upsert_record(
            tenant_id=TENANT_ID,
            project_number="EGP-2026-3002",
            search_name="โครงการอื่น",
            detail_name="โครงการอื่น",
            project_name="โครงการอื่น",
            organization_name="กรมอื่น",
            proposal_submission_date="2026-06-02",
            budget_amount="2500000",
            procurement_type=ProcurementType.GOODS,
            project_state=ProjectState.DISCOVERED,
        ),
        source_status_text="ค้นพบโครงการ",
    )

    run = run_repository.create_run(
        tenant_id=TENANT_ID,
        trigger_type="manual",
        summary_json={"projects_seen": 2},
    )
    target_task = run_repository.create_task(
        run_id=run.id,
        task_type="update",
        project_id=target_project.id,
        keyword="ระบบติดตาม",
        payload={"page": 2},
    )
    other_task = run_repository.create_task(
        run_id=run.id,
        task_type="discover",
        project_id=other_project.id,
        keyword="โครงการอื่น",
        payload={"page": 1},
    )
    run_repository.mark_run_started(run.id)
    run_repository.mark_task_started(target_task.id)
    run_repository.mark_task_finished(
        target_task.id,
        status="succeeded",
        result_json={"documents_checked": 3, "changes_detected": 1},
    )
    run_repository.mark_task_started(other_task.id)
    run_repository.mark_task_finished(
        other_task.id,
        status="failed",
        result_json={"error": "timeout"},
    )
    run_repository.mark_run_finished(
        run.id,
        status=CrawlRunStatus.PARTIAL,
        summary_json={"projects_seen": 2, "projects_failed": 1},
        error_count=1,
    )

    response = client.get(
        f"/v1/projects/{target_project.id}/crawl-evidence",
        params={"tenant_id": TENANT_ID},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["limit"] == 20
    assert body["offset"] == 0
    assert len(body["evidence"]) == 1
    assert body["evidence"][0]["task_id"] == target_task.id
    assert body["evidence"][0]["run_id"] == run.id
    assert body["evidence"][0]["trigger_type"] == "manual"
    assert body["evidence"][0]["run_status"] == CrawlRunStatus.PARTIAL.value
    assert body["evidence"][0]["task_type"] == "update"
    assert body["evidence"][0]["task_status"] == "succeeded"
    assert body["evidence"][0]["keyword"] == "ระบบติดตาม"
    assert body["evidence"][0]["payload"] == {"page": 2}
    assert body["evidence"][0]["result_json"] == {
        "documents_checked": 3,
        "changes_detected": 1,
    }
    assert body["evidence"][0]["run_summary_json"] == {
        "projects_seen": 2,
        "projects_failed": 1,
    }
    assert body["evidence"][0]["run_error_count"] == 1
