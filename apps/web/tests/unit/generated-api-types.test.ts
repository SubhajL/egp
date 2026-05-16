import { describe, expect, it } from "vitest";

import openapiSchema from "../../src/lib/generated/openapi.json";
import type { paths } from "../../src/lib/generated/api-types";
import type {
  AdminSnapshotResponse,
  AdminTenantStorageSettings,
  AuditLogListResponse,
  BillingListResponse,
  BillingPlansResponse,
  CurrentSessionResponse,
  DashboardSummaryResponse,
  DocumentListResponse,
  MfaSetupResponse,
  ProjectDetailResponse,
  ProjectListResponse as ApiProjectListResponse,
  RunListResponse,
  RulesResponse,
  SupportSummaryResponse,
  SupportTenantListResponse,
  WebhookListResponse,
} from "../../src/lib/api";

type ProjectListResponse =
  paths["/v1/projects"]["get"]["responses"][200]["content"]["application/json"];
type ProjectDetailOpenApiResponse =
  paths["/v1/projects/{project_id}"]["get"]["responses"][200]["content"]["application/json"];
type DocumentListOpenApiResponse =
  paths["/v1/documents/projects/{project_id}"]["get"]["responses"][200]["content"]["application/json"];
type RulesOpenApiResponse =
  paths["/v1/rules"]["get"]["responses"][200]["content"]["application/json"];
type RunListOpenApiResponse =
  paths["/v1/runs"]["get"]["responses"][200]["content"]["application/json"];
type DashboardOpenApiResponse =
  paths["/v1/dashboard/summary"]["get"]["responses"][200]["content"]["application/json"];
type BillingListOpenApiResponse =
  paths["/v1/billing/records"]["get"]["responses"][200]["content"]["application/json"];
type BillingPlansOpenApiResponse =
  paths["/v1/billing/plans"]["get"]["responses"][200]["content"]["application/json"];
type AdminSnapshotOpenApiResponse =
  paths["/v1/admin"]["get"]["responses"][200]["content"]["application/json"];
type AuditLogOpenApiResponse =
  paths["/v1/admin/audit-log"]["get"]["responses"][200]["content"]["application/json"];
type StorageSettingsOpenApiResponse =
  paths["/v1/admin/storage"]["get"]["responses"][200]["content"]["application/json"];
type SupportTenantsOpenApiResponse =
  paths["/v1/admin/support/tenants"]["get"]["responses"][200]["content"]["application/json"];
type SupportSummaryOpenApiResponse =
  paths["/v1/admin/support/tenants/{tenant_id}/summary"]["get"]["responses"][200]["content"]["application/json"];
type WebhookListOpenApiResponse =
  paths["/v1/webhooks"]["get"]["responses"][200]["content"]["application/json"];
type SessionOpenApiResponse =
  paths["/v1/me"]["get"]["responses"][200]["content"]["application/json"];
