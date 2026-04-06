"use client";

import type {
  DashboardDailyDiscoveryPoint,
  DashboardStateBreakdownPoint,
} from "@/lib/api";
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  PieChart,
  Pie,
  Cell,
} from "recharts";

const tooltipStyle = {
  backgroundColor: "var(--bg-surface)",
  border: "1px solid var(--border-default)",
  borderRadius: "12px",
  fontSize: "13px",
  boxShadow: "var(--shadow-md)",
};

const STATE_BUCKET_STYLE: Record<string, { name: string; color: string }> = {
  discovered: { name: "ค้นพบใหม่", color: "#1D4ED8" },
  open_invitation: { name: "เปิดรับข้อเสนอ", color: "#0F766E" },
  open_consulting: { name: "เปิดรับที่ปรึกษา", color: "#0284C7" },
  tor_downloaded: { name: "ดาวน์โหลด TOR", color: "#15803D" },
  winner: { name: "ประกาศผู้ชนะ", color: "#7C3AED" },
  closed: { name: "ปิดแล้ว", color: "#64748B" },
};

function formatChartDate(value: string): string {
  return new Intl.DateTimeFormat("th-TH", {
    day: "numeric",
    month: "short",
  }).format(new Date(value));
}

type DailyDiscoveryChartProps = {
  points: DashboardDailyDiscoveryPoint[];
};

type ProjectStateChartProps = {
  breakdown: DashboardStateBreakdownPoint[];
};

export function DailyDiscoveryChart({ points }: DailyDiscoveryChartProps) {
  const chartData = points.map((point) => ({
    ...point,
    label: formatChartDate(point.date),
  }));
  return (
    <div className="min-w-0 rounded-2xl bg-[var(--bg-surface)] p-6 shadow-[var(--shadow-soft)] md:col-span-8">
      <h3 className="text-sm font-semibold text-[var(--text-primary)]">โครงการค้นพบรายวัน</h3>
      <div className="mt-4 h-72 min-w-0 w-full">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={chartData} margin={{ top: 4, right: 4, bottom: 0, left: -20 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="var(--border-light)" vertical={false} />
            <XAxis dataKey="label" tick={{ fontSize: 11, fill: "var(--text-muted)" }} axisLine={false} tickLine={false} />
            <YAxis tick={{ fontSize: 11, fill: "var(--text-muted)" }} axisLine={false} tickLine={false} />
            <Tooltip
              contentStyle={tooltipStyle}
              labelStyle={{ color: "var(--text-primary)", fontWeight: 600 }}
              formatter={(value: unknown) => [`${value} โครงการ`, "จำนวน"]}
            />
            <Bar dataKey="count" fill="#4338CA" radius={[6, 6, 0, 0]} maxBarSize={40} />
          </BarChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}

export function ProjectStateChart({ breakdown }: ProjectStateChartProps) {
  const chartData = breakdown.map((point) => ({
    name: STATE_BUCKET_STYLE[point.bucket]?.name ?? point.bucket,
    value: point.count,
    color: STATE_BUCKET_STYLE[point.bucket]?.color ?? "#64748B",
  }));
  return (
    <div className="min-w-0 rounded-2xl bg-[var(--bg-surface)] p-6 shadow-[var(--shadow-soft)] md:col-span-4">
      <h3 className="text-sm font-semibold text-[var(--text-primary)]">สถานะโครงการ</h3>
      <div className="mt-4 h-72 min-w-0 w-full">
        <ResponsiveContainer width="100%" height="100%">
          <PieChart>
            <Pie
              data={chartData}
              cx="50%"
              cy="50%"
              innerRadius={60}
              outerRadius={90}
              paddingAngle={3}
              dataKey="value"
            >
              {chartData.map((entry) => (
                <Cell key={entry.name} fill={entry.color} />
              ))}
            </Pie>
            <Tooltip
              contentStyle={tooltipStyle}
              formatter={(value: unknown, name: unknown) => [`${value} โครงการ`, String(name)]}
            />
          </PieChart>
        </ResponsiveContainer>
      </div>
      <div className="-mt-4 grid grid-cols-2 gap-x-4 gap-y-1.5 px-2">
        {chartData.map((entry) => (
          <div key={entry.name} className="flex items-center gap-2">
            <span className="size-2.5 shrink-0 rounded-full" style={{ backgroundColor: entry.color }} />
            <span className="truncate text-xs text-[var(--text-muted)]">{entry.name}</span>
            <span className="ml-auto font-mono text-xs font-semibold tabular-nums text-[var(--text-secondary)]">
              {entry.value}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}
