"use client";

import { use, useState } from "react";
import Link from "next/link";
import { AlertTriangle, ChevronRight, Download, FileText } from "lucide-react";
import { StatusBadge } from "@/components/ui/status-badge";
import { QueryState } from "@/components/ui/query-state";
import { STATE_BADGE_CONFIG, PROCUREMENT_TYPE_LABELS } from "@/lib/constants";
import { fetchDocumentDownloadUrl, localizeApiError, type ProjectCrawlEvidence } from "@/lib/api";
import { useProjectDetail, useDocuments, useProjectCrawlEvidence } from "@/lib/hooks";
import { formatBudget, formatThaiDate } from "@/lib/utils";

const CLOSED_STATES = [
  "winner_announced",
  "contract_signed",
  "closed_timeout_consulting",
  "closed_stale_no_tor",
  "closed_manual",
];

const CLOSED_REASON_LABELS: Record<string, string> = {
  winner_announced: "ปิดเมื่อประกาศผู้ชนะ",
  contract_signed: "ปิดเมื่อลงนามสัญญา",
  consulting_timeout_30d: "ครบกำหนดโครงการที่ปรึกษา 30 วัน",
  prelim_pricing: "ปิดหลังเห็นราคากลาง",
  stale_no_tor: "ปิดเพราะไม่มี TOR",
  manual: "ปิดด้วยตนเอง",
  merged_duplicate: "รวมกับโครงการซ้ำ",
};

