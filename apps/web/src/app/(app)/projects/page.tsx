"use client";

import { useDeferredValue, useEffect, useState } from "react";
import Link from "next/link";
import { useQueryClient } from "@tanstack/react-query";
import { Download, Search } from "lucide-react";
import { PageHeader } from "@/components/layout/page-header";
import { StatusBadge } from "@/components/ui/status-badge";
import { QueryState } from "@/components/ui/query-state";
import { PROCUREMENT_TYPE_LABELS } from "@/lib/constants";
import { useProjects, useRules, useRuns } from "@/lib/hooks";
import {
  getActiveRuns,
  getRunActivitySnapshot,
  getRunDiscoveredCount,
} from "@/lib/run-progress";
import { formatBudget, formatRelativeTime, formatThaiDate } from "@/lib/utils";
import { fetchProjectExport, localizeApiError, triggerManualRecrawl } from "@/lib/api";
import type {
  ExportProjectsParams,
  FetchProjectsParams,
  ProjectSummary,
  RunDetailResponse,
} from "@/lib/api";

type StatusFilter = {
  key: string;
  label: string;
  checked: boolean;
};

type ProcurementTypeFilter = {
  key: string;
  label: string;
  checked: boolean;
};

type ProjectRow = {
  id: string;
  name: string;
  agency: string;
  projectNumber: string;
  type: string;
  state: string;
  budgetAmount: string | null;
  latestStatus: string;
  lastSeen: string;
  hasWinner: boolean;
  hasChangedTor: boolean;
};

type ManualRecrawlTracking = {
  queuedJobCount: number;
  queuedKeywords: string[];
  requestedAt: number;
  timedOut: boolean;
};

type ActiveRunCard = {
  id: string;
  displayId: string;
  status: string;
  triggerLabel: string;
  detail: string;
  updatedAt: string | null;
  discoveredCount: number;
};

const MANUAL_RECRAWL_RUN_WAIT_MS = 90_000;

const ACTIVE_STATES = [
  "discovered",
  "open_invitation",
  "open_consulting",
  "open_public_hearing",
  "tor_downloaded",
  "prelim_pricing_seen",
  "error",
];

const CLOSED_STATES = [
  "winner_announced",
  "contract_signed",
  "closed_timeout_consulting",
  "closed_stale_no_tor",
  "closed_manual",
];

const INITIAL_STATUS_FILTERS: StatusFilter[] = [
  { key: "discovered", label: "ค้นพบใหม่", checked: false },
  { key: "open_invitation", label: "เปิดรับข้อเสนอ", checked: false },
  { key: "open_consulting", label: "เปิดรับที่ปรึกษา", checked: false },
  { key: "open_public_hearing", label: "ประชาพิจารณ์", checked: false },
  { key: "tor_downloaded", label: "ดาวน์โหลด TOR", checked: false },
  { key: "prelim_pricing_seen", label: "เห็นราคากลาง", checked: false },
  { key: "winner_announced", label: "ประกาศผู้ชนะ", checked: false },
  { key: "contract_signed", label: "ลงนามสัญญา", checked: false },
  { key: "closed_timeout_consulting", label: "ปิด-หมดเวลา", checked: false },
  { key: "closed_stale_no_tor", label: "ปิด-ไม่มี TOR", checked: false },
  { key: "closed_manual", label: "ปิดด้วยตนเอง", checked: false },
  { key: "error", label: "ข้อผิดพลาด", checked: false },
];

const INITIAL_TYPE_FILTERS: ProcurementTypeFilter[] = [
  { key: "goods", label: "สินค้า", checked: false },
  { key: "services", label: "บริการ", checked: false },
  { key: "consulting", label: "ที่ปรึกษา", checked: false },
  { key: "unknown", label: "ไม่ระบุ", checked: false },
];

function normalizeNumericFilter(value: string): string | undefined {
  const normalized = value.replace(/,/g, "").trim();
  return normalized || undefined;
}

