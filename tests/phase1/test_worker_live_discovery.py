from __future__ import annotations

from types import SimpleNamespace

from egp_shared_types.enums import ProjectState
from egp_worker.main import run_worker_job
from egp_worker.scheduler import build_scheduled_discovery_jobs, run_scheduled_discovery
from egp_worker.workflows.discover import run_discover_workflow
from egp_worker.workflows.close_check import run_close_check_workflow

TENANT_ID = "11111111-1111-1111-1111-111111111111"


class FakeRunRepository:
    def __init__(self) -> None:
        self.tasks: list[dict[str, object]] = []
        self.started_run_id: str | None = None
        self.finished_status: str | None = None
        self.finished_summary: dict[str, object] | None = None
        self.finished_error_count: int | None = None

    def create_run(self, *, tenant_id: str, trigger_type: str):
        return SimpleNamespace(id="run-1", tenant_id=tenant_id, trigger_type=trigger_type)

    def mark_run_started(self, run_id: str) -> None:
        self.started_run_id = run_id

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

    def mark_task_finished(self, task_id: str, *, status: str, result_json: dict[str, object]) -> None:
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
            run=SimpleNamespace(id=run_id, tenant_id=tenant_id, status=self.finished_status),
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
        return SimpleNamespace(id=f"project-{len(self.discovery_events)}", project_state=event.project_state)


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


class FakeScheduledRunRepository:
    def list_runs(self, *, tenant_id: str, limit: int = 50, offset: int = 0):
        return SimpleNamespace(items=[])


def test_run_discover_workflow_uses_live_discovery_source_when_projects_missing() -> None:
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


def test_run_worker_job_dispatches_live_discover_command(monkeypatch, tmp_path) -> None:
    captured: dict[str, object] = {}

    def fake_run_discover_workflow(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(
            run=SimpleNamespace(run=SimpleNamespace(id="run-live", status="succeeded")),
            projects=[SimpleNamespace(id="project-1"), SimpleNamespace(id="project-2")],
        )

    monkeypatch.setattr("egp_worker.main.run_discover_workflow", fake_run_discover_workflow)

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


def test_run_discover_workflow_uses_per_project_keyword_when_live_source_returns_it() -> None:
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
    run_repository = FakeRunRepository()
    sink = FakeProjectEventSink()
    captured: dict[str, object] = {}

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
        database_url=f"sqlite+pysqlite:///{tmp_path / 'discover.sqlite3'}",
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


def test_run_close_check_workflow_uses_live_observation_source_when_observations_missing() -> None:
    run_repository = FakeRunRepository()
    close_events: list[object] = []

    class CloseSink:
        def record_close_check(self, event):
            close_events.append(event)
            return SimpleNamespace(id=event.project_id, project_state=ProjectState.WINNER_ANNOUNCED)

    observed_project_ids: list[str] = []

    def sweep(projects: list[dict[str, object]]) -> list[dict[str, object]]:
        observed_project_ids.extend([str(project["project_id"]) for project in projects])
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


def test_run_close_check_workflow_loads_open_projects_for_live_sweep_when_needed() -> None:
    run_repository = FakeRunRepository()
    observed_projects: list[dict[str, object]] = []
    close_events: list[object] = []

    class CloseSink:
        def record_close_check(self, event):
            close_events.append(event)
            return SimpleNamespace(id=event.project_id, project_state=ProjectState.WINNER_ANNOUNCED)

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

    monkeypatch.setattr("egp_worker.main.run_scheduled_discovery", fake_run_scheduled_discovery)
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
    run_repository = FakeRunRepository()
    sink = FakeProjectEventSink()

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
        database_url=f"sqlite+pysqlite:///{tmp_path / 'discover-safe.sqlite3'}",
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


def test_run_worker_job_dispatches_live_close_check_command(monkeypatch, tmp_path) -> None:
    captured: dict[str, object] = {}

    def fake_run_close_check_workflow(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(
            run=SimpleNamespace(run=SimpleNamespace(id="run-close", status="succeeded")),
            updated_projects=[SimpleNamespace(id="project-1")],
        )

    monkeypatch.setattr("egp_worker.main.run_close_check_workflow", fake_run_close_check_workflow)

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

    monkeypatch.setattr("egp_worker.main.run_scheduled_discovery", fake_run_scheduled_discovery)

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
