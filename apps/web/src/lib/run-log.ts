import type { RunDetailResponse, TaskSummary } from "./api";
import { formatRunProgress } from "./run-progress";
import { formatThaiDate } from "./utils";

function formatDateTime(value: string | null): string {
  return value ? formatThaiDate(value) : "-";
}

function formatJsonBlock(value: Record<string, unknown> | null): string {
  if (!value || Object.keys(value).length === 0) {
    return "{}";
  }
  return JSON.stringify(value, null, 2);
}

function formatTaskLog(task: TaskSummary, index: number): string {
  const lines = [
    `[task ${index}] ${task.task_type} · ${task.status}`,
    `id: ${task.id}`,
    `keyword: ${task.keyword ?? "-"}`,
    `project_id: ${task.project_id ?? "-"}`,
    `attempts: ${task.attempts}`,
    `created_at: ${formatDateTime(task.created_at)}`,
    `started_at: ${formatDateTime(task.started_at)}`,
    `finished_at: ${formatDateTime(task.finished_at)}`,
  ];

  if (task.payload) {
    lines.push("payload:");
    lines.push(formatJsonBlock(task.payload));
  }

  if (task.result_json) {
    lines.push("result_json:");
    lines.push(formatJsonBlock(task.result_json));
  }

  return lines.join("\n");
}

export function buildRunLogText(runDetail: RunDetailResponse | null): string {
  if (!runDetail) {
    return "ยังไม่มี run ล่าสุดสำหรับ tenant นี้";
  }

  const progress = formatRunProgress(runDetail.run.summary_json);
  const sections = [
    [
      "[run]",
      `id: ${runDetail.run.id}`,
      `status: ${runDetail.run.status}`,
      `trigger_type: ${runDetail.run.trigger_type}`,
      `profile_id: ${runDetail.run.profile_id ?? "-"}`,
      `error_count: ${runDetail.run.error_count}`,
      `created_at: ${formatDateTime(runDetail.run.created_at)}`,
      `started_at: ${formatDateTime(runDetail.run.started_at)}`,
      `finished_at: ${formatDateTime(runDetail.run.finished_at)}`,
    ].join("\n"),
  ];

  if (progress.detail) {
    sections.push(
      [
        "[latest_progress]",
        `detail: ${progress.detail}`,
        `updated_at: ${formatDateTime(progress.updatedAt)}`,
      ].join("\n"),
    );
  }

  sections.push(["[summary_json]", formatJsonBlock(runDetail.run.summary_json)].join("\n"));

  if (runDetail.tasks.length === 0) {
    sections.push("[tasks]\nไม่มี task ที่บันทึกไว้");
  } else {
    const taskSections = runDetail.tasks.map((task, index) => formatTaskLog(task, index + 1));
    sections.push(["[tasks]", ...taskSections].join("\n\n"));
  }

  return sections.join("\n\n");
}