function getEffectiveStates(
  activeTab: "all" | "active" | "closed",
  selectedStates: string[],
): string[] | undefined {
  const tabStates =
    activeTab === "active"
      ? ACTIVE_STATES
      : activeTab === "closed"
        ? CLOSED_STATES
        : [];

  if (selectedStates.length === 0) {
    return tabStates.length > 0 ? tabStates : undefined;
  }

  if (tabStates.length === 0) {
    return selectedStates;
  }

  const intersection = selectedStates.filter((state) => tabStates.includes(state));
  return intersection.length > 0 ? intersection : ["__no_match__"];
}

function buildProjectRows(projects: ProjectSummary[]): ProjectRow[] {
  return projects.map((project) => ({
    id: project.id,
    name: project.project_name,
    agency: project.organization_name,
    projectNumber: project.project_number ?? "—",
    type: project.procurement_type,
    state: project.project_state,
    budgetAmount: project.budget_amount,
    latestStatus: project.source_status_text ?? "—",
    lastSeen: formatRelativeTime(project.last_seen_at),
    hasWinner:
      project.project_state === "winner_announced" ||
      project.project_state === "contract_signed",
    hasChangedTor: project.has_changed_tor,
  }));
}

function formatRunTriggerLabel(triggerType: string): string {
  switch (triggerType) {
    case "schedule":
      return "กำหนดเวลา";
    case "manual":
      return "ด้วยตนเอง";
    case "retry":
      return "ลองใหม่";
    case "backfill":
      return "ย้อนเก็บข้อมูล";
    default:
      return triggerType;
  }
}

function buildActiveRunCard(runDetail: RunDetailResponse): ActiveRunCard {
  const activity = getRunActivitySnapshot(runDetail);
  return {
    id: runDetail.run.id,
    displayId: runDetail.run.id.slice(0, 12),
    status: runDetail.run.status,
    triggerLabel: formatRunTriggerLabel(runDetail.run.trigger_type),
    detail: activity.detail ?? "worker เริ่ม run แล้ว แต่ยังไม่มีสถานะล่าสุดให้แสดง",
    updatedAt: activity.updatedAt,
    discoveredCount: getRunDiscoveredCount(runDetail.run),
  };
}

