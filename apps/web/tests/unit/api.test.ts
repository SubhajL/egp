import { afterEach, describe, expect, it, vi } from "vitest";
import { readFileSync } from "node:fs";

import {
  ApiError,
  createRuleProfile,
  fetchDocuments,
  fetchMe,
  fetchProjectDetail,
  fetchProjects,
  fetchRules,
} from "../../src/lib/api";
import type {
  DocumentListResponse,
  ProjectDetailResponse,
  ProjectListResponse,
  RulesResponse,
} from "../../src/lib/api";

describe("fetchMe", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("parses structured validation errors", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify({
            detail: [
              { loc: ["body", "password"], msg: "String should have at least 12 characters" },
            ],
          }),
          { status: 422, statusText: "Unprocessable Entity" },
        ),
      ),
    );

    await expect(fetchMe()).rejects.toEqual(
      new ApiError(422, "password: String should have at least 12 characters"),
    );
  });

  it("falls back when the response body is unreadable", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response("not-json", {
          status: 500,
          statusText: "Internal Server Error",
        }),
      ),
    );

    await expect(fetchMe()).rejects.toEqual(
      new ApiError(500, "API request failed: 500 Internal Server Error"),
    );
  });
});

describe("generated API type adoption", () => {
  it("uses generated OpenAPI types for the first migrated domains", () => {
    const source = readFileSync("src/lib/api.ts", "utf8");

    expect(source).toContain('from "./generated/api-types"');
    expect(source).not.toContain("export type ProjectSummary = {");
    expect(source).not.toContain("export type DocumentSummary = {");
    expect(source).not.toContain("export type RulesResponse = {");
  });
});

describe("project, document, and rules wrappers", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("builds project query parameters and returns a generated project list", async () => {
    const response: ProjectListResponse = {
      projects: [],
      total: 0,
      limit: 25,
      offset: 50,
    };
    const fetchMock = vi.fn().mockResolvedValue(Response.json(response));
    vi.stubGlobal("fetch", fetchMock);

    await expect(
      fetchProjects({
        project_state: ["open_invitation", "winner_announced"],
        budget_min: 1000,
        limit: 25,
        offset: 50,
      }),
    ).resolves.toEqual(response);

    const url = new URL(fetchMock.mock.calls[0][0] as string);
    expect(url.pathname).toBe("/v1/projects");
    expect(url.searchParams.getAll("project_state")).toEqual([
      "open_invitation",
      "winner_announced",
    ]);
    expect(url.searchParams.get("budget_min")).toBe("1000");
    expect(url.searchParams.get("limit")).toBe("25");
    expect(url.searchParams.get("offset")).toBe("50");
  });

  it("returns generated project detail and document list response shapes", async () => {
    const projectDetail: ProjectDetailResponse = {
      project: {
        id: "project-1",
        tenant_id: "tenant-1",
        canonical_project_id: "canonical-1",
        project_number: "P-1",
        project_name: "Road upgrade",
        organization_name: "City",
        procurement_type: "goods",
        proposal_submission_date: null,
        budget_amount: "1000.00",
        project_state: "open_invitation",
        closed_reason: null,
        source_status_text: null,
        has_changed_tor: false,
        first_seen_at: "2026-05-16T00:00:00Z",
        last_seen_at: "2026-05-16T00:00:00Z",
        last_changed_at: "2026-05-16T00:00:00Z",
        created_at: "2026-05-16T00:00:00Z",
        updated_at: "2026-05-16T00:00:00Z",
      },
      aliases: [],
      status_events: [],
    };
    const documents: DocumentListResponse = {
      documents: [
        {
          id: "document-1",
          project_id: "project-1",
          file_name: "tor.pdf",
          sha256: "abc",
          storage_key: "managed:tor.pdf",
          document_type: "tor",
          document_phase: "current",
          source_label: "egp",
          source_status_text: "",
          size_bytes: 123,
          is_current: true,
          supersedes_document_id: null,
          created_at: "2026-05-16T00:00:00Z",
        },
      ],
    };
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(Response.json(projectDetail))
      .mockResolvedValueOnce(Response.json(documents));
    vi.stubGlobal("fetch", fetchMock);

    await expect(fetchProjectDetail("project-1")).resolves.toEqual(projectDetail);
    await expect(fetchDocuments("project-1")).resolves.toEqual(documents);

    expect(new URL(fetchMock.mock.calls[0][0] as string).pathname).toBe(
      "/v1/projects/project-1",
    );
    expect(new URL(fetchMock.mock.calls[1][0] as string).pathname).toBe(
      "/v1/documents/projects/project-1",
    );
  });

  it("returns generated rules response and sends generated profile payload", async () => {
    const rules: RulesResponse = {
      profiles: [],
      entitlements: {
        plan_code: "free",
        plan_label: "Free",
        subscription_status: null,
        has_active_subscription: false,
        keyword_limit: 3,
        active_keyword_count: 1,
        remaining_keyword_slots: 2,
        active_keywords: ["ถนน"],
        over_keyword_limit: false,
        runs_allowed: true,
        exports_allowed: false,
        document_download_allowed: true,
        notifications_allowed: false,
        source: "billing",
      },
      closure_rules: {
        close_on_winner_status: true,
        close_on_contract_status: true,
        winner_status_terms: [],
        contract_status_terms: [],
        consulting_timeout_days: 30,
        stale_no_tor_days: 45,
        stale_eligible_states: [],
        source: "default",
      },
      notification_rules: {
        supported_channels: ["webhook"],
        supported_types: ["new_project"],
        event_wiring_complete: true,
        source: "default",
      },
      schedule_rules: {
        supported_trigger_types: ["scheduled"],
        schedule_execution_supported: true,
        editable_in_product: true,
        tenant_crawl_interval_hours: null,
        default_crawl_interval_hours: 24,
        effective_crawl_interval_hours: 24,
        source: "default",
      },
    };
    const createdProfile = {
      id: "profile-1",
      name: "Daily",
      profile_type: "custom",
      is_active: true,
      max_pages_per_keyword: 15,
      close_consulting_after_days: 30,
      close_stale_after_days: 45,
      keywords: ["ถนน"],
      created_at: "2026-05-16T00:00:00Z",
      updated_at: "2026-05-16T00:00:00Z",
    };
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(Response.json(rules))
      .mockResolvedValueOnce(Response.json(createdProfile));
    vi.stubGlobal("fetch", fetchMock);

    await expect(fetchRules()).resolves.toEqual(rules);
    await expect(createRuleProfile({ name: "Daily", keywords: ["ถนน"] })).resolves.toEqual(
      createdProfile,
    );

    expect(new URL(fetchMock.mock.calls[0][0] as string).pathname).toBe("/v1/rules");
    expect(new URL(fetchMock.mock.calls[1][0] as string).pathname).toBe(
      "/v1/rules/profiles",
    );
    expect(JSON.parse(fetchMock.mock.calls[1][1]?.body as string)).toStrictEqual({
      name: "Daily",
      keywords: ["ถนน"],
      is_active: true,
      profile_type: "custom",
    });
  });
});
