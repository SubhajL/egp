"use client";

import { Fragment, useEffect, useState, type ComponentType } from "react";
import {
  Activity,
  CheckCircle,
  ChevronDown,
  ChevronRight,
  Clock,
  RotateCcw,
  XCircle,
} from "lucide-react";
import { PageHeader } from "@/components/layout/page-header";
import { QueryState } from "@/components/ui/query-state";
import { StatusBadge } from "@/components/ui/status-badge";
import { useRuns } from "@/lib/hooks";
import { buildRunLogText } from "@/lib/run-log";
import { formatRunProgress, isActiveRunStatus } from "@/lib/run-progress";
import { formatThaiDate } from "@/lib/utils";
import type { RunDetailResponse, TaskSummary } from "@/lib/api";

type DisplayTask = {
  id: string;
  type: string;
  keyword: string;
  project: string;
  status: string;
  attempts: number;
  duration: string;
  errorDetail: string | null;
};

type DisplayRun = {
  id: string;
  displayId: string;
  profile: string;
  trigger: string;
  status: string;
  startedAt: string;
  duration: string;
  discovered: number;
  updated: number;
  closed: number;
  errors: number;
  errorDetail: string | null;
  progressDetail: string | null;
  progressUpdatedAt: string | null;
  tasks: DisplayTask[];
};

