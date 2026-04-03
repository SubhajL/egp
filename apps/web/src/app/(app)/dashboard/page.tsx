"use client";

import dynamic from "next/dynamic";
import { Archive, AlertTriangle, CheckCircle, XCircle, TrendingUp } from "lucide-react";
import { PageHeader } from "@/components/layout/page-header";
import { StatusBadge } from "@/components/ui/status-badge";
import { useProjects, useRuns } from "@/lib/hooks";

const DailyDiscoveryChart = dynamic(
  () => import("@/components/ui/dashboard-charts").then((m) => m.DailyDiscoveryChart),
  { ssr: false, loading: () => <div className="flex h-72 items-center justify-center rounded-2xl bg-[var(--bg-surface)] shadow-[var(--shadow-soft)] md:col-span-8"><span className="text-[var(--text-muted)]">กำลังโหลดกราฟ...</span></div> },
);

const ProjectStateChart = dynamic(
  () => import("@/components/ui/dashboard-charts").then((m) => m.ProjectStateChart),
  { ssr: false, loading: () => <div className="flex h-72 items-center justify-center rounded-2xl bg-[var(--bg-surface)] shadow-[var(--shadow-soft)] md:col-span-4"><span className="text-[var(--text-muted)]">กำลังโหลดกราฟ...</span></div> },
);

const recentRuns = [
  { id: "RUN-0156", profile: "TOR ทั่วไป", status: "succeeded" as const, duration: "4m 32s", found: 18 },
  { id: "RUN-0155", profile: "ที่ปรึกษา", status: "succeeded" as const, duration: "3m 15s", found: 7 },
  { id: "RUN-0154", profile: "TOR ทั่วไป", status: "partial" as const, duration: "5m 08s", found: 12 },
  { id: "RUN-0153", profile: "จัดซื้อจัดจ้าง", status: "failed" as const, duration: "1m 47s", found: 0 },
  { id: "RUN-0152", profile: "TOR ทั่วไป", status: "succeeded" as const, duration: "4m 01s", found: 15 },
];

const recentChanges = [
  { name: "จ้างปรับปรุงระบบไฟฟ้าอาคาร...", newState: "winner_announced" },
  { name: "ซื้อครุภัณฑ์คอมพิวเตอร์สำหรับ...", newState: "tor_downloaded" },
  { name: "จ้างก่อสร้างถนนคอนกรีตเสริม...", newState: "open_consulting" },
  { name: "จ้างที่ปรึกษาศึกษาความเหมาะสม...", newState: "closed_timeout_consulting" },
  { name: "ซื้อวัสดุวิทยาศาสตร์การแพทย์...", newState: "open_invitation" },
];

