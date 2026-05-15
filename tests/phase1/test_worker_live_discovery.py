from __future__ import annotations

from datetime import date, timedelta
import logging
from types import SimpleNamespace

import pytest
from egp_db.repositories.billing_repo import create_billing_repository
from egp_db.repositories.profile_repo import create_profile_repository
from sqlalchemy import text

from egp_shared_types.enums import ProjectState
from egp_worker.browser_discovery import (
    BrowserDiscoverySettings,
    LiveDiscoveryPartialError,
    SearchPageStateError,
)
from egp_worker.main import main as worker_main
from egp_worker.main import run_worker_job
from egp_worker.scheduler import build_scheduled_discovery_jobs, run_scheduled_discovery
from egp_worker.workflows.discover import run_discover_workflow
from egp_worker.workflows.close_check import run_close_check_workflow

TENANT_ID = "11111111-1111-1111-1111-111111111111"


class FakeRunRepository:
    def __init__(self) -> None:
        self.tasks: list[dict[str, object]] = []
        self.started_run_id: str | None = None
        self.created_profile_id: str | None = None
        self.created_run_id: str | None = None
        self.finished_status: str | None = None
        self.finished_summary: dict[str, object] | None = None
        self.finished_error_count: int | None = None
        self.summary_updates: list[dict[str, object] | None] = []
        self._runs: dict[str, SimpleNamespace] = {}

    def create_run(
        self,
        *,
        tenant_id: str,
        trigger_type: str,
        profile_id: str | None = None,
        run_id: str | None = None,
    ):
        self.created_profile_id = profile_id
        created_run = SimpleNamespace(
            id=run_id or "run-1",
            tenant_id=tenant_id,
            trigger_type=trigger_type,
            profile_id=profile_id,
        )
        self.created_run_id = created_run.id
        self._runs[created_run.id] = created_run
        return created_run

    def mark_run_started(self, run_id: str):
        self.started_run_id = run_id
        return self._runs.get(run_id) or SimpleNamespace(
            id=run_id,
            tenant_id=TENANT_ID,
            trigger_type="manual",
            profile_id=self.created_profile_id,
        )

    def update_run_summary(self, run_id: str, summary_json: dict[str, object]) -> None:
        self.summary_updates.append(summary_json)

    def create_task(
        self,
        *,
        run_id: str,
        task_type: str,
        keyword: str | None = None,
        project_id: str | None = None,
        payload: dict[str, object],
    ):
        task = SimpleNamespace(id=f"task-{len(self.tasks) + 1}", run_id=run_id)
        self.tasks.append(
            {
                "id": task.id,
                "task_type": task_type,
                "keyword": keyword,
                "project_id": project_id,
                "payload": payload,
                "status": "created",
            }
        )
        return task

    def mark_task_started(self, task_id: str) -> None:
        for task in self.tasks:
            if task["id"] == task_id:
                task["status"] = "started"
                return
        raise KeyError(task_id)

    def mark_task_finished(
        self, task_id: str, *, status: str, result_json: dict[str, object]
    ) -> None:
        for task in self.tasks:
            if task["id"] == task_id:
                task["status"] = status
                task["result_json"] = result_json
                return
        raise KeyError(task_id)

    def mark_run_finished(
        self,
        run_id: str,
        *,
        status: str,
        summary_json: dict[str, object],
        error_count: int,
    ) -> None:
        self.finished_status = status
        self.finished_summary = summary_json
        self.finished_error_count = error_count

    def get_run_detail(self, *, tenant_id: str, run_id: str):
        return SimpleNamespace(
            run=SimpleNamespace(
                id=run_id, tenant_id=tenant_id, status=self.finished_status
            ),
            tasks=[
                SimpleNamespace(
                    task_type=str(task["task_type"]),
                    keyword=str(task["keyword"]),
                    status=str(task["status"]),
                    result_json=task.get("result_json") or {},
                )
                for task in self.tasks
            ],
        )


class FakeProjectEventSink:
    def __init__(self) -> None:
        self.discovery_events: list[object] = []

    def record_discovery(self, event):
        self.discovery_events.append(event)
        return SimpleNamespace(
            id=f"project-{len(self.discovery_events)}",
            project_state=event.project_state,
        )


class FakeCloseProjectRepository:
    def list_projects(self, *, tenant_id: str, project_states=None, **kwargs):
        return SimpleNamespace(
            items=[
                SimpleNamespace(
                    id="project-1",
                    project_name="ประกวดราคาจัดซื้อระบบเครือข่าย",
                    project_number="EGP-2026-4001",
                    organization_name="กรมตัวอย่าง",
                    project_state=ProjectState.OPEN_INVITATION,
                )
            ]
        )


class FakeAdminRepository:
    def list_active_tenants(self):
        return [SimpleNamespace(id=TENANT_ID)]

    def get_tenant_settings(self, *, tenant_id: str):
        return SimpleNamespace(crawl_interval_hours=24)


class FakeProfileRepository:
    def __init__(self) -> None:
        self.active_keyword_calls = 0

    def list_profiles_with_keywords(self, *, tenant_id: str):
        return [
            SimpleNamespace(
                profile=SimpleNamespace(
                    id="profile-1",
                    profile_type="tor",
                    is_active=True,
                ),
                keywords=[
                    SimpleNamespace(keyword="analytics"),
                    SimpleNamespace(keyword="cloud"),
                ],
            )
        ]

    def list_active_keywords(self, *, tenant_id: str):
        self.active_keyword_calls += 1
        return ["analytics", "cloud"]


class FakeScheduledRunRepository:
    def list_runs(self, *, tenant_id: str, limit: int = 50, offset: int = 0):
        return SimpleNamespace(items=[])


class FakeBillingRepository:
    def __init__(self, subscriptions_by_tenant: dict[str, list[object]]) -> None:
        self._subscriptions_by_tenant = subscriptions_by_tenant
        self.subscription_calls = 0

    def list_subscriptions_for_tenant(self, *, tenant_id: str):
        self.subscription_calls += 1
        return list(self._subscriptions_by_tenant.get(tenant_id, []))


def _seed_subscription(
    *,
    database_url: str,
    plan_code: str,
    keyword_limit: int,
    billing_period_start: date,
    billing_period_end: date,
) -> None:
    repository = create_billing_repository(
        database_url=database_url, bootstrap_schema=True
    )
    now = "2026-04-08T00:00:00+00:00"
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
                    'INV-WORKER',
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
                "now": now,
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
                "now": now,
            },
        )


def _seed_profile(
    *, database_url: str, keywords: list[str], is_active: bool = True
) -> None:
    repository = create_profile_repository(
        database_url=database_url, bootstrap_schema=True
    )
    repository.create_profile(
        tenant_id=TENANT_ID,
        name="Watchlist",
        profile_type="custom",
        is_active=is_active,
        max_pages_per_keyword=15,
        close_consulting_after_days=30,
        close_stale_after_days=45,
        keywords=keywords,
    )


def test_run_discover_workflow_denies_without_active_subscription(tmp_path) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'worker-denied.sqlite3'}"
    run_repository = FakeRunRepository()
    sink = FakeProjectEventSink()
    _seed_profile(database_url=database_url, keywords=["analytics"])

    with pytest.raises(PermissionError, match="active subscription required for runs"):
        run_discover_workflow(
            database_url=database_url,
            tenant_id=TENANT_ID,
            keyword="analytics",
            discovered_projects=[],
            run_repository=run_repository,
            project_event_sink=sink,
        )

    assert run_repository.tasks == []
    assert run_repository.finished_status is None
    assert sink.discovery_events == []


def test_run_worker_job_discover_denies_when_keyword_not_entitled(tmp_path) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'worker-not-entitled.sqlite3'}"
    today = date.today()
    _seed_subscription(
        database_url=database_url,
        plan_code="monthly_membership",
        keyword_limit=5,
        billing_period_start=today - timedelta(days=1),
        billing_period_end=today + timedelta(days=29),
    )
    _seed_profile(database_url=database_url, keywords=["analytics"])

    with pytest.raises(
        PermissionError, match="discover keyword is not entitled for tenant"
    ):
        run_worker_job(
            {
                "command": "discover",
                "database_url": database_url,
                "tenant_id": TENANT_ID,
                "keyword": "cloud",
                "discovered_projects": [],
            }
        )


