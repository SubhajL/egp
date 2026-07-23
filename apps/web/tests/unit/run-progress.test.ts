import { describe, expect, it } from "vitest";

import {
  getActiveRuns,
  getStaleActiveRuns,
  isStaleActiveRun,
} from "../../src/lib/run-progress";
import type { RunDetailResponse } from "../../src/lib/api";

function buildRunDetail(
  overrides: Partial<RunDetailResponse["run"]>,
): RunDetailResponse {
  return {
    run: {
      id: "11111111-1111-1111-1111-111111111111",
      tenant_id: "22222222-2222-2222-2222-222222222222",
      trigger_type: "manual",
      status: "running",
      profile_id: null,
      started_at: "2026-06-20T00:00:00.000Z",
      finished_at: null,
      last_activity_at: "2026-06-20T00:00:00.000Z",
      is_stale: false,
      summary_json: null,
      error_count: 0,
      created_at: "2026-06-20T00:00:00.000Z",
      ...overrides,
    },
    tasks: [],
  };
}

describe("run progress freshness", () => {
  it("uses the server stale classification for active runs", () => {
    const staleRun = buildRunDetail({
      id: "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
      started_at: "2026-06-16T12:00:00.000Z",
      created_at: "2026-06-16T12:00:00.000Z",
      last_activity_at: "2026-06-16T12:00:00.000Z",
      is_stale: true,
    });
    const liveRun = buildRunDetail({
      id: "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
      started_at: "2026-06-16T12:00:00.000Z",
      created_at: "2026-06-16T12:00:00.000Z",
      last_activity_at: "2026-06-20T11:30:00.000Z",
      is_stale: false,
    });

    expect(isStaleActiveRun(staleRun)).toBe(true);
    expect(
      getActiveRuns([staleRun, liveRun]).map((detail) => detail.run.id),
    ).toEqual(["bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"]);
    expect(
      getStaleActiveRuns([staleRun, liveRun]).map((detail) => detail.run.id),
    ).toEqual(["aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"]);
  });

  it("does not recompute freshness from live progress timestamps", () => {
    const run = buildRunDetail({
      started_at: "2026-06-20T06:00:00.000Z",
      created_at: "2026-06-20T06:00:00.000Z",
      last_activity_at: "2026-06-20T11:45:00.000Z",
      is_stale: false,
      summary_json: {
        live_progress: {
          stage: "project_documents_start",
          updated_at: "2026-06-20T11:45:00.000Z",
        },
      },
    });

    expect(isStaleActiveRun(run)).toBe(false);
    expect(getActiveRuns([run])).toHaveLength(1);
  });
});
