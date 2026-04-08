from __future__ import annotations

from datetime import date, timedelta
from types import SimpleNamespace
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import text

from egp_api.main import create_app
from egp_db.repositories.notification_repo import SqlNotificationRepository
from egp_db.repositories.project_repo import (
    SqlProjectRepository,
    build_project_upsert_record,
)
from egp_db.repositories.run_repo import SqlRunRepository
from egp_notifications.dispatcher import NotificationDispatcher
from egp_notifications.service import NotificationService
from egp_shared_types.enums import ClosedReason, ProcurementType, ProjectState
from egp_shared_types.project_events import (
    CloseCheckProjectEvent,
    DiscoveredProjectEvent,
)
from egp_worker.main import run_worker_job
from egp_worker.project_event_sink import ApiProjectEventSink
from egp_worker.workflows.close_check import run_close_check_workflow
from egp_worker.workflows.discover import run_discover_workflow

TENANT_ID = "11111111-1111-1111-1111-111111111111"
INTERNAL_WORKER_TOKEN = "phase1-internal-worker-token"


def _seed_subscription(
    *,
    database_url: str,
    plan_code: str,
    keyword_limit: int,
    billing_period_start: date,
    billing_period_end: date,
) -> None:
    repository = SqlRunRepository(database_url=database_url, bootstrap_schema=True)
    with repository._engine.begin() as connection:
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
                    'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa',
                    :tenant_id,
                    'INV-WORKFLOW',
                    :plan_code,
                    'paid',
                    :billing_period_start,
                    :billing_period_end,
                    'THB',
                    '0.00',
                    :now,
                    :now
                )
                """
            ),
            {
                "tenant_id": TENANT_ID,
                "plan_code": plan_code,
                "billing_period_start": billing_period_start.isoformat(),
                "billing_period_end": billing_period_end.isoformat(),
                "now": "2026-04-08T00:00:00+00:00",
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
                    'bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb',
                    :tenant_id,
                    'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa',
                    :plan_code,
                    'active',
                    :billing_period_start,
                    :billing_period_end,
                    :keyword_limit,
                    :now,
                    :now,
                    :now
                )
                """
            ),
            {
                "tenant_id": TENANT_ID,
                "plan_code": plan_code,
                "billing_period_start": billing_period_start.isoformat(),
                "billing_period_end": billing_period_end.isoformat(),
                "keyword_limit": keyword_limit,
                "now": "2026-04-08T00:00:00+00:00",
            },
        )


def _seed_profile(*, database_url: str, keywords: list[str]) -> None:
    project_repository = SqlProjectRepository(database_url=database_url, bootstrap_schema=True)
    with project_repository._engine.begin() as connection:
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
                    'cccccccc-cccc-cccc-cccc-cccccccccccc',
                    :tenant_id,
                    'Watchlist',
                    'custom',
                    1,
                    15,
                    30,
                    45,
                    :now,
                    :now
                )
                """
            ),
            {"tenant_id": TENANT_ID, "now": "2026-04-08T00:00:00+00:00"},
        )
        for index, keyword in enumerate(keywords, start=1):
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
                        'cccccccc-cccc-cccc-cccc-cccccccccccc',
                        :keyword,
                        :position,
                        :created_at
                    )
                    """
                ),
                {
                    "id": str(uuid4()),
                    "keyword": keyword,
                    "position": index,
                    "created_at": "2026-04-08T00:00:00+00:00",
                },
            )


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


class FakeProjectEventSink:
    def __init__(self) -> None:
        self.discovery_events: list[DiscoveredProjectEvent] = []
        self.close_check_events: list[CloseCheckProjectEvent] = []

    def record_discovery(self, event: DiscoveredProjectEvent):
        self.discovery_events.append(event)
        return SimpleNamespace(
            id="project-from-sink",
            project_state=ProjectState.OPEN_INVITATION,
        )

    def record_close_check(self, event: CloseCheckProjectEvent):
        self.close_check_events.append(event)
        return SimpleNamespace(
            id=event.project_id,
            project_state=ProjectState.WINNER_ANNOUNCED
            if event.closed_reason is ClosedReason.WINNER_ANNOUNCED
            else ProjectState.CONTRACT_SIGNED,
        )


