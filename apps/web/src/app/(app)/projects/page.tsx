"use client";

import { useState } from "react";
import Link from "next/link";
import { Search } from "lucide-react";
import { PageHeader } from "@/components/layout/page-header";
import { StatusBadge } from "@/components/ui/status-badge";
import { QueryState } from "@/components/ui/query-state";
import { PROCUREMENT_TYPE_LABELS, BADGE_STYLE_MAP } from "@/lib/constants";
import { useProjects } from "@/lib/hooks";
import { formatBudget, formatRelativeTime } from "@/lib/utils";
import type { ProjectSummary } from "@/lib/api";

/* ------------------------------------------------------------------ */
/*  Types                                                              */
/* ------------------------------------------------------------------ */

type StatusFilter = {
  key: string;
  label: string;
  count: number;
  checked: boolean;
};

type ProcurementTypeFilter = {
  key: string;
  label: string;
  checked: boolean;
};

type MockProject = {
  id: string;
  name: string;
  agency: string;
  projectNumber: string;
  type: string;
  state: string;
  budget: number;
  latestStatus: string;
  lastSeen: string;
  winner: "yes" | "no";
  torChanged: "yes" | "no";
};

/* ------------------------------------------------------------------ */
/*  Mock Data                                                          */
/* ------------------------------------------------------------------ */

const INITIAL_STATUS_FILTERS: StatusFilter[] = [
  { key: "discovered", label: "ค้นพบใหม่", count: 45, checked: true },
  { key: "open_invitation", label: "เปิดรับข้อเสนอ", count: 89, checked: true },
  { key: "tor_downloaded", label: "ดาวน์โหลด TOR", count: 34, checked: false },
  { key: "winner_announced", label: "ประกาศผู้ชนะ", count: 28, checked: false },
  { key: "closed_timeout_consulting", label: "ปิด-หมดเวลา", count: 15, checked: false },
  { key: "error", label: "ข้อผิดพลาด", count: 4, checked: false },
];

const INITIAL_TYPE_FILTERS: ProcurementTypeFilter[] = [
  { key: "goods", label: "สินค้า", checked: true },
  { key: "services", label: "บริการ", checked: true },
  { key: "consulting", label: "ที่ปรึกษา", checked: false },
];

const MOCK_PROJECTS: MockProject[] = [
  {
    id: "egp-2026-0142",
    name: "จัดซื้อระบบสารสนเทศเพื่อการบริหารจัดการภายในองค์กร",
    agency: "กรมสรรพากร",
    projectNumber: "EGP-2026-0142",
    type: "services",
    state: "open_invitation",
    budget: 12500000,
    latestStatus: "ประกาศเชิญชวน",
    lastSeen: "2 ชม.",
    winner: "no",
    torChanged: "no",
  },
  {
    id: "egp-2026-0138",
    name: "พัฒนาระบบฐานข้อมูลสาธารณสุขแห่งชาติ",
    agency: "กระทรวงสาธารณสุข",
    projectNumber: "EGP-2026-0138",
    type: "services",
    state: "tor_downloaded",
    budget: 8750000,
    latestStatus: "ดาวน์โหลดเอกสาร",
    lastSeen: "5 ชม.",
    winner: "no",
    torChanged: "yes",
  },
  {
    id: "egp-2026-0135",
    name: "จ้างที่ปรึกษาวิเคราะห์ระบบงบประมาณแผ่นดิน",
    agency: "สำนักงบประมาณ",
    projectNumber: "EGP-2026-0135",
    type: "consulting",
    state: "winner_announced",
    budget: 3200000,
    latestStatus: "ประกาศผู้ชนะ",
    lastSeen: "1 วัน",
    winner: "yes",
    torChanged: "no",
  },
  {
    id: "egp-2026-0131",
    name: "ประกวดราคาซื้อครุภัณฑ์คอมพิวเตอร์",
    agency: "ม.เชียงใหม่",
    projectNumber: "EGP-2026-0131",
    type: "goods",
    state: "discovered",
    budget: 950000,
    latestStatus: "ค้นพบ",
    lastSeen: "30 นาที",
    winner: "no",
    torChanged: "no",
  },
  {
    id: "egp-2026-0128",
    name: "จัดซื้อระบบคลาวด์สำหรับระบบศุลกากรอิเล็กทรอนิกส์",
    agency: "กรมศุลกากร",
    projectNumber: "EGP-2026-0128",
    type: "services",
    state: "open_invitation",
    budget: 25000000,
    latestStatus: "ประกาศเชิญชวน",
    lastSeen: "3 ชม.",
    winner: "no",
    torChanged: "no",
  },
  {
    id: "egp-2026-0125",
    name: "พัฒนาแอปพลิเคชันท่องเที่ยวอัจฉริยะ",
    agency: "การท่องเที่ยวฯ",
    projectNumber: "EGP-2026-0125",
    type: "services",
    state: "closed_timeout_consulting",
    budget: 5400000,
    latestStatus: "หมดเวลา",
    lastSeen: "3 วัน",
    winner: "no",
    torChanged: "no",
  },
  {
    id: "egp-2026-0121",
    name: "จ้างบำรุงรักษาระบบสารสนเทศทางหลวง",
    agency: "กรมทางหลวง",
    projectNumber: "EGP-2026-0121",
    type: "services",
    state: "open_invitation",
    budget: 18900000,
    latestStatus: "ประชาพิจารณ์",
    lastSeen: "6 ชม.",
    winner: "no",
    torChanged: "yes",
  },
  {
    id: "egp-2026-0118",
    name: "จัดซื้อเครื่องแม่ข่ายและอุปกรณ์จัดเก็บข้อมูล",
    agency: "กรม DSI",
    projectNumber: "EGP-2026-0118",
    type: "goods",
    state: "error",
    budget: 7600000,
    latestStatus: "ล้มเหลว",
    lastSeen: "1 วัน",
    winner: "no",
    torChanged: "no",
  },
];

