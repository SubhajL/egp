import type { RunDetailResponse, RunSummary } from "./api";

export type RunProgressSnapshot = {
  detail: string | null;
  updatedAt: string | null;
};

function readRecordSummary(
  summary: Record<string, unknown> | null,
  key: string,
): Record<string, unknown> | null {
  if (!summary) return null;
  const value = summary[key];
  if (value && typeof value === "object" && !Array.isArray(value)) {
    return value as Record<string, unknown>;
  }
  return null;
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

function parseTimestamp(value: string | null | undefined): number {
  if (!value) return 0;
  const parsed = Date.parse(value);
  return Number.isFinite(parsed) ? parsed : 0;
}

export function formatProgressStage(stage: string): string {
  switch (stage) {
    case "keyword_start":
      return "เริ่มคำค้น";
    case "keyword_no_results":
      return "ไม่พบผลลัพธ์";
    case "page_scan_finished":
      return "สแกนหน้าผลลัพธ์";
    case "project_open_start":
      return "เปิดโครงการ";
    case "project_detail_extract_start":
      return "อ่านรายละเอียด";
    case "project_documents_start":
      return "เก็บเอกสาร";
    case "project_documents_finished":
      return "เก็บเอกสารเสร็จ";
    case "pagination_next_start":
      return "ไปหน้าถัดไป";
    case "pagination_next_finished":
      return "โหลดหน้าถัดไปแล้ว";
    case "keyword_finished":
      return "จบคำค้น";
    case "project_timeout":
      return "โครงการใช้เวลานานเกินกำหนด";
    default:
      return stage;
  }
}

export function formatRunProgress(
  summary: Record<string, unknown> | null,
): RunProgressSnapshot {
  const progress = readRecordSummary(summary, "live_progress");
  if (!progress) return { detail: null, updatedAt: null };
  const stage = typeof progress.stage === "string" ? progress.stage : "";
  const keyword = typeof progress.keyword === "string" ? progress.keyword : "";
  const projectName = typeof progress.project_name === "string" ? progress.project_name : "";
  const pageNum = typeof progress.page_num === "number" ? progress.page_num : null;
  const eligibleCount =
    typeof progress.eligible_count === "number" ? progress.eligible_count : null;
  const documentCount =
    typeof progress.document_count === "number" ? progress.document_count : null;
  const parts = [stage ? formatProgressStage(stage) : "กำลัง crawl"];
  if (keyword) parts.push(`คำค้น "${keyword}"`);
  if (pageNum !== null) parts.push(`หน้า ${pageNum}`);
  if (eligibleCount !== null) parts.push(`พบ ${eligibleCount} โครงการที่เข้าเงื่อนไข`);
  if (documentCount !== null) parts.push(`เอกสาร ${documentCount} ไฟล์`);
  if (projectName) parts.push(projectName);
  return {
    detail: parts.join(" · "),
    updatedAt: typeof progress.updated_at === "string" ? progress.updated_at : null,
  };
}

export function isActiveRunStatus(status: string): boolean {
  return status === "queued" || status === "running";
}

export function getActiveRuns(runs: RunDetailResponse[]): RunDetailResponse[] {
  return [...runs]
    .filter((detail) => isActiveRunStatus(detail.run.status))
    .sort((left, right) => {
      if (left.run.status !== right.run.status) {
        return left.run.status === "running" ? -1 : 1;
      }
      return (
        parseTimestamp(right.run.started_at ?? right.run.created_at) -
        parseTimestamp(left.run.started_at ?? left.run.created_at)
      );
    });
}

export function getRunPrimaryKeyword(runDetail: RunDetailResponse): string | null {
  const progress = readRecordSummary(runDetail.run.summary_json, "live_progress");
  if (typeof progress?.keyword === "string" && progress.keyword.trim() !== "") {
    return progress.keyword.trim();
  }
  const taskKeyword = runDetail.tasks.find((task) => typeof task.keyword === "string" && task.keyword);
  return taskKeyword?.keyword ?? null;
}

export function getRunActivitySnapshot(runDetail: RunDetailResponse): RunProgressSnapshot {
  const progress = formatRunProgress(runDetail.run.summary_json);
  if (progress.detail) {
    return progress;
  }

  const keyword = getRunPrimaryKeyword(runDetail);
  if (runDetail.run.status === "queued") {
    return {
      detail: keyword
        ? `รอ worker รับงานสำหรับคำค้น "${keyword}"`
        : "รอ worker รับงานจากคิว",
      updatedAt: runDetail.run.created_at,
    };
  }

  if (runDetail.run.status === "running") {
    return {
      detail: keyword
        ? `worker เริ่มทำงานสำหรับคำค้น "${keyword}" แล้ว`
        : "worker เริ่ม run แล้ว กำลังรอ progress event แรก",
      updatedAt: runDetail.run.started_at ?? runDetail.run.created_at,
    };
  }

  return { detail: null, updatedAt: null };
}

export function getRunDiscoveredCount(run: RunSummary): number {
  return readNumericSummary(run.summary_json, [
    "projects_seen",
    "projects_discovered",
    "discovered",
  ]);
}