function formatDateTime(value: string | null): string {
  if (!value) return "—";
  return new Intl.DateTimeFormat("th-TH", {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(value));
}

function formatBytes(value: number): string {
  if (value >= 1_000_000) {
    return `${(value / 1_000_000).toFixed(1)} MB`;
  }
  if (value >= 1_000) {
    return `${(value / 1_000).toFixed(0)} KB`;
  }
  return `${value} B`;
}

function formatDuration(startedAt: string | null, finishedAt: string | null): string {
  if (!startedAt || !finishedAt) return "—";
  const durationMs = new Date(finishedAt).getTime() - new Date(startedAt).getTime();
  if (!Number.isFinite(durationMs) || durationMs < 0) return "—";
  const durationSeconds = durationMs / 1000;
  if (durationSeconds < 60) return `${durationSeconds.toFixed(1)}s`;
  const durationMinutes = Math.floor(durationSeconds / 60);
  const remainderSeconds = Math.round(durationSeconds % 60);
  return `${durationMinutes}m ${remainderSeconds}s`;
}

function formatEvidenceSummary(evidence: ProjectCrawlEvidence): string {
  const resultEntries = Object.entries(evidence.result_json ?? {});
  if (resultEntries.length > 0) {
    return resultEntries
      .map(([key, value]) => `${key}: ${String(value)}`)
      .join(", ");
  }

  if (evidence.keyword) {
    return `keyword: ${evidence.keyword}`;
  }

  const payloadEntries = Object.entries(evidence.payload ?? {});
  if (payloadEntries.length > 0) {
    return payloadEntries
      .map(([key, value]) => `${key}: ${String(value)}`)
      .join(", ");
  }

  const runSummaryEntries = Object.entries(evidence.run_summary_json ?? {});
  if (runSummaryEntries.length > 0) {
    return runSummaryEntries
      .map(([key, value]) => `${key}: ${String(value)}`)
      .join(", ");
  }

  return "—";
}

export default function ProjectDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const [downloadingDocumentId, setDownloadingDocumentId] = useState<string | null>(null);
  const [downloadError, setDownloadError] = useState<string | null>(null);
  const {
    data: detailData,
    isLoading,
    isError,
    error,
  } = useProjectDetail(id);
  const {
    data: documentData,
    isError: isDocumentsError,
    error: documentsError,
  } = useDocuments(id);
  const {
    data: evidenceData,
    isLoading: isEvidenceLoading,
    isError: isEvidenceError,
    error: evidenceError,
  } = useProjectCrawlEvidence(id);

  const project = detailData?.project;
  const aliases = detailData?.aliases ?? [];
  const statusEvents = detailData?.status_events ?? [];
  const documents = documentData?.documents ?? [];
  const crawlEvidence = evidenceData?.evidence ?? [];
  const isClosed = project ? CLOSED_STATES.includes(project.project_state) : false;
  const timeline =
    statusEvents.length > 0
      ? statusEvents.map((event) => {
          const config = STATE_BADGE_CONFIG[event.normalized_status ?? ""] ?? {
            label: event.observed_status_text,
            color: "gray" as const,
          };
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
            id: event.id,
            label: config.label,
            date: formatDateTime(event.observed_at),
            note: event.observed_status_text,
            dotColor: dotColors[config.color] ?? dotColors.gray,
          };
        })
      : project
        ? [
            {
              id: `${project.id}-current`,
              label:
                STATE_BADGE_CONFIG[project.project_state]?.label ?? project.project_state,
              date: formatDateTime(project.last_changed_at),
              note: project.source_status_text ?? "อัปเดตล่าสุดของโครงการ",
              dotColor: "bg-[var(--badge-indigo-text)]",
            },
          ]
        : [];

  async function handleDownload(documentId: string) {
    setDownloadError(null);
    setDownloadingDocumentId(documentId);
    try {
      const { download_url } = await fetchDocumentDownloadUrl(documentId);
      const link = document.createElement("a");
      link.href = download_url;
      link.target = "_blank";
      link.rel = "noreferrer";
      link.click();
    } catch (downloadException) {
      const message = localizeApiError(downloadException, "ไม่สามารถดาวน์โหลดเอกสารได้");
      setDownloadError(message);
    } finally {
      setDownloadingDocumentId(null);
    }
  }

  return (
    <QueryState
      isLoading={isLoading}
      isError={isError}
      error={error as Error | null}
      isEmpty={!isLoading && !isError && !project}
      emptyMessage="ไม่พบโครงการนี้"
    >
      {project ? (
        <>
          <nav className="mb-4 flex items-center gap-1 text-sm text-[var(--text-muted)]">
            <Link href="/projects" className="hover:text-primary">
              สำรวจโครงการ
            </Link>
            <ChevronRight className="size-4" />
            <span className="font-medium text-[var(--text-primary)]">
              {project.project_number ?? project.id}
            </span>
          </nav>

          <div className="rounded-2xl bg-[var(--bg-surface)] p-6 shadow-[var(--shadow-soft)]">
            <div className="flex flex-col gap-4">
              <div className="space-y-3">
                <div className="flex flex-wrap items-center gap-3">
                  <h1 className="text-xl font-bold text-[var(--text-primary)]">
                    {project.project_name}
                  </h1>
                  <StatusBadge state={project.project_state} />
                </div>
                <div className="grid grid-cols-2 gap-x-8 gap-y-2 text-sm lg:grid-cols-4">
                  <div>
                    <span className="text-[var(--text-muted)]">หน่วยงาน</span>
                    <p className="font-medium">{project.organization_name || "—"}</p>
                  </div>
                  <div>
                    <span className="text-[var(--text-muted)]">เลขที่โครงการ</span>
                    <p className="font-mono font-medium">{project.project_number ?? "—"}</p>
                  </div>
                  <div>
                    <span className="text-[var(--text-muted)]">งบประมาณ</span>
                    <p className="font-mono font-bold tabular-nums text-primary">
                      {formatBudget(project.budget_amount)}
                    </p>
                  </div>
                  <div>
                    <span className="text-[var(--text-muted)]">ประเภท</span>
                    <p className="font-medium">
                      {PROCUREMENT_TYPE_LABELS[project.procurement_type] ??
                        project.procurement_type}
                    </p>
                  </div>
                </div>
                <div className="flex flex-wrap gap-6 text-xs text-[var(--text-muted)]">
                  <span>เห็นครั้งแรก: {formatDateTime(project.first_seen_at)}</span>
                  <span>เห็นล่าสุด: {formatDateTime(project.last_seen_at)}</span>
                  <span>เปลี่ยนแปลงล่าสุด: {formatDateTime(project.last_changed_at)}</span>
                </div>
              </div>
            </div>
          </div>

          <div className="mt-6 grid grid-cols-1 gap-6 lg:grid-cols-12">
            <div className="rounded-2xl bg-[var(--bg-surface)] p-6 shadow-[var(--shadow-soft)] lg:col-span-4">
              <h2 className="mb-4 text-lg font-bold text-[var(--text-primary)]">
                ประวัติสถานะ
              </h2>
              <div className="relative space-y-6 pl-6">
                <div className="absolute bottom-0 left-[5px] top-0 w-0.5 bg-[var(--border-default)]" />
                {timeline.map((entry) => (
                  <div key={entry.id} className="relative">
                    <div
                      className={`absolute -left-6 top-0.5 size-3 rounded-full ${entry.dotColor} ring-2 ring-[var(--bg-surface)]`}
                    />
                    <p className="text-sm font-semibold text-[var(--text-primary)]">
                      {entry.label}
                    </p>
                    <p className="text-xs text-[var(--text-muted)]">{entry.date}</p>
                    <p className="mt-0.5 text-xs text-[var(--text-muted)]">{entry.note}</p>
                  </div>
                ))}
              </div>
            </div>

            <div className="space-y-6 lg:col-span-4">
              <div className="rounded-2xl bg-[var(--bg-surface)] p-6 shadow-[var(--shadow-soft)]">
                <h2 className="mb-4 text-lg font-bold text-[var(--text-primary)]">
                  ชื่อเรียกอื่น (Aliases)
                </h2>
                {aliases.length === 0 ? (
                  <p className="text-sm text-[var(--text-muted)]">ยังไม่มี aliases สำหรับโครงการนี้</p>
                ) : (
                  <div className="overflow-x-auto">
                    <table className="w-full text-sm">
                      <thead>
                        <tr className="border-b border-[var(--border-light)]">
                          <th className="pb-2 pr-3 text-left text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">
                            ประเภท
                          </th>
                          <th className="pb-2 pr-3 text-left text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">
                            ค่า
                          </th>
                          <th className="pb-2 text-left text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">
                            วันที่
                          </th>
                        </tr>
                      </thead>
                      <tbody>
                        {aliases.map((alias) => (
                          <tr key={alias.id} className="border-b border-[var(--border-light)]">
                            <td className="py-2 pr-3 text-xs text-[var(--text-muted)]">
                              {alias.alias_type}
                            </td>
                            <td
                              className={`py-2 pr-3 text-xs ${
                                alias.alias_type === "project_number" ||
                                alias.alias_type === "fingerprint"
                                  ? "font-mono"
                                  : ""
                              }`}
                            >
                              {alias.alias_type === "fingerprint"
                                ? `${alias.alias_value.slice(0, 12)}...`
                                : alias.alias_value}
                            </td>
                            <td className="py-2 text-xs text-[var(--text-muted)]">
                              {formatThaiDate(alias.created_at)}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </div>

              <div className="rounded-2xl bg-[var(--bg-surface)] p-6 shadow-[var(--shadow-soft)]">
                <h2 className="mb-4 text-lg font-bold text-[var(--text-primary)]">
                  ข้อมูลการปิด
                </h2>
                <div className="space-y-2 text-sm">
                  <div className="flex items-center gap-2">
                    <span className="text-[var(--text-muted)]">สถานะ:</span>
                    <span className="font-medium">
                      {isClosed ? "ปิดแล้ว" : "ยังไม่ปิด"}
                    </span>
                  </div>
                  <div>
                    <span className="text-[var(--text-muted)]">เหตุผล:</span>
                    <span className="ml-2">
                      {project.closed_reason
                        ? CLOSED_REASON_LABELS[project.closed_reason] ?? project.closed_reason
                        : "—"}
                    </span>
                  </div>
                  <div>
                    <span className="text-[var(--text-muted)]">สถานะต้นทางล่าสุด:</span>
                    <span className="ml-2">{project.source_status_text ?? "—"}</span>
                  </div>
                  <p className="mt-2 text-xs text-[var(--text-muted)]">
                    {isClosed
                      ? `อัปเดตล่าสุดเมื่อ ${formatDateTime(project.last_changed_at)}`
                      : "โครงการนี้ยังคงเปิดอยู่และกำลังติดตาม"}
                  </p>
                </div>
              </div>
            </div>

            <div className="rounded-2xl bg-[var(--bg-surface)] p-6 shadow-[var(--shadow-soft)] lg:col-span-4">
              <h2 className="mb-4 text-lg font-bold text-[var(--text-primary)]">เอกสาร</h2>
              {downloadError ? (
                <div className="mb-3 rounded-2xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800">
                  <div className="flex items-start gap-3">
                    <AlertTriangle className="mt-0.5 size-4 shrink-0" />
                    <div>
                      <p className="font-semibold">ดาวน์โหลดเอกสารไม่สำเร็จ</p>
                      <p className="mt-1">{downloadError}</p>
                      <p className="mt-1 text-xs text-red-700">
                        หากเอกสารถูกเก็บไว้บน Google Drive หรือ OneDrive ให้ตรวจสอบแท็บ
                        {" "}Support ในหน้า Admin หรือติดต่อทีม support เพื่อเช็กการเชื่อมต่อของ
                        {" "}tenant นี้
                      </p>
                    </div>
                  </div>
                </div>
              ) : null}
              {isDocumentsError ? (
                <p className="text-sm text-[var(--badge-red-text)]">
                  {localizeApiError(documentsError, "ไม่สามารถโหลดรายการเอกสารได้")}
                </p>
              ) : documents.length === 0 ? (
                <p className="text-sm text-[var(--text-muted)]">ยังไม่มีเอกสารสำหรับโครงการนี้</p>
              ) : (
                <div className="space-y-3">
                  {documents.map((document) => (
                    <div
                      key={document.id}
                      className="flex items-start justify-between gap-3 rounded-xl border border-[var(--border-light)] p-3"
                    >
                      <div className="flex items-start gap-3">
                        <FileText className="mt-0.5 size-5 shrink-0 text-primary" />
                        <div>
                          <p className="text-sm font-medium text-[var(--text-primary)]">
                            {document.source_label || document.file_name}
                          </p>
                          <p className="text-xs text-[var(--text-muted)]">
                            {document.document_phase} • {formatBytes(document.size_bytes)} •{" "}
                            {formatDateTime(document.created_at)}
                          </p>
                          <div className="mt-1 flex gap-1.5">
                            {document.is_current ? (
                              <span className="inline-flex rounded-full bg-[var(--badge-green-bg)] px-2 py-0.5 text-[10px] font-semibold text-[var(--badge-green-text)]">
                                ปัจจุบัน
                              </span>
                            ) : null}
                            {document.supersedes_document_id ? (
                              <span className="inline-flex rounded-full bg-[var(--badge-amber-bg)] px-2 py-0.5 text-[10px] font-semibold text-[var(--badge-amber-text)]">
                                เปลี่ยนแปลง
                              </span>
                            ) : null}
                          </div>
                        </div>
                      </div>
                      <button
                        type="button"
                        onClick={() => void handleDownload(document.id)}
                        disabled={downloadingDocumentId === document.id}
                        className="shrink-0 rounded-lg p-1.5 text-[var(--text-muted)] hover:bg-[var(--bg-surface-hover)] hover:text-primary disabled:cursor-not-allowed disabled:opacity-50"
                        aria-label={
                          downloadingDocumentId === document.id
                            ? "กำลังเตรียมดาวน์โหลดเอกสาร"
                            : "ดาวน์โหลดเอกสาร"
                        }
                      >
                        <Download className="size-4" />
                      </button>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>

          <div className="mt-6 rounded-2xl bg-[var(--bg-surface)] p-6 shadow-[var(--shadow-soft)]">
            <h2 className="mb-4 text-lg font-bold text-[var(--text-primary)]">
              หลักฐานการ Crawl
            </h2>
            {isEvidenceLoading ? (
              <p className="text-sm text-[var(--text-muted)]">กำลังโหลดประวัติการ crawl...</p>
            ) : isEvidenceError ? (
              <p className="text-sm text-[var(--badge-red-text)]">
                {localizeApiError(evidenceError, "ไม่สามารถโหลดหลักฐานการ crawl ได้")}
              </p>
            ) : crawlEvidence.length === 0 ? (
              <p className="text-sm text-[var(--text-muted)]">
                ยังไม่พบงาน crawl ที่ผูกกับโครงการนี้
              </p>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-[var(--border-default)] bg-[var(--bg-surface-secondary)]">
                      <th className="px-3 py-2 text-left text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">
                        Run ID
                      </th>
                      <th className="px-3 py-2 text-left text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">
                        วันที่
                      </th>
                      <th className="px-3 py-2 text-left text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">
                        ประเภท
                      </th>
                      <th className="px-3 py-2 text-left text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">
                        สถานะงาน
                      </th>
                      <th className="px-3 py-2 text-left text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">
                        สถานะรัน
                      </th>
                      <th className="px-3 py-2 text-left text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">
                        ระยะเวลา
                      </th>
                      <th className="px-3 py-2 text-left text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">
                        ข้อมูลที่พบ
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {crawlEvidence.map((evidence) => (
                      <tr
                        key={evidence.task_id}
                        className="h-10 border-b border-[var(--border-light)] hover:bg-[var(--bg-surface-hover)]"
                      >
                        <td className="px-3 py-2 font-mono text-[13px]">{evidence.run_id}</td>
                        <td className="px-3 py-2 text-[13px]">
                          {formatDateTime(
                            evidence.finished_at ?? evidence.started_at ?? evidence.created_at,
                          )}
                        </td>
                        <td className="px-3 py-2 text-[13px]">
                          {evidence.trigger_type} / {evidence.task_type}
                        </td>
                        <td className="px-3 py-2">
                          <StatusBadge state={evidence.task_status} variant="task" />
                        </td>
                        <td className="px-3 py-2">
                          <StatusBadge state={evidence.run_status} variant="run" />
                        </td>
                        <td className="px-3 py-2 font-mono text-[13px] tabular-nums">
                          {formatDuration(evidence.started_at, evidence.finished_at)}
                        </td>
                        <td className="px-3 py-2 text-[13px] text-[var(--text-secondary)]">
                          {formatEvidenceSummary(evidence)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </>
      ) : null}
    </QueryState>
  );
}
