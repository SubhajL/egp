import { describe, expect, it } from "vitest";

import openapiSchema from "../../src/lib/generated/openapi.json";
import type { paths } from "../../src/lib/generated/api-types";
import type {
  DocumentListResponse,
  ProjectDetailResponse,
  ProjectListResponse as ApiProjectListResponse,
  RulesResponse,
} from "../../src/lib/api";

type ProjectListResponse =
  paths["/v1/projects"]["get"]["responses"][200]["content"]["application/json"];
type ProjectDetailOpenApiResponse =
  paths["/v1/projects/{project_id}"]["get"]["responses"][200]["content"]["application/json"];
type DocumentListOpenApiResponse =
  paths["/v1/documents/projects/{project_id}"]["get"]["responses"][200]["content"]["application/json"];
type RulesOpenApiResponse =
  paths["/v1/rules"]["get"]["responses"][200]["content"]["application/json"];

describe("generated API contract", () => {
  it("commits the backend OpenAPI schema used for type generation", () => {
    expect(openapiSchema.openapi).toBe("3.1.0");
    expect(openapiSchema.info.title).toBe("e-GP Intelligence Platform");
    expect(openapiSchema.paths).toHaveProperty("/v1/projects");
  });

  it("exposes generated response types for frontend callers", () => {
    const response: ApiProjectListResponse = {
      projects: [],
      total: 0,
      limit: 50,
      offset: 0,
    };
    const generatedResponse: ProjectListResponse = response;

    expect(response.projects).toEqual([]);
    expect(generatedResponse.limit).toBe(50);
  });

  it("covers the first migrated frontend domains with generated endpoint types", () => {
    const projectList: ApiProjectListResponse = {
      projects: [],
      total: 0,
      limit: 50,
      offset: 0,
    };
    const projectDetail: ProjectDetailResponse = {
      project: {
        id: "project-1",
        tenant_id: "tenant-1",
        canonical_project_id: "canonical-1",
        project_number: null,
        project_name: "Road upgrade",
        organization_name: "City",
        procurement_type: "goods",
        proposal_submission_date: null,
        budget_amount: null,
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
    const documents: DocumentListResponse = { documents: [] };
    const rules: RulesResponse = {
      profiles: [],
      entitlements: {
        plan_code: null,
        plan_label: null,
        subscription_status: null,
        has_active_subscription: false,
        keyword_limit: null,
        active_keyword_count: 0,
        remaining_keyword_slots: null,
        active_keywords: [],
        over_keyword_limit: false,
        runs_allowed: false,
        exports_allowed: false,
        document_download_allowed: false,
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
        supported_channels: [],
        supported_types: [],
        event_wiring_complete: false,
        source: "default",
      },
      schedule_rules: {
        supported_trigger_types: [],
        schedule_execution_supported: false,
        editable_in_product: false,
        tenant_crawl_interval_hours: null,
        default_crawl_interval_hours: 24,
        effective_crawl_interval_hours: 24,
        source: "default",
      },
    };

    const generatedProjectList: ProjectListOpenApiResponse = projectList;
    const generatedProjectDetail: ProjectDetailOpenApiResponse = projectDetail;
    const generatedDocuments: DocumentListOpenApiResponse = documents;
    const generatedRules: RulesOpenApiResponse = rules;

    expect(generatedProjectList.projects).toEqual([]);
    expect(generatedProjectDetail.project.id).toBe("project-1");
    expect(generatedDocuments.documents).toEqual([]);
    expect(generatedRules.profiles).toEqual([]);
  });
});