function formatRunTrigger(triggerType: string): string {
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

function formatTaskType(taskType: string): string {
  switch (taskType) {
    case "discover":
      return "ค้นหา";
    case "update":
      return "อัปเดต";
    case "close_check":
      return "ตรวจสอบปิด";
    case "download":
      return "ดาวน์โหลด";
    default:
      return taskType;
  }
}

function formatDuration(
  startedAt: string | null,
  finishedAt: string | null,
  status: string,
): string {
  if (!startedAt) {
    return status === "queued" ? "รอคิว" : "—";
  }
  if (!finishedAt) {
    return status === "running" ? "กำลังทำงาน..." : "—";
  }

  const diffMs = new Date(finishedAt).getTime() - new Date(startedAt).getTime();
  if (diffMs < 60000) {
    return `${Math.max(1, Math.round(diffMs / 1000))} วินาที`;
  }

  const totalMinutes = Math.round(diffMs / 60000);
  if (totalMinutes < 60) {
    return `${totalMinutes} นาที`;
  }

  const hours = Math.floor(totalMinutes / 60);
  const minutes = totalMinutes % 60;
  return minutes > 0 ? `${hours} ชม. ${minutes} นาที` : `${hours} ชม.`;
}

function readNumericSummary(
  summary: Record<string, unknown> | null,
  keys: string[],
): number {
  if (!summary) return 0;
  for (const key of keys) {
    const value = summary[key];
    if (typeof value === "number" && Number.isFinite(value)) return value;
    if (typeof value === "string" && value.trim() !== "") {
      const parsed = Number(value);
      if (Number.isFinite(parsed)) return parsed;
    }
  }
  return 0;
}

function readStringSummary(
  summary: Record<string, unknown> | null,
  keys: string[],
): string | null {
  if (!summary) return null;
  for (const key of keys) {
    const value = summary[key];
    if (typeof value === "string" && value.trim() !== "") {
      return value.trim();
    }
  }
  return null;
}

function formatProfileLabel(profileId: string | null): string {
  return profileId ? profileId.slice(0, 8).toUpperCase() : "—";
}

function readTaskError(task: TaskSummary): string | null {
  const result = task.result_json;
  if (!result) return null;
  const error = result.error;
  return typeof error === "string" && error.trim() !== "" ? error.trim() : null;
}

function buildDisplayTask(task: TaskSummary): DisplayTask {
  return {
    id: task.id.slice(0, 12),
    type: formatTaskType(task.task_type),
    keyword: task.keyword ?? "—",
    project: task.project_id ? task.project_id.slice(0, 12) : "—",
    status: task.status,
    attempts: task.attempts,
    duration: formatDuration(task.started_at, task.finished_at, task.status),
    errorDetail: readTaskError(task),
  };
}

function buildDisplayRun(runDetail: RunDetailResponse): DisplayRun {
  const tasks = runDetail.tasks.map(buildDisplayTask);
  const progress = formatRunProgress(runDetail.run.summary_json);
  const runLevelError = readStringSummary(runDetail.run.summary_json, ["error"]);
  const taskLevelError = tasks.find((task) => task.errorDetail)?.errorDetail ?? null;
  const errorDetail =
    runLevelError ??
    taskLevelError ??
    (runDetail.run.status === "failed" && runDetail.run.error_count > 0
      ? "Run นี้ล้มเหลวก่อนระบบบันทึกข้อความผิดพลาดแบบละเอียด"
      : null);
  return {
    id: runDetail.run.id,
    displayId: runDetail.run.id.slice(0, 12),
    profile: formatProfileLabel(runDetail.run.profile_id),
    trigger: formatRunTrigger(runDetail.run.trigger_type),
    status: runDetail.run.status,
    startedAt: runDetail.run.started_at ? formatThaiDate(runDetail.run.started_at) : "—",
    duration: formatDuration(
      runDetail.run.started_at,
      runDetail.run.finished_at,
      runDetail.run.status,
    ),
    discovered: readNumericSummary(runDetail.run.summary_json, [
      "projects_seen",
      "projects_discovered",
      "discovered",
    ]),
    updated: readNumericSummary(runDetail.run.summary_json, [
      "projects_updated",
      "updated",
      "changes_detected",
    ]),
    closed: readNumericSummary(runDetail.run.summary_json, [
      "projects_closed",
      "closed",
      "closed_projects",
    ]),
    errors: runDetail.run.error_count,
    errorDetail,
    progressDetail: progress.detail,
    progressUpdatedAt: progress.updatedAt ? formatThaiDate(progress.updatedAt) : null,
    tasks,
  };
}

function StatCard({
  label,
  value,
  icon: Icon,
  colorClass,
  bgClass,
}: {
  label: string;
  value: string | number;
  icon: ComponentType<{ className?: string }>;
  colorClass: string;
  bgClass: string;
}) {
  return (
    <div className="flex items-center gap-4 rounded-2xl bg-[var(--bg-surface)] p-5 shadow-[var(--shadow-soft)]">
      <div className={`flex size-10 shrink-0 items-center justify-center rounded-xl ${bgClass}`}>
        <Icon className={`size-5 ${colorClass}`} />
      </div>
      <div>
        <p className="text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">
          {label}
        </p>
        <p className={`font-mono text-2xl font-bold tabular-nums ${colorClass}`}>{value}</p>
      </div>
    </div>
  );
}

export default function RunsPage() {
  const [expandedRun, setExpandedRun] = useState<string | null>(null);
  const [currentPage, setCurrentPage] = useState(1);
  const rowsPerPage = 50;
  const { data, isLoading, isError, error, refetch, isFetching } = useRuns({
    limit: rowsPerPage,
    offset: (currentPage - 1) * rowsPerPage,
  });
  const {
    data: latestRunData,
    isLoading: isLatestRunLoading,
    isError: isLatestRunError,
    error: latestRunError,
    refetch: refetchLatestRun,
    isFetching: isLatestRunFetching,
  } = useRuns({
    limit: 1,
    offset: 0,
  });

  const displayRuns = (data?.runs ?? []).map(buildDisplayRun);
  const latestRunDetail = latestRunData?.runs[0] ?? null;
  const latestRunLogText = buildRunLogText(latestRunDetail);
  const totalRunCount = data?.total ?? 0;
  const totalPages = Math.max(1, Math.ceil(Math.max(totalRunCount, 1) / rowsPerPage));
  const rangeStart = totalRunCount === 0 ? 0 : (currentPage - 1) * rowsPerPage + 1;
  const rangeEnd = totalRunCount === 0 ? 0 : rangeStart + displayRuns.length - 1;
  const hasActiveRuns =
    displayRuns.some((run) => isActiveRunStatus(run.status)) ||
    (latestRunDetail ? isActiveRunStatus(latestRunDetail.run.status) : false);

  useEffect(() => {
    if (currentPage > totalPages) {
      setCurrentPage(totalPages);
    }
  }, [currentPage, totalPages]);

  useEffect(() => {
    if (expandedRun && !displayRuns.some((run) => run.id === expandedRun)) {
      setExpandedRun(null);
    }
  }, [displayRuns, expandedRun]);

  useEffect(() => {
    if (!hasActiveRuns) return;
    const interval = window.setInterval(() => {
      void refetch();
      void refetchLatestRun();
    }, 5000);
    return () => window.clearInterval(interval);
  }, [hasActiveRuns, refetch, refetchLatestRun]);

  return (
    <>
      <PageHeader
        title="การทำงานและปฏิบัติการ"
        subtitle="ติดตามประวัติการทำงานของ Crawler จากข้อมูลรันจริง"
        actions={
          <button
            type="button"
            onClick={() => {
              void refetch();
              void refetchLatestRun();
            }}
            disabled={isFetching || isLatestRunFetching}
            className="flex items-center gap-1.5 rounded-xl border border-[var(--border-default)] px-4 py-2.5 text-sm font-medium text-[var(--text-secondary)] hover:bg-[var(--bg-surface-hover)] disabled:cursor-not-allowed disabled:opacity-60"
          >
            <RotateCcw
              className={`size-4 ${isFetching || isLatestRunFetching ? "animate-spin" : ""}`}
            />
            รีเฟรช
          </button>
        }
      />

      <div className="mt-6 rounded-2xl bg-[var(--bg-surface)] shadow-[var(--shadow-soft)]">
        <div className="border-b border-[var(--border-default)] px-6 py-4">
          <h2 className="text-lg font-bold text-[var(--text-primary)]">
            Transcript ของ Run ล่าสุด
          </h2>
          <p className="mt-1 text-sm text-[var(--text-muted)]">
            แสดงข้อความที่สรุปจากข้อมูล run/task ที่บันทึกไว้ ไม่ใช่ stdout/stderr ดิบของ worker
          </p>
        </div>
        <div className="p-6">
          {isLatestRunLoading ? (
            <div className="rounded-2xl border border-[var(--border-default)] bg-[var(--bg-surface-secondary)] px-4 py-6 text-sm text-[var(--text-muted)]">
              กำลังโหลด transcript ของ run ล่าสุด...
            </div>
          ) : isLatestRunError ? (
            <div className="rounded-2xl border border-red-200 bg-red-50 px-4 py-6 text-sm text-red-800">
              {latestRunError instanceof Error
                ? latestRunError.message
                : "ไม่สามารถโหลด transcript ของ run ล่าสุดได้"}
            </div>
          ) : (
            <textarea
              readOnly
              value={latestRunLogText}
              spellCheck={false}
              className="h-[28rem] w-full resize-none rounded-2xl border border-[var(--border-default)] bg-[var(--bg-surface-secondary)] px-4 py-4 font-mono text-xs leading-6 text-[var(--text-primary)] outline-none"
            />
          )}
        </div>
      </div>

      <div className="grid grid-cols-1 gap-6 sm:grid-cols-2 md:grid-cols-4">
        <StatCard
          label="Run ทั้งหมด"
          value={totalRunCount}
          icon={Activity}
          colorClass="text-[var(--text-secondary)]"
          bgClass="bg-[var(--badge-gray-bg)]"
        />
        <StatCard
          label="กำลังทำงานในหน้า"
          value={displayRuns.filter((run) => run.status === "running").length}
          icon={Clock}
          colorClass="text-[var(--badge-indigo-text)]"
          bgClass="bg-[var(--badge-indigo-bg)]"
        />
        <StatCard
          label="สำเร็จในหน้า"
          value={displayRuns.filter((run) => run.status === "succeeded").length}
          icon={CheckCircle}
          colorClass="text-[var(--badge-green-text)]"
          bgClass="bg-[var(--badge-green-bg)]"
        />
        <StatCard
          label="ล้มเหลวในหน้า"
          value={displayRuns.filter((run) => run.status === "failed").length}
          icon={XCircle}
          colorClass="text-[var(--badge-red-text)]"
          bgClass="bg-[var(--badge-red-bg)]"
        />
      </div>

      <QueryState
        isLoading={isLoading}
        isError={isError}
        error={error}
        isEmpty={!isLoading && !isError && displayRuns.length === 0}
        emptyMessage="ยังไม่มีประวัติการทำงานสำหรับ tenant นี้"
      >
        <div className="mt-6 rounded-2xl bg-[var(--bg-surface)] shadow-[var(--shadow-soft)]">
          <div className="border-b border-[var(--border-default)] px-6 py-4">
            <h2 className="text-lg font-bold text-[var(--text-primary)]">ประวัติการทำงาน</h2>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-[13px]">
              <thead>
                <tr className="bg-[var(--bg-surface-secondary)]">
                  <th className="w-8 px-3 py-2" />
                  <th className="px-3 py-2 text-left text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">
                    Run ID
                  </th>
                  <th className="px-3 py-2 text-left text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">
                    โปรไฟล์
                  </th>
                  <th className="px-3 py-2 text-left text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">
                    ทริกเกอร์
                  </th>
                  <th className="px-3 py-2 text-left text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">
                    สถานะ
                  </th>
                  <th className="px-3 py-2 text-left text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">
                    เริ่มเมื่อ
                  </th>
                  <th className="px-3 py-2 text-left text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">
                    ระยะเวลา
                  </th>
                  <th className="px-3 py-2 text-left text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">
                    ความคืบหน้าล่าสุด
                  </th>
                  <th className="px-3 py-2 text-right text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">
                    ค้นพบ
                  </th>
                  <th className="px-3 py-2 text-right text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">
                    อัปเดต
                  </th>
                  <th className="px-3 py-2 text-right text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">
                    ปิด
                  </th>
                  <th className="px-3 py-2 text-right text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">
                    ข้อผิดพลาด
                  </th>
                </tr>
              </thead>
              <tbody>
                {displayRuns.map((run) => (
                  <Fragment key={run.id}>
                    <tr
                      className="h-10 cursor-pointer border-b border-[var(--border-light)] hover:bg-[var(--bg-surface-hover)]"
                      onClick={() => setExpandedRun(expandedRun === run.id ? null : run.id)}
                    >
                      <td className="px-3 py-2 text-[var(--text-muted)]">
                        {expandedRun === run.id ? (
                          <ChevronDown className="size-4" />
                        ) : (
                          <ChevronRight className="size-4" />
                        )}
                      </td>
                      <td className="px-3 py-2 font-mono font-medium">{run.displayId}</td>
                      <td className="px-3 py-2">{run.profile}</td>
                      <td className="px-3 py-2">{run.trigger}</td>
                      <td className="px-3 py-2">
                        <StatusBadge state={run.status} variant="run" />
                      </td>
                      <td className="px-3 py-2 text-[var(--text-muted)]">{run.startedAt}</td>
                      <td className="px-3 py-2 font-mono tabular-nums">{run.duration}</td>
                      <td className="max-w-[320px] truncate px-3 py-2 text-[var(--text-muted)]">
                        {run.progressDetail ?? "—"}
                      </td>
                      <td className="px-3 py-2 text-right font-mono tabular-nums">
                        {run.discovered}
                      </td>
                      <td className="px-3 py-2 text-right font-mono tabular-nums">
                        {run.updated}
                      </td>
                      <td className="px-3 py-2 text-right font-mono tabular-nums">{run.closed}</td>
                      <td
                        className={`px-3 py-2 text-right font-mono tabular-nums ${
                          run.errors > 0 ? "font-semibold text-[var(--badge-red-text)]" : ""
                        }`}
                      >
                        {run.errors}
                      </td>
                    </tr>
                    {expandedRun === run.id && (
                      <tr>
                        <td
                          colSpan={12}
                          className="bg-[var(--bg-surface-secondary)] px-6 py-4"
                        >
                          {run.progressDetail ? (
                            <div className="mb-4 rounded-2xl border border-[var(--border-default)] bg-[var(--bg-surface)] px-4 py-3 text-sm text-[var(--text-secondary)]">
                              <p className="font-semibold text-[var(--text-primary)]">
                                สถานะ crawl ล่าสุด
                              </p>
                              <p className="mt-1">{run.progressDetail}</p>
                              {run.progressUpdatedAt ? (
                                <p className="mt-1 text-xs text-[var(--text-muted)]">
                                  อัปเดตล่าสุด {run.progressUpdatedAt}
                                </p>
                              ) : null}
                            </div>
                          ) : null}
                          <p className="mb-3 text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">
                            Tasks ใน {run.displayId}
                          </p>
                          {run.errorDetail ? (
                            <div className="mb-4 rounded-2xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800">
                              <p className="font-semibold">สาเหตุที่บันทึกได้ล่าสุด</p>
                              <p className="mt-1 whitespace-pre-wrap break-words">
                                {run.errorDetail}
                              </p>
                            </div>
                          ) : null}
                          {run.tasks.length === 0 ? (
                            <div className="rounded-xl border border-dashed border-[var(--border-default)] bg-[var(--bg-surface)] px-4 py-6 text-sm text-[var(--text-muted)]">
                              ยังไม่มี task ที่บันทึกไว้สำหรับ run นี้
                            </div>
                          ) : (
                            <table className="w-full text-[13px]">
                              <thead>
                                <tr className="border-b border-[var(--border-default)]">
                                  <th className="px-3 py-1.5 text-left text-xs font-semibold text-[var(--text-muted)]">
                                    Task ID
                                  </th>
                                  <th className="px-3 py-1.5 text-left text-xs font-semibold text-[var(--text-muted)]">
                                    ประเภท
                                  </th>
                                  <th className="px-3 py-1.5 text-left text-xs font-semibold text-[var(--text-muted)]">
                                    คำค้น
                                  </th>
                                  <th className="px-3 py-1.5 text-left text-xs font-semibold text-[var(--text-muted)]">
                                    โครงการ
                                  </th>
                                  <th className="px-3 py-1.5 text-left text-xs font-semibold text-[var(--text-muted)]">
                                    สถานะ
                                  </th>
                                  <th className="px-3 py-1.5 text-right text-xs font-semibold text-[var(--text-muted)]">
                                    ความพยายาม
                                  </th>
                                  <th className="px-3 py-1.5 text-left text-xs font-semibold text-[var(--text-muted)]">
                                    ระยะเวลา
                                  </th>
                                </tr>
                              </thead>
                              <tbody>
                                {run.tasks.map((task) => (
                                  <Fragment key={task.id}>
                                    <tr className="border-b border-[var(--border-light)]">
                                      <td className="px-3 py-1.5 font-mono">{task.id}</td>
                                      <td className="px-3 py-1.5">{task.type}</td>
                                      <td className="px-3 py-1.5">{task.keyword}</td>
                                      <td className="px-3 py-1.5 font-mono">{task.project}</td>
                                      <td className="px-3 py-1.5">
                                        <StatusBadge state={task.status} variant="task" />
                                      </td>
                                      <td className="px-3 py-1.5 text-right font-mono tabular-nums">
                                        {task.attempts}
                                      </td>
                                      <td className="px-3 py-1.5 font-mono tabular-nums">
                                        {task.duration}
                                      </td>
                                    </tr>
                                    {task.errorDetail ? (
                                      <tr className="border-b border-[var(--border-light)] bg-red-50/70">
                                        <td
                                          colSpan={7}
                                          className="px-3 py-2 text-sm text-red-800"
                                        >
                                          <span className="font-semibold">ข้อผิดพลาด:</span>{" "}
                                          <span className="whitespace-pre-wrap break-words">
                                            {task.errorDetail}
                                          </span>
                                        </td>
                                      </tr>
                                    ) : null}
                                  </Fragment>
                                ))}
                              </tbody>
                            </table>
                          )}
                        </td>
                      </tr>
                    )}
                  </Fragment>
                ))}
              </tbody>
            </table>
          </div>

          <div className="flex items-center justify-between border-t border-[var(--border-default)] px-6 py-3">
            <span className="text-sm text-[var(--text-muted)]">
              แสดง {rangeStart}-{rangeEnd} จาก {totalRunCount} รายการ
            </span>
            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={() => setCurrentPage((page) => Math.max(1, page - 1))}
                className="rounded-lg px-3 py-1.5 text-sm text-[var(--text-secondary)] hover:bg-[var(--bg-surface-hover)] disabled:text-[var(--text-disabled)]"
                disabled={currentPage === 1}
              >
                ก่อนหน้า
              </button>
              <span className="text-sm font-medium text-[var(--text-secondary)]">
                หน้า {currentPage} / {totalPages}
              </span>
              <button
                type="button"
                onClick={() => setCurrentPage((page) => Math.min(totalPages, page + 1))}
                className="rounded-lg px-3 py-1.5 text-sm text-[var(--text-secondary)] hover:bg-[var(--bg-surface-hover)] disabled:text-[var(--text-disabled)]"
                disabled={currentPage >= totalPages}
              >
                ถัดไป
              </button>
            </div>
            <span className="text-sm text-[var(--text-muted)]">{rowsPerPage} แถว/หน้า</span>
          </div>
        </div>
      </QueryState>
    </>
  );
}
