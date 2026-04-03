"use client";

import { useState } from "react";
import { Activity, Clock, CheckCircle, XCircle, ChevronDown, ChevronRight, RotateCcw } from "lucide-react";
import { PageHeader } from "@/components/layout/page-header";
import { StatusBadge } from "@/components/ui/status-badge";
import { useRuns } from "@/lib/hooks";
import { formatThaiDate } from "@/lib/utils";
import type { RunDetailResponse } from "@/lib/api";

/* ------------------------------------------------------------------ */
/*  Mock Data                                                          */
/* ------------------------------------------------------------------ */

type MockRun = {
  id: string;
  profile: string;
  trigger: string;
  status: string;
  startedAt: string;
  duration: string;
  discovered: number;
  updated: number;
  closed: number;
  errors: number;
};

type MockTask = {
  id: string;
  type: string;
  keyword: string;
  project: string;
  status: string;
  attempts: number;
  duration: string;
};

const MOCK_RUNS: MockRun[] = [
  { id: "RUN-0156", profile: "TOR", trigger: "กำหนดเวลา", status: "running", startedAt: "3 เม.ย. 69 09:00", duration: "12 นาที...", discovered: 3, updated: 1, closed: 0, errors: 0 },
  { id: "RUN-0155", profile: "TOR", trigger: "กำหนดเวลา", status: "succeeded", startedAt: "3 เม.ย. 69 06:00", duration: "45 นาที", discovered: 18, updated: 5, closed: 2, errors: 0 },
  { id: "RUN-0154", profile: "TOE", trigger: "ด้วยตนเอง", status: "succeeded", startedAt: "2 เม.ย. 69 14:30", duration: "32 นาที", discovered: 7, updated: 3, closed: 1, errors: 0 },
  { id: "RUN-0153", profile: "TOR", trigger: "กำหนดเวลา", status: "partial", startedAt: "2 เม.ย. 69 09:00", duration: "51 นาที", discovered: 15, updated: 4, closed: 0, errors: 3 },
  { id: "RUN-0152", profile: "LUE", trigger: "กำหนดเวลา", status: "succeeded", startedAt: "2 เม.ย. 69 06:00", duration: "28 นาที", discovered: 5, updated: 2, closed: 0, errors: 0 },
  { id: "RUN-0151", profile: "TOR", trigger: "ลองใหม่", status: "failed", startedAt: "1 เม.ย. 69 15:00", duration: "5 นาที", discovered: 0, updated: 0, closed: 0, errors: 12 },
  { id: "RUN-0150", profile: "TOR", trigger: "กำหนดเวลา", status: "succeeded", startedAt: "1 เม.ย. 69 09:00", duration: "42 นาที", discovered: 14, updated: 6, closed: 1, errors: 0 },
  { id: "RUN-0149", profile: "TOE", trigger: "กำหนดเวลา", status: "succeeded", startedAt: "1 เม.ย. 69 06:00", duration: "35 นาที", discovered: 9, updated: 3, closed: 0, errors: 0 },
];

const MOCK_TASKS: MockTask[] = [
  { id: "TASK-001", type: "ค้นพบ", keyword: "ระบบสารสนเทศ", project: "—", status: "succeeded", attempts: 1, duration: "8 นาที" },
  { id: "TASK-002", type: "ค้นพบ", keyword: "เทคโนโลยี", project: "—", status: "succeeded", attempts: 1, duration: "12 นาที" },
  { id: "TASK-003", type: "ค้นพบ", keyword: "คลังข้อมูล", project: "—", status: "failed", attempts: 3, duration: "15 นาที" },
  { id: "TASK-004", type: "ตรวจสอบปิด", keyword: "—", project: "EGP-2026-0098", status: "skipped", attempts: 1, duration: "2 วินาที" },
];

/* ------------------------------------------------------------------ */
/*  Component                                                          */
/* ------------------------------------------------------------------ */

function StatCard({ label, value, icon: Icon, colorClass, bgClass }: {
  label: string;
  value: string | number;
  icon: React.ComponentType<{ className?: string }>;
  colorClass: string;
  bgClass: string;
}) {
  return (
    <div className="flex items-center gap-4 rounded-2xl bg-[var(--bg-surface)] p-5 shadow-[var(--shadow-soft)]">
      <div className={`flex size-10 shrink-0 items-center justify-center rounded-xl ${bgClass}`}>
        <Icon className={`size-5 ${colorClass}`} />
      </div>
      <div>
        <p className="text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">{label}</p>
        <p className={`font-mono text-2xl font-bold tabular-nums ${colorClass}`}>{value}</p>
      </div>
    </div>
  );
}

