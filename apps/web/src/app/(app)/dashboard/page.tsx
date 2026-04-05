"use client";

import dynamic from "next/dynamic";
import { Archive, AlertTriangle, CheckCircle, XCircle, TrendingUp } from "lucide-react";
import { PageHeader } from "@/components/layout/page-header";
import { StatusBadge } from "@/components/ui/status-badge";
import type { DashboardSummaryResponse } from "@/lib/api";
import { useDashboardSummary } from "@/lib/hooks";
import { formatBudget, formatRelativeTime } from "@/lib/utils";

const DailyDiscoveryChart = dynamic(
  () => import("@/components/ui/dashboard-charts").then((m) => m.DailyDiscoveryChart),
  { ssr: false, loading: () => <div className="flex h-72 items-center justify-center rounded-2xl bg-[var(--bg-surface)] shadow-[var(--shadow-soft)] md:col-span-8"><span className="text-[var(--text-muted)]">กำลังโหลดกราฟ...</span></div> },
);

const ProjectStateChart = dynamic(
  () => import("@/components/ui/dashboard-charts").then((m) => m.ProjectStateChart),
  { ssr: false, loading: () => <div className="flex h-72 items-center justify-center rounded-2xl bg-[var(--bg-surface)] shadow-[var(--shadow-soft)] md:col-span-4"><span className="text-[var(--text-muted)]">กำลังโหลดกราฟ...</span></div> },
);

const EMPTY_DASHBOARD_SUMMARY: DashboardSummaryResponse = {
  kpis: {
    active_projects: 0,
    discovered_today: 0,
    winner_projects_this_week: 0,
    closed_today: 0,
    changed_tor_projects: 0,
    crawl_success_rate_percent: 0,
    failed_runs_recent: 0,
    crawl_success_window_runs: 0,
  },
  recent_runs: [],
  recent_changes: [],
  winner_projects: [],
  daily_discovery: [],
  project_state_breakdown: [
    { bucket: "discovered", count: 0 },
    { bucket: "open_invitation", count: 0 },
    { bucket: "open_consulting", count: 0 },
    { bucket: "tor_downloaded", count: 0 },
    { bucket: "winner", count: 0 },
    { bucket: "closed", count: 0 },
  ],
  cost_summary: {
    window_days: 30,
    currency: "THB",
    estimated_total_thb: "0.00",
    crawl: {
      estimated_cost_thb: "0.00",
      run_count: 0,
      task_count: 0,
      failed_run_count: 0,
    },
    storage: {
      estimated_cost_thb: "0.00",
      document_count: 0,
      total_bytes: 0,
    },
    notifications: {
      estimated_cost_thb: "0.00",
      sent_count: 0,
      failed_webhook_delivery_count: 0,
    },
    payments: {
      estimated_cost_thb: "0.00",
      billing_record_count: 0,
      payment_request_count: 0,
      collected_amount_thb: "0.00",
    },
  },
};

function formatRunDuration(startedAt: string | null, finishedAt: string | null, status: string): string {
  if (startedAt && finishedAt) {
    const diffMs = new Date(finishedAt).getTime() - new Date(startedAt).getTime();
    if (diffMs < 60000) {
      return `${Math.max(1, Math.round(diffMs / 1000))} วินาที`;
    }
    const totalMinutes = Math.round(diffMs / 60000);
    const hours = Math.floor(totalMinutes / 60);
    const minutes = totalMinutes % 60;
    if (hours > 0) {
      return `${hours} ชม. ${minutes} นาที`;
    }
    return `${totalMinutes} นาที`;
  }
  if (status === "running") {
    return "กำลังทำงาน...";
  }
  return "—";
}

/* ------------------------------------------------------------------ */
/*  Stat Card Components                                               */
/* ------------------------------------------------------------------ */

