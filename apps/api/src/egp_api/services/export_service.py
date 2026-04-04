"""Excel export service for backwards-compatible project list export."""

from __future__ import annotations

from io import BytesIO
from decimal import Decimal
from typing import TYPE_CHECKING

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill, Border, Side

if TYPE_CHECKING:
    from egp_db.repositories.project_repo import ProjectRecord, SqlProjectRepository


HEADER_FILL = PatternFill(start_color="4F46E5", end_color="4F46E5", fill_type="solid")
HEADER_FONT = Font(color="FFFFFF", bold=True, size=11)
HEADER_ALIGNMENT = Alignment(horizontal="center", vertical="center", wrap_text=True)
THIN_BORDER = Border(
    left=Side(style="thin", color="E2E8F0"),
    right=Side(style="thin", color="E2E8F0"),
    top=Side(style="thin", color="E2E8F0"),
    bottom=Side(style="thin", color="E2E8F0"),
)

COLUMNS = [
    ("ชื่อโครงการ", 45),
    ("หน่วยงาน", 30),
    ("เลขที่โครงการ", 20),
    ("ประเภทการจัดซื้อ", 15),
    ("สถานะ", 20),
    ("งบประมาณ (บาท)", 18),
    ("สถานะล่าสุด", 20),
    ("เห็นล่าสุด", 20),
    ("เปลี่ยนแปลงล่าสุด", 20),
    ("เหตุผลการปิด", 20),
]

PROCUREMENT_TYPE_LABELS = {
    "goods": "สินค้า",
    "services": "บริการ",
    "consulting": "ที่ปรึกษา",
    "unknown": "ไม่ระบุ",
}

STATE_LABELS = {
    "discovered": "ค้นพบใหม่",
    "open_invitation": "เปิดรับข้อเสนอ",
    "open_consulting": "เปิดรับที่ปรึกษา",
    "open_public_hearing": "ประชาพิจารณ์",
    "tor_downloaded": "ดาวน์โหลด TOR",
    "prelim_pricing_seen": "เห็นราคากลาง",
    "winner_announced": "ประกาศผู้ชนะ",
    "contract_signed": "ลงนามสัญญา",
    "closed_timeout_consulting": "ปิด-หมดเวลาที่ปรึกษา",
    "closed_stale_no_tor": "ปิด-ไม่มี TOR",
    "closed_manual": "ปิด-ด้วยตนเอง",
    "error": "ข้อผิดพลาด",
}

CLOSED_REASON_LABELS = {
    "winner_announced": "ประกาศผู้ชนะ",
    "contract_signed": "ลงนามสัญญา",
    "consulting_timeout_30d": "หมดเวลาที่ปรึกษา 30 วัน",
    "prelim_pricing": "เห็นราคากลาง",
    "stale_no_tor": "ไม่มี TOR",
    "manual": "ปิดด้วยตนเอง",
    "merged_duplicate": "รวมซ้ำ",
}


def _project_to_row(project: ProjectRecord) -> list[str | float | None]:
    budget = float(project.budget_amount) if project.budget_amount else None
    state_label = STATE_LABELS.get(project.project_state.value, project.project_state.value)
    type_label = PROCUREMENT_TYPE_LABELS.get(
        project.procurement_type.value, project.procurement_type.value
    )
    closed_label = (
        CLOSED_REASON_LABELS.get(project.closed_reason.value, project.closed_reason.value)
        if project.closed_reason
        else None
    )
    return [
        project.project_name,
        project.organization_name,
        project.project_number,
        type_label,
        state_label,
        budget,
        project.source_status_text,
        project.last_seen_at,
        project.last_changed_at,
        closed_label,
    ]


class ExportService:
    def __init__(self, project_repository: SqlProjectRepository) -> None:
        self._repository = project_repository

    def export_to_excel(
        self,
        *,
        tenant_id: str,
        project_states: list[str] | None = None,
        procurement_types: list[str] | None = None,
        closed_reasons: list[str] | None = None,
        organization: str | None = None,
        keyword: str | None = None,
        budget_min: Decimal | float | int | str | None = None,
        budget_max: Decimal | float | int | str | None = None,
        updated_after: str | None = None,
        has_changed_tor: bool | None = None,
        has_winner: bool | None = None,
    ) -> bytes:
        page = self._repository.list_projects(
            tenant_id=tenant_id,
            project_states=project_states,
            procurement_types=procurement_types,
            closed_reasons=closed_reasons,
            organization=organization,
            keyword=keyword,
            budget_min=budget_min,
            budget_max=budget_max,
            updated_after=updated_after,
            has_changed_tor=has_changed_tor,
            has_winner=has_winner,
            limit=10000,
            offset=0,
        )
        projects = page.items

        wb = Workbook()
        ws = wb.active
        if ws is None:
            ws = wb.create_sheet()
        ws.title = "โครงการ"

        # Header row
        for col_idx, (header, width) in enumerate(COLUMNS, start=1):
            cell = ws.cell(row=1, column=col_idx, value=header)
            cell.fill = HEADER_FILL
            cell.font = HEADER_FONT
            cell.alignment = HEADER_ALIGNMENT
            cell.border = THIN_BORDER
            ws.column_dimensions[cell.column_letter].width = width

        # Data rows
        for row_idx, project in enumerate(projects, start=2):
            row_data = _project_to_row(project)
            for col_idx, value in enumerate(row_data, start=1):
                cell = ws.cell(row=row_idx, column=col_idx, value=value)
                cell.border = THIN_BORDER
                cell.alignment = Alignment(vertical="center", wrap_text=True)
                if col_idx == 6 and isinstance(value, (int, float)):
                    cell.number_format = "#,##0"
                    cell.alignment = Alignment(horizontal="right", vertical="center")

        ws.freeze_panes = "A2"

        buffer = BytesIO()
        wb.save(buffer)
        return buffer.getvalue()
