from __future__ import annotations

import base64

from fastapi.testclient import TestClient

from egp_api.main import create_app
from egp_db.repositories.project_repo import build_project_upsert_record
from egp_shared_types.enums import ClosedReason, ProcurementType, ProjectState

TENANT_ID = "11111111-1111-1111-1111-111111111111"


def _seed_project(
    client: TestClient,
    *,
    project_number: str,
    project_name: str,
    organization_name: str,
    procurement_type: ProcurementType,
    project_state: ProjectState,
    budget_amount: str,
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
            organization_name=organization_name,
            proposal_submission_date="2026-05-01",
            budget_amount=budget_amount,
            procurement_type=procurement_type,
            project_state=project_state,
            closed_reason=closed_reason,
        ),
        source_status_text=project_name,
    )


def _ingest_document(
    client: TestClient,
    *,
    project_id: str,
    file_name: str,
    content: bytes,
    source_label: str,
    source_status_text: str,
) -> dict[str, object]:
    response = client.post(
        "/v1/documents/ingest",
        json={
            "tenant_id": TENANT_ID,
            "project_id": project_id,
            "file_name": file_name,
            "content_base64": base64.b64encode(content).decode("ascii"),
            "source_label": source_label,
            "source_status_text": source_status_text,
        },
    )
    assert response.status_code == 201
    return response.json()


def test_projects_endpoint_supports_explorer_filters(tmp_path) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'phase2-project-filters.sqlite3'}"
    client = TestClient(create_app(artifact_root=tmp_path, database_url=database_url, auth_required=False))

    open_project = _seed_project(
        client,
        project_number="EGP-2026-2201",
        project_name="ระบบข้อมูลเปิดภาครัฐ",
        organization_name="กรมข้อมูล",
        procurement_type=ProcurementType.SERVICES,
        project_state=ProjectState.OPEN_INVITATION,
        budget_amount="1500000",
    )
    winner_project = _seed_project(
        client,
        project_number="EGP-2026-2202",
        project_name="ที่ปรึกษาระบบสุขภาพดิจิทัล",
        organization_name="กระทรวงสาธารณสุข",
        procurement_type=ProcurementType.CONSULTING,
        project_state=ProjectState.WINNER_ANNOUNCED,
        budget_amount="3200000",
        closed_reason=ClosedReason.WINNER_ANNOUNCED,
    )
    _seed_project(
        client,
        project_number="EGP-2026-2203",
        project_name="จัดซื้อเครื่องแม่ข่ายส่วนกลาง",
        organization_name="เทศบาลตัวอย่าง",
        procurement_type=ProcurementType.GOODS,
        project_state=ProjectState.CLOSED_MANUAL,
        budget_amount="800000",
        closed_reason=ClosedReason.MANUAL,
    )

    _ingest_document(
        client,
        project_id=winner_project.id,
        file_name="tor-final-v1.pdf",
        content=b"tor-v1",
        source_label="เอกสารประกวดราคา",
        source_status_text="ประกาศเชิญชวน",
    )
    _ingest_document(
        client,
        project_id=winner_project.id,
        file_name="tor-final-v2.pdf",
        content=b"tor-v2",
        source_label="เอกสารประกวดราคา",
        source_status_text="ประกาศเชิญชวน",
    )

    multi_state = client.get(
        "/v1/projects",
        params=[
            ("tenant_id", TENANT_ID),
            ("project_state", ProjectState.OPEN_INVITATION.value),
            ("project_state", ProjectState.WINNER_ANNOUNCED.value),
        ],
    )
    keyword = client.get(
        "/v1/projects",
        params={"tenant_id": TENANT_ID, "keyword": "สุขภาพ"},
    )
    procurement = client.get(
        "/v1/projects",
        params={"tenant_id": TENANT_ID, "procurement_type": ProcurementType.CONSULTING.value},
    )
    budget = client.get(
        "/v1/projects",
        params={"tenant_id": TENANT_ID, "budget_min": 2000000, "budget_max": 4000000},
    )
    changed_tor = client.get(
        "/v1/projects",
        params={"tenant_id": TENANT_ID, "has_changed_tor": "true"},
    )
    winner_only = client.get(
        "/v1/projects",
        params={"tenant_id": TENANT_ID, "has_winner": "true"},
    )

    assert multi_state.status_code == 200
    assert multi_state.json()["total"] == 2
    assert {project["id"] for project in multi_state.json()["projects"]} == {
        open_project.id,
        winner_project.id,
    }

    assert keyword.status_code == 200
    assert [project["id"] for project in keyword.json()["projects"]] == [winner_project.id]

    assert procurement.status_code == 200
    assert [project["id"] for project in procurement.json()["projects"]] == [winner_project.id]

    assert budget.status_code == 200
    assert [project["id"] for project in budget.json()["projects"]] == [winner_project.id]

    assert changed_tor.status_code == 200
    assert [project["id"] for project in changed_tor.json()["projects"]] == [winner_project.id]

    assert winner_only.status_code == 200
    assert [project["id"] for project in winner_only.json()["projects"]] == [winner_project.id]


