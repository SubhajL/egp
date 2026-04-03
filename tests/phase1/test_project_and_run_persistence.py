from __future__ import annotations

import sqlite3

import pytest

from egp_db.repositories.project_repo import SqlProjectRepository, build_project_upsert_record
from egp_db.repositories.run_repo import SqlRunRepository
from egp_shared_types.enums import CrawlRunStatus, ProcurementType, ProjectState

TENANT_ID = "11111111-1111-1111-1111-111111111111"
SECOND_TENANT_ID = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"


def test_upsert_project_merges_aliases_and_backfills_project_number(tmp_path) -> None:
    database_path = tmp_path / "phase1.sqlite3"
    repository = SqlProjectRepository(
        database_url=f"sqlite+pysqlite:///{database_path}",
        bootstrap_schema=True,
    )

    first = repository.upsert_project(
        build_project_upsert_record(
            tenant_id=TENANT_ID,
            project_number=None,
            search_name="ระบบข้อมูลกลาง",
            detail_name="โครงการระบบข้อมูลกลาง",
            project_name="โครงการระบบข้อมูลกลาง",
            organization_name="กรมตัวอย่าง",
            proposal_submission_date="2026-05-01",
            budget_amount="1500000.00",
            procurement_type=ProcurementType.SERVICES,
            project_state=ProjectState.DISCOVERED,
        ),
        source_status_text="ประกาศเชิญชวน",
    )
    second = repository.upsert_project(
        build_project_upsert_record(
            tenant_id=TENANT_ID,
            project_number="EGP-2026-0042",
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

    detail = repository.get_project_detail(tenant_id=TENANT_ID, project_id=second.id)

    assert first.id == second.id
    assert second.canonical_project_id == "project-number:EGP-2026-0042"
    assert second.project_number == "EGP-2026-0042"
    assert second.project_state is ProjectState.OPEN_INVITATION
    assert detail is not None
    assert {alias.alias_type for alias in detail.aliases} == {
        "search_name",
        "detail_name",
        "fingerprint",
        "project_number",
    }
    assert detail.status_events[-1].observed_status_text == "ประกาศเชิญชวน"


def test_list_projects_is_tenant_scoped_and_returns_newest_first(tmp_path) -> None:
    database_path = tmp_path / "phase1.sqlite3"
    repository = SqlProjectRepository(
        database_url=f"sqlite+pysqlite:///{database_path}",
        bootstrap_schema=True,
    )

    older = repository.upsert_project(
        build_project_upsert_record(
            tenant_id=TENANT_ID,
            project_number="EGP-2026-0001",
            search_name="โครงการแรก",
            detail_name="โครงการแรก",
            project_name="โครงการแรก",
            organization_name="กรมหนึ่ง",
            proposal_submission_date="2026-05-01",
            budget_amount="1000",
            procurement_type=ProcurementType.GOODS,
            project_state=ProjectState.DISCOVERED,
        ),
        source_status_text="ประกาศเชิญชวน",
    )
    newer = repository.upsert_project(
        build_project_upsert_record(
            tenant_id=TENANT_ID,
            project_number="EGP-2026-0002",
            search_name="โครงการสอง",
            detail_name="โครงการสอง",
            project_name="โครงการสอง",
            organization_name="กรมสอง",
            proposal_submission_date="2026-05-02",
            budget_amount="2000",
            procurement_type=ProcurementType.SERVICES,
            project_state=ProjectState.OPEN_INVITATION,
        ),
        source_status_text="ประกาศเชิญชวน",
    )
    repository.upsert_project(
        build_project_upsert_record(
            tenant_id=SECOND_TENANT_ID,
            project_number="EGP-2026-0003",
            search_name="hidden",
            detail_name="hidden",
            project_name="hidden",
            organization_name="กรมสาม",
            proposal_submission_date="2026-05-03",
            budget_amount="3000",
            procurement_type=ProcurementType.SERVICES,
            project_state=ProjectState.OPEN_INVITATION,
        ),
        source_status_text="ประกาศเชิญชวน",
    )

    project_page = repository.list_projects(tenant_id=TENANT_ID)

    assert [project.id for project in project_page.items] == [newer.id, older.id]
    assert all(project.tenant_id == TENANT_ID for project in project_page.items)
    assert project_page.total == 2


def test_project_repository_persists_alias_and_status_event_rows(tmp_path) -> None:
    database_path = tmp_path / "phase1.sqlite3"
    repository = SqlProjectRepository(
        database_url=f"sqlite+pysqlite:///{database_path}",
        bootstrap_schema=True,
    )

    project = repository.upsert_project(
        build_project_upsert_record(
            tenant_id=TENANT_ID,
            project_number="EGP-2026-0099",
            search_name="ประกวดราคากลาง",
            detail_name="ประกวดราคากลาง",
            project_name="ประกวดราคากลาง",
            organization_name="กรมทดสอบ",
            proposal_submission_date="2026-05-10",
            budget_amount="9000",
            procurement_type=ProcurementType.CONSULTING,
            project_state=ProjectState.OPEN_CONSULTING,
        ),
        source_status_text="เปิดรับฟังคำวิจารณ์",
    )

    with sqlite3.connect(database_path) as connection:
        alias_count = connection.execute(
            "SELECT COUNT(*) FROM project_aliases WHERE project_id = ?",
            (project.id,),
        ).fetchone()[0]
        status_event = connection.execute(
            """
            SELECT observed_status_text, normalized_status
            FROM project_status_events
            WHERE project_id = ?
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (project.id,),
        ).fetchone()

    assert alias_count == 4
    assert status_event == ("เปิดรับฟังคำวิจารณ์", "open_consulting")


def test_projects_with_same_display_name_but_different_fingerprint_do_not_merge(tmp_path) -> None:
    database_path = tmp_path / "phase1.sqlite3"
    repository = SqlProjectRepository(
        database_url=f"sqlite+pysqlite:///{database_path}",
        bootstrap_schema=True,
    )

    first = repository.upsert_project(
        build_project_upsert_record(
            tenant_id=TENANT_ID,
            project_number=None,
            search_name="Common Name",
            detail_name="Common Name",
            project_name="Common Name",
            organization_name="Org A",
            proposal_submission_date="2026-05-01",
            budget_amount="100.00",
            procurement_type=ProcurementType.GOODS,
            project_state=ProjectState.DISCOVERED,
        ),
        source_status_text="ประกาศเชิญชวน",
    )
    second = repository.upsert_project(
        build_project_upsert_record(
            tenant_id=TENANT_ID,
            project_number=None,
            search_name="Common Name",
            detail_name="Common Name",
            project_name="Common Name",
            organization_name="Org B",
            proposal_submission_date="2026-06-01",
            budget_amount="200.00",
            procurement_type=ProcurementType.SERVICES,
            project_state=ProjectState.OPEN_INVITATION,
        ),
        source_status_text="ประกาศเชิญชวน",
    )

    project_page = repository.list_projects(tenant_id=TENANT_ID)

    assert first.id != second.id
    assert len(project_page.items) == 2


def test_upsert_project_rejects_state_regression_for_existing_project(tmp_path) -> None:
    database_path = tmp_path / "phase1.sqlite3"
    repository = SqlProjectRepository(
        database_url=f"sqlite+pysqlite:///{database_path}",
        bootstrap_schema=True,
    )

    repository.upsert_project(
        build_project_upsert_record(
            tenant_id=TENANT_ID,
            project_number="EGP-2026-0101",
            search_name="regression project",
            detail_name="regression project",
            project_name="regression project",
            organization_name="กรมตัวอย่าง",
            proposal_submission_date="2026-05-01",
            budget_amount="1000",
            procurement_type=ProcurementType.SERVICES,
            project_state=ProjectState.OPEN_INVITATION,
        ),
        source_status_text="ประกาศเชิญชวน",
    )

    with pytest.raises(ValueError, match="illegal project state transition"):
        repository.upsert_project(
            build_project_upsert_record(
                tenant_id=TENANT_ID,
                project_number="EGP-2026-0101",
                search_name="regression project",
                detail_name="regression project",
                project_name="regression project",
                organization_name="กรมตัวอย่าง",
                proposal_submission_date="2026-05-01",
                budget_amount="1000",
                procurement_type=ProcurementType.SERVICES,
                project_state=ProjectState.DISCOVERED,
            ),
            source_status_text="ประกาศเชิญชวน",
        )


def test_run_repository_tracks_runs_and_tasks(tmp_path) -> None:
    database_path = tmp_path / "phase1.sqlite3"
    repository = SqlRunRepository(
        database_url=f"sqlite+pysqlite:///{database_path}",
        bootstrap_schema=True,
    )

    run = repository.create_run(tenant_id=TENANT_ID, trigger_type="manual")
    task = repository.create_task(
        run_id=run.id,
        task_type="discover",
        keyword="โรงพยาบาล",
        payload={"page": 1},
    )
    repository.mark_run_started(run.id)
    repository.mark_task_finished(task.id, status="succeeded", result_json={"count": 3})
    finished = repository.mark_run_finished(
        run.id,
        status=CrawlRunStatus.SUCCEEDED,
        summary_json={"projects_seen": 3},
    )
    detail = repository.get_run_detail(tenant_id=TENANT_ID, run_id=run.id)

    assert finished.status is CrawlRunStatus.SUCCEEDED
    assert detail is not None
    assert detail.run.started_at is not None
    assert detail.run.finished_at is not None
    assert detail.tasks[0].keyword == "โรงพยาบาล"
    assert detail.tasks[0].status == "succeeded"
    assert detail.tasks[0].result_json == {"count": 3}


def test_run_repository_rejects_invalid_trigger_and_task_type(tmp_path) -> None:
    database_path = tmp_path / "phase1.sqlite3"
    repository = SqlRunRepository(
        database_url=f"sqlite+pysqlite:///{database_path}",
        bootstrap_schema=True,
    )

    with pytest.raises(ValueError, match="invalid crawl run trigger_type"):
        repository.create_run(tenant_id=TENANT_ID, trigger_type="not-a-real-trigger")

    run = repository.create_run(tenant_id=TENANT_ID, trigger_type="manual")

    with pytest.raises(ValueError, match="invalid crawl task_type"):
        repository.create_task(run_id=run.id, task_type="bogus-task")


def test_project_and_run_listing_supports_limit_and_offset(tmp_path) -> None:
    database_path = tmp_path / "phase1.sqlite3"
    project_repository = SqlProjectRepository(
        database_url=f"sqlite+pysqlite:///{database_path}",
        bootstrap_schema=True,
    )
    run_repository = SqlRunRepository(
        database_url=f"sqlite+pysqlite:///{database_path}",
        bootstrap_schema=False,
    )

    first_project = project_repository.upsert_project(
        build_project_upsert_record(
            tenant_id=TENANT_ID,
            project_number="EGP-2026-0201",
            search_name="โครงการแรก",
            detail_name="โครงการแรก",
            project_name="โครงการแรก",
            organization_name="กรมหนึ่ง",
            proposal_submission_date="2026-05-01",
            budget_amount="1000",
            procurement_type=ProcurementType.GOODS,
            project_state=ProjectState.DISCOVERED,
        ),
        source_status_text="ประกาศเชิญชวน",
    )
    project_repository.upsert_project(
        build_project_upsert_record(
            tenant_id=TENANT_ID,
            project_number="EGP-2026-0202",
            search_name="โครงการสอง",
            detail_name="โครงการสอง",
            project_name="โครงการสอง",
            organization_name="กรมสอง",
            proposal_submission_date="2026-05-02",
            budget_amount="2000",
            procurement_type=ProcurementType.SERVICES,
            project_state=ProjectState.OPEN_INVITATION,
        ),
        source_status_text="ประกาศเชิญชวน",
    )
    first_run = run_repository.create_run(tenant_id=TENANT_ID, trigger_type="manual")
    run_repository.create_run(tenant_id=TENANT_ID, trigger_type="retry")

    project_page = project_repository.list_projects(tenant_id=TENANT_ID, limit=1, offset=1)
    run_page = run_repository.list_runs(tenant_id=TENANT_ID, limit=1, offset=1)

    assert project_page.total == 2
    assert project_page.limit == 1
    assert project_page.offset == 1
    assert [project.id for project in project_page.items] == [first_project.id]

    assert run_page.total == 2
    assert run_page.limit == 1
    assert run_page.offset == 1
    assert [run.id for run in run_page.items] == [first_run.id]