def test_run_worker_job_discover_allows_active_free_trial_entitled_keyword(
    tmp_path,
) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'worker-trial.sqlite3'}"
    today = date.today()
    _seed_subscription(
        database_url=database_url,
        plan_code="free_trial",
        keyword_limit=1,
        billing_period_start=today - timedelta(days=1),
        billing_period_end=today + timedelta(days=5),
    )
    _seed_profile(database_url=database_url, keywords=["analytics"])

    result = run_worker_job(
        {
            "command": "discover",
            "database_url": database_url,
            "tenant_id": TENANT_ID,
            "keyword": "analytics",
            "discovered_projects": [
                {
                    "project_number": "EGP-2026-5010",
                    "search_name": "ระบบข้อมูลกลาง",
                    "detail_name": "โครงการระบบข้อมูลกลาง",
                    "project_name": "โครงการระบบข้อมูลกลาง",
                    "organization_name": "กรมตัวอย่าง",
                    "proposal_submission_date": "2026-05-01",
                    "budget_amount": "1500000.00",
                    "project_state": ProjectState.OPEN_INVITATION.value,
                    "source_status_text": "ประกาศเชิญชวน",
                }
            ],
        }
    )

    assert result["command"] == "discover"
    assert result["run_status"] == "succeeded"
    assert result["project_count"] == 1


def test_run_discover_workflow_reuses_authorization_snapshot_for_discovered_projects(
    monkeypatch,
) -> None:
    billing_repository = FakeBillingRepository(
        {
            TENANT_ID: [
                SimpleNamespace(
                    subscription_status=SimpleNamespace(value="active"),
                    keyword_limit=5,
                )
            ]
        }
    )
    profile_repository = FakeProfileRepository()

    monkeypatch.setattr(
        "egp_worker.workflows.discover.create_billing_repository",
        lambda **kwargs: billing_repository,
    )
    monkeypatch.setattr(
        "egp_worker.workflows.discover.create_profile_repository",
        lambda **kwargs: profile_repository,
    )

    run_discover_workflow(
        database_url="sqlite+pysqlite:///unused.sqlite3",
        tenant_id=TENANT_ID,
        keyword="analytics",
        discovered_projects=[
            {
                "project_number": "EGP-2026-5010",
                "project_name": "โครงการระบบข้อมูลกลาง A",
                "organization_name": "กรมตัวอย่าง",
            },
            {
                "project_number": "EGP-2026-5011",
                "project_name": "โครงการระบบข้อมูลกลาง B",
                "organization_name": "กรมตัวอย่าง",
            },
        ],
        run_repository=FakeRunRepository(),
        project_event_sink=FakeProjectEventSink(),
    )

    assert billing_repository.subscription_calls == 1
    assert profile_repository.active_keyword_calls == 1


def test_run_discover_workflow_denies_per_project_keyword_outside_entitlement(
    tmp_path,
) -> None:
    database_url = (
        f"sqlite+pysqlite:///{tmp_path / 'worker-per-project-keyword.sqlite3'}"
    )
    today = date.today()
    _seed_subscription(
        database_url=database_url,
        plan_code="free_trial",
        keyword_limit=1,
        billing_period_start=today - timedelta(days=1),
        billing_period_end=today + timedelta(days=5),
    )
    _seed_profile(database_url=database_url, keywords=["analytics"])

    with pytest.raises(
        PermissionError, match="discover keyword is not entitled for tenant"
    ):
        run_discover_workflow(
            database_url=database_url,
            tenant_id=TENANT_ID,
            keyword="analytics",
            discovered_projects=[
                {
                    "keyword": "cloud",
                    "project_number": "EGP-2026-5011",
                    "search_name": "ระบบข้อมูลกลาง",
                    "detail_name": "โครงการระบบข้อมูลกลาง",
                    "project_name": "โครงการระบบข้อมูลกลาง",
                    "organization_name": "กรมตัวอย่าง",
                    "proposal_submission_date": "2026-05-01",
                    "budget_amount": "1500000.00",
                    "project_state": ProjectState.OPEN_INVITATION.value,
                    "source_status_text": "ประกาศเชิญชวน",
                }
            ],
        )


def test_run_discover_workflow_uses_live_discovery_source_when_projects_missing() -> (
    None
):
    run_repository = FakeRunRepository()
    sink = FakeProjectEventSink()
    crawled_keywords: list[str] = []

    def crawl(keyword: str) -> list[dict[str, object]]:
        crawled_keywords.append(keyword)
        return [
            {
                "keyword": keyword,
                "project_name": f"ประกวดราคา {keyword}",
                "organization_name": "กรมตัวอย่าง",
                "search_name": f"ค้นหา {keyword}",
                "detail_name": f"รายละเอียด {keyword}",
                "project_number": f"EGP-{keyword}",
                "proposal_submission_date": "2026-05-01",
                "budget_amount": "1000000.00",
                "project_state": ProjectState.OPEN_INVITATION.value,
                "source_status_text": "หนังสือเชิญชวน/ประกาศเชิญชวน",
                "raw_snapshot": {"keyword": keyword},
            }
        ]

    result = run_discover_workflow(
        tenant_id=TENANT_ID,
        keyword="โรงพยาบาล",
        discovered_projects=[],
        run_repository=run_repository,
        project_event_sink=sink,
        live_discovery=crawl,
    )

    assert crawled_keywords == ["โรงพยาบาล"]
    assert run_repository.finished_status == "succeeded"
    assert run_repository.finished_summary == {"projects_seen": 1}
    assert len(sink.discovery_events) == 1
    assert sink.discovery_events[0].project_name == "ประกวดราคา โรงพยาบาล"
    assert sink.discovery_events[0].project_state == ProjectState.OPEN_INVITATION.value
    assert sink.discovery_events[0].keyword == "โรงพยาบาล"
    assert run_repository.tasks[0]["keyword"] == "โรงพยาบาล"
    assert result.projects[0].id == "project-1"


def test_run_discover_workflow_persists_live_progress(monkeypatch) -> None:
    import egp_worker.workflows.discover as discover_module

    run_repository = FakeRunRepository()
    sink = FakeProjectEventSink()

    def fake_crawl_live_discovery(**kwargs):
        progress_callback = kwargs["progress_callback"]
        progress_callback(
            {
                "stage": "page_scan_finished",
                "keyword": "แพลตฟอร์ม",
                "page_num": 2,
                "eligible_count": 3,
            }
        )
        return []

    monkeypatch.setattr(
        discover_module,
        "crawl_live_discovery",
        fake_crawl_live_discovery,
    )

    result = run_discover_workflow(
        tenant_id=TENANT_ID,
        keyword="แพลตฟอร์ม",
        discovered_projects=[],
        run_repository=run_repository,
        project_event_sink=sink,
        live=True,
    )

    assert result.run.run.status == "succeeded"
    latest_update = run_repository.summary_updates[-1]
    assert latest_update is not None
    assert latest_update["projects_seen"] == 0
    assert latest_update["live_progress"] == {
        **{
            "stage": "page_scan_finished",
            "keyword": "แพลตฟอร์ม",
            "page_num": 2,
            "eligible_count": 3,
        },
        "updated_at": latest_update["live_progress"]["updated_at"],
    }
    assert isinstance(latest_update["live_progress"]["updated_at"], str)
    assert run_repository.finished_summary == {
        "projects_seen": 0,
        "live_progress": {
            "stage": "page_scan_finished",
            "keyword": "แพลตฟอร์ม",
            "page_num": 2,
            "eligible_count": 3,
            "updated_at": latest_update["live_progress"]["updated_at"],
        },
    }


