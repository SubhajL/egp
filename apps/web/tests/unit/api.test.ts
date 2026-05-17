import { afterEach, describe, expect, it, vi } from "vitest";
import { readFileSync } from "node:fs";

import {
  ApiError,
  acceptInvite,
  connectTenantStorage,
  createAdminUser,
  createBillingPaymentRequest,
  createBillingRecord,
  createRuleProfile,
  createWebhook,
  fetchAdminSnapshot,
  fetchAuditLog,
  fetchBillingPlans,
  fetchBillingRecords,
  fetchDashboardSummary,
  fetchDocuments,
  fetchMe,
  fetchProjectDetail,
  fetchProjects,
  fetchRules,
  fetchRuns,
  fetchSupportSummary,
  fetchSupportTenants,
  fetchTenantStorageSettings,
  fetchWebhooks,
  login,
  register,
  startGoogleDriveOAuth,
  updateTenantSettings,
} from "../../src/lib/api";
import type {
  AdminSnapshotResponse,
  AdminTenantStorageSettings,
  BillingListResponse,
  BillingPlansResponse,
  CurrentSessionResponse,
  DashboardSummaryResponse,
  DocumentListResponse,
  ProjectDetailResponse,
  ProjectListResponse,
  RunListResponse,
  RulesResponse,
  SupportSummaryResponse,
  SupportTenantListResponse,
  WebhookListResponse,
  WebhookSubscription,
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
  it("uses generated OpenAPI types for every migrated frontend domain", () => {
    const source = readFileSync("src/lib/api.ts", "utf8");

    expect(source).toContain('from "./generated/api-types"');
    for (const manualTypePrefix of [
      "export type ProjectSummary = {",
      "export type DocumentSummary = {",
      "export type RulesResponse = {",
      "export type AuthenticatedUser = {",
      "export type AuthTenant = {",
      "export type CurrentSessionResponse = {",
      "export type RunSummary = {",
      "export type TaskSummary = {",
      "export type RunDetailResponse = {",
      "export type RunListResponse = {",
      "export type DashboardKpis = {",
      "export type DashboardSummaryResponse = {",
      "export type BillingRecord = {",
      "export type BillingListResponse = {",
      "export type BillingPlansResponse = {",
      "export type AdminTenantSummary = {",
      "export type AdminSnapshotResponse = {",
      "export type AdminTenantStorageSettings = {",
      "export type WebhookSubscription = {",
      "export type WebhookListResponse = {",
      "export type AuditLogEvent = {",
      "export type AuditLogListResponse = {",
      "export type SupportTenant = {",
      "export type SupportSummaryResponse = {",
      "export type RegisterInput = {",
      "export type LoginInput = {",
      "export type AcceptInviteInput = {",
    ]) {
      expect(source).not.toContain(manualTypePrefix);
    }
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

describe("runs, dashboard, billing, admin, storage, webhook, and auth wrappers", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("builds run and dashboard requests with generated response shapes", async () => {
    const runs: RunListResponse = { runs: [], total: 0, limit: 10, offset: 5 };
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
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(Response.json(runs))
      .mockResolvedValueOnce(Response.json(dashboard));
    vi.stubGlobal("fetch", fetchMock);

    await expect(fetchRuns({ limit: 10, offset: 5 })).resolves.toEqual(runs);
    await expect(fetchDashboardSummary()).resolves.toEqual(dashboard);

    const runsUrl = new URL(fetchMock.mock.calls[0][0] as string);
    expect(runsUrl.pathname).toBe("/v1/runs");
    expect(runsUrl.searchParams.get("limit")).toBe("10");
    expect(runsUrl.searchParams.get("offset")).toBe("5");
    expect(new URL(fetchMock.mock.calls[1][0] as string).pathname).toBe(
      "/v1/dashboard/summary",
    );
  });

  it("builds billing requests with generated payload defaults", async () => {
    const billing: BillingListResponse = {
      records: [],
      total: 0,
      limit: 50,
      offset: 0,
      current_subscription: null,
      summary: {
        open_records: 0,
        awaiting_reconciliation: 0,
        outstanding_amount: "0.00",
        collected_amount: "0.00",
      },
    };
    const plans: BillingPlansResponse = { plans: [] };
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(Response.json(billing))
      .mockResolvedValueOnce(Response.json(plans))
      .mockResolvedValueOnce(Response.json({ record: {}, payment_requests: [], payments: [], events: [], subscription: null }))
      .mockResolvedValueOnce(Response.json({ record: {}, payment_requests: [], payments: [], events: [], subscription: null }));
    vi.stubGlobal("fetch", fetchMock);

    await expect(fetchBillingRecords()).resolves.toEqual(billing);
    await expect(fetchBillingPlans()).resolves.toEqual(plans);
    await createBillingRecord({
      record_number: "INV-1",
      plan_code: "starter",
      billing_period_start: "2026-05-16",
    });
    await createBillingPaymentRequest("record-1", { provider: "opn" });

    expect(new URL(fetchMock.mock.calls[0][0] as string).pathname).toBe(
      "/v1/billing/records",
    );
    expect(new URL(fetchMock.mock.calls[1][0] as string).pathname).toBe(
      "/v1/billing/plans",
    );
    expect(JSON.parse(fetchMock.mock.calls[2][1]?.body as string)).toMatchObject({
      record_number: "INV-1",
      status: "awaiting_payment",
      currency: "THB",
    });
    expect(JSON.parse(fetchMock.mock.calls[3][1]?.body as string)).toStrictEqual({
      provider: "opn",
      payment_method: "promptpay_qr",
      expires_in_minutes: 30,
    });
  });

  it("builds admin support storage and webhook requests with stable wrappers", async () => {
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
    const webhooks: WebhookListResponse = { webhooks: [] };
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
        active_user_count: 1,
      },
      triage: {
        failed_runs_recent: 0,
        pending_document_reviews: 0,
        failed_webhook_deliveries: 0,
        outstanding_billing_records: 0,
      },
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
    const createdWebhook: WebhookSubscription = {
      id: "webhook-1",
      name: "Ops",
      url: "https://example.com/hook",
      notification_types: ["new_project"],
      is_active: true,
      created_at: "2026-05-16T00:00:00Z",
      updated_at: "2026-05-16T00:00:00Z",
      last_delivery_status: null,
      last_delivery_attempted_at: null,
      last_delivered_at: null,
      last_response_status_code: null,
    };
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(Response.json(admin))
      .mockResolvedValueOnce(Response.json({ items: [], total: 0, limit: 50, offset: 0 }))
      .mockResolvedValueOnce(Response.json(supportTenants))
      .mockResolvedValueOnce(Response.json(supportSummary))
      .mockResolvedValueOnce(Response.json(storage))
      .mockResolvedValueOnce(Response.json(storage))
      .mockResolvedValueOnce(Response.json({ provider: "google_drive", authorization_url: "https://example.com/oauth", state: "state" }))
      .mockResolvedValueOnce(Response.json(webhooks))
      .mockResolvedValueOnce(Response.json(createdWebhook));
    vi.stubGlobal("fetch", fetchMock);

    await fetchAdminSnapshot({ tenant_id: "tenant-1" });
    await fetchAuditLog({ tenant_id: "tenant-1", source: "billing" });
    await fetchSupportTenants({ query: "tenant", limit: 5 });
    await fetchSupportSummary({ tenant_id: "tenant-1", window_days: 7 });
    await fetchTenantStorageSettings({ tenant_id: "tenant-1" });
    await connectTenantStorage({
      tenant_id: "tenant-1",
      provider: "google_drive",
      credential_type: "oauth_tokens",
      credentials: { refresh_token: "token" },
    });
    await startGoogleDriveOAuth({ tenant_id: "tenant-1" });
    await fetchWebhooks({ tenant_id: "tenant-1" });
    await createWebhook({
      tenant_id: "tenant-1",
      name: "Ops",
      url: "https://example.com/hook",
      notification_types: ["new_project"],
      signing_secret: "secret",
    });

    expect(new URL(fetchMock.mock.calls[0][0] as string).pathname).toBe("/v1/admin");
    expect(new URL(fetchMock.mock.calls[3][0] as string).pathname).toBe(
      "/v1/admin/support/tenants/tenant-1/summary",
    );
    expect(JSON.parse(fetchMock.mock.calls[5][1]?.body as string)).toStrictEqual({
      tenant_id: "tenant-1",
      provider: "google_drive",
      credential_type: "oauth_tokens",
      credentials: { refresh_token: "token" },
    });
    expect(JSON.parse(fetchMock.mock.calls[8][1]?.body as string)).toMatchObject({
      tenant_id: "tenant-1",
      name: "Ops",
      signing_secret: "secret",
    });
  });

  it("builds auth and session requests with generated response shapes", async () => {
    const session: CurrentSessionResponse = {
      user: {
        id: "user-1",
        subject: "auth0|user-1",
        email: "ops@example.com",
        full_name: "Ops User",
        role: "admin",
        status: "active",
        email_verified: true,
        email_verified_at: "2026-05-16T00:00:00Z",
        mfa_enabled: false,
      },
      tenant: {
        id: "tenant-1",
        name: "Tenant",
        slug: "tenant",
        plan_code: "starter",
        is_active: true,
        created_at: "2026-05-16T00:00:00Z",
        updated_at: "2026-05-16T00:00:00Z",
      },
      requires_billing_update: false,
    };
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(Response.json(session))
      .mockResolvedValueOnce(Response.json(session))
      .mockResolvedValueOnce(Response.json(session))
      .mockResolvedValueOnce(Response.json(session))
      .mockResolvedValueOnce(Response.json({
        id: "user-2",
        email: "new@example.com",
        full_name: null,
        role: "viewer",
        status: "active",
        email_verified_at: null,
        mfa_enabled: false,
        created_at: "2026-05-16T00:00:00Z",
        updated_at: "2026-05-16T00:00:00Z",
        notification_preferences: {},
      }))
      .mockResolvedValueOnce(Response.json({
        support_email: "support@example.com",
        billing_contact_email: null,
        timezone: "Asia/Bangkok",
        locale: "th-TH",
        daily_digest_enabled: true,
        weekly_digest_enabled: true,
        crawl_interval_hours: null,
        created_at: null,
        updated_at: null,
      }));
    vi.stubGlobal("fetch", fetchMock);

    await expect(register({
      company_name: "Tenant",
      email: "ops@example.com",
      password: "long-password",
    })).resolves.toEqual(session);
    await expect(login({
      email: "ops@example.com",
      password: "long-password",
      tenant_slug: "tenant",
    })).resolves.toEqual(session);
    await expect(acceptInvite({
      token: "invite-token",
      password: "long-password",
    })).resolves.toEqual(session);
    await expect(fetchMe()).resolves.toEqual(session);
    await createAdminUser({ email: "new@example.com" });
    await updateTenantSettings({ support_email: "support@example.com" });

    expect(new URL(fetchMock.mock.calls[0][0] as string).pathname).toBe(
      "/v1/auth/register",
    );
    expect(new URL(fetchMock.mock.calls[3][0] as string).pathname).toBe("/v1/me");
    expect(JSON.parse(fetchMock.mock.calls[4][1]?.body as string)).toMatchObject({
      email: "new@example.com",
      role: "viewer",
      status: "active",
    });
    expect(JSON.parse(fetchMock.mock.calls[5][1]?.body as string)).toMatchObject({
      support_email: "support@example.com",
    });
  });
});