function SmallStatCard({
  label,
  value,
  icon: Icon,
  colorClass,
  bgClass,
}: {
  label: string;
  value: string | number;
  icon: React.ComponentType<{ className?: string }>;
  colorClass: string;
  bgClass: string;
}) {
  return (
    <div className="flex items-center gap-4 rounded-2xl bg-[var(--bg-surface)] p-6 shadow-[var(--shadow-soft)]">
      <div className={`flex size-11 shrink-0 items-center justify-center rounded-xl ${bgClass}`}>
        <Icon className={`size-5 ${colorClass}`} />
      </div>
      <div className="min-w-0">
        <p className="truncate text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">
          {label}
        </p>
        <p className={`mt-0.5 font-mono text-2xl font-bold tabular-nums ${colorClass}`}>
          {value}
        </p>
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Dashboard Page                                                     */
/* ------------------------------------------------------------------ */

export default function DashboardPage() {
  const { data, error, isLoading } = useDashboardSummary();
  const summary = data ?? EMPTY_DASHBOARD_SUMMARY;
  const kpis = summary.kpis;
  const crawlSuccessRate = `${kpis.crawl_success_rate_percent.toFixed(1)}%`;
  const costSummary = summary.cost_summary;

  return (
    <>
      <PageHeader
        title="แดชบอร์ด"
        subtitle="ภาพรวมการติดตามโครงการจัดซื้อจัดจ้าง"
      />
      {error ? (
        <div className="mb-6 rounded-2xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          โหลดข้อมูลแดชบอร์ดไม่สำเร็จ: {error instanceof Error ? error.message : "unknown error"}
        </div>
      ) : null}

      {/* ── Row 1: Large KPI Cards ── */}
      <div className="grid grid-cols-1 gap-6 md:grid-cols-12">
        {/* Active Projects */}
        <div className="rounded-2xl bg-[var(--bg-surface)] p-6 shadow-[var(--shadow-soft)] md:col-span-4">
          <p className="text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">
            โครงการที่กำลังดำเนินการ
          </p>
          <p className="mt-2 font-mono text-4xl font-bold tabular-nums text-primary">{kpis.active_projects}</p>
          <div className="mt-2 flex items-center gap-1 text-sm text-success">
            <TrendingUp className="size-4" />
            <span>+{kpis.discovered_today} วันนี้</span>
          </div>
          <p className="mt-1 text-xs text-[var(--text-muted)]">โครงการเปิดอยู่ทั้งหมด</p>
        </div>

        {/* New Projects Today */}
        <div className="rounded-2xl bg-[var(--bg-surface)] p-6 shadow-[var(--shadow-soft)] md:col-span-4">
          <p className="text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">
            โครงการใหม่วันนี้
          </p>
          <p className="mt-2 font-mono text-4xl font-bold tabular-nums text-secondary">{kpis.discovered_today}</p>
          <p className="mt-2 text-sm text-[var(--text-muted)]">
            {summary.recent_changes[0]
              ? `อัปเดตล่าสุด ${formatRelativeTime(summary.recent_changes[0].last_changed_at)} ที่แล้ว`
              : isLoading
                ? "กำลังโหลดข้อมูลล่าสุด"
                : "ยังไม่มีโครงการใหม่ในช่วงนี้"}
          </p>
        </div>

        {/* Winner Announced */}
        <div className="rounded-2xl bg-[var(--bg-surface)] p-6 shadow-[var(--shadow-soft)] md:col-span-4">
          <p className="text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">
            ประกาศผู้ชนะ
          </p>
          <p className="mt-2 font-mono text-4xl font-bold tabular-nums text-purple">{kpis.winner_projects_this_week}</p>
          <p className="mt-2 text-sm text-[var(--text-muted)]">สัปดาห์นี้</p>
          <ul className="mt-3 space-y-1">
            {summary.winner_projects.length > 0 ? summary.winner_projects.map((winner) => (
              <li
                key={winner.project_id}
                className="truncate text-xs text-[var(--text-secondary)]"
                title={winner.project_name}
              >
                &bull; {winner.project_name}
              </li>
            )) : (
              <li className="text-xs text-[var(--text-muted)]">ยังไม่มีโครงการที่ประกาศผู้ชนะในช่วงนี้</li>
            )}
          </ul>
        </div>
      </div>

      {/* ── Row 2: Small Stat Cards ── */}
      <div className="mt-6 grid grid-cols-1 gap-6 sm:grid-cols-2 md:grid-cols-12">
        <div className="md:col-span-3">
          <SmallStatCard
            label="ปิดวันนี้"
            value={kpis.closed_today}
            icon={Archive}
            colorClass="text-[var(--text-muted)]"
            bgClass="bg-[var(--badge-gray-bg)]"
          />
        </div>
        <div className="md:col-span-3">
          <SmallStatCard
            label="TOR เปลี่ยนแปลง"
            value={kpis.changed_tor_projects}
            icon={AlertTriangle}
            colorClass="text-[var(--badge-amber-text)]"
            bgClass="bg-[var(--badge-amber-bg)]"
          />
        </div>
        <div className="md:col-span-3">
          <SmallStatCard
            label="Crawl สำเร็จ"
            value={crawlSuccessRate}
            icon={CheckCircle}
            colorClass="text-[var(--badge-green-text)]"
            bgClass="bg-[var(--badge-green-bg)]"
          />
        </div>
        <div className="md:col-span-3">
          <SmallStatCard
            label="ล้มเหลว"
            value={kpis.failed_runs_recent}
            icon={XCircle}
            colorClass="text-[var(--badge-red-text)]"
            bgClass="bg-[var(--badge-red-bg)]"
          />
        </div>
      </div>

      <div className="mt-6 rounded-3xl bg-[linear-gradient(135deg,#0f172a_0%,#1e293b_100%)] p-6 text-white shadow-[var(--shadow-soft)]">
        <div className="flex flex-col gap-3 md:flex-row md:items-end md:justify-between">
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.2em] text-slate-300">
              Cost Observatory
            </p>
            <h2 className="mt-2 text-3xl font-bold">ต้นทุนเชิงปฏิบัติการย้อนหลัง {costSummary.window_days} วัน</h2>
            <p className="mt-2 max-w-2xl text-sm text-slate-300">
              สรุปตัวขับต้นทุนหลักจากการ crawl, การเก็บเอกสาร, การแจ้งเตือน และขั้นตอนการชำระเงิน เพื่อให้ทีมปฏิบัติการเห็นจุดที่ต้องควบคุมก่อนต้นทุนสูงเกินแผน
            </p>
          </div>
          <div className="rounded-2xl bg-white/10 px-5 py-4 backdrop-blur">
            <p className="text-xs uppercase tracking-[0.2em] text-slate-300">Estimated Total</p>
            <p className="mt-2 text-3xl font-bold">{formatBudget(costSummary.estimated_total_thb)}</p>
          </div>
        </div>

        <div className="mt-6 grid gap-4 md:grid-cols-4">
          <div className="rounded-2xl bg-white/8 p-4">
            <p className="text-xs uppercase tracking-[0.2em] text-slate-300">Crawl</p>
            <p className="mt-2 text-2xl font-bold">{formatBudget(costSummary.crawl.estimated_cost_thb)}</p>
            <p className="mt-3 text-sm text-slate-200">
              {costSummary.crawl.run_count} runs, {costSummary.crawl.task_count} tasks, ล้มเหลว {costSummary.crawl.failed_run_count}
            </p>
          </div>
          <div className="rounded-2xl bg-white/8 p-4">
            <p className="text-xs uppercase tracking-[0.2em] text-slate-300">Storage</p>
            <p className="mt-2 text-2xl font-bold">{formatBudget(costSummary.storage.estimated_cost_thb)}</p>
            <p className="mt-3 text-sm text-slate-200">
              {costSummary.storage.document_count} เอกสาร, {costSummary.storage.total_bytes.toLocaleString()} bytes
            </p>
          </div>
          <div className="rounded-2xl bg-white/8 p-4">
            <p className="text-xs uppercase tracking-[0.2em] text-slate-300">Notifications</p>
            <p className="mt-2 text-2xl font-bold">{formatBudget(costSummary.notifications.estimated_cost_thb)}</p>
            <p className="mt-3 text-sm text-slate-200">
              ส่งแล้ว {costSummary.notifications.sent_count}, webhook fail {costSummary.notifications.failed_webhook_delivery_count}
            </p>
          </div>
          <div className="rounded-2xl bg-white/8 p-4">
            <p className="text-xs uppercase tracking-[0.2em] text-slate-300">Payments</p>
            <p className="mt-2 text-2xl font-bold">{formatBudget(costSummary.payments.estimated_cost_thb)}</p>
            <p className="mt-3 text-sm text-slate-200">
              {costSummary.payments.billing_record_count} billing records, {costSummary.payments.payment_request_count} payment requests
            </p>
          </div>
        </div>
      </div>

      {/* ── Row 3: Charts ── */}
      <div className="mt-6 grid grid-cols-1 gap-6 md:grid-cols-12">
        <DailyDiscoveryChart points={summary.daily_discovery} />
        <ProjectStateChart breakdown={summary.project_state_breakdown} />
      </div>

      {/* ── Row 4: Tables ── */}
      <div className="mt-6 grid grid-cols-1 gap-6 md:grid-cols-12">
        {/* Recent Runs */}
        <div className="rounded-2xl bg-[var(--bg-surface)] p-6 shadow-[var(--shadow-soft)] md:col-span-7">
          <h3 className="mb-4 text-sm font-semibold text-[var(--text-primary)]">
            การทำงานล่าสุด
          </h3>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="bg-[var(--bg-surface-secondary)]">
                  <th className="rounded-l-lg px-3 py-2 text-left text-xs font-semibold uppercase text-[var(--text-muted)]">
                    ID
                  </th>
                  <th className="px-3 py-2 text-left text-xs font-semibold uppercase text-[var(--text-muted)]">
                    โปรไฟล์
                  </th>
                  <th className="px-3 py-2 text-left text-xs font-semibold uppercase text-[var(--text-muted)]">
                    สถานะ
                  </th>
                  <th className="px-3 py-2 text-right text-xs font-semibold uppercase text-[var(--text-muted)]">
                    ระยะเวลา
                  </th>
                  <th className="rounded-r-lg px-3 py-2 text-right text-xs font-semibold uppercase text-[var(--text-muted)]">
                    ค้นพบ
                  </th>
                </tr>
              </thead>
              <tbody>
                {summary.recent_runs.length > 0 ? summary.recent_runs.map((run) => (
                  <tr
                    key={run.id}
                    className="h-10 border-b border-[var(--border-light)] last:border-b-0"
                  >
                    <td className="px-3 py-2 font-mono text-xs tabular-nums text-[var(--text-primary)]">
                      {run.id.slice(0, 12)}
                    </td>
                    <td className="px-3 py-2 text-[var(--text-secondary)]">
                      {run.profile_id ? run.profile_id.slice(0, 8) : "ค่าเริ่มต้น"}
                    </td>
                    <td className="px-3 py-2">
                      <StatusBadge state={run.status} variant="run" />
                    </td>
                    <td className="px-3 py-2 text-right font-mono text-xs tabular-nums text-[var(--text-muted)]">
                      {formatRunDuration(run.started_at, run.finished_at, run.status)}
                    </td>
                    <td className="px-3 py-2 text-right font-mono tabular-nums text-[var(--text-primary)]">
                      {run.discovered_projects}
                    </td>
                  </tr>
                )) : (
                  <tr>
                    <td colSpan={5} className="px-3 py-6 text-center text-sm text-[var(--text-muted)]">
                      {isLoading ? "กำลังโหลดการทำงานล่าสุด..." : "ยังไม่มีประวัติการทำงาน"}
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </div>

        {/* Recent Changes */}
        <div className="rounded-2xl bg-[var(--bg-surface)] p-6 shadow-[var(--shadow-soft)] md:col-span-5">
          <h3 className="mb-4 text-sm font-semibold text-[var(--text-primary)]">
            โครงการเปลี่ยนแปลงล่าสุด
          </h3>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="bg-[var(--bg-surface-secondary)]">
                  <th className="rounded-l-lg px-3 py-2 text-left text-xs font-semibold uppercase text-[var(--text-muted)]">
                    ชื่อโครงการ
                  </th>
                  <th className="rounded-r-lg px-3 py-2 text-right text-xs font-semibold uppercase text-[var(--text-muted)]">
                    สถานะใหม่
                  </th>
                </tr>
              </thead>
              <tbody>
                {summary.recent_changes.length > 0 ? summary.recent_changes.map((change) => (
                  <tr
                    key={change.project_id}
                    className="h-10 border-b border-[var(--border-light)] last:border-b-0"
                  >
                    <td
                      className="max-w-[200px] truncate px-3 py-2 text-[var(--text-secondary)]"
                      title={change.project_name}
                    >
                      {change.project_name}
                    </td>
                    <td className="px-3 py-2 text-right">
                      <StatusBadge state={change.project_state} variant="project" />
                    </td>
                  </tr>
                )) : (
                  <tr>
                    <td colSpan={2} className="px-3 py-6 text-center text-sm text-[var(--text-muted)]">
                      {isLoading ? "กำลังโหลดการเปลี่ยนแปลง..." : "ยังไม่มีการเปลี่ยนแปลงล่าสุด"}
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </>
  );
}
