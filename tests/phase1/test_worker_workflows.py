from __future__ import annotations

from egp_db.repositories.notification_repo import SqlNotificationRepository
from egp_db.repositories.project_repo import (
    SqlProjectRepository,
    build_project_upsert_record,
)
from egp_db.repositories.run_repo import SqlRunRepository
from egp_notifications.dispatcher import NotificationDispatcher
from egp_notifications.service import NotificationService
from egp_shared_types.enums import ClosedReason, ProcurementType, ProjectState
from egp_worker.workflows.close_check import run_close_check_workflow
from egp_worker.workflows.discover import run_discover_workflow

TENANT_ID = "11111111-1111-1111-1111-111111111111"


def _notification_dispatcher(
    database_url: str,
) -> tuple[SqlNotificationRepository, NotificationDispatcher]:
    repository = SqlNotificationRepository(
        database_url=database_url, bootstrap_schema=True
    )
    repository.create_user(tenant_id=TENANT_ID, email="owner@example.com", role="owner")
    dispatcher = NotificationDispatcher(
        service=NotificationService(
            in_app_store=repository,
            email_sender=lambda *, to, subject, body: None,
        ),
        recipient_resolver=repository,
    )
    return repository, dispatcher


def test_discover_workflow_upserts_projects_and_records_run_tasks(tmp_path) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'phase1.sqlite3'}"

    result = run_discover_workflow(
        database_url=database_url,
        tenant_id=TENANT_ID,
        keyword="โรงพยาบาล",
        discovered_projects=[
            {
                "project_number": "EGP-2026-3001",
                "search_name": "ระบบข้อมูลกลาง",
                "detail_name": "โครงการระบบข้อมูลกลาง",
                "project_name": "โครงการระบบข้อมูลกลาง",
                "organization_name": "กรมตัวอย่าง",
                "proposal_submission_date": "2026-05-01",
                "budget_amount": "1500000.00",
                "procurement_type": ProcurementType.SERVICES.value,
                "project_state": ProjectState.OPEN_INVITATION.value,
                "source_status_text": "ประกาศเชิญชวน",
            }
        ],
    )

    project_repository = SqlProjectRepository(
        database_url=database_url, bootstrap_schema=False
    )
    run_repository = SqlRunRepository(database_url=database_url, bootstrap_schema=False)
    project_page = project_repository.list_projects(tenant_id=TENANT_ID)
    run_detail = run_repository.get_run_detail(
        tenant_id=TENANT_ID, run_id=result.run.run.id
    )

    assert len(project_page.items) == 1
    assert project_page.items[0].canonical_project_id == "project-number:EGP-2026-3001"
    assert run_detail is not None
    assert run_detail.tasks[0].task_type == "discover"
    assert run_detail.tasks[0].keyword == "โรงพยาบาล"


def test_close_check_workflow_transitions_project_from_status_text(tmp_path) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'phase1.sqlite3'}"
    project_repository = SqlProjectRepository(
        database_url=database_url, bootstrap_schema=True
    )
    seeded = project_repository.upsert_project(
        build_project_upsert_record(
            tenant_id=TENANT_ID,
            project_number="EGP-2026-3002",
            search_name="ประกวดราคาไอที",
            detail_name="ประกวดราคาไอที",
            project_name="ประกวดราคาไอที",
            organization_name="กรมตัวอย่าง",
            proposal_submission_date="2026-05-02",
            budget_amount="2500000.00",
            procurement_type=ProcurementType.SERVICES,
            project_state=ProjectState.OPEN_INVITATION,
        ),
        source_status_text="ประกาศเชิญชวน",
    )

    result = run_close_check_workflow(
        database_url=database_url,
        tenant_id=TENANT_ID,
        observations=[
            {
                "project_id": seeded.id,
                "source_status_text": "ประกาศผู้ชนะการเสนอราคา",
            }
        ],
    )

    updated = project_repository.get_project(tenant_id=TENANT_ID, project_id=seeded.id)

    assert result.updated_projects[0].id == seeded.id
    assert updated is not None
    assert updated.project_state is ProjectState.WINNER_ANNOUNCED
    assert updated.closed_reason is ClosedReason.WINNER_ANNOUNCED