/* ------------------------------------------------------------------ */
/*  Helpers                                                            */
/* ------------------------------------------------------------------ */

function formatBudgetLocal(amount: number): string {
  return (
    "\u0E3F" +
    amount.toLocaleString("th-TH", {
      minimumFractionDigits: 0,
      maximumFractionDigits: 0,
    })
  );
}

/* ------------------------------------------------------------------ */
/*  Component                                                          */
/* ------------------------------------------------------------------ */

export default function ProjectsPage() {
  const [searchQuery, setSearchQuery] = useState("");
  const [activeTab, setActiveTab] = useState<"all" | "active" | "closed">("all");
  const [statusFilters, setStatusFilters] = useState(INITIAL_STATUS_FILTERS);
  const [typeFilters, setTypeFilters] = useState(INITIAL_TYPE_FILTERS);
  const [budgetMin, setBudgetMin] = useState("");
  const [budgetMax, setBudgetMax] = useState("");
  const [torChangedOnly, setTorChangedOnly] = useState(false);
  const [winnerOnly, setWinnerOnly] = useState(false);
  const [currentPage, setCurrentPage] = useState(1);
  const rowsPerPage = 50;

  // Determine state filter for API
  const checkedStates = statusFilters.filter((f) => f.checked).map((f) => f.key);
  const stateParam = checkedStates.length === 1 ? checkedStates[0] : undefined;

  const { data, isLoading, isError, error } = useProjects({
    project_state: stateParam,
    limit: rowsPerPage,
    offset: (currentPage - 1) * rowsPerPage,
  });

  const apiProjects: ProjectSummary[] = data?.projects ?? [];
  const totalProjects = data?.total ?? MOCK_PROJECTS.length;
  const activeProjects = apiProjects.filter((p) => !p.project_state.startsWith("closed") && p.project_state !== "error").length;
  const closedProjects = apiProjects.filter((p) => p.project_state.startsWith("closed")).length;
  const totalPages = Math.max(1, Math.ceil(totalProjects / rowsPerPage));

  // Use API data if available, fall back to mock
  const displayProjects: MockProject[] = apiProjects.length > 0
    ? apiProjects.map((p) => ({
        id: p.id,
        name: p.project_name,
        agency: p.organization_name,
        projectNumber: p.project_number ?? "—",
        type: p.procurement_type,
        state: p.project_state,
        budget: Number(p.budget_amount) || 0,
        latestStatus: p.source_status_text ?? "—",
        lastSeen: formatRelativeTime(p.last_seen_at),
        winner: (p.project_state === "winner_announced" || p.project_state === "contract_signed") ? "yes" as const : "no" as const,
        torChanged: "no" as const,
      }))
    : MOCK_PROJECTS;

  function toggleStatusFilter(key: string) {
    setStatusFilters((prev) =>
      prev.map((f) => (f.key === key ? { ...f, checked: !f.checked } : f)),
    );
  }

  function toggleTypeFilter(key: string) {
    setTypeFilters((prev) =>
      prev.map((f) => (f.key === key ? { ...f, checked: !f.checked } : f)),
    );
  }

  function clearAllFilters() {
    setStatusFilters((prev) => prev.map((f) => ({ ...f, checked: false })));
    setTypeFilters((prev) => prev.map((f) => ({ ...f, checked: false })));
    setBudgetMin("");
    setBudgetMax("");
    setTorChangedOnly(false);
    setWinnerOnly(false);
  }

  const tabs = [
    { key: "all" as const, label: "ทั้งหมด", count: totalProjects },
    { key: "active" as const, label: "ใช้งานอยู่", count: activeProjects },
    { key: "closed" as const, label: "ปิดแล้ว", count: closedProjects },
  ];

  return (
    <>
      <PageHeader
        title="สำรวจโครงการ"
        subtitle="ค้นหาและกรองโครงการจัดซื้อจัดจ้างทั้งหมด"
        actions={
          <>
            <button
              type="button"
              className="rounded-xl border border-[var(--border-default)] px-4 py-2.5 text-sm font-medium text-[var(--text-secondary)] hover:bg-[var(--bg-surface-hover)]"
            >
              ส่งออก Excel
            </button>
            <button
              type="button"
              className="rounded-xl bg-primary px-4 py-2.5 text-sm font-medium text-white hover:bg-primary-hover"
            >
              Crawl ใหม่
            </button>
          </>
        }
      />

      <div className="flex gap-0">
        {/* ============================================================ */}
        {/*  LEFT COLUMN — Filter Rail                                    */}
        {/* ============================================================ */}
        <aside className="sticky top-0 h-[calc(100vh-140px)] w-[280px] shrink-0 overflow-y-auto border-r border-[var(--border-default)] bg-[var(--bg-surface)] p-5">
          {/* Header */}
          <div className="mb-5 flex items-center justify-between">
            <span className="text-sm font-bold text-[var(--text-primary)]">
              ตัวกรอง
            </span>
            <button
              type="button"
              onClick={clearAllFilters}
              className="text-xs font-medium text-[var(--color-primary)] hover:underline"
            >
              ล้างทั้งหมด
            </button>
          </div>

          {/* 1. สถานะโครงการ */}
          <div className="mb-6">
            <h3 className="mb-3 text-sm font-semibold text-[var(--text-primary)]">
              สถานะโครงการ
            </h3>
            <div className="space-y-2">
              {statusFilters.map((filter) => (
                <label
                  key={filter.key}
                  className="flex cursor-pointer items-center gap-2 text-sm text-[var(--text-secondary)]"
                >
                  <input
                    type="checkbox"
                    checked={filter.checked}
                    onChange={() => toggleStatusFilter(filter.key)}
                    className="h-4 w-4 rounded border-[var(--border-default)] text-[var(--color-primary)] focus:ring-[var(--color-primary)]"
                  />
                  <span className="flex-1">{filter.label}</span>
                  <StatusBadge state={filter.key} className="text-[10px] px-1.5 py-0" />
                  <span className="text-xs text-[var(--text-muted)]">
                    ({filter.count})
                  </span>
                </label>
              ))}
            </div>
          </div>

          {/* 2. ประเภทการจัดซื้อ */}
          <div className="mb-6">
            <h3 className="mb-3 text-sm font-semibold text-[var(--text-primary)]">
              ประเภทการจัดซื้อ
            </h3>
            <div className="space-y-2">
              {typeFilters.map((filter) => (
                <label
                  key={filter.key}
                  className="flex cursor-pointer items-center gap-2 text-sm text-[var(--text-secondary)]"
                >
                  <input
                    type="checkbox"
                    checked={filter.checked}
                    onChange={() => toggleTypeFilter(filter.key)}
                    className="h-4 w-4 rounded border-[var(--border-default)] text-[var(--color-primary)] focus:ring-[var(--color-primary)]"
                  />
                  <span>{filter.label}</span>
                </label>
              ))}
            </div>
          </div>

          {/* 3. ช่วงงบประมาณ */}
          <div className="mb-6">
            <h3 className="mb-3 text-sm font-semibold text-[var(--text-primary)]">
              ช่วงงบประมาณ
            </h3>
            <div className="space-y-2">
              <div>
                <label className="mb-1 block text-xs text-[var(--text-muted)]">
                  ขั้นต่ำ (บาท)
                </label>
                <input
                  type="text"
                  value={budgetMin}
                  onChange={(e) => setBudgetMin(e.target.value)}
                  placeholder="0"
                  className="w-full rounded-lg border border-[var(--border-default)] bg-[var(--bg-surface)] px-3 py-1.5 text-sm text-[var(--text-primary)] placeholder:text-[var(--text-disabled)] focus:border-[var(--color-primary)] focus:outline-none focus:ring-1 focus:ring-[var(--color-primary)]"
                />
              </div>
              <div>
                <label className="mb-1 block text-xs text-[var(--text-muted)]">
                  สูงสุด (บาท)
                </label>
                <input
                  type="text"
                  value={budgetMax}
                  onChange={(e) => setBudgetMax(e.target.value)}
                  placeholder="100,000,000"
                  className="w-full rounded-lg border border-[var(--border-default)] bg-[var(--bg-surface)] px-3 py-1.5 text-sm text-[var(--text-primary)] placeholder:text-[var(--text-disabled)] focus:border-[var(--color-primary)] focus:outline-none focus:ring-1 focus:ring-[var(--color-primary)]"
                />
              </div>
            </div>
          </div>

          {/* 4. TOR เปลี่ยนแปลง */}
          <div className="mb-6">
            <h3 className="mb-3 text-sm font-semibold text-[var(--text-primary)]">
              TOR เปลี่ยนแปลง
            </h3>
            <label className="flex cursor-pointer items-center gap-2 text-sm text-[var(--text-secondary)]">
              <input
                type="checkbox"
                checked={torChangedOnly}
                onChange={() => setTorChangedOnly((v) => !v)}
                className="h-4 w-4 rounded border-[var(--border-default)] text-[var(--color-primary)] focus:ring-[var(--color-primary)]"
              />
              <span>แสดงเฉพาะ TOR ที่เปลี่ยน</span>
            </label>
          </div>

          {/* 5. มีผู้ชนะ */}
          <div className="mb-6">
            <h3 className="mb-3 text-sm font-semibold text-[var(--text-primary)]">
              มีผู้ชนะ
            </h3>
            <label className="flex cursor-pointer items-center gap-2 text-sm text-[var(--text-secondary)]">
              <input
                type="checkbox"
                checked={winnerOnly}
                onChange={() => setWinnerOnly((v) => !v)}
                className="h-4 w-4 rounded border-[var(--border-default)] text-[var(--color-primary)] focus:ring-[var(--color-primary)]"
              />
              <span>แสดงเฉพาะที่มีผู้ชนะ</span>
            </label>
          </div>
        </aside>

        {/* ============================================================ */}
        {/*  RIGHT COLUMN — Table Area                                    */}
        {/* ============================================================ */}
        <div className="flex-1 min-w-0">
          {/* Top bar */}
          <div className="mb-4 space-y-3">
            {/* Search + Tabs row */}
            <div className="flex items-center gap-4">
              {/* Search input */}
              <div className="relative w-[360px]">
                <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-[var(--text-muted)]" />
                <input
                  type="text"
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                  placeholder="ค้นหาโครงการ, หน่วยงาน, เลขที่..."
                  className="w-full rounded-xl border border-[var(--border-default)] bg-[var(--bg-surface)] py-2 pl-10 pr-4 text-sm text-[var(--text-primary)] placeholder:text-[var(--text-disabled)] focus:border-[var(--color-primary)] focus:outline-none focus:ring-1 focus:ring-[var(--color-primary)]"
                />
              </div>

              {/* Tabs */}
              <div className="flex items-center gap-1 rounded-xl bg-[var(--bg-surface-secondary)] p-1">
                {tabs.map((tab) => (
                  <button
                    key={tab.key}
                    type="button"
                    onClick={() => setActiveTab(tab.key)}
                    className={`rounded-lg px-3 py-1.5 text-sm font-medium transition-colors ${
                      activeTab === tab.key
                        ? "bg-[var(--bg-surface)] text-[var(--text-primary)] shadow-sm"
                        : "text-[var(--text-muted)] hover:text-[var(--text-secondary)]"
                    }`}
                  >
                    {tab.label} ({tab.count})
                  </button>
                ))}
              </div>

              {/* Count label */}
              <span className="ml-auto text-xs text-[var(--text-muted)]">
                แสดง 1-50 จาก {totalProjects} โครงการ
              </span>
            </div>
          </div>

          {/* Table card */}
          <div className="overflow-hidden rounded-2xl bg-[var(--bg-surface)] shadow-[var(--shadow-soft)]">
            <div className="overflow-x-auto">
              <table className="w-full min-w-[1200px]">
                <thead>
                  <tr className="bg-[var(--bg-surface-secondary)]">
                    <th className="px-3 py-2.5 text-left text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">
                      ชื่อโครงการ
                    </th>
                    <th className="px-3 py-2.5 text-left text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">
                      หน่วยงาน
                    </th>
                    <th className="px-3 py-2.5 text-left text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">
                      เลขที่โครงการ
                    </th>
                    <th className="px-3 py-2.5 text-left text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">
                      ประเภท
                    </th>
                    <th className="px-3 py-2.5 text-left text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">
                      สถานะ
                    </th>
                    <th className="px-3 py-2.5 text-right text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">
                      งบประมาณ (บาท)
                    </th>
                    <th className="px-3 py-2.5 text-left text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">
                      สถานะล่าสุด
                    </th>
                    <th className="px-3 py-2.5 text-left text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">
                      เห็นล่าสุด
                    </th>
                    <th className="px-3 py-2.5 text-center text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">
                      ผู้ชนะ
                    </th>
                    <th className="px-3 py-2.5 text-center text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">
                      TOR เปลี่ยน
                    </th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-[var(--border-default)]">
                  {displayProjects.map((project) => (
                    <tr
                      key={project.id}
                      className="h-10 hover:bg-[var(--bg-surface-hover)] transition-colors"
                    >
                      {/* ชื่อโครงการ */}
                      <td className="px-3 py-2 text-[13px]">
                        <Link
                          href={`/projects/${project.id}`}
                          className="font-medium text-[var(--color-primary)] hover:underline line-clamp-1"
                          title={project.name}
                        >
                          {project.name}
                        </Link>
                      </td>
                      {/* หน่วยงาน */}
                      <td className="px-3 py-2 text-[13px] text-[var(--text-secondary)]">
                        {project.agency}
                      </td>
                      {/* เลขที่โครงการ */}
                      <td className="px-3 py-2 font-mono text-[13px] text-[var(--text-secondary)]">
                        {project.projectNumber}
                      </td>
                      {/* ประเภท */}
                      <td className="px-3 py-2 text-[13px] text-[var(--text-secondary)]">
                        {PROCUREMENT_TYPE_LABELS[project.type] ?? project.type}
                      </td>
                      {/* สถานะ */}
                      <td className="px-3 py-2">
                        <StatusBadge state={project.state} />
                      </td>
                      {/* งบประมาณ */}
                      <td className="px-3 py-2 text-right font-mono text-[13px] tabular-nums text-[var(--text-primary)]">
                        {formatBudgetLocal(project.budget)}
                      </td>
                      {/* สถานะล่าสุด */}
                      <td className="px-3 py-2 text-[13px] text-[var(--text-secondary)]">
                        {project.latestStatus}
                      </td>
                      {/* เห็นล่าสุด */}
                      <td className="px-3 py-2 text-[13px] text-[var(--text-muted)]">
                        {project.lastSeen}
                      </td>
                      {/* ผู้ชนะ */}
                      <td className="px-3 py-2 text-center text-[13px]">
                        {project.winner === "yes" ? (
                          <span className="text-green-600">&#10003;</span>
                        ) : (
                          <span className="text-[var(--text-disabled)]">&mdash;</span>
                        )}
                      </td>
                      {/* TOR เปลี่ยน */}
                      <td className="px-3 py-2 text-center text-[13px]">
                        {project.torChanged === "yes" ? (
                          <span className="text-amber-500">&#9888;&#65039;</span>
                        ) : (
                          <span className="text-[var(--text-disabled)]">&mdash;</span>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            {/* Pagination footer */}
            <div className="flex items-center justify-between border-t border-[var(--border-default)] px-4 py-3">
              <button
                type="button"
                disabled
                className="rounded-lg border border-[var(--border-default)] px-3 py-1.5 text-sm text-[var(--text-disabled)] disabled:cursor-not-allowed disabled:opacity-50"
              >
                ก่อนหน้า
              </button>

              <div className="flex items-center gap-1">
                {Array.from({ length: totalPages }, (_, i) => i + 1).map((page) => (
                  <button
                    key={page}
                    type="button"
                    onClick={() => setCurrentPage(page)}
                    className={`h-8 w-8 rounded-lg text-sm font-medium transition-colors ${
                      currentPage === page
                        ? "bg-[var(--color-primary)] text-white"
                        : "text-[var(--text-secondary)] hover:bg-[var(--bg-surface-hover)]"
                    }`}
                  >
                    {page}
                  </button>
                ))}
              </div>

              <div className="flex items-center gap-3">
                <button
                  type="button"
                  onClick={() =>
                    setCurrentPage((p) => Math.min(p + 1, totalPages))
                  }
                  className="rounded-lg border border-[var(--border-default)] px-3 py-1.5 text-sm text-[var(--text-secondary)] hover:bg-[var(--bg-surface-hover)]"
                >
                  ถัดไป
                </button>
                <span className="text-xs text-[var(--text-muted)]">
                  {rowsPerPage} แถว/หน้า
                </span>
              </div>
            </div>
          </div>
        </div>
      </div>
    </>
  );
}
