"use client";

import { use } from "react";
import Link from "next/link";
import { ChevronRight, FileText, Download, ExternalLink } from "lucide-react";
import { StatusBadge } from "@/components/ui/status-badge";
import { QueryState } from "@/components/ui/query-state";
import { useProjectDetail, useDocuments } from "@/lib/hooks";
import { formatBudget, formatThaiDate } from "@/lib/utils";
import { STATE_BADGE_CONFIG } from "@/lib/constants";

/* ------------------------------------------------------------------ */
/*  Mock Data                                                          */
/* ------------------------------------------------------------------ */

const TIMELINE = [
  { state: "discovered", label: "ค้นพบใหม่", date: "15 มี.ค. 2569 10:30", note: "ค้นพบจากคำค้น: ระบบสารสนเทศ", dotColor: "bg-[var(--badge-indigo-text)]" },
  { state: "open_invitation", label: "เปิดรับข้อเสนอ", date: "18 มี.ค. 2569 14:15", note: "ประกาศเชิญชวน", dotColor: "bg-[var(--badge-teal-text)]" },
  { state: "open_public_hearing", label: "ประชาพิจารณ์", date: "25 มี.ค. 2569 09:00", note: "เปิดรับฟังคำวิจารณ์", dotColor: "bg-[var(--badge-amber-text)]" },
  { state: "tor_downloaded", label: "ดาวน์โหลด TOR", date: "1 เม.ย. 2569 11:45", note: "ดาวน์โหลดเอกสารประกวดราคา", dotColor: "bg-[var(--badge-green-text)]" },
  { state: "pending", label: "รอการอัปเดต...", date: "", note: "", dotColor: "bg-[var(--text-disabled)]" },
];

const ALIASES = [
  { type: "search_name", value: "จัดซื้อระบบสารสนเทศ", date: "15 มี.ค. 69" },
  { type: "detail_name", value: "จัดซื้อระบบสารสนเทศเพื่อการบริหารจัดการภาษี", date: "15 มี.ค. 69" },
  { type: "project_number", value: "EGP-2026-0142", date: "18 มี.ค. 69" },
  { type: "fingerprint", value: "a3f8c9d2e7b4a1f6", date: "15 มี.ค. 69" },
];

const DOCUMENTS = [
  { name: "TOR (ประชาพิจารณ์)", version: "v1", size: "2.4 MB", isCurrent: true, changed: false },
  { name: "TOR (สุดท้าย)", version: "v2", size: "2.8 MB", isCurrent: true, changed: true },
  { name: "ประกาศเชิญชวน", version: "v1", size: "1.1 MB", isCurrent: true, changed: false },
  { name: "ราคากลาง", version: "v1", size: "850 KB", isCurrent: true, changed: false },
];

const CRAWL_EVIDENCE = [
  { runId: "CRWL-0042", date: "03 เม.ย. 2569 08:00", type: "Scheduled Incremental", status: "succeeded", duration: "1.4s", findings: "No changes detected" },
  { runId: "CRWL-0035", date: "02 เม.ย. 2569 08:45", type: "Event Triggered", status: "succeeded", duration: "2.1s", findings: "New Status: Open bidding" },
  { runId: "CRWL-0019", date: "01 เม.ย. 2569 08:00", type: "Scheduled Full", status: "succeeded", duration: "12.5s", findings: "Verified 4 documents" },
];

/* ------------------------------------------------------------------ */
/*  Page                                                               */
/* ------------------------------------------------------------------ */