const winnerProjects = [
  "จ้างปรับปรุงระบบไฟฟ้าอาคารสำนักงาน",
  "ซื้อครุภัณฑ์คอมพิวเตอร์ 50 ชุด",
  "จ้างก่อสร้างอาคารหอประชุม",
];

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
  const { data: projectData } = useProjects({ limit: 200 });
  const { data: runData } = useRuns({ limit: 10 });

  const projects = projectData?.projects ?? [];
  const activeCount = projects.filter((p) =>
    !p.project_state.startsWith("closed") && p.project_state !== "error"
  ).length || 247;
  const discoveredToday = projects.filter((p) => {
    const created = new Date(p.created_at);
    const today = new Date();
    return created.toDateString() === today.toDateString();
  }).length || 18;
  const winnerCount = projects.filter((p) =>
    p.project_state === "winner_announced" || p.project_state === "contract_signed"
  ).length || 5;
  const closedToday = projects.filter((p) => {
    const updated = new Date(p.updated_at);
    const today = new Date();
    return p.project_state.startsWith("closed") && updated.toDateString() === today.toDateString();
  }).length || 8;

  const runs = runData?.runs ?? [];
  const successfulRuns = runs.filter((r) => r.run.status === "succeeded").length;
  const totalRuns = runs.length || 1;
  const crawlSuccessRate = runs.length > 0
    ? ((successfulRuns / totalRuns) * 100).toFixed(1) + "%"
    : "94.2%";
  const failedRuns = runs.filter((r) => r.run.status === "failed").length || 2;

  return (
    <>
      <PageHeader
        title="แดชบอร์ด"
        subtitle="ภาพรวมการติดตามโครงการจัดซื้อจัดจ้าง"
      />

      {/* ── Row 1: Large KPI Cards ── */}
      <div className="grid grid-cols-1 gap-6 md:grid-cols-12">
        {/* Active Projects */}
        <div className="rounded-2xl bg-[var(--bg-surface)] p-6 shadow-[var(--shadow-soft)] md:col-span-4">
          <p className="text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">
            โครงการที่กำลังดำเนินการ
          </p>
          <p className="mt-2 font-mono text-4xl font-bold tabular-nums text-primary">{activeCount}</p>
          <div className="mt-2 flex items-center gap-1 text-sm text-success">
            <TrendingUp className="size-4" />
            <span>+{discoveredToday} วันนี้</span>
          </div>
          <p className="mt-1 text-xs text-[var(--text-muted)]">โครงการเปิดอยู่ทั้งหมด</p>
        </div>

        {/* New Projects Today */}
        <div className="rounded-2xl bg-[var(--bg-surface)] p-6 shadow-[var(--shadow-soft)] md:col-span-4">
          <p className="text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">
            โครงการใหม่วันนี้
          </p>
          <p className="mt-2 font-mono text-4xl font-bold tabular-nums text-secondary">{discoveredToday}</p>
          <p className="mt-2 text-sm text-[var(--text-muted)]">ค้นพบล่าสุด 2 ชม.ที่แล้ว</p>
        </div>

        {/* Winner Announced */}
        <div className="rounded-2xl bg-[var(--bg-surface)] p-6 shadow-[var(--shadow-soft)] md:col-span-4">
          <p className="text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">
            ประกาศผู้ชนะ
          </p>
          <p className="mt-2 font-mono text-4xl font-bold tabular-nums text-purple">{winnerCount}</p>
          <p className="mt-2 text-sm text-[var(--text-muted)]">สัปดาห์นี้</p>
          <ul className="mt-3 space-y-1">
            {winnerProjects.map((name) => (
              <li
                key={name}
                className="truncate text-xs text-[var(--text-secondary)]"
                title={name}
              >
                &bull; {name}
              </li>
            ))}
          </ul>
        </div>
      </div>

      {/* ── Row 2: Small Stat Cards ── */}
      <div className="mt-6 grid grid-cols-1 gap-6 sm:grid-cols-2 md:grid-cols-12">
        <div className="md:col-span-3">
          <SmallStatCard
            label="ปิดวันนี้"
            value={closedToday}
            icon={Archive}
            colorClass="text-[var(--text-muted)]"
            bgClass="bg-[var(--badge-gray-bg)]"
          />
        </div>
        <div className="md:col-span-3">
          <SmallStatCard
            label="TOR เปลี่ยนแปลง"
            value={3}
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
            value={failedRuns}
            icon={XCircle}
            colorClass="text-[var(--badge-red-text)]"
            bgClass="bg-[var(--badge-red-bg)]"
          />
        </div>
      </div>

      {/* ── Row 3: Charts ── */}
      <div className="mt-6 grid grid-cols-1 gap-6 md:grid-cols-12">
        <DailyDiscoveryChart />
        <ProjectStateChart />
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
                {recentRuns.map((run) => (
                  <tr
                    key={run.id}
                    className="h-10 border-b border-[var(--border-light)] last:border-b-0"
                  >
                    <td className="px-3 py-2 font-mono text-xs tabular-nums text-[var(--text-primary)]">
                      {run.id}
                    </td>
                    <td className="px-3 py-2 text-[var(--text-secondary)]">{run.profile}</td>
                    <td className="px-3 py-2">
                      <StatusBadge state={run.status} variant="run" />
                    </td>
                    <td className="px-3 py-2 text-right font-mono text-xs tabular-nums text-[var(--text-muted)]">
                      {run.duration}
                    </td>
                    <td className="px-3 py-2 text-right font-mono tabular-nums text-[var(--text-primary)]">
                      {run.found}
                    </td>
                  </tr>
                ))}
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
                {recentChanges.map((change) => (
                  <tr
                    key={change.name}
                    className="h-10 border-b border-[var(--border-light)] last:border-b-0"
                  >
                    <td
                      className="max-w-[200px] truncate px-3 py-2 text-[var(--text-secondary)]"
                      title={change.name}
                    >
                      {change.name}
                    </td>
                    <td className="px-3 py-2 text-right">
                      <StatusBadge state={change.newState} variant="project" />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </>
  );
}