export default function RunsPage() {
  const [expandedRun, setExpandedRun] = useState<string | null>("RUN-0153");
  const [currentPage, setCurrentPage] = useState(1);
  const rowsPerPage = 50;
  const { data: runData } = useRuns({ limit: rowsPerPage, offset: (currentPage - 1) * rowsPerPage });

  // Map API runs to display format, fall back to mock
  const apiRuns: RunDetailResponse[] = runData?.runs ?? [];
  const displayRuns: MockRun[] = apiRuns.length > 0
    ? apiRuns.map((r) => ({
        id: r.run.id.slice(0, 12),
        profile: r.run.profile_id?.slice(0, 8) ?? "TOR",
        trigger: r.run.trigger_type === "schedule" ? "กำหนดเวลา" : r.run.trigger_type === "manual" ? "ด้วยตนเอง" : r.run.trigger_type === "retry" ? "ลองใหม่" : r.run.trigger_type,
        status: r.run.status,
        startedAt: r.run.started_at ? formatThaiDate(r.run.started_at) : "—",
        duration: r.run.started_at && r.run.finished_at
          ? Math.round((new Date(r.run.finished_at).getTime() - new Date(r.run.started_at).getTime()) / 60000) + " นาที"
          : r.run.status === "running" ? "กำลังทำงาน..." : "—",
        discovered: (r.run.summary_json?.projects_seen as number) ?? 0,
        updated: 0,
        closed: 0,
        errors: r.run.error_count,
      }))
    : MOCK_RUNS;
  const totalRunCount = runData?.total ?? 156;

  return (
    <>
      <PageHeader
        title="การทำงานและปฏิบัติการ"
        subtitle="ติดตามการทำงานของ Crawler และจัดการ Tasks"
        actions={
          <>
            <button type="button" className="flex items-center gap-1.5 rounded-xl border border-[var(--border-default)] px-4 py-2.5 text-sm font-medium text-[var(--text-secondary)] hover:bg-[var(--bg-surface-hover)]">
              <RotateCcw className="size-4" /> รีเฟรช
            </button>
            <button type="button" className="rounded-xl bg-primary px-4 py-2.5 text-sm font-medium text-white hover:bg-primary-hover">
              สร้าง Run ใหม่
            </button>
          </>
        }
      />

      {/* Stat Cards */}
      <div className="grid grid-cols-1 gap-6 sm:grid-cols-2 md:grid-cols-4">
        <StatCard label="Run ทั้งหมด" value={totalRunCount} icon={Activity} colorClass="text-[var(--text-secondary)]" bgClass="bg-[var(--badge-gray-bg)]" />
        <StatCard label="กำลังทำงาน" value={displayRuns.filter((r) => r.status === "running").length} icon={Clock} colorClass="text-[var(--badge-indigo-text)]" bgClass="bg-[var(--badge-indigo-bg)]" />
        <StatCard label="สำเร็จ" value={displayRuns.filter((r) => r.status === "succeeded").length} icon={CheckCircle} colorClass="text-[var(--badge-green-text)]" bgClass="bg-[var(--badge-green-bg)]" />
        <StatCard label="ล้มเหลว" value={displayRuns.filter((r) => r.status === "failed").length} icon={XCircle} colorClass="text-[var(--badge-red-text)]" bgClass="bg-[var(--badge-red-bg)]" />
      </div>

      {/* Runs Table */}
      <div className="mt-6 rounded-2xl bg-[var(--bg-surface)] shadow-[var(--shadow-soft)]">
        <div className="border-b border-[var(--border-default)] px-6 py-4">
          <h2 className="text-lg font-bold text-[var(--text-primary)]">ประวัติการทำงาน</h2>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-[13px]">
            <thead>
              <tr className="bg-[var(--bg-surface-secondary)]">
                <th className="w-8 px-3 py-2" />
                <th className="px-3 py-2 text-left text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">Run ID</th>
                <th className="px-3 py-2 text-left text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">โปรไฟล์</th>
                <th className="px-3 py-2 text-left text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">ทริกเกอร์</th>
                <th className="px-3 py-2 text-left text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">สถานะ</th>
                <th className="px-3 py-2 text-left text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">เริ่มเมื่อ</th>
                <th className="px-3 py-2 text-left text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">ระยะเวลา</th>
                <th className="px-3 py-2 text-right text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">ค้นพบ</th>
                <th className="px-3 py-2 text-right text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">อัปเดต</th>
                <th className="px-3 py-2 text-right text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">ปิด</th>
                <th className="px-3 py-2 text-right text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">ข้อผิดพลาด</th>
              </tr>
            </thead>
            <tbody>
              {displayRuns.map((run) => (
                <>
                  <tr
                    key={run.id}
                    className="h-10 cursor-pointer border-b border-[var(--border-light)] hover:bg-[var(--bg-surface-hover)]"
                    onClick={() => setExpandedRun(expandedRun === run.id ? null : run.id)}
                  >
                    <td className="px-3 py-2 text-[var(--text-muted)]">
                      {expandedRun === run.id ? <ChevronDown className="size-4" /> : <ChevronRight className="size-4" />}
                    </td>
                    <td className="px-3 py-2 font-mono font-medium">{run.id}</td>
                    <td className="px-3 py-2">{run.profile}</td>
                    <td className="px-3 py-2">{run.trigger}</td>
                    <td className="px-3 py-2"><StatusBadge state={run.status} variant="run" /></td>
                    <td className="px-3 py-2 text-[var(--text-muted)]">{run.startedAt}</td>
                    <td className="px-3 py-2 font-mono tabular-nums">{run.duration}</td>
                    <td className="px-3 py-2 text-right font-mono tabular-nums">{run.discovered}</td>
                    <td className="px-3 py-2 text-right font-mono tabular-nums">{run.updated}</td>
                    <td className="px-3 py-2 text-right font-mono tabular-nums">{run.closed}</td>
                    <td className={`px-3 py-2 text-right font-mono tabular-nums ${run.errors > 0 ? "font-semibold text-[var(--badge-red-text)]" : ""}`}>{run.errors}</td>
                  </tr>
                  {expandedRun === run.id && (
                    <tr key={`${run.id}-detail`}>
                      <td colSpan={11} className="bg-[var(--bg-surface-secondary)] px-6 py-4">
                        <p className="mb-3 text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">Tasks ใน {run.id}</p>
                        <table className="w-full text-[13px]">
                          <thead>
                            <tr className="border-b border-[var(--border-default)]">
                              <th className="px-3 py-1.5 text-left text-xs font-semibold text-[var(--text-muted)]">Task ID</th>
                              <th className="px-3 py-1.5 text-left text-xs font-semibold text-[var(--text-muted)]">ประเภท</th>
                              <th className="px-3 py-1.5 text-left text-xs font-semibold text-[var(--text-muted)]">คำค้น</th>
                              <th className="px-3 py-1.5 text-left text-xs font-semibold text-[var(--text-muted)]">โครงการ</th>
                              <th className="px-3 py-1.5 text-left text-xs font-semibold text-[var(--text-muted)]">สถานะ</th>
                              <th className="px-3 py-1.5 text-right text-xs font-semibold text-[var(--text-muted)]">ความพยายาม</th>
                              <th className="px-3 py-1.5 text-left text-xs font-semibold text-[var(--text-muted)]">ระยะเวลา</th>
                            </tr>
                          </thead>
                          <tbody>
                            {MOCK_TASKS.map((task) => (
                              <tr key={task.id} className="border-b border-[var(--border-light)]">
                                <td className="px-3 py-1.5 font-mono">{task.id}</td>
                                <td className="px-3 py-1.5">{task.type}</td>
                                <td className="px-3 py-1.5">{task.keyword}</td>
                                <td className="px-3 py-1.5 font-mono">{task.project}</td>
                                <td className="px-3 py-1.5"><StatusBadge state={task.status} variant="task" /></td>
                                <td className="px-3 py-1.5 text-right font-mono tabular-nums">{task.attempts}</td>
                                <td className="px-3 py-1.5 font-mono tabular-nums">{task.duration}</td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                        <div className="mt-3 flex items-center gap-3">
                          <button type="button" className="text-sm font-medium text-primary hover:text-primary-hover">ดูรายละเอียดเต็ม →</button>
                          {run.errors > 0 && (
                            <button type="button" className="flex items-center gap-1 rounded-lg border border-red-300 px-3 py-1.5 text-sm font-medium text-red-600 hover:bg-red-50">
                              <RotateCcw className="size-3.5" /> ลองใหม่ Tasks ที่ล้มเหลว
                            </button>
                          )}
                        </div>
                      </td>
                    </tr>
                  )}
                </>
              ))}
            </tbody>
          </table>
        </div>

        {/* Pagination */}
        <div className="flex items-center justify-between border-t border-[var(--border-default)] px-6 py-3">
          <span className="text-sm text-[var(--text-muted)]">แสดง 1-8 จาก 156 รายการ</span>
          <div className="flex items-center gap-1">
            <button type="button" className="rounded-lg px-3 py-1.5 text-sm text-[var(--text-disabled)]" disabled>ก่อนหน้า</button>
            <button type="button" className="size-8 rounded-lg bg-primary text-sm font-semibold text-white">1</button>
            <button type="button" className="size-8 rounded-lg text-sm text-[var(--text-secondary)] hover:bg-[var(--bg-surface-hover)]">2</button>
            <button type="button" className="size-8 rounded-lg text-sm text-[var(--text-secondary)] hover:bg-[var(--bg-surface-hover)]">3</button>
            <button type="button" className="size-8 rounded-lg text-sm text-[var(--text-secondary)] hover:bg-[var(--bg-surface-hover)]">4</button>
            <button type="button" className="size-8 rounded-lg text-sm text-[var(--text-secondary)] hover:bg-[var(--bg-surface-hover)]">5</button>
            <button type="button" className="rounded-lg px-3 py-1.5 text-sm text-[var(--text-secondary)] hover:bg-[var(--bg-surface-hover)]">ถัดไป</button>
          </div>
          <span className="text-sm text-[var(--text-muted)]">50 แถว/หน้า</span>
        </div>
      </div>
    </>
  );
}
