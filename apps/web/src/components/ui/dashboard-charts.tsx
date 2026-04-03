"use client";

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

const dailyProjectData = [
  { date: "20 มี.ค.", count: 12 },
  { date: "21 มี.ค.", count: 15 },
  { date: "22 มี.ค.", count: 9 },
  { date: "23 มี.ค.", count: 18 },
  { date: "24 มี.ค.", count: 22 },
  { date: "25 มี.ค.", count: 14 },
  { date: "26 มี.ค.", count: 11 },
  { date: "27 มี.ค.", count: 16 },
  { date: "28 มี.ค.", count: 20 },
  { date: "29 มี.ค.", count: 13 },
  { date: "30 มี.ค.", count: 8 },
  { date: "31 มี.ค.", count: 17 },
  { date: "1 เม.ย.", count: 19 },
  { date: "2 เม.ย.", count: 10 },
];

const projectStateData = [
  { name: "ค้นพบใหม่", value: 64, color: "#4338CA" },
  { name: "เปิดรับข้อเสนอ", value: 48, color: "#0F766E" },
  { name: "เปิดรับที่ปรึกษา", value: 35, color: "#0EA5E9" },
  { name: "ดาวน์โหลด TOR", value: 42, color: "#15803D" },
  { name: "ประกาศผู้ชนะ", value: 31, color: "#7C3AED" },
  { name: "ปิดแล้ว", value: 27, color: "#64748B" },
];

const tooltipStyle = {
  backgroundColor: "var(--bg-surface)",
  border: "1px solid var(--border-default)",
  borderRadius: "12px",
  fontSize: "13px",
  boxShadow: "var(--shadow-md)",
};

export function DailyDiscoveryChart() {
  return (
    <div className="rounded-2xl bg-[var(--bg-surface)] p-6 shadow-[var(--shadow-soft)] md:col-span-8">
      <h3 className="text-sm font-semibold text-[var(--text-primary)]">โครงการค้นพบรายวัน</h3>
      <div className="mt-4 h-72">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={dailyProjectData} margin={{ top: 4, right: 4, bottom: 0, left: -20 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="var(--border-light)" vertical={false} />
            <XAxis dataKey="date" tick={{ fontSize: 11, fill: "var(--text-muted)" }} axisLine={false} tickLine={false} />
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

export function ProjectStateChart() {
  return (
    <div className="rounded-2xl bg-[var(--bg-surface)] p-6 shadow-[var(--shadow-soft)] md:col-span-4">
      <h3 className="text-sm font-semibold text-[var(--text-primary)]">สถานะโครงการ</h3>
      <div className="mt-4 h-72">
        <ResponsiveContainer width="100%" height="100%">
          <PieChart>
            <Pie
              data={projectStateData}
              cx="50%"
              cy="50%"
              innerRadius={60}
              outerRadius={90}
              paddingAngle={3}
              dataKey="value"
            >
              {projectStateData.map((entry) => (
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
        {projectStateData.map((entry) => (
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