def test_projects_endpoint_has_changed_tor_ignores_identical_phase_transition(tmp_path) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'phase2-project-identical-phase.sqlite3'}"
    client = TestClient(create_app(artifact_root=tmp_path, database_url=database_url, auth_required=False))

    unchanged_project = _seed_project(
        client,
        project_number="EGP-2026-2291",
        project_name="โครงการ TOR เท่าเดิม",
        organization_name="กรมข้อมูล",
        procurement_type=ProcurementType.SERVICES,
        project_state=ProjectState.OPEN_INVITATION,
        budget_amount="1000000",
    )
    changed_project = _seed_project(
        client,
        project_number="EGP-2026-2292",
        project_name="โครงการ TOR เปลี่ยน",
        organization_name="กรมข้อมูล",
        procurement_type=ProcurementType.SERVICES,
        project_state=ProjectState.OPEN_INVITATION,
        budget_amount="1200000",
    )

    _ingest_document(
        client,
        project_id=unchanged_project.id,
        file_name="tor-hearing.pdf",
        content=b"same-phase-transition",
        source_label="ร่างขอบเขตของงาน",
        source_status_text="เปิดรับฟังคำวิจารณ์",
    )
    _ingest_document(
        client,
        project_id=unchanged_project.id,
        file_name="tor-final.pdf",
        content=b"same-phase-transition",
        source_label="เอกสารประกวดราคา",
        source_status_text="ประกาศเชิญชวน",
    )
    _ingest_document(
        client,
        project_id=changed_project.id,
        file_name="tor-hearing.pdf",
        content=b"draft line\nshared line\n",
        source_label="ร่างขอบเขตของงาน",
        source_status_text="เปิดรับฟังคำวิจารณ์",
    )
    _ingest_document(
        client,
        project_id=changed_project.id,
        file_name="tor-final.pdf",
        content=b"final line\nshared line\n",
        source_label="เอกสารประกวดราคา",
        source_status_text="ประกาศเชิญชวน",
    )

    changed_tor = client.get(
        "/v1/projects",
        params={"tenant_id": TENANT_ID, "has_changed_tor": "true"},
    )

    assert changed_tor.status_code == 200
    assert [project["id"] for project in changed_tor.json()["projects"]] == [changed_project.id]


def test_projects_endpoint_filters_by_closed_reason_and_updated_after(tmp_path) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'phase2-project-date-filter.sqlite3'}"
    client = TestClient(create_app(artifact_root=tmp_path, database_url=database_url, auth_required=False))
    repository = client.app.state.project_repository

    old_project = repository.upsert_project(
        build_project_upsert_record(
            tenant_id=TENANT_ID,
            project_number="EGP-2026-2210",
            search_name="โครงการเก่า",
            detail_name="โครงการเก่า",
            project_name="โครงการเก่า",
            organization_name="กรมตัวอย่าง",
            proposal_submission_date="2026-05-01",
            budget_amount="500000",
            procurement_type=ProcurementType.SERVICES,
            project_state=ProjectState.OPEN_INVITATION,
        ),
        source_status_text="ประกาศเดิม",
        observed_at="2026-04-01T08:00:00+00:00",
    )
    closed_project = repository.upsert_project(
        build_project_upsert_record(
            tenant_id=TENANT_ID,
            project_number="EGP-2026-2211",
            search_name="โครงการปิด",
            detail_name="โครงการปิด",
            project_name="โครงการปิด",
            organization_name="กรมตัวอย่าง",
            proposal_submission_date="2026-05-01",
            budget_amount="900000",
            procurement_type=ProcurementType.SERVICES,
            project_state=ProjectState.CLOSED_MANUAL,
            closed_reason=ClosedReason.MANUAL,
        ),
        source_status_text="ปิดด้วยตนเอง",
        observed_at="2026-04-03T08:00:00+00:00",
    )

    filtered = client.get(
        "/v1/projects",
        params={
            "tenant_id": TENANT_ID,
            "closed_reason": ClosedReason.MANUAL.value,
            "updated_after": "2026-04-02T00:00:00+00:00",
        },
    )

    assert filtered.status_code == 200
    assert filtered.json()["total"] == 1
    assert [project["id"] for project in filtered.json()["projects"]] == [closed_project.id]
    assert old_project.id != closed_project.id
