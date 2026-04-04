"""Tests for Excel export service."""

from __future__ import annotations

from io import BytesIO

from openpyxl import load_workbook

from egp_api.services.export_service import ExportService
from egp_db.repositories.project_repo import SqlProjectRepository, build_project_upsert_record
from egp_shared_types.enums import ProcurementType, ProjectState

TENANT_ID = "11111111-1111-1111-1111-111111111111"


def test_export_to_excel_produces_valid_xlsx_with_headers(tmp_path) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'export.sqlite3'}"
    repo = SqlProjectRepository(database_url=database_url, bootstrap_schema=True)

    repo.upsert_project(
        build_project_upsert_record(
            tenant_id=TENANT_ID,
            project_number="EGP-2026-0001",
            search_name="ระบบสารสนเทศ",
            detail_name="จัดซื้อระบบสารสนเทศ",
            project_name="จัดซื้อระบบสารสนเทศ",
            organization_name="กรมตัวอย่าง",
            proposal_submission_date="2026-05-01",
            budget_amount="1500000.00",
            procurement_type=ProcurementType.SERVICES,
            project_state=ProjectState.OPEN_INVITATION,
        ),
        source_status_text="ประกาศเชิญชวน",
    )

    service = ExportService(repo)
    excel_bytes = service.export_to_excel(tenant_id=TENANT_ID)

    assert len(excel_bytes) > 0
    wb = load_workbook(BytesIO(excel_bytes))
    ws = wb.active
    assert ws is not None

    # Check header row has all 10 columns
    headers = [ws.cell(row=1, column=i).value for i in range(1, 11)]
    assert headers[0] == "ชื่อโครงการ"
    assert headers[5] == "งบประมาณ (บาท)"
    assert headers[9] == "เหตุผลการปิด"

    # Check data row
    assert ws.cell(row=2, column=1).value == "จัดซื้อระบบสารสนเทศ"
    assert ws.cell(row=2, column=2).value == "กรมตัวอย่าง"
    assert ws.cell(row=2, column=3).value == "EGP-2026-0001"
    assert ws.cell(row=2, column=4).value == "บริการ"
    assert ws.cell(row=2, column=5).value == "เปิดรับข้อเสนอ"
    budget_value = ws.cell(row=2, column=6).value
    assert budget_value is not None and float(budget_value) > 0


def test_export_respects_state_filter(tmp_path) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'export.sqlite3'}"
    repo = SqlProjectRepository(database_url=database_url, bootstrap_schema=True)

    for i, state in enumerate([ProjectState.OPEN_INVITATION, ProjectState.DISCOVERED]):
        repo.upsert_project(
            build_project_upsert_record(
                tenant_id=TENANT_ID,
                project_number=f"EGP-2026-{i:04d}",
                search_name=f"โครงการ {i}",
                detail_name=f"โครงการ {i}",
                project_name=f"โครงการ {i}",
                organization_name="กรม",
                proposal_submission_date="2026-05-01",
                budget_amount="1000000",
                procurement_type=ProcurementType.SERVICES,
                project_state=state,
            ),
        )

    service = ExportService(repo)
    excel_bytes = service.export_to_excel(
        tenant_id=TENANT_ID,
        project_state="discovered",
    )
    wb = load_workbook(BytesIO(excel_bytes))
    ws = wb.active
    assert ws is not None
    assert ws.max_row == 2  # header + 1 filtered row
    assert ws.cell(row=2, column=5).value == "ค้นพบใหม่"