export default function ProjectsPage() {
  const queryClient = useQueryClient();
  const [searchQuery, setSearchQuery] = useState("");
  const [activeTab, setActiveTab] = useState<"all" | "active" | "closed">("all");
  const [statusFilters, setStatusFilters] = useState(INITIAL_STATUS_FILTERS);
  const [typeFilters, setTypeFilters] = useState(INITIAL_TYPE_FILTERS);
  const [budgetMin, setBudgetMin] = useState("");
  const [budgetMax, setBudgetMax] = useState("");
  const [torChangedOnly, setTorChangedOnly] = useState(false);
  const [winnerOnly, setWinnerOnly] = useState(false);
  const [currentPage, setCurrentPage] = useState(1);
  const [isExporting, setIsExporting] = useState(false);
  const [exportError, setExportError] = useState<string | null>(null);
  const [isRecrawling, setIsRecrawling] = useState(false);
  const [recrawlError, setRecrawlError] = useState<string | null>(null);
  const [recrawlNotice, setRecrawlNotice] = useState<string | null>(null);
  const [manualRecrawlTracking, setManualRecrawlTracking] =
    useState<ManualRecrawlTracking | null>(null);
  const rowsPerPage = 50;
  const { data: rulesData, isLoading: isRulesLoading } = useRules();

  const deferredSearchQuery = useDeferredValue(searchQuery);
  const selectedStatusKeys = statusFilters.filter((filter) => filter.checked).map((filter) => filter.key);
  const selectedTypeKeys = typeFilters.filter((filter) => filter.checked).map((filter) => filter.key);
  const selectedStatusSignature = selectedStatusKeys.join(",");
  const selectedTypeSignature = selectedTypeKeys.join(",");
  const effectiveStates = getEffectiveStates(activeTab, selectedStatusKeys);
  const normalizedBudgetMin = normalizeNumericFilter(budgetMin);
  const normalizedBudgetMax = normalizeNumericFilter(budgetMax);

  useEffect(() => {
    setCurrentPage(1);
  }, [
    activeTab,
    deferredSearchQuery,
    normalizedBudgetMin,
    normalizedBudgetMax,
    torChangedOnly,
    winnerOnly,
    selectedStatusSignature,
    selectedTypeSignature,
  ]);

  const exportQuery: ExportProjectsParams = {
    project_state: effectiveStates,
    procurement_type: selectedTypeKeys.length > 0 ? selectedTypeKeys : undefined,
    keyword: deferredSearchQuery.trim() || undefined,
    budget_min: normalizedBudgetMin,
    budget_max: normalizedBudgetMax,
    has_changed_tor: torChangedOnly ? true : undefined,
    has_winner: winnerOnly ? true : undefined,
  };

  const projectQuery: FetchProjectsParams = {
    ...exportQuery,
    limit: rowsPerPage,
    offset: (currentPage - 1) * rowsPerPage,
  };

  const { data, isLoading, isError, error } = useProjects(projectQuery);
  const {
    data: runsData,
    error: runsError,
    isError: isRunsError,
    refetch: refetchRuns,
  } = useRuns({ limit: 10, offset: 0 });
  const apiProjects = data?.projects ?? [];
  const totalProjects = data?.total ?? 0;
  const totalPages = Math.max(1, Math.ceil(Math.max(totalProjects, 1) / rowsPerPage));
  const displayProjects = buildProjectRows(apiProjects);
  const rangeStart = totalProjects === 0 ? 0 : (currentPage - 1) * rowsPerPage + 1;
  const rangeEnd = totalProjects === 0 ? 0 : rangeStart + displayProjects.length - 1;
  const activeRuns = getActiveRuns(runsData?.runs ?? []);
  const activeRunCards = activeRuns.slice(0, 3).map(buildActiveRunCard);
  const runningRunCount = activeRuns.filter((detail) => detail.run.status === "running").length;
  const queuedRunCount = activeRuns.filter((detail) => detail.run.status === "queued").length;
  const waitingForManualRun =
    manualRecrawlTracking !== null &&
    !manualRecrawlTracking.timedOut &&
    activeRuns.length === 0;
  const shouldShowRunActivity =
    activeRuns.length > 0 ||
    manualRecrawlTracking !== null ||
    (recrawlNotice !== null && isRunsError);
  const tabs = [
    { key: "all" as const, label: "ทั้งหมด" },
    { key: "active" as const, label: "ใช้งานอยู่" },
    { key: "closed" as const, label: "ปิดแล้ว" },
  ];

  useEffect(() => {
    if (activeRuns.length === 0 || manualRecrawlTracking === null) {
      return;
    }
    setManualRecrawlTracking(null);
  }, [activeRuns.length, manualRecrawlTracking]);

  useEffect(() => {
    if (!waitingForManualRun && activeRuns.length === 0) {
      return;
    }
    const interval = window.setInterval(() => {
      void refetchRuns();
    }, 5000);
    return () => window.clearInterval(interval);
  }, [activeRuns.length, refetchRuns, waitingForManualRun]);

  useEffect(() => {
    if (!waitingForManualRun || manualRecrawlTracking === null) {
      return;
    }
    const remainingMs =
      MANUAL_RECRAWL_RUN_WAIT_MS - (Date.now() - manualRecrawlTracking.requestedAt);
    if (remainingMs <= 0) {
      setManualRecrawlTracking((current) =>
        current ? { ...current, timedOut: true } : current,
      );
      return;
    }
    const timeout = window.setTimeout(() => {
      setManualRecrawlTracking((current) =>
        current ? { ...current, timedOut: true } : current,
      );
    }, remainingMs);
    return () => window.clearTimeout(timeout);
  }, [manualRecrawlTracking, waitingForManualRun]);

  function toggleStatusFilter(key: string) {
    setStatusFilters((previous) =>
      previous.map((filter) =>
        filter.key === key ? { ...filter, checked: !filter.checked } : filter,
      ),
    );
  }

  function toggleTypeFilter(key: string) {
    setTypeFilters((previous) =>
      previous.map((filter) =>
        filter.key === key ? { ...filter, checked: !filter.checked } : filter,
      ),
    );
  }

  function clearAllFilters() {
    setStatusFilters((previous) => previous.map((filter) => ({ ...filter, checked: false })));
    setTypeFilters((previous) => previous.map((filter) => ({ ...filter, checked: false })));
    setBudgetMin("");
    setBudgetMax("");
    setTorChangedOnly(false);
    setWinnerOnly(false);
    setSearchQuery("");
    setActiveTab("all");
  }

  async function handleExport() {
    setIsExporting(true);
    setExportError(null);
    try {
      const { blob, filename } = await fetchProjectExport(exportQuery);
      const downloadUrl = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = downloadUrl;
      link.download = filename;
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(downloadUrl);
    } catch (error) {
      setExportError(
        localizeApiError(error, "ไม่สามารถส่งออกไฟล์ Excel ได้"),
      );
    } finally {
      setIsExporting(false);
    }
  }

  async function handleRecrawl() {
    setIsRecrawling(true);
    setRecrawlError(null);
    setRecrawlNotice(null);
    setManualRecrawlTracking(null);
    try {
      const result = await triggerManualRecrawl();
      const keywordCount = result.queued_keywords.length;
      setRecrawlNotice(
        `เริ่ม crawl ${result.queued_job_count} งานจาก ${keywordCount} คำค้นแล้ว`,
      );
      if (result.queued_job_count > 0) {
        setManualRecrawlTracking({
          queuedJobCount: result.queued_job_count,
          queuedKeywords: result.queued_keywords,
          requestedAt: Date.now(),
          timedOut: false,
        });
      }
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["rules"] }),
        queryClient.invalidateQueries({ queryKey: ["runs"] }),
      ]);
    } catch (error) {
      setRecrawlError(
        localizeApiError(error, "ยังไม่สามารถเริ่ม crawl ใหม่ได้"),
      );
    } finally {
      setIsRecrawling(false);
    }
  }

  const canRecrawl =
    !!rulesData?.entitlements.runs_allowed &&
    (rulesData?.entitlements.active_keyword_count ?? 0) > 0;

  return (
    <>
      <PageHeader
        title="สำรวจโครงการ"
        subtitle="ค้นหาและกรองโครงการจัดซื้อจัดจ้างทั้งหมด"
        actions={
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => void handleExport()}
              disabled={isExporting || isLoading}
              className="inline-flex items-center gap-2 rounded-xl border border-[var(--border-default)] bg-[var(--bg-surface)] px-4 py-2.5 text-sm font-medium text-[var(--text-primary)] transition-colors hover:bg-[var(--bg-surface-hover)] disabled:cursor-not-allowed disabled:opacity-60"
            >
              <Download className="h-4 w-4" />
              {isExporting ? "กำลังส่งออก..." : "ส่งออก Excel"}
            </button>
            <button
              type="button"
              onClick={() => void handleRecrawl()}
              disabled={isRecrawling || isLoading || isRulesLoading || !canRecrawl}
              className="rounded-xl bg-primary px-4 py-2.5 text-sm font-medium text-white hover:bg-primary-hover disabled:cursor-not-allowed disabled:opacity-60"
            >
              {isRecrawling ? "กำลังเริ่ม crawl..." : "Crawl ใหม่"}
            </button>
          </div>
        }
      />

      {recrawlError ? (
        <div className="mb-4 rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          {recrawlError}
        </div>
      ) : null}

      {recrawlNotice ? (
        <div className="mb-4 rounded-xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-700">
          {recrawlNotice}
        </div>
      ) : null}

      {shouldShowRunActivity ? (
        <section className="mb-4 rounded-2xl border border-[var(--border-default)] bg-[var(--bg-surface)] p-4 shadow-[var(--shadow-soft)]">
          <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
            <div>
              <h2 className="text-base font-semibold text-[var(--text-primary)]">
                สถานะการ crawl ล่าสุด
              </h2>
              <p className="mt-1 text-sm text-[var(--text-muted)]">
                แผงนี้อ่านจากข้อมูล run จริงของ worker เพื่อบอกว่างานค้างคิวหรือกำลังทำอะไรอยู่
              </p>
            </div>
            <Link
              href="/runs"
              className="text-sm font-medium text-[var(--color-primary)] hover:underline"
            >
              ดูหน้าการทำงานทั้งหมด
            </Link>
          </div>

          {activeRuns.length > 0 ? (
            <>
              <div className="mt-4 flex flex-wrap gap-2 text-sm">
                <span className="rounded-full bg-[var(--badge-indigo-bg)] px-3 py-1 font-medium text-[var(--badge-indigo-text)]">
                  กำลังทำงาน {runningRunCount} งาน
                </span>
                <span className="rounded-full bg-[var(--badge-amber-bg)] px-3 py-1 font-medium text-[var(--badge-amber-text)]">
                  รอคิว {queuedRunCount} งาน
                </span>
              </div>
              <div className="mt-4 space-y-3">
                {activeRunCards.map((run) => (
                  <article
                    key={run.id}
                    className="rounded-xl border border-[var(--border-default)] bg-[var(--bg-surface-secondary)] p-4"
                  >
                    <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
                      <div className="flex flex-wrap items-center gap-2">
                        <StatusBadge state={run.status} variant="run" />
                        <span className="font-mono text-sm text-[var(--text-primary)]">
                          {run.displayId}
                        </span>
                        <span className="text-sm text-[var(--text-muted)]">
                          ทริกเกอร์: {run.triggerLabel}
                        </span>
                      </div>
                      <span className="text-sm text-[var(--text-muted)]">
                        ค้นพบแล้ว {run.discoveredCount} โครงการ
                      </span>
                    </div>
                    <p className="mt-3 text-sm text-[var(--text-secondary)]">{run.detail}</p>
                    {run.updatedAt ? (
                      <p className="mt-2 text-xs text-[var(--text-muted)]">
                        อัปเดตล่าสุด {formatThaiDate(run.updatedAt)}
                      </p>
                    ) : null}
                  </article>
                ))}
              </div>
            </>
          ) : manualRecrawlTracking ? (
            <div className="mt-4 rounded-xl border border-[var(--border-default)] bg-[var(--bg-surface-secondary)] p-4 text-sm text-[var(--text-secondary)]">
              <p className="font-medium text-[var(--text-primary)]">
                {manualRecrawlTracking.timedOut
                  ? "ระบบรับคำสั่ง crawl แล้ว แต่ยังไม่พบ run ที่ worker เริ่มทำงาน"
                  : "ระบบรับคำสั่ง crawl แล้ว กำลังรอ worker สร้าง run แรก"}
              </p>
              <p className="mt-2">
                {manualRecrawlTracking.queuedJobCount} งาน /{" "}
                {manualRecrawlTracking.queuedKeywords.length} คำค้น
              </p>
              {manualRecrawlTracking.queuedKeywords.length > 0 ? (
                <p className="mt-1 text-xs text-[var(--text-muted)]">
                  คำค้นที่ส่งแล้ว: {manualRecrawlTracking.queuedKeywords.join(", ")}
                </p>
              ) : null}
              {manualRecrawlTracking.timedOut ? (
                <p className="mt-2 text-xs text-[var(--badge-amber-text)]">
                  หาก worker เริ่มช้ากว่านี้ ให้รีเฟรชอีกครั้งหรือเปิดหน้าการทำงานเพื่อตรวจสอบ
                </p>
              ) : (
                <p className="mt-2 text-xs text-[var(--text-muted)]">
                  ระบบจะดึงสถานะใหม่ทุก 5 วินาทีจนกว่าจะเห็นงานเริ่มทำงานจริง
                </p>
              )}
            </div>
          ) : isRunsError ? (
            <div className="mt-4 rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
              {localizeApiError(runsError, "ไม่สามารถโหลดสถานะการ crawl ล่าสุดได้")}
            </div>
          ) : null}
        </section>
      ) : null}

      {exportError ? (
        <div className="mb-4 rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          {exportError}
        </div>
      ) : null}

      <div className="flex gap-0">
        <aside className="sticky top-0 h-[calc(100vh-140px)] w-[280px] shrink-0 overflow-y-auto border-r border-[var(--border-default)] bg-[var(--bg-surface)] p-5">
          <div className="mb-5 flex items-center justify-between">
            <span className="text-sm font-bold text-[var(--text-primary)]">ตัวกรอง</span>
            <button
              type="button"
              onClick={clearAllFilters}
              className="text-xs font-medium text-[var(--color-primary)] hover:underline"
            >
              ล้างทั้งหมด
            </button>
          </div>

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
                  <StatusBadge state={filter.key} className="px-1.5 py-0 text-[10px]" />
                </label>
              ))}
            </div>
          </div>

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

          <div className="mb-6">
            <h3 className="mb-3 text-sm font-semibold text-[var(--text-primary)]">
              ช่วงงบประมาณ
            </h3>
            <div className="space-y-2">
              <div>
                <label className="mb-1 block text-xs text-[var(--text-muted)]">ขั้นต่ำ (บาท)</label>
                <input
                  type="text"
                  value={budgetMin}
                  onChange={(event) => setBudgetMin(event.target.value)}
                  placeholder="0"
                  className="w-full rounded-lg border border-[var(--border-default)] bg-[var(--bg-surface)] px-3 py-1.5 text-sm text-[var(--text-primary)] placeholder:text-[var(--text-disabled)] focus:border-[var(--color-primary)] focus:outline-none focus:ring-1 focus:ring-[var(--color-primary)]"
                />
              </div>
              <div>
                <label className="mb-1 block text-xs text-[var(--text-muted)]">สูงสุด (บาท)</label>
                <input
                  type="text"
                  value={budgetMax}
                  onChange={(event) => setBudgetMax(event.target.value)}
                  placeholder="100000000"
                  className="w-full rounded-lg border border-[var(--border-default)] bg-[var(--bg-surface)] px-3 py-1.5 text-sm text-[var(--text-primary)] placeholder:text-[var(--text-disabled)] focus:border-[var(--color-primary)] focus:outline-none focus:ring-1 focus:ring-[var(--color-primary)]"
                />
              </div>
            </div>
          </div>

          <div className="mb-6">
            <h3 className="mb-3 text-sm font-semibold text-[var(--text-primary)]">
              TOR เปลี่ยนแปลง
            </h3>
            <label className="flex cursor-pointer items-center gap-2 text-sm text-[var(--text-secondary)]">
              <input
                type="checkbox"
                checked={torChangedOnly}
                onChange={() => setTorChangedOnly((value) => !value)}
                className="h-4 w-4 rounded border-[var(--border-default)] text-[var(--color-primary)] focus:ring-[var(--color-primary)]"
              />
              <span>แสดงเฉพาะ TOR ที่เปลี่ยน</span>
            </label>
          </div>

          <div className="mb-6">
            <h3 className="mb-3 text-sm font-semibold text-[var(--text-primary)]">มีผู้ชนะ</h3>
            <label className="flex cursor-pointer items-center gap-2 text-sm text-[var(--text-secondary)]">
              <input
                type="checkbox"
                checked={winnerOnly}
                onChange={() => setWinnerOnly((value) => !value)}
                className="h-4 w-4 rounded border-[var(--border-default)] text-[var(--color-primary)] focus:ring-[var(--color-primary)]"
              />
              <span>แสดงเฉพาะที่มีผู้ชนะ</span>
            </label>
          </div>
        </aside>

        <div className="min-w-0 flex-1">
          <div className="mb-4 space-y-3">
            <div className="flex items-center gap-4">
              <div className="relative w-[360px]">
                <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-[var(--text-muted)]" />
                <input
                  type="text"
                  value={searchQuery}
                  onChange={(event) => setSearchQuery(event.target.value)}
                  placeholder="ค้นหาโครงการ, หน่วยงาน, เลขที่..."
                  className="w-full rounded-xl border border-[var(--border-default)] bg-[var(--bg-surface)] py-2 pl-10 pr-4 text-sm text-[var(--text-primary)] placeholder:text-[var(--text-disabled)] focus:border-[var(--color-primary)] focus:outline-none focus:ring-1 focus:ring-[var(--color-primary)]"
                />
              </div>

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
                    {tab.label}
                  </button>
                ))}
              </div>

              <span className="ml-auto text-xs text-[var(--text-muted)]">
                แสดง {rangeStart}-{rangeEnd} จาก {totalProjects} โครงการ
              </span>
            </div>
          </div>

          <QueryState
            isLoading={isLoading}
            isError={isError}
            error={error as Error | null}
            isEmpty={!isLoading && !isError && displayProjects.length === 0}
            emptyMessage="ไม่พบโครงการที่ตรงกับตัวกรองนี้"
          >
            <div className="overflow-hidden rounded-2xl bg-[var(--bg-surface)] shadow-[var(--shadow-soft)]">
              <div className="overflow-x-auto">
                <table className="w-full min-w-[1320px] table-fixed">
                  <colgroup>
                    <col className="w-[22rem]" />
                    <col className="w-[16rem]" />
                    <col className="w-[10rem]" />
                    <col className="w-[7rem]" />
                    <col className="w-[8rem]" />
                    <col className="w-[10rem]" />
                    <col className="w-[14rem]" />
                    <col className="w-[6rem]" />
                    <col className="w-[5rem]" />
                    <col className="w-[6rem]" />
                  </colgroup>
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
                      <th className="px-3 py-2.5 text-right text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)] whitespace-nowrap">
                        งบประมาณ
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
                        className="h-10 transition-colors hover:bg-[var(--bg-surface-hover)]"
                      >
                        <td className="px-3 py-2 text-[13px]">
                          <Link
                            href={`/projects/${project.id}`}
                            className="line-clamp-2 font-medium text-[var(--color-primary)] hover:underline"
                            title={project.name}
                          >
                            {project.name}
                          </Link>
                        </td>
                        <td
                          className="px-3 py-2 text-[13px] text-[var(--text-secondary)]"
                          title={project.agency}
                        >
                          <span className="line-clamp-2">{project.agency}</span>
                        </td>
                        <td className="px-3 py-2 font-mono text-[13px] text-[var(--text-secondary)]">
                          {project.projectNumber}
                        </td>
                        <td className="px-3 py-2 text-[13px] text-[var(--text-secondary)]">
                          {PROCUREMENT_TYPE_LABELS[project.type] ?? project.type}
                        </td>
                        <td className="px-3 py-2">
                          <StatusBadge state={project.state} />
                        </td>
                        <td
                          className="px-3 py-2 text-right font-mono text-[13px] tabular-nums text-[var(--text-primary)] whitespace-nowrap"
                          title={formatBudget(project.budgetAmount)}
                        >
                          {formatBudget(project.budgetAmount)}
                        </td>
                        <td
                          className="px-3 py-2 text-[13px] text-[var(--text-secondary)]"
                          title={project.latestStatus}
                        >
                          <span className="line-clamp-2">{project.latestStatus}</span>
                        </td>
                        <td className="px-3 py-2 text-[13px] text-[var(--text-muted)]">
                          {project.lastSeen}
                        </td>
                        <td className="px-3 py-2 text-center text-[13px]">
                          {project.hasWinner ? (
                            <span className="text-green-600">&#10003;</span>
                          ) : (
                            <span className="text-[var(--text-disabled)]">&mdash;</span>
                          )}
                        </td>
                        <td className="px-3 py-2 text-center text-[13px]">
                          {project.hasChangedTor ? (
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

              <div className="flex items-center justify-between border-t border-[var(--border-default)] px-4 py-3">
                <button
                  type="button"
                  disabled={currentPage <= 1}
                  onClick={() => setCurrentPage((page) => Math.max(page - 1, 1))}
                  className="rounded-lg border border-[var(--border-default)] px-3 py-1.5 text-sm text-[var(--text-secondary)] disabled:cursor-not-allowed disabled:opacity-50"
                >
                  ก่อนหน้า
                </button>

                <div className="flex items-center gap-1">
                  {Array.from({ length: totalPages }, (_, index) => index + 1).map((page) => (
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
                    disabled={currentPage >= totalPages || totalProjects === 0}
                    onClick={() =>
                      setCurrentPage((page) => Math.min(page + 1, totalPages))
                    }
                    className="rounded-lg border border-[var(--border-default)] px-3 py-1.5 text-sm text-[var(--text-secondary)] disabled:cursor-not-allowed disabled:opacity-50"
                  >
                    ถัดไป
                  </button>
                  <span className="text-xs text-[var(--text-muted)]">{rowsPerPage} แถว/หน้า</span>
                </div>
              </div>
            </div>
          </QueryState>
        </div>
      </div>
    </>
  );
}