def test_discover_workflow_emits_project_events_and_records_run_tasks(tmp_path) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'phase1.sqlite3'}"
    sink = FakeProjectEventSink()
    today = date.today()
    _seed_subscription(
        database_url=database_url,
        plan_code="free_trial",
        keyword_limit=1,
        billing_period_start=today - timedelta(days=1),
        billing_period_end=today + timedelta(days=5),
    )
    _seed_profile(database_url=database_url, keywords=["โรงพยาบาล"])

    result = run_discover_workflow(
        database_url=database_url,
        tenant_id=TENANT_ID,
        keyword="โรงพยาบาล",
        project_event_sink=sink,
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

    assert len(project_page.items) == 0
    assert len(sink.discovery_events) == 1
    assert sink.discovery_events[0].project_number == "EGP-2026-3001"
    assert sink.discovery_events[0].keyword == "โรงพยาบาล"
    assert result.projects[0].id == "project-from-sink"
    assert run_detail is not None
    assert run_detail.tasks[0].task_type == "discover"
    assert run_detail.tasks[0].keyword == "โรงพยาบาล"
    assert run_detail.tasks[0].result_json == {"project_id": "project-from-sink"}


def test_close_check_workflow_emits_close_events_after_reason_match(tmp_path) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'phase1.sqlite3'}"
    sink = FakeProjectEventSink()
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
        project_event_sink=sink,
        observations=[
            {
                "project_id": seeded.id,
                "source_status_text": "ประกาศผู้ชนะการเสนอราคา",
            }
        ],
    )

    updated = project_repository.get_project(tenant_id=TENANT_ID, project_id=seeded.id)

    assert result.updated_projects[0].id == seeded.id
    assert len(sink.close_check_events) == 1
    assert sink.close_check_events[0].project_id == seeded.id
    assert sink.close_check_events[0].closed_reason is ClosedReason.WINNER_ANNOUNCED
    assert updated is not None
    assert updated.project_state is ProjectState.OPEN_INVITATION
    assert updated.closed_reason is None


def test_close_check_workflow_skips_non_matching_status_without_sink_call(
    tmp_path,
) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'phase1.sqlite3'}"
    sink = FakeProjectEventSink()
    run_repository = SqlRunRepository(database_url=database_url, bootstrap_schema=True)

    result = run_close_check_workflow(
        database_url=database_url,
        tenant_id=TENANT_ID,
        project_event_sink=sink,
        observations=[
            {
                "project_id": "11111111-1111-1111-1111-111111111112",
                "source_status_text": "ยังเปิดรับข้อเสนอ",
            }
        ],
    )

    run_detail = run_repository.get_run_detail(
        tenant_id=TENANT_ID, run_id=result.run.run.id
    )

    assert result.updated_projects == []
    assert sink.close_check_events == []
    assert run_detail is not None
    assert run_detail.tasks[0].status == "skipped"
    assert run_detail.tasks[0].result_json == {"matched": False}


def test_discover_workflow_uses_service_backed_sink_for_notifications(tmp_path) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'phase1.sqlite3'}"
    repository, dispatcher = _notification_dispatcher(database_url)
    today = date.today()
    _seed_subscription(
        database_url=database_url,
        plan_code="free_trial",
        keyword_limit=1,
        billing_period_start=today - timedelta(days=1),
        billing_period_end=today + timedelta(days=5),
    )
    _seed_profile(database_url=database_url, keywords=["โรงพยาบาล"])

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


def test_close_check_workflow_uses_service_backed_sink_for_winner_notification(
    tmp_path,
) -> None:
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


def test_close_check_workflow_uses_service_backed_sink_for_contract_notification(
    tmp_path,
) -> None:
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


def test_api_project_event_sink_posts_discovery_to_auth_enabled_api(tmp_path) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'phase1-worker-remote.sqlite3'}"
    client = TestClient(
        create_app(
            artifact_root=tmp_path,
            database_url=database_url,
            auth_required=True,
            jwt_secret="unused-for-internal-route",
            internal_worker_token=INTERNAL_WORKER_TOKEN,
        )
    )
    sink = ApiProjectEventSink(
        base_url=str(client.base_url),
        worker_token=INTERNAL_WORKER_TOKEN,
        client=client,
    )

    project = sink.record_discovery(
        DiscoveredProjectEvent(
            tenant_id=TENANT_ID,
            keyword="โรงพยาบาล",
            project_number="EGP-2026-3099",
            search_name="ระบบข้อมูลกลาง",
            detail_name="โครงการระบบข้อมูลกลาง",
            project_name="โครงการระบบข้อมูลกลาง",
            organization_name="กรมตัวอย่าง",
            proposal_submission_date="2026-05-01",
            budget_amount="1500000.00",
            procurement_type=ProcurementType.SERVICES,
            project_state=ProjectState.OPEN_INVITATION,
            source_status_text="ประกาศเชิญชวน",
            raw_snapshot={"page": 1},
        )
    )

    stored = client.app.state.project_repository.get_project(
        tenant_id=TENANT_ID,
        project_id=project.id,
    )

    assert stored is not None
    assert stored.project_number == "EGP-2026-3099"
    assert stored.project_state is ProjectState.OPEN_INVITATION