type MfaSetupOpenApiResponse =
  paths["/v1/auth/mfa/setup"]["post"]["responses"][200]["content"]["application/json"];

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

  it("covers all migrated frontend domains with generated endpoint types", () => {
    const runs: RunListResponse = { runs: [], total: 0, limit: 50, offset: 0 };
    const dashboard: DashboardSummaryResponse = {
      kpis: {
        active_projects: 0,
        discovered_today: 0,
        winner_projects_this_week: 0,
        closed_today: 0,
        changed_tor_projects: 0,
        crawl_success_rate_percent: 0,
        failed_runs_recent: 0,
        crawl_success_window_runs: 0,
      },
      recent_runs: [],
      recent_changes: [],
      winner_projects: [],
      daily_discovery: [],
      project_state_breakdown: [],
      cost_summary: {
        window_days: 30,
        currency: "THB",
        estimated_total_thb: "0.00",
        crawl: {
          estimated_cost_thb: "0.00",
          run_count: 0,
          task_count: 0,
          failed_run_count: 0,
        },
        storage: {
          estimated_cost_thb: "0.00",
          document_count: 0,
          total_bytes: 0,
        },
        notifications: {
          estimated_cost_thb: "0.00",
          sent_count: 0,
          failed_webhook_delivery_count: 0,
        },
        payments: {
          estimated_cost_thb: "0.00",
          billing_record_count: 0,
          payment_request_count: 0,
          collected_amount_thb: "0.00",
        },
      },
    };
    const billing: BillingListResponse = {
      records: [],
      total: 0,
      limit: 50,
      offset: 0,
      summary: {
        open_records: 0,
        awaiting_reconciliation: 0,
        outstanding_amount: "0.00",
        collected_amount: "0.00",
      },
    };
    const billingPlans: BillingPlansResponse = { plans: [] };
    const admin: AdminSnapshotResponse = {
      tenant: {
        id: "tenant-1",
        name: "Tenant",
        slug: "tenant",
        plan_code: "starter",
        is_active: true,
        created_at: "2026-05-16T00:00:00Z",
        updated_at: "2026-05-16T00:00:00Z",
      },
      settings: {
        support_email: null,
        billing_contact_email: null,
        timezone: "Asia/Bangkok",
        locale: "th-TH",
        daily_digest_enabled: true,
        weekly_digest_enabled: true,
        crawl_interval_hours: null,
        created_at: null,
        updated_at: null,
      },
      users: [],
      billing: {
        summary: {
          open_records: 0,
          awaiting_reconciliation: 0,
          outstanding_amount: "0.00",
          collected_amount: "0.00",
        },
        current_subscription: null,
        upcoming_subscription: null,
        records: [],
      },
    };
    const auditLog: AuditLogListResponse = { items: [], total: 0, limit: 50, offset: 0 };
    const storage: AdminTenantStorageSettings = {
      provider: "managed",
      connection_status: "connected",
      account_email: null,
      folder_label: null,
      folder_path_hint: null,
      provider_folder_id: null,
      provider_folder_url: null,
      managed_fallback_enabled: true,
      managed_backup_enabled: true,
      last_validated_at: null,
      last_validation_error: null,
      has_credentials: false,
      credential_type: null,
      credential_updated_at: null,
      created_at: null,
      updated_at: null,
    };
    const supportTenants: SupportTenantListResponse = { tenants: [] };
    const supportSummary: SupportSummaryResponse = {
      tenant: {
        id: "tenant-1",
        name: "Tenant",
        slug: "tenant",
        plan_code: "starter",
        is_active: true,
        support_email: null,
        billing_contact_email: null,
        active_user_count: 0,
      },
      triage: {
        failed_runs_recent: 0,
        pending_document_reviews: 0,
        failed_webhook_deliveries: 0,
        outstanding_billing_records: 0,
      },
      cost_summary: dashboard.cost_summary,
      storage_diagnostics: {
        provider: "managed",
        connection_status: "connected",
        account_email: null,
        provider_folder_id: null,
        provider_folder_url: null,
        managed_fallback_enabled: true,
        managed_backup_enabled: true,
        has_credentials: false,
        last_validated_at: null,
        last_validation_error: null,
      },
      alerts: [],
      recent_failed_runs: [],
      pending_reviews: [],
      failed_webhooks: [],
      billing_issues: [],
    };
    const webhooks: WebhookListResponse = { webhooks: [] };
    const session: CurrentSessionResponse = {
      user: {
        id: null,
        subject: "auth0|user-1",
        email: "ops@example.com",
        full_name: null,
        role: "admin",
        status: "active",
        email_verified: true,
        email_verified_at: null,
        mfa_enabled: false,
      },
      tenant: admin.tenant,
      requires_billing_update: false,
    };
    const mfaSetup: MfaSetupResponse = { secret: "secret", otpauth_uri: "otpauth://totp" };

    const generatedRuns: RunListOpenApiResponse = runs;
    const generatedDashboard: DashboardOpenApiResponse = dashboard;
    const generatedBilling: BillingListOpenApiResponse = billing;
    const generatedPlans: BillingPlansOpenApiResponse = billingPlans;
    const generatedAdmin: AdminSnapshotOpenApiResponse = admin;
    const generatedAuditLog: AuditLogOpenApiResponse = auditLog;
    const generatedStorage: StorageSettingsOpenApiResponse = storage;
    const generatedSupportTenants: SupportTenantsOpenApiResponse = supportTenants;
    const generatedSupportSummary: SupportSummaryOpenApiResponse = supportSummary;
    const generatedWebhooks: WebhookListOpenApiResponse = webhooks;
    const generatedSession: SessionOpenApiResponse = session;
    const generatedMfaSetup: MfaSetupOpenApiResponse = mfaSetup;

    expect(generatedRuns.runs).toEqual([]);
    expect(generatedDashboard.cost_summary.window_days).toBe(30);
    expect(generatedBilling.records).toEqual([]);
    expect(generatedPlans.plans).toEqual([]);
    expect(generatedAdmin.users).toEqual([]);
    expect(generatedAuditLog.items).toEqual([]);
    expect(generatedStorage.provider).toBe("managed");
    expect(generatedSupportTenants.tenants).toEqual([]);
    expect(generatedSupportSummary.tenant.id).toBe("tenant-1");
    expect(generatedWebhooks.webhooks).toEqual([]);
    expect(generatedSession.user.subject).toBe("auth0|user-1");
    expect(generatedMfaSetup.secret).toBe("secret");
  });
});