export default function ProjectDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const { data: detailData, isLoading, isError, error } = useProjectDetail(id);
  const { data: docData } = useDocuments(id);

  const project = detailData?.project;
  const aliases = detailData?.aliases ?? ALIASES;
  const statusEvents = detailData?.status_events ?? [];
  const documents = docData?.documents ?? [];

  // Build timeline from API status_events or fall back to mock
  const timeline = statusEvents.length > 0
    ? statusEvents.map((e) => {
        const config = STATE_BADGE_CONFIG[e.normalized_status ?? ""] ?? { label: e.observed_status_text, color: "gray" };
        const dotColors: Record<string, string> = {
          indigo: "bg-[var(--badge-indigo-text)]",
          teal: "bg-[var(--badge-teal-text)]",
          amber: "bg-[var(--badge-amber-text)]",
          green: "bg-[var(--badge-green-text)]",
          purple: "bg-[var(--badge-purple-text)]",
          red: "bg-[var(--badge-red-text)]",
          gray: "bg-[var(--text-disabled)]",
        };
        return {
          state: e.normalized_status ?? "",
          label: config.label,
          date: formatThaiDate(e.observed_at) + " " + new Date(e.observed_at).toLocaleTimeString("th-TH", { hour: "2-digit", minute: "2-digit" }),
          note: e.observed_status_text,
          dotColor: dotColors[config.color] ?? dotColors.gray,
        };
      })
    : TIMELINE;

  // Map API documents or fall back to mock
  const displayDocs = documents.length > 0
    ? documents.map((d) => ({
        name: d.source_label || d.file_name,
        version: "v" + (d.supersedes_document_id ? "2" : "1"),
        size: d.size_bytes > 1_000_000 ? (d.size_bytes / 1_000_000).toFixed(1) + " MB" : (d.size_bytes / 1_000).toFixed(0) + " KB",
        isCurrent: d.is_current,
        changed: !!d.supersedes_document_id,
      }))
    : DOCUMENTS;

  const displayName = project?.project_name ?? "จัดซื้อระบบสารสนเทศเพื่อการบริหารจัดการภาษี";
  const displayState = project?.project_state ?? "open_invitation";
  const displayOrg = project?.organization_name ?? "กรมสรรพากร";
  const displayNumber = project?.project_number ?? "EGP-2026-0142";
  const displayBudget = project ? formatBudget(project.budget_amount) : "฿12,500,000.00";
  const displayType = project?.procurement_type ?? "บริการ";

  return (
    <>
      {/* Breadcrumb */}
      <nav className="mb-4 flex items-center gap-1 text-sm text-[var(--text-muted)]">
        <Link href="/projects" className="hover:text-primary">สำรวจโครงการ</Link>
        <ChevronRight className="size-4" />
        <span className="font-medium text-[var(--text-primary)]">{displayNumber}</span>
      </nav>

      {/* Header Card */}
      <div className="rounded-2xl bg-[var(--bg-surface)] p-6 shadow-[var(--shadow-soft)]">
        <div className="flex flex-col justify-between gap-4 lg:flex-row lg:items-start">
          <div className="space-y-3">
            <div className="flex flex-wrap items-center gap-3">
              <h1 className="text-xl font-bold text-[var(--text-primary)]">
                {displayName}
              </h1>
              <StatusBadge state={displayState} />
            </div>
            <div className="grid grid-cols-2 gap-x-8 gap-y-2 text-sm lg:grid-cols-4">
              <div>
                <span className="text-[var(--text-muted)]">หน่วยงาน</span>
                <p className="font-medium">{displayOrg}</p>
              </div>
              <div>
                <span className="text-[var(--text-muted)]">เลขที่โครงการ</span>
                <p className="font-mono font-medium">{displayNumber}</p>
              </div>
              <div>
                <span className="text-[var(--text-muted)]">งบประมาณ</span>
                <p className="font-mono font-bold tabular-nums text-primary">{displayBudget}</p>
              </div>
              <div>
                <span className="text-[var(--text-muted)]">ประเภท</span>
                <p className="font-medium">{displayType}</p>
              </div>
            </div>
            <div className="flex flex-wrap gap-6 text-xs text-[var(--text-muted)]">
              <span>เห็นครั้งแรก: 15 มี.ค. 2569</span>
              <span>เห็นล่าสุด: 3 เม.ย. 2569</span>
              <span>เปลี่ยนแปลงล่าสุด: 2 เม.ย. 2569</span>
            </div>
          </div>
          <div className="flex shrink-0 items-center gap-2">
            <button type="button" className="rounded-xl border border-red-300 px-3 py-2 text-sm font-medium text-red-600 hover:bg-red-50">
              ปิดโครงการ
            </button>
            <button type="button" className="flex items-center gap-1.5 rounded-xl border border-[var(--border-default)] px-3 py-2 text-sm font-medium text-[var(--text-secondary)] hover:bg-[var(--bg-surface-hover)]">
              <ExternalLink className="size-4" /> เปิดใน e-GP
            </button>
            <button type="button" className="rounded-xl bg-primary px-4 py-2 text-sm font-medium text-white hover:bg-primary-hover">
              ส่งออก
            </button>
          </div>
        </div>
      </div>

      {/* 3-Column Bento */}
      <div className="mt-6 grid grid-cols-1 gap-6 lg:grid-cols-12">

        {/* Left: Timeline */}
        <div className="rounded-2xl bg-[var(--bg-surface)] p-6 shadow-[var(--shadow-soft)] lg:col-span-4">
          <h2 className="mb-4 text-lg font-bold text-[var(--text-primary)]">ประวัติสถานะ</h2>
          <div className="relative space-y-6 pl-6">
            <div className="absolute bottom-0 left-[5px] top-0 w-0.5 bg-[var(--border-default)]" />
            {timeline.map((entry, idx) => (
              <div key={idx} className="relative">
                <div className={`absolute -left-6 top-0.5 size-3 rounded-full ${entry.dotColor} ring-2 ring-[var(--bg-surface)]`} />
                <p className="text-sm font-semibold text-[var(--text-primary)]">{entry.label}</p>
                {entry.date && (
                  <p className="text-xs text-[var(--text-muted)]">{entry.date}</p>
                )}
                {entry.note && (
                  <p className="mt-0.5 text-xs text-[var(--text-muted)]">{entry.note}</p>
                )}
              </div>
            ))}
          </div>
        </div>

        {/* Center: Aliases + Closure */}
        <div className="space-y-6 lg:col-span-4">
          {/* Aliases */}
          <div className="rounded-2xl bg-[var(--bg-surface)] p-6 shadow-[var(--shadow-soft)]">
            <h2 className="mb-4 text-lg font-bold text-[var(--text-primary)]">ชื่อเรียกอื่น (Aliases)</h2>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-[var(--border-light)]">
                    <th className="pb-2 pr-3 text-left text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">ประเภท</th>
                    <th className="pb-2 pr-3 text-left text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">ค่า</th>
                    <th className="pb-2 text-left text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">วันที่</th>
                  </tr>
                </thead>
                <tbody>
                  {ALIASES.map((alias) => (
                    <tr key={alias.type} className="border-b border-[var(--border-light)]">
                      <td className="py-2 pr-3 text-xs text-[var(--text-muted)]">{alias.type}</td>
                      <td className={`py-2 pr-3 ${alias.type === "project_number" || alias.type === "fingerprint" ? "font-mono text-xs" : "text-xs"}`}>
                        {alias.type === "fingerprint" ? alias.value.slice(0, 12) + "..." : alias.value}
                      </td>
                      <td className="py-2 text-xs text-[var(--text-muted)]">{alias.date}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>

          {/* Closure Info */}
          <div className="rounded-2xl bg-[var(--bg-surface)] p-6 shadow-[var(--shadow-soft)]">
            <h2 className="mb-4 text-lg font-bold text-[var(--text-primary)]">ข้อมูลการปิด</h2>
            <div className="space-y-2 text-sm">
              <div className="flex items-center gap-2">
                <span className="text-[var(--text-muted)]">สถานะ:</span>
                <span className="flex items-center gap-1.5">
                  <span className="size-2 rounded-full bg-[var(--badge-green-text)]" />
                  <span className="font-medium">ยังไม่ปิด</span>
                </span>
              </div>
              <div>
                <span className="text-[var(--text-muted)]">เหตุผล:</span>
                <span className="ml-2">—</span>
              </div>
              <p className="mt-2 text-xs text-[var(--text-muted)]">
                โครงการนี้ยังคงเปิดอยู่และกำลังติดตาม
              </p>
            </div>
          </div>
        </div>

        {/* Right: Documents */}
        <div className="rounded-2xl bg-[var(--bg-surface)] p-6 shadow-[var(--shadow-soft)] lg:col-span-4">
          <h2 className="mb-4 text-lg font-bold text-[var(--text-primary)]">เอกสาร</h2>
          <div className="space-y-3">
            {displayDocs.map((doc) => (
              <div key={doc.name + doc.version} className="flex items-start justify-between gap-3 rounded-xl border border-[var(--border-light)] p-3">
                <div className="flex items-start gap-3">
                  <FileText className="mt-0.5 size-5 shrink-0 text-primary" />
                  <div>
                    <p className="text-sm font-medium text-[var(--text-primary)]">{doc.name}</p>
                    <p className="text-xs text-[var(--text-muted)]">{doc.version} — {doc.size}</p>
                    <div className="mt-1 flex gap-1.5">
                      {doc.isCurrent && (
                        <span className="inline-flex rounded-full bg-[var(--badge-green-bg)] px-2 py-0.5 text-[10px] font-semibold text-[var(--badge-green-text)]">
                          ปัจจุบัน
                        </span>
                      )}
                      {doc.changed && (
                        <span className="inline-flex rounded-full bg-[var(--badge-amber-bg)] px-2 py-0.5 text-[10px] font-semibold text-[var(--badge-amber-text)]">
                          เปลี่ยนแปลง
                        </span>
                      )}
                    </div>
                  </div>
                </div>
                <button type="button" className="shrink-0 rounded-lg p-1.5 text-[var(--text-muted)] hover:bg-[var(--bg-surface-hover)] hover:text-primary">
                  <Download className="size-4" />
                </button>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* Crawl Evidence */}
      <div className="mt-6 rounded-2xl bg-[var(--bg-surface)] p-6 shadow-[var(--shadow-soft)]">
        <h2 className="mb-4 text-lg font-bold text-[var(--text-primary)]">หลักฐานการ Crawl</h2>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-[var(--border-default)] bg-[var(--bg-surface-secondary)]">
                <th className="px-3 py-2 text-left text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">Run ID</th>
                <th className="px-3 py-2 text-left text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">วันที่</th>
                <th className="px-3 py-2 text-left text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">ประเภท</th>
                <th className="px-3 py-2 text-left text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">สถานะ</th>
                <th className="px-3 py-2 text-left text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">ระยะเวลา</th>
                <th className="px-3 py-2 text-left text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">ข้อมูลที่พบ</th>
              </tr>
            </thead>
            <tbody>
              {CRAWL_EVIDENCE.map((row) => (
                <tr key={row.runId} className="h-10 border-b border-[var(--border-light)] hover:bg-[var(--bg-surface-hover)]">
                  <td className="px-3 py-2 font-mono text-[13px]">{row.runId}</td>
                  <td className="px-3 py-2 text-[13px]">{row.date}</td>
                  <td className="px-3 py-2 text-[13px]">{row.type}</td>
                  <td className="px-3 py-2"><StatusBadge state={row.status} variant="run" /></td>
                  <td className="px-3 py-2 font-mono text-[13px] tabular-nums">{row.duration}</td>
                  <td className="px-3 py-2 text-[13px] text-[var(--text-secondary)]">{row.findings}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </>
  );
}