def test_api_project_event_sink_posts_close_check_to_auth_enabled_api(tmp_path) -> None:
    database_url = (
        f"sqlite+pysqlite:///{tmp_path / 'phase1-worker-remote-close.sqlite3'}"
    )
    client = TestClient(
        create_app(
            artifact_root=tmp_path,
            database_url=database_url,
            auth_required=True,
            jwt_secret="unused-for-internal-route",
            internal_worker_token=INTERNAL_WORKER_TOKEN,
        )
    )
    seeded = client.app.state.project_repository.upsert_project(
        build_project_upsert_record(
            tenant_id=TENANT_ID,
            project_number="EGP-2026-3098",
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
    sink = ApiProjectEventSink(
        base_url=str(client.base_url),
        worker_token=INTERNAL_WORKER_TOKEN,
        client=client,
    )

    project = sink.record_close_check(
        CloseCheckProjectEvent(
            tenant_id=TENANT_ID,
            project_id=seeded.id,
            closed_reason=ClosedReason.WINNER_ANNOUNCED,
            source_status_text="ประกาศผู้ชนะการเสนอราคา",
            raw_snapshot={"page": 2},
        )
    )

    stored = client.app.state.project_repository.get_project(
        tenant_id=TENANT_ID,
        project_id=project.id,
    )

    assert stored is not None
    assert stored.project_state is ProjectState.WINNER_ANNOUNCED
    assert stored.closed_reason is ClosedReason.WINNER_ANNOUNCED


def test_run_worker_job_dispatches_discover_workflow(tmp_path) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'phase1-worker-dispatch.sqlite3'}"
    today = date.today()
    _seed_subscription(
        database_url=database_url,
        plan_code="free_trial",
        keyword_limit=1,
        billing_period_start=today - timedelta(days=1),
        billing_period_end=today + timedelta(days=5),
    )
    _seed_profile(database_url=database_url, keywords=["โรงพยาบาล"])

    result = run_worker_job(
        {
            "command": "discover",
            "database_url": database_url,
            "tenant_id": TENANT_ID,
            "keyword": "โรงพยาบาล",
            "discovered_projects": [
                {
                    "project_number": "EGP-2026-3009",
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
        }
    )

    assert result["command"] == "discover"
    assert result["run_status"] == "succeeded"
    assert result["project_count"] == 1


def test_run_worker_job_preserves_profile_id_in_discover_result(tmp_path) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'phase1-worker-profile.sqlite3'}"
    today = date.today()
    _seed_subscription(
        database_url=database_url,
        plan_code="free_trial",
        keyword_limit=1,
        billing_period_start=today - timedelta(days=1),
        billing_period_end=today + timedelta(days=5),
    )
    _seed_profile(database_url=database_url, keywords=["โรงพยาบาล"])

    result = run_worker_job(
        {
            "command": "discover",
            "database_url": database_url,
            "tenant_id": TENANT_ID,
            "profile_id": "profile-123",
            "keyword": "โรงพยาบาล",
            "discovered_projects": [],
        }
    )

    assert result["command"] == "discover"
    assert result["profile_id"] == "profile-123"


def test_run_worker_job_dispatches_timeout_evaluation() -> None:
    result = run_worker_job(
        {
            "command": "timeout_evaluate",
            "procurement_type": ProcurementType.CONSULTING.value,
            "project_state": ProjectState.OPEN_INVITATION.value,
            "last_changed_at": "2026-01-01T00:00:00+00:00",
            "now": "2026-02-15T00:00:00+00:00",
        }
    )

    assert result["command"] == "timeout_evaluate"
    assert result["transition"]["closed_reason"] == "consulting_timeout_30d"
    assert result["transition"]["project_state"] == "closed_timeout_consulting"