def test_run_discover_workflow_marks_run_started_before_live_discovery_begins() -> None:
    run_repository = FakeRunRepository()
    sink = FakeProjectEventSink()

    def crawl(keyword: str) -> list[dict[str, object]]:
        assert keyword == "แพลตฟอร์ม"
        assert run_repository.started_run_id == "run-1"
        return []

    result = run_discover_workflow(
        tenant_id=TENANT_ID,
        keyword="แพลตฟอร์ม",
        discovered_projects=[],
        run_repository=run_repository,
        project_event_sink=sink,
        live_discovery=crawl,
    )

    assert result.run.run.id == "run-1"
    assert run_repository.created_profile_id is None
    assert run_repository.finished_status == "succeeded"
    assert run_repository.finished_summary == {"projects_seen": 0}


def test_run_discover_workflow_persists_profile_id_on_run() -> None:
    run_repository = FakeRunRepository()
    sink = FakeProjectEventSink()

    result = run_discover_workflow(
        tenant_id=TENANT_ID,
        profile_id="profile-123",
        keyword="analytics",
        discovered_projects=[],
        run_repository=run_repository,
        project_event_sink=sink,
    )

    assert result.run.run.id == "run-1"
    assert run_repository.created_profile_id == "profile-123"


def test_run_discover_workflow_uses_reserved_run_id_without_creating_another_run() -> (
    None
):
    run_repository = FakeRunRepository()
    sink = FakeProjectEventSink()
    run_repository.create_run(
        tenant_id=TENANT_ID,
        trigger_type="manual",
        profile_id="profile-123",
        run_id="run-reserved",
    )

    result = run_discover_workflow(
        tenant_id=TENANT_ID,
        run_id="run-reserved",
        profile_id="profile-123",
        keyword="analytics",
        discovered_projects=[],
        run_repository=run_repository,
        project_event_sink=sink,
    )

    assert result.run.run.id == "run-reserved"
    assert run_repository.created_run_id == "run-reserved"
    assert run_repository.started_run_id == "run-reserved"


def test_run_discover_workflow_marks_run_failed_when_live_discovery_crashes() -> None:
    run_repository = FakeRunRepository()
    sink = FakeProjectEventSink()

    def crawl(keyword: str) -> list[dict[str, object]]:
        raise RuntimeError(f"crawl blew up for {keyword}")

    with pytest.raises(RuntimeError, match="crawl blew up for analytics"):
        run_discover_workflow(
            tenant_id=TENANT_ID,
            keyword="analytics",
            discovered_projects=[],
            run_repository=run_repository,
            project_event_sink=sink,
            live_discovery=crawl,
        )

    assert run_repository.started_run_id == "run-1"
    assert run_repository.finished_status == "failed"
    assert run_repository.finished_summary == {
        "projects_seen": 0,
        "error": "crawl blew up for analytics",
    }
    assert run_repository.finished_error_count == 1


def test_run_discover_workflow_uses_metadata_only_browser_discovery_for_live_runs(
    monkeypatch,
) -> None:
    run_repository = FakeRunRepository()
    sink = FakeProjectEventSink()
    captured: dict[str, object] = {}

    def fake_crawl_live_discovery(**kwargs) -> list[dict[str, object]]:
        captured.update(kwargs)
        payload = {
            "keyword": "แพลตฟอร์ม",
            "project_name": "ประกวดราคาแพลตฟอร์ม",
            "organization_name": "กรมตัวอย่าง",
            "search_name": "ประกวดราคาแพลตฟอร์ม",
            "detail_name": "ประกวดราคาแพลตฟอร์ม",
            "project_number": "EGP-PLATFORM",
            "proposal_submission_date": "2026-05-02",
            "budget_amount": "200000.00",
            "project_state": ProjectState.OPEN_INVITATION.value,
            "source_status_text": "หนังสือเชิญชวน/ประกาศเชิญชวน",
            "downloaded_documents": [],
        }
        kwargs["project_callback"](payload)
        return [payload]

    monkeypatch.setattr(
        "egp_worker.workflows.discover.crawl_live_discovery",
        fake_crawl_live_discovery,
    )

    result = run_discover_workflow(
        tenant_id=TENANT_ID,
        keyword="แพลตฟอร์ม",
        profile="tor",
        discovered_projects=[],
        run_repository=run_repository,
        project_event_sink=sink,
        live=True,
    )

    assert captured["keyword"] == "แพลตฟอร์ม"
    assert captured["profile"] == "tor"
    assert captured["include_documents"] is False
    assert callable(captured["project_callback"])
    assert result.projects[0].id == "project-1"
    assert run_repository.finished_status == "succeeded"


def test_run_discover_workflow_marks_live_browser_documents_deferred(
    monkeypatch,
) -> None:
    run_repository = FakeRunRepository()
    sink = FakeProjectEventSink()

    def fake_crawl_live_discovery(**kwargs) -> list[dict[str, object]]:
        payload = {
            "keyword": "แพลตฟอร์ม",
            "project_name": "ประกวดราคาแพลตฟอร์ม",
            "organization_name": "กรมตัวอย่าง",
            "search_name": "ประกวดราคาแพลตฟอร์ม",
            "detail_name": "ประกวดราคาแพลตฟอร์ม",
            "project_number": "EGP-PLATFORM",
            "proposal_submission_date": "2026-05-02",
            "budget_amount": "200000.00",
            "project_state": ProjectState.OPEN_INVITATION.value,
            "source_status_text": "หนังสือเชิญชวน/ประกาศเชิญชวน",
            "downloaded_documents": [],
        }
        kwargs["project_callback"](payload)
        return [payload]

    monkeypatch.setattr(
        "egp_worker.workflows.discover.crawl_live_discovery",
        fake_crawl_live_discovery,
    )

    run_discover_workflow(
        tenant_id=TENANT_ID,
        keyword="แพลตฟอร์ม",
        discovered_projects=[],
        run_repository=run_repository,
        project_event_sink=sink,
        live=True,
    )

    assert (
        run_repository.tasks[0]["payload"]["document_collection_status"] == "deferred"
    )
    assert (
        run_repository.tasks[0]["payload"]["document_collection_reason"]
        == "live_discovery_metadata_first"
    )
    assert (
        sink.discovery_events[0].raw_snapshot["document_collection_status"]
        == "deferred"
    )


def test_run_discover_workflow_can_opt_into_live_browser_document_downloads(
    monkeypatch,
    tmp_path,
) -> None:
    run_repository = FakeRunRepository()
    sink = FakeProjectEventSink()
    captured_crawl: dict[str, object] = {}
    captured_ingest: dict[str, object] = {}

    def fake_crawl_live_discovery(**kwargs) -> list[dict[str, object]]:
        captured_crawl.update(kwargs)
        payload = {
            "keyword": "แพลตฟอร์ม",
            "project_name": "ประกวดราคาแพลตฟอร์ม",
            "organization_name": "กรมตัวอย่าง",
            "search_name": "ประกวดราคาแพลตฟอร์ม",
            "detail_name": "ประกวดราคาแพลตฟอร์ม",
            "project_number": "EGP-PLATFORM",
            "proposal_submission_date": "2026-05-02",
            "budget_amount": "200000.00",
            "project_state": ProjectState.OPEN_INVITATION.value,
            "source_status_text": "หนังสือเชิญชวน/ประกาศเชิญชวน",
            "downloaded_documents": [
                {
                    "file_name": "tor.pdf",
                    "file_bytes": b"tor-v1",
                    "source_label": "ร่างเอกสารประกวดราคา",
                    "source_status_text": "หนังสือเชิญชวน/ประกาศเชิญชวน",
                }
            ],
        }
        kwargs["project_callback"](payload)
        return [payload]

    def fake_ingest_downloaded_documents(**kwargs):
        captured_ingest.update(kwargs)
        return [SimpleNamespace(created=True)]

    monkeypatch.setattr(
        "egp_worker.workflows.discover.crawl_live_discovery",
        fake_crawl_live_discovery,
    )
    monkeypatch.setattr(
        "egp_worker.workflows.discover.ingest_downloaded_documents",
        fake_ingest_downloaded_documents,
    )

    run_discover_workflow(
        tenant_id=TENANT_ID,
        keyword="แพลตฟอร์ม",
        discovered_projects=[],
        run_repository=run_repository,
        project_event_sink=sink,
        live=True,
        live_include_documents=True,
        artifact_root=tmp_path / "artifacts",
    )

    assert captured_crawl["include_documents"] is True
    assert "document_collection_status" not in run_repository.tasks[0]["payload"]
    assert run_repository.tasks[0]["payload"]["downloaded_documents"] == [
        {
            "file_name": "tor.pdf",
            "source_label": "ร่างเอกสารประกวดราคา",
            "source_status_text": "หนังสือเชิญชวน/ประกาศเชิญชวน",
            "source_page_text": "",
            "project_state": None,
        }
    ]
    assert captured_ingest["artifact_root"] == tmp_path / "artifacts"
    assert captured_ingest["project_id"] == "project-1"
    assert captured_ingest["downloaded_documents"][0]["file_bytes"] == b"tor-v1"