def test_close_check_workflow_sets_contract_signed_reason(tmp_path) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'phase1.sqlite3'}"
    project_repository = SqlProjectRepository(
        database_url=database_url, bootstrap_schema=True
    )
    seeded = project_repository.upsert_project(
        build_project_upsert_record(
            tenant_id=TENANT_ID,
            project_number="EGP-2026-3003",
            search_name="ก่อสร้างอาคาร",
            detail_name="ก่อสร้างอาคาร",
            project_name="ก่อสร้างอาคาร",
            organization_name="กรมตัวอย่าง",
            proposal_submission_date="2026-05-03",
            budget_amount="5000000.00",
            procurement_type=ProcurementType.SERVICES,
            project_state=ProjectState.OPEN_INVITATION,
        ),
        source_status_text="ประกาศเชิญชวน",
    )

    result = run_close_check_workflow(
        database_url=database_url,
        tenant_id=TENANT_ID,
        observations=[
            {
                "project_id": seeded.id,
                "source_status_text": "อยู่ระหว่างลงนามสัญญา",
            }
        ],
    )

    updated = project_repository.get_project(tenant_id=TENANT_ID, project_id=seeded.id)

    assert result.updated_projects[0].id == seeded.id
    assert updated is not None
    assert updated.project_state is ProjectState.CONTRACT_SIGNED
    assert updated.closed_reason is ClosedReason.CONTRACT_SIGNED


def test_discover_workflow_emits_new_project_notification(tmp_path) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'phase1.sqlite3'}"
    repository, dispatcher = _notification_dispatcher(database_url)

    run_discover_workflow(
        database_url=database_url,
        tenant_id=TENANT_ID,
        keyword="โรงพยาบาล",
        discovered_projects=[
            {
                "project_number": "EGP-2026-3010",
                "search_name": "ระบบข้อมูลกลาง",
                "detail_name": "โครงการระบบข้อมูลกลาง",
                "project_name": "โครงการระบบข้อมูลกลาง",
                "organization_name": "กรมตัวอย่าง",
                "proposal_submission_date": "2026-05-01",
                "budget_amount": "1500000.00",
                "procurement_type": ProcurementType.SERVICES.value,
                "project_state": ProjectState.OPEN_INVITATION.value,
                "source_status_text": "ประกาศเชิญชวน",
            }
        ],
        notification_dispatcher=dispatcher,
    )

    notifications = repository.list_for_tenant(TENANT_ID)

    assert len(notifications) == 1
    assert notifications[0].notification_type.value == "new_project"


def test_close_check_workflow_emits_winner_announced_notification(tmp_path) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'phase1.sqlite3'}"
    repository, dispatcher = _notification_dispatcher(database_url)
    project_repository = SqlProjectRepository(
        database_url=database_url, bootstrap_schema=True
    )
    seeded = project_repository.upsert_project(
        build_project_upsert_record(
            tenant_id=TENANT_ID,
            project_number="EGP-2026-3011",
            search_name="ประกวดราคาไอที",
            detail_name="ประกวดราคาไอที",
            project_name="ประกวดราคาไอที",
            organization_name="กรมตัวอย่าง",
            proposal_submission_date="2026-05-02",
            budget_amount="2500000.00",
            procurement_type=ProcurementType.SERVICES,
            project_state=ProjectState.OPEN_INVITATION,
        ),
        source_status_text="ประกาศเชิญชวน",
    )

    run_close_check_workflow(
        database_url=database_url,
        tenant_id=TENANT_ID,
        observations=[
            {"project_id": seeded.id, "source_status_text": "ประกาศผู้ชนะการเสนอราคา"}
        ],
        notification_dispatcher=dispatcher,
    )

    notifications = repository.list_for_tenant(TENANT_ID)

    assert notifications[0].notification_type.value == "winner_announced"


def test_close_check_workflow_emits_contract_signed_notification(tmp_path) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'phase1.sqlite3'}"
    repository, dispatcher = _notification_dispatcher(database_url)
    project_repository = SqlProjectRepository(
        database_url=database_url, bootstrap_schema=True
    )
    seeded = project_repository.upsert_project(
        build_project_upsert_record(
            tenant_id=TENANT_ID,
            project_number="EGP-2026-3012",
            search_name="ก่อสร้างอาคาร",
            detail_name="ก่อสร้างอาคาร",
            project_name="ก่อสร้างอาคาร",
            organization_name="กรมตัวอย่าง",
            proposal_submission_date="2026-05-03",
            budget_amount="5000000.00",
            procurement_type=ProcurementType.SERVICES,
            project_state=ProjectState.OPEN_INVITATION,
        ),
        source_status_text="ประกาศเชิญชวน",
    )

    run_close_check_workflow(
        database_url=database_url,
        tenant_id=TENANT_ID,
        observations=[
            {"project_id": seeded.id, "source_status_text": "อยู่ระหว่างลงนามสัญญา"}
        ],
        notification_dispatcher=dispatcher,
    )

    notifications = repository.list_for_tenant(TENANT_ID)

    assert notifications[0].notification_type.value == "contract_signed"