def test_run_discover_workflow_streams_live_browser_projects_before_later_crawl_error(
    monkeypatch,
) -> None:
    run_repository = FakeRunRepository()
    sink = FakeProjectEventSink()

    def project_payload(project_number: str) -> dict[str, object]:
        return {
            "keyword": "แพลตฟอร์ม",
            "project_name": f"ประกวดราคาแพลตฟอร์ม {project_number}",
            "organization_name": "กรมตัวอย่าง",
            "search_name": f"ประกวดราคาแพลตฟอร์ม {project_number}",
            "detail_name": f"ประกวดราคาแพลตฟอร์ม {project_number}",
            "project_number": project_number,
            "proposal_submission_date": "2026-05-02",
            "budget_amount": "200000.00",
            "project_state": ProjectState.OPEN_INVITATION.value,
            "source_status_text": "หนังสือเชิญชวน/ประกาศเชิญชวน",
            "downloaded_documents": [],
        }

    def fake_crawl_live_discovery(**kwargs) -> list[dict[str, object]]:
        project_callback = kwargs["project_callback"]
        project_callback(project_payload("EGP-1"))
        project_callback(project_payload("EGP-2"))
        raise RuntimeError("page state drift after streamed projects")

    monkeypatch.setattr(
        "egp_worker.workflows.discover.crawl_live_discovery",
        fake_crawl_live_discovery,
    )

    with pytest.raises(RuntimeError, match="page state drift"):
        run_discover_workflow(
            tenant_id=TENANT_ID,
            keyword="แพลตฟอร์ม",
            discovered_projects=[],
            run_repository=run_repository,
            project_event_sink=sink,
            live=True,
        )

    assert [event.project_number for event in sink.discovery_events] == [
        "EGP-1",
        "EGP-2",
    ]
    assert [task["status"] for task in run_repository.tasks] == [
        "succeeded",
        "succeeded",
    ]
    assert run_repository.finished_status == "failed"
    assert run_repository.finished_summary == {
        "projects_seen": 2,
        "error": "page state drift after streamed projects",
    }


def test_run_discover_workflow_marks_partial_for_live_pagination_site_error(
    monkeypatch,
) -> None:
    run_repository = FakeRunRepository()
    sink = FakeProjectEventSink()

    def fake_crawl_live_discovery(**kwargs) -> list[dict[str, object]]:
        kwargs["project_callback"](
            {
                "keyword": "แพลตฟอร์ม",
                "project_name": "ประกวดราคาแพลตฟอร์ม",
                "organization_name": "กรมตัวอย่าง",
                "search_name": "ประกวดราคาแพลตฟอร์ม",
                "detail_name": "ประกวดราคาแพลตฟอร์ม",
                "project_number": "EGP-PARTIAL",
                "proposal_submission_date": "2026-05-02",
                "budget_amount": "200000.00",
                "project_state": ProjectState.OPEN_INVITATION.value,
                "source_status_text": "หนังสือเชิญชวน/ประกาศเชิญชวน",
                "downloaded_documents": [],
            }
        )
        raise LiveDiscoveryPartialError("pagination site error at page 6")

    monkeypatch.setattr(
        "egp_worker.workflows.discover.crawl_live_discovery",
        fake_crawl_live_discovery,
    )

    result = run_discover_workflow(
        tenant_id=TENANT_ID,
        keyword="แพลตฟอร์ม",
        discovered_projects=[],
        run_repository=run_repository,
        project_event_sink=sink,
        live=True,
    )

    assert result.run.run.status == "partial"
    assert run_repository.finished_status == "partial"
    assert run_repository.finished_error_count == 1
    assert run_repository.finished_summary == {
        "projects_seen": 1,
        "error": "pagination site error at page 6",
    }


def test_run_discover_workflow_marks_partial_for_live_search_page_state_error(
    monkeypatch,
) -> None:
    run_repository = FakeRunRepository()
    sink = FakeProjectEventSink()

    def fake_crawl_live_discovery(**kwargs) -> list[dict[str, object]]:
        kwargs["project_callback"](
            {
                "keyword": "แพลตฟอร์ม",
                "project_name": "ประกวดราคาแพลตฟอร์ม",
                "organization_name": "กรมตัวอย่าง",
                "search_name": "ประกวดราคาแพลตฟอร์ม",
                "detail_name": "ประกวดราคาแพลตฟอร์ม",
                "project_number": "EGP-STATE",
                "proposal_submission_date": "2026-05-02",
                "budget_amount": "200000.00",
                "project_state": ProjectState.OPEN_INVITATION.value,
                "source_status_text": "หนังสือเชิญชวน/ประกาศเชิญชวน",
                "downloaded_documents": [],
            }
        )
        raise SearchPageStateError("e-GP site error after search results load")

    monkeypatch.setattr(
        "egp_worker.workflows.discover.crawl_live_discovery",
        fake_crawl_live_discovery,
    )

    result = run_discover_workflow(
        tenant_id=TENANT_ID,
        keyword="แพลตฟอร์ม",
        discovered_projects=[],
        run_repository=run_repository,
        project_event_sink=sink,
        live=True,
    )

    assert result.run.run.status == "partial"
    assert run_repository.finished_status == "partial"
    assert run_repository.finished_error_count == 1
    assert run_repository.finished_summary == {
        "projects_seen": 1,
        "error": "e-GP site error after search results load",
    }


def test_run_worker_job_dispatches_live_discover_command(monkeypatch, tmp_path) -> None:
    captured: dict[str, object] = {}

    def fake_run_discover_workflow(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(
            run=SimpleNamespace(run=SimpleNamespace(id="run-live", status="succeeded")),
            projects=[SimpleNamespace(id="project-1"), SimpleNamespace(id="project-2")],
        )

    monkeypatch.setattr(
        "egp_worker.main.run_discover_workflow", fake_run_discover_workflow
    )

    result = run_worker_job(
        {
            "command": "discover",
            "database_url": f"sqlite+pysqlite:///{tmp_path / 'worker-live.sqlite3'}",
            "tenant_id": TENANT_ID,
            "keyword": "analytics",
            "profile": "tor",
            "live": True,
            "trigger_type": "schedule",
        }
    )

    assert result == {
        "command": "discover",
        "run_id": "run-live",
        "run_status": "succeeded",
        "project_count": 2,
        "project_ids": ["project-1", "project-2"],
    }
    assert captured["tenant_id"] == TENANT_ID
    assert captured["keyword"] == "analytics"
    assert captured["trigger_type"] == "schedule"
    assert captured["live"] is True
    assert captured["profile"] == "tor"


def test_run_worker_job_forwards_browser_settings_to_discover_workflow(
    monkeypatch, tmp_path
) -> None:
    captured: dict[str, object] = {}

    def fake_run_discover_workflow(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(
            run=SimpleNamespace(run=SimpleNamespace(id="run-live", status="succeeded")),
            projects=[],
        )

    monkeypatch.setattr(
        "egp_worker.main.run_discover_workflow", fake_run_discover_workflow
    )

    result = run_worker_job(
        {
            "command": "discover",
            "database_url": f"sqlite+pysqlite:///{tmp_path / 'worker-live.sqlite3'}",
            "tenant_id": TENANT_ID,
            "keyword": "แพลตฟอร์ม",
            "live": True,
            "browser_settings": {
                "cdp_port": 9333,
                "browser_profile_dir": str(tmp_path / "browser-profile"),
            },
        }
    )

    assert result["run_id"] == "run-live"
    assert isinstance(captured["browser_settings"], BrowserDiscoverySettings)
    assert captured["browser_settings"].cdp_port == 9333
    assert (
        captured["browser_settings"].browser_profile_dir == tmp_path / "browser-profile"
    )


def test_run_worker_job_forwards_live_include_documents_to_discover_workflow(
    monkeypatch, tmp_path
) -> None:
    captured: dict[str, object] = {}

    def fake_run_discover_workflow(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(
            run=SimpleNamespace(run=SimpleNamespace(id="run-live", status="succeeded")),
            projects=[],
        )

    monkeypatch.setattr(
        "egp_worker.main.run_discover_workflow", fake_run_discover_workflow
    )

    result = run_worker_job(
        {
            "command": "discover",
            "database_url": f"sqlite+pysqlite:///{tmp_path / 'worker-live.sqlite3'}",
            "tenant_id": TENANT_ID,
            "keyword": "แพลตฟอร์ม",
            "live": True,
            "live_include_documents": True,
        }
    )

    assert result["run_id"] == "run-live"
    assert captured["live_include_documents"] is True


def test_run_worker_job_forwards_profile_id_to_discover_workflow(
    monkeypatch, tmp_path
) -> None:
    captured: dict[str, object] = {}

    def fake_run_discover_workflow(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(
            run=SimpleNamespace(
                run=SimpleNamespace(id="run-profile", status="succeeded")
            ),
            projects=[],
        )

    monkeypatch.setattr(
        "egp_worker.main.run_discover_workflow", fake_run_discover_workflow
    )

    result = run_worker_job(
        {
            "command": "discover",
            "database_url": f"sqlite+pysqlite:///{tmp_path / 'worker-profile.sqlite3'}",
            "tenant_id": TENANT_ID,
            "profile_id": "profile-123",
            "keyword": "analytics",
        }
    )

    assert result["run_id"] == "run-profile"
    assert captured["profile_id"] == "profile-123"


def test_run_worker_job_forwards_run_id_and_artifact_root_to_discover_workflow(
    monkeypatch, tmp_path
) -> None:
    captured: dict[str, object] = {}

    def fake_run_discover_workflow(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(
            run=SimpleNamespace(
                run=SimpleNamespace(id="run-reserved", status="succeeded")
            ),
            projects=[],
        )

    monkeypatch.setattr(
        "egp_worker.main.run_discover_workflow", fake_run_discover_workflow
    )

    result = run_worker_job(
        {
            "command": "discover",
            "database_url": f"sqlite+pysqlite:///{tmp_path / 'worker-reserved.sqlite3'}",
            "tenant_id": TENANT_ID,
            "run_id": "run-reserved",
            "keyword": "analytics",
            "artifact_root": str(tmp_path / "reserved-artifacts"),
        }
    )

    assert result["run_id"] == "run-reserved"
    assert captured["run_id"] == "run-reserved"
    assert captured["artifact_root"] == tmp_path / "reserved-artifacts"


def test_run_discover_workflow_uses_per_project_keyword_when_live_source_returns_it() -> (
    None
):
    run_repository = FakeRunRepository()
    sink = FakeProjectEventSink()

    def crawl(keyword: str) -> list[dict[str, object]]:
        return [
            {
                "keyword": "smart tv",
                "project_name": "จัดซื้อ Smart TV",
                "organization_name": "กรมตัวอย่าง",
                "search_name": "จัดซื้อ Smart TV",
                "detail_name": "จัดซื้อ Smart TV",
                "project_number": "EGP-SMART-TV",
                "proposal_submission_date": "2026-05-02",
                "budget_amount": "200000.00",
                "project_state": ProjectState.OPEN_INVITATION.value,
                "source_status_text": "หนังสือเชิญชวน/ประกาศเชิญชวน",
                "raw_snapshot": {"keyword": "smart tv"},
            }
        ]

    result = run_discover_workflow(
        tenant_id=TENANT_ID,
        keyword="",
        discovered_projects=[],
        run_repository=run_repository,
        project_event_sink=sink,
        live_discovery=crawl,
    )

    assert result.projects[0].id == "project-1"
    assert run_repository.finished_status == "succeeded"
    assert run_repository.finished_summary == {"projects_seen": 1}
    assert run_repository.tasks[0]["keyword"] == "smart tv"
    assert sink.discovery_events[0].keyword == "smart tv"


def test_run_discover_workflow_ingests_live_downloaded_documents_after_persist(
    monkeypatch, tmp_path
) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'discover.sqlite3'}"
    run_repository = FakeRunRepository()
    sink = FakeProjectEventSink()
    captured: dict[str, object] = {}
    today = date.today()

    _seed_subscription(
        database_url=database_url,
        plan_code="free_trial",
        keyword_limit=1,
        billing_period_start=today - timedelta(days=1),
        billing_period_end=today + timedelta(days=5),
    )
    _seed_profile(database_url=database_url, keywords=["analytics"])

    def fake_ingest_downloaded_documents(**kwargs):
        captured.update(kwargs)
        return [SimpleNamespace(created=True)]

    monkeypatch.setattr(
        "egp_worker.workflows.discover.ingest_downloaded_documents",
        fake_ingest_downloaded_documents,
    )

    result = run_discover_workflow(
        tenant_id=TENANT_ID,
        keyword="analytics",
        discovered_projects=[
            {
                "keyword": "analytics",
                "project_name": "ระบบวิเคราะห์ข้อมูล",
                "organization_name": "กรมตัวอย่าง",
                "search_name": "ระบบวิเคราะห์ข้อมูล",
                "detail_name": "ระบบวิเคราะห์ข้อมูล",
                "project_number": "EGP-ANALYTICS",
                "proposal_submission_date": "2026-05-02",
                "budget_amount": "200000.00",
                "project_state": ProjectState.OPEN_INVITATION.value,
                "source_status_text": "หนังสือเชิญชวน/ประกาศเชิญชวน",
                "downloaded_documents": [
                    {
                        "file_name": "tor.pdf",
                        "file_bytes": b"tor-v1",
                        "source_label": "ร่างขอบเขตของงาน",
                        "source_status_text": "หนังสือเชิญชวน/ประกาศเชิญชวน",
                    }
                ],
            }
        ],
        run_repository=run_repository,
        project_event_sink=sink,
        database_url=database_url,
        artifact_root=tmp_path / "artifacts",
    )

    assert result.projects[0].id == "project-1"
    assert captured["tenant_id"] == TENANT_ID
    assert captured["project_id"] == "project-1"
    assert captured["downloaded_documents"] == [
        {
            "file_name": "tor.pdf",
            "file_bytes": b"tor-v1",
            "source_label": "ร่างขอบเขตของงาน",
            "source_status_text": "หนังสือเชิญชวน/ประกาศเชิญชวน",
        }
    ]


def test_run_discover_workflow_sanitizes_raw_snapshot_before_project_ingest(
    monkeypatch,
) -> None:
    run_repository = FakeRunRepository()
    sink = FakeProjectEventSink()

    monkeypatch.setattr(
        "egp_worker.workflows.discover.ingest_downloaded_documents",
        lambda **kwargs: [],
    )

    result = run_discover_workflow(
        tenant_id=TENANT_ID,
        keyword="analytics",
        discovered_projects=[
            {
                "keyword": "analytics",
                "project_name": "ระบบวิเคราะห์ข้อมูล",
                "organization_name": "กรมตัวอย่าง",
                "search_name": "ระบบวิเคราะห์ข้อมูล",
                "detail_name": "ระบบวิเคราะห์ข้อมูล",
                "project_number": "EGP-ANALYTICS",
                "proposal_submission_date": "2026-05-02",
                "budget_amount": "200000.00",
                "project_state": ProjectState.OPEN_INVITATION.value,
                "source_status_text": "หนังสือเชิญชวน/ประกาศเชิญชวน",
                "downloaded_documents": [
                    {
                        "file_name": "tor.pdf",
                        "file_bytes": b"tor-v1",
                        "source_label": "ร่างขอบเขตของงาน",
                        "source_status_text": "หนังสือเชิญชวน/ประกาศเชิญชวน",
                    }
                ],
            }
        ],
        run_repository=run_repository,
        project_event_sink=sink,
    )

    assert result.projects[0].id == "project-1"
    raw_snapshot = sink.discovery_events[0].raw_snapshot
    assert raw_snapshot is not None
    assert raw_snapshot["downloaded_documents"] == [
        {
            "file_name": "tor.pdf",
            "source_label": "ร่างขอบเขตของงาน",
            "source_status_text": "หนังสือเชิญชวน/ประกาศเชิญชวน",
            "source_page_text": "",
            "project_state": None,
        }
    ]


def test_run_discover_workflow_recursively_sanitizes_nested_bytes_before_project_ingest(
    monkeypatch,
) -> None:
    run_repository = FakeRunRepository()
    sink = FakeProjectEventSink()

    monkeypatch.setattr(
        "egp_worker.workflows.discover.ingest_downloaded_documents",
        lambda **kwargs: [],
    )

    run_discover_workflow(
        tenant_id=TENANT_ID,
        keyword="analytics",
        discovered_projects=[
            {
                "keyword": "analytics",
                "project_name": "ระบบวิเคราะห์ข้อมูล",
                "organization_name": "กรมตัวอย่าง",
                "search_name": "ระบบวิเคราะห์ข้อมูล",
                "detail_name": "ระบบวิเคราะห์ข้อมูล",
                "project_number": "EGP-ANALYTICS",
                "proposal_submission_date": "2026-05-02",
                "budget_amount": "200000.00",
                "project_state": ProjectState.OPEN_INVITATION.value,
                "source_status_text": "หนังสือเชิญชวน/ประกาศเชิญชวน",
                "raw_snapshot": {
                    "html_bytes": b"<html></html>",
                    "nested": {"pdf_bytes": b"pdf-v1"},
                    "items": [b"chunk-1", {"doc_bytes": b"chunk-2"}],
                },
                "downloaded_documents": [
                    {
                        "file_name": "tor.pdf",
                        "file_bytes": b"tor-v1",
                        "source_label": "ร่างขอบเขตของงาน",
                        "source_status_text": "หนังสือเชิญชวน/ประกาศเชิญชวน",
                    }
                ],
            }
        ],
        run_repository=run_repository,
        project_event_sink=sink,
    )

    raw_snapshot = sink.discovery_events[0].raw_snapshot
    assert raw_snapshot is not None
    assert raw_snapshot["raw_snapshot"] == {
        "html_bytes": "<bytes:13>",
        "nested": {"pdf_bytes": "<bytes:6>"},
        "items": ["<bytes:7>", {"doc_bytes": "<bytes:7>"}],
    }


def test_run_discover_workflow_records_run_error_when_task_creation_fails() -> None:
    class CreateTaskFailsRunRepository(FakeRunRepository):
        def create_task(self, **kwargs):
            raise TypeError("Object of type bytes is not JSON serializable")

    run_repository = CreateTaskFailsRunRepository()
    sink = FakeProjectEventSink()

    result = run_discover_workflow(
        tenant_id=TENANT_ID,
        keyword="analytics",
        discovered_projects=[
            {
                "keyword": "analytics",
                "project_name": "ระบบวิเคราะห์ข้อมูล",
                "organization_name": "กรมตัวอย่าง",
            }
        ],
        run_repository=run_repository,
        project_event_sink=sink,
    )

    assert result.run.run.status == "failed"
    assert run_repository.tasks == []
    assert run_repository.finished_summary == {
        "projects_seen": 0,
        "error": "Object of type bytes is not JSON serializable",
    }
    assert run_repository.finished_error_count == 1


def test_run_discover_workflow_keeps_run_summary_clean_when_task_row_has_error() -> (
    None
):
    run_repository = FakeRunRepository()

    class ExplodingSink:
        def record_discovery(self, event):
            raise RuntimeError("project ingest exploded")

    result = run_discover_workflow(
        tenant_id=TENANT_ID,
        keyword="analytics",
        discovered_projects=[
            {
                "keyword": "analytics",
                "project_name": "ระบบวิเคราะห์ข้อมูล",
                "organization_name": "กรมตัวอย่าง",
            }
        ],
        run_repository=run_repository,
        project_event_sink=ExplodingSink(),
    )

    assert result.run.run.status == "failed"
    assert run_repository.finished_summary == {"projects_seen": 0}
    assert run_repository.tasks[0]["status"] == "failed"
    assert run_repository.tasks[0]["result_json"] == {
        "artifact_root": "artifacts",
        "error": "project ingest exploded",
        "error_type": "RuntimeError",
        "project_key": "ระบบวิเคราะห์ข้อมูล",
        "run_id": "run-1",
        "task_keyword": "analytics",
    }


def test_run_discover_workflow_logs_document_ingest_failure_context(
    monkeypatch, caplog
) -> None:
    run_repository = FakeRunRepository()
    sink = FakeProjectEventSink()
    caplog.set_level(logging.INFO, logger="egp_worker.workflows.discover")

    def fake_ingest_downloaded_documents(**kwargs):
        raise RuntimeError("document ingest exploded")

    monkeypatch.setattr(
        "egp_worker.workflows.discover.ingest_downloaded_documents",
        fake_ingest_downloaded_documents,
    )

    result = run_discover_workflow(
        tenant_id=TENANT_ID,
        keyword="analytics",
        discovered_projects=[
            {
                "keyword": "analytics",
                "project_name": "ระบบวิเคราะห์ข้อมูล",
                "organization_name": "กรมตัวอย่าง",
                "downloaded_documents": [
                    {
                        "file_name": "tor.pdf",
                        "file_bytes": b"tor-v1",
                        "source_label": "ร่างขอบเขตของงาน",
                        "source_status_text": "เปิดรับฟังคำวิจารณ์",
                    }
                ],
            }
        ],
        run_repository=run_repository,
        project_event_sink=sink,
        artifact_root="artifacts",
    )

    failure_event = next(
        record
        for record in caplog.records
        if getattr(record, "egp_event", "") == "project_document_ingest_failed"
    )
    assert failure_event.keyword == "analytics"
    assert failure_event.document_count == 1
    assert failure_event.task_id == "task-1"
    assert result.run.run.status == "failed"
    assert run_repository.tasks[0]["result_json"] == {
        "artifact_root": "artifacts",
        "error": "document ingest exploded",
        "error_type": "RuntimeError",
        "project_key": "ระบบวิเคราะห์ข้อมูล",
        "run_id": "run-1",
        "task_keyword": "analytics",
    }


def test_worker_main_initializes_info_logging(monkeypatch, capsys) -> None:
    captured: dict[str, object] = {}

    def fake_basic_config(**kwargs):
        captured.update(kwargs)

    monkeypatch.setattr("egp_worker.main.logging.basicConfig", fake_basic_config)

    worker_main('{"command":"noop"}')

    assert captured == {"level": logging.INFO}
    assert '"status": "idle"' in capsys.readouterr().out


def test_run_close_check_workflow_uses_live_observation_source_when_observations_missing() -> (
    None
):
    run_repository = FakeRunRepository()
    close_events: list[object] = []

    class CloseSink:
        def record_close_check(self, event):
            close_events.append(event)
            return SimpleNamespace(
                id=event.project_id, project_state=ProjectState.WINNER_ANNOUNCED
            )

    observed_project_ids: list[str] = []

    def sweep(projects: list[dict[str, object]]) -> list[dict[str, object]]:
        observed_project_ids.extend(
            [str(project["project_id"]) for project in projects]
        )
        return [
            {
                "project_id": projects[0]["project_id"],
                "source_status_text": "ผู้ชนะการเสนอราคา",
            }
        ]

    result = run_close_check_workflow(
        tenant_id=TENANT_ID,
        observations=[],
        run_repository=run_repository,
        project_event_sink=CloseSink(),
        live_projects=[{"project_id": "project-1", "project_name": "Test"}],
        live_observation_sweep=sweep,
    )

    assert observed_project_ids == ["project-1"]
    assert result.updated_projects[0].id == "project-1"
    assert run_repository.finished_status == "succeeded"
    assert run_repository.finished_summary == {"updated_projects": 1}
    assert close_events[0].project_id == "project-1"


def test_run_close_check_workflow_records_run_error_when_task_creation_fails() -> None:
    class CreateTaskFailsRunRepository(FakeRunRepository):
        def create_task(self, **kwargs):
            raise TypeError("Object of type bytes is not JSON serializable")

    run_repository = CreateTaskFailsRunRepository()

    class CloseSink:
        def record_close_check(self, event):
            raise AssertionError("task creation failure should stop before sink call")

    result = run_close_check_workflow(
        tenant_id=TENANT_ID,
        observations=[
            {
                "project_id": "project-1",
                "source_status_text": "ผู้ชนะการเสนอราคา",
            }
        ],
        run_repository=run_repository,
        project_event_sink=CloseSink(),
    )

    assert result.run.run.status == "failed"
    assert run_repository.tasks == []
    assert run_repository.finished_summary == {
        "updated_projects": 0,
        "error": "Object of type bytes is not JSON serializable",
    }
    assert run_repository.finished_error_count == 1


def test_run_close_check_workflow_keeps_run_summary_clean_when_task_row_has_error() -> (
    None
):
    run_repository = FakeRunRepository()

    class CloseSink:
        def record_close_check(self, event):
            raise RuntimeError("close-check ingest exploded")

    result = run_close_check_workflow(
        tenant_id=TENANT_ID,
        observations=[
            {
                "project_id": "project-1",
                "source_status_text": "ผู้ชนะการเสนอราคา",
            }
        ],
        run_repository=run_repository,
        project_event_sink=CloseSink(),
    )

    assert result.run.run.status == "failed"
    assert run_repository.finished_summary == {"updated_projects": 0}
    assert run_repository.tasks[0]["status"] == "failed"
    assert run_repository.tasks[0]["result_json"] == {
        "error": "close-check ingest exploded"
    }


def test_run_close_check_workflow_loads_open_projects_for_live_sweep_when_needed() -> (
    None
):
    run_repository = FakeRunRepository()
    observed_projects: list[dict[str, object]] = []
    close_events: list[object] = []

    class CloseSink:
        def record_close_check(self, event):
            close_events.append(event)
            return SimpleNamespace(
                id=event.project_id, project_state=ProjectState.WINNER_ANNOUNCED
            )

    def sweep(projects: list[dict[str, object]]) -> list[dict[str, object]]:
        observed_projects.extend(projects)
        return [
            {
                "project_id": projects[0]["project_id"],
                "source_status_text": "ประกาศผู้ชนะการเสนอราคา",
            }
        ]

    result = run_close_check_workflow(
        tenant_id=TENANT_ID,
        observations=[],
        run_repository=run_repository,
        project_repository=FakeCloseProjectRepository(),
        project_event_sink=CloseSink(),
        live=True,
        live_observation_sweep=sweep,
    )

    assert observed_projects == [
        {
            "project_id": "project-1",
            "project_name": "ประกวดราคาจัดซื้อระบบเครือข่าย",
            "project_number": "EGP-2026-4001",
            "organization_name": "กรมตัวอย่าง",
            "project_state": ProjectState.OPEN_INVITATION.value,
        }
    ]
    assert result.updated_projects[0].id == "project-1"
    assert close_events[0].project_id == "project-1"


def test_build_scheduled_discovery_jobs_returns_due_active_profile_keywords() -> None:
    jobs = build_scheduled_discovery_jobs(
        tenants=[
            {
                "tenant_id": TENANT_ID,
                "crawl_interval_hours": 24,
                "last_scheduled_run_at": None,
                "profiles": [
                    {
                        "profile_id": "profile-1",
                        "profile_type": "tor",
                        "is_active": True,
                        "keywords": ["analytics", "cloud"],
                    },
                    {
                        "profile_id": "profile-2",
                        "profile_type": "toe",
                        "is_active": False,
                        "keywords": ["smart tv"],
                    },
                ],
            }
        ]
    )

    assert jobs == [
        {
            "tenant_id": TENANT_ID,
            "profile_id": "profile-1",
            "profile": "tor",
            "keyword": "analytics",
            "trigger_type": "schedule",
            "live": True,
        },
        {
            "tenant_id": TENANT_ID,
            "profile_id": "profile-1",
            "profile": "tor",
            "keyword": "cloud",
            "trigger_type": "schedule",
            "live": True,
        },
    ]


def test_run_scheduled_discovery_executes_due_jobs_from_repository_state() -> None:
    executed_jobs: list[dict[str, object]] = []

    def job_runner(job: dict[str, object]) -> dict[str, object]:
        executed_jobs.append(job)
        return {"run_id": f"run-{job['keyword']}", "project_count": 0}

    result = run_scheduled_discovery(
        database_url="sqlite+pysqlite:///unused.sqlite3",
        admin_repository=FakeAdminRepository(),
        billing_repository=FakeBillingRepository(
            {
                TENANT_ID: [
                    SimpleNamespace(
                        subscription_status=SimpleNamespace(value="active"),
                        keyword_limit=5,
                    )
                ]
            }
        ),
        profile_repository=FakeProfileRepository(),
        run_repository=FakeScheduledRunRepository(),
        job_runner=job_runner,
    )

    assert result["due_job_count"] == 2
    assert executed_jobs == [
        {
            "tenant_id": TENANT_ID,
            "profile_id": "profile-1",
            "profile": "tor",
            "keyword": "analytics",
            "trigger_type": "schedule",
            "live": True,
        },
        {
            "tenant_id": TENANT_ID,
            "profile_id": "profile-1",
            "profile": "tor",
            "keyword": "cloud",
            "trigger_type": "schedule",
            "live": True,
        },
    ]


def test_run_scheduled_discovery_reuses_authorization_snapshot_per_tenant_batch() -> None:
    executed_jobs: list[dict[str, object]] = []
    billing_repository = FakeBillingRepository(
        {
            TENANT_ID: [
                SimpleNamespace(
                    subscription_status=SimpleNamespace(value="active"),
                    keyword_limit=5,
                )
            ]
        }
    )
    profile_repository = FakeProfileRepository()

    result = run_scheduled_discovery(
        database_url="sqlite+pysqlite:///unused.sqlite3",
        admin_repository=FakeAdminRepository(),
        billing_repository=billing_repository,
        profile_repository=profile_repository,
        run_repository=FakeScheduledRunRepository(),
        job_runner=lambda job: executed_jobs.append(job) or {"run_id": "run-1"},
    )

    assert result["due_job_count"] == 2
    assert result["executed_job_count"] == 2
    assert billing_repository.subscription_calls == 1
    assert profile_repository.active_keyword_calls == 1


def test_run_scheduled_discovery_skips_expired_subscription_profiles() -> None:
    executed_jobs: list[dict[str, object]] = []

    result = run_scheduled_discovery(
        database_url="sqlite+pysqlite:///unused.sqlite3",
        admin_repository=FakeAdminRepository(),
        billing_repository=FakeBillingRepository(
            {
                TENANT_ID: [
                    SimpleNamespace(
                        subscription_status=SimpleNamespace(value="expired"),
                        keyword_limit=5,
                    )
                ]
            }
        ),
        profile_repository=FakeProfileRepository(),
        run_repository=FakeScheduledRunRepository(),
        job_runner=lambda job: executed_jobs.append(job) or {"run_id": "run-1"},
    )

    assert result["due_job_count"] == 0
    assert result["executed_job_count"] == 0
    assert executed_jobs == []


def test_run_scheduled_discovery_skips_pending_activation_profiles() -> None:
    executed_jobs: list[dict[str, object]] = []

    result = run_scheduled_discovery(
        database_url="sqlite+pysqlite:///unused.sqlite3",
        admin_repository=FakeAdminRepository(),
        billing_repository=FakeBillingRepository(
            {
                TENANT_ID: [
                    SimpleNamespace(
                        subscription_status=SimpleNamespace(value="pending_activation"),
                        keyword_limit=5,
                    )
                ]
            }
        ),
        profile_repository=FakeProfileRepository(),
        run_repository=FakeScheduledRunRepository(),
        job_runner=lambda job: executed_jobs.append(job) or {"run_id": "run-1"},
    )

    assert result["due_job_count"] == 0
    assert result["executed_job_count"] == 0
    assert executed_jobs == []


def test_run_scheduled_discovery_skips_keywords_outside_entitlement() -> None:
    executed_jobs: list[dict[str, object]] = []

    result = run_scheduled_discovery(
        database_url="sqlite+pysqlite:///unused.sqlite3",
        admin_repository=FakeAdminRepository(),
        billing_repository=FakeBillingRepository(
            {
                TENANT_ID: [
                    SimpleNamespace(
                        subscription_status=SimpleNamespace(value="active"),
                        keyword_limit=1,
                    )
                ]
            }
        ),
        profile_repository=FakeProfileRepository(),
        run_repository=FakeScheduledRunRepository(),
        job_runner=lambda job: executed_jobs.append(job) or {"run_id": "run-1"},
    )

    assert result["due_job_count"] == 0
    assert result["executed_job_count"] == 0
    assert executed_jobs == []


def test_run_worker_job_executes_scheduled_discovery_jobs_through_worker_runner(
    monkeypatch,
) -> None:
    captured_job_runner: dict[str, object] = {}

    def fake_run_scheduled_discovery(**kwargs):
        captured_job_runner.update(kwargs)
        kwargs["job_runner"](
            {
                "tenant_id": TENANT_ID,
                "profile_id": "profile-1",
                "profile": "tor",
                "keyword": "analytics",
                "trigger_type": "schedule",
                "live": True,
            }
        )
        return {"due_job_count": 1, "executed_job_count": 1}

    executed_payloads: list[dict[str, object]] = []

    def fake_run_worker_job(payload: dict[str, object]) -> dict[str, object]:
        executed_payloads.append(payload)
        return {"command": payload["command"], "run_id": "run-1"}

    monkeypatch.setattr(
        "egp_worker.main.run_scheduled_discovery", fake_run_scheduled_discovery
    )
    monkeypatch.setattr("egp_worker.main._run_discovery_job", fake_run_worker_job)

    result = run_worker_job(
        {
            "command": "run_scheduled_discovery",
            "database_url": "sqlite+pysqlite:///worker-schedule.sqlite3",
        }
    )

    assert result == {
        "command": "run_scheduled_discovery",
        "due_job_count": 1,
        "executed_job_count": 1,
    }
    assert callable(captured_job_runner["job_runner"])
    assert executed_payloads == [
        {
            "command": "discover",
            "database_url": "sqlite+pysqlite:///worker-schedule.sqlite3",
            "tenant_id": TENANT_ID,
            "profile_id": "profile-1",
            "profile": "tor",
            "keyword": "analytics",
            "trigger_type": "schedule",
            "live": True,
        }
    ]


def test_run_discover_workflow_keeps_task_payload_json_safe_for_downloaded_documents(
    monkeypatch, tmp_path
) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'discover-safe.sqlite3'}"
    run_repository = FakeRunRepository()
    sink = FakeProjectEventSink()
    today = date.today()

    _seed_subscription(
        database_url=database_url,
        plan_code="free_trial",
        keyword_limit=1,
        billing_period_start=today - timedelta(days=1),
        billing_period_end=today + timedelta(days=5),
    )
    _seed_profile(database_url=database_url, keywords=["analytics"])

    monkeypatch.setattr(
        "egp_worker.workflows.discover.ingest_downloaded_documents",
        lambda **kwargs: [SimpleNamespace(created=True)],
    )

    run_discover_workflow(
        tenant_id=TENANT_ID,
        keyword="analytics",
        discovered_projects=[
            {
                "keyword": "analytics",
                "project_name": "ระบบวิเคราะห์ข้อมูล",
                "organization_name": "กรมตัวอย่าง",
                "search_name": "ระบบวิเคราะห์ข้อมูล",
                "detail_name": "ระบบวิเคราะห์ข้อมูล",
                "project_number": "EGP-ANALYTICS",
                "proposal_submission_date": "2026-05-02",
                "budget_amount": "200000.00",
                "project_state": ProjectState.OPEN_INVITATION.value,
                "source_status_text": "หนังสือเชิญชวน/ประกาศเชิญชวน",
                "downloaded_documents": [
                    {
                        "file_name": "tor.pdf",
                        "file_bytes": b"tor-v1",
                        "source_label": "ร่างขอบเขตของงาน",
                        "source_status_text": "หนังสือเชิญชวน/ประกาศเชิญชวน",
                    }
                ],
            }
        ],
        run_repository=run_repository,
        project_event_sink=sink,
        database_url=database_url,
        artifact_root=tmp_path / "artifacts",
    )

    assert run_repository.tasks[0]["payload"]["downloaded_documents"] == [
        {
            "file_name": "tor.pdf",
            "source_label": "ร่างขอบเขตของงาน",
            "source_status_text": "หนังสือเชิญชวน/ประกาศเชิญชวน",
            "source_page_text": "",
            "project_state": None,
        }
    ]


def test_run_worker_job_dispatches_live_close_check_command(
    monkeypatch, tmp_path
) -> None:
    captured: dict[str, object] = {}

    def fake_run_close_check_workflow(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(
            run=SimpleNamespace(
                run=SimpleNamespace(id="run-close", status="succeeded")
            ),
            updated_projects=[SimpleNamespace(id="project-1")],
        )

    monkeypatch.setattr(
        "egp_worker.main.run_close_check_workflow", fake_run_close_check_workflow
    )

    result = run_worker_job(
        {
            "command": "close_check",
            "database_url": f"sqlite+pysqlite:///{tmp_path / 'worker-close.sqlite3'}",
            "tenant_id": TENANT_ID,
            "live": True,
            "trigger_type": "schedule",
        }
    )

    assert result == {
        "command": "close_check",
        "run_id": "run-close",
        "run_status": "succeeded",
        "updated_project_count": 1,
        "updated_project_ids": ["project-1"],
    }
    assert captured["live"] is True
    assert captured["trigger_type"] == "schedule"


def test_run_worker_job_dispatches_scheduled_discovery_command(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_run_scheduled_discovery(**kwargs):
        captured.update(kwargs)
        return {"due_job_count": 2, "executed_job_count": 2}

    monkeypatch.setattr(
        "egp_worker.main.run_scheduled_discovery", fake_run_scheduled_discovery
    )

    result = run_worker_job(
        {
            "command": "run_scheduled_discovery",
            "database_url": "sqlite+pysqlite:///worker-schedule.sqlite3",
        }
    )

    assert result == {
        "command": "run_scheduled_discovery",
        "due_job_count": 2,
        "executed_job_count": 2,
    }
    assert captured["database_url"] == "sqlite+pysqlite:///worker-schedule.sqlite3"
