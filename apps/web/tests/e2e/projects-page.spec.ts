import { expect, test, type Page, type Route } from "@playwright/test";

const CURRENT_SESSION = {
  user: {
    id: "user-1",
    subject: "user-1",
    email: "analyst@example.com",
    full_name: "Example Analyst",
    role: "admin",
    status: "active",
    email_verified: true,
    email_verified_at: "2026-04-06T00:00:00Z",
    mfa_enabled: false,
  },
  tenant: {
    id: "tenant-1",
    name: "Example Tenant",
    slug: "example-tenant",
    plan_code: "monthly_membership",
    is_active: true,
    created_at: "2026-04-06T00:00:00Z",
    updated_at: "2026-04-06T00:00:00Z",
  },
};

const RULES_RESPONSE = {
  profiles: [],
  entitlements: {
    plan_code: "monthly_membership",
    plan_label: "Monthly Membership",
    subscription_status: "active",
    has_active_subscription: true,
    keyword_limit: 5,
    active_keyword_count: 1,
    remaining_keyword_slots: 4,
    active_keywords: ["analytics"],
    over_keyword_limit: false,
    runs_allowed: true,
    exports_allowed: true,
    document_download_allowed: true,
    notifications_allowed: true,
    source: "billing_subscriptions + crawl_profile_keywords",
  },
  closure_rules: {
    close_on_winner_status: true,
    close_on_contract_status: true,
    winner_status_terms: ["ประกาศผู้ชนะ"],
    contract_status_terms: ["ลงนามสัญญา"],
    consulting_timeout_days: 30,
    stale_no_tor_days: 45,
    stale_eligible_states: ["discovered"],
    source: "packages/crawler-core/src/egp_crawler_core/closure_rules.py",
  },
  notification_rules: {
    supported_channels: ["in_app", "email", "webhook"],
    supported_types: ["new_project"],
    event_wiring_complete: true,
    source: "packages/notification-core/src/egp_notifications/service.py",
  },
  schedule_rules: {
    supported_trigger_types: ["schedule", "manual"],
    schedule_execution_supported: true,
    editable_in_product: true,
    tenant_crawl_interval_hours: 6,
    default_crawl_interval_hours: 24,
    effective_crawl_interval_hours: 6,
    source: "tenant_settings + default schedule policy",
  },
};

const PROJECTS_RESPONSE = {
  projects: [
    {
      id: "project-1",
      tenant_id: "tenant-1",
      canonical_project_id: "egp-analytics",
      project_number: "EGP-001",
      project_name: "ระบบวิเคราะห์ข้อมูลจัดซื้อ",
      organization_name: "กรมตัวอย่าง",
      procurement_type: "services",
      proposal_submission_date: "2026-05-01",
      budget_amount: "1250000.00",
      project_state: "open_invitation",
      closed_reason: null,
      source_status_text: "หนังสือเชิญชวน/ประกาศเชิญชวน",
      has_changed_tor: false,
      first_seen_at: "2026-04-20T00:00:00Z",
      last_seen_at: "2026-04-24T00:00:00Z",
      last_changed_at: "2026-04-24T00:00:00Z",
      created_at: "2026-04-20T00:00:00Z",
      updated_at: "2026-04-24T00:00:00Z",
    },
  ],
  total: 1,
  limit: 50,
  offset: 0,
};

const EMPTY_RUNS_RESPONSE = {
  runs: [],
  total: 0,
  limit: 10,
  offset: 0,
};

const ACTIVE_RUNS_RESPONSE = {
  runs: [
    {
      run: {
        id: "run-1234567890ab",
        tenant_id: "tenant-1",
        trigger_type: "manual",
        status: "running",
        profile_id: "profile-1",
        started_at: "2026-04-24T02:00:00Z",
        finished_at: null,
        summary_json: {
          projects_seen: 2,
          live_progress: {
            stage: "page_scan_finished",
            keyword: "analytics",
            page_num: 2,
            eligible_count: 3,
            updated_at: "2026-04-24T02:00:05Z",
          },
        },
        error_count: 0,
        created_at: "2026-04-24T02:00:00Z",
      },
      tasks: [
        {
          id: "task-1",
          run_id: "run-1234567890ab",
          task_type: "discover",
          project_id: null,
          keyword: "analytics",
          status: "running",
          attempts: 1,
          started_at: "2026-04-24T02:00:00Z",
          finished_at: null,
          payload: null,
          result_json: null,
          created_at: "2026-04-24T02:00:00Z",
        },
      ],
    },
  ],
  total: 1,
  limit: 10,
  offset: 0,
};

async function fulfillJson(route: Route, status: number, body: unknown) {
  await route.fulfill({
    status,
    contentType: "application/json",
    body: JSON.stringify(body),
  });
}

async function mockProjectsApp(page: Page) {
  let runsRequestCount = 0;

  await page.route("**/v1/**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const key = `${request.method()} ${url.pathname}`;

    switch (key) {
      case "GET /v1/me":
        await fulfillJson(route, 200, CURRENT_SESSION);
        return;
      case "GET /v1/rules":
        await fulfillJson(route, 200, RULES_RESPONSE);
        return;
      case "GET /v1/projects":
        await fulfillJson(route, 200, PROJECTS_RESPONSE);
        return;
      case "POST /v1/rules/recrawl":
        await fulfillJson(route, 202, {
          queued_job_count: 1,
          queued_keywords: ["analytics"],
        });
        return;
      case "GET /v1/runs":
        runsRequestCount += 1;
        await fulfillJson(
          route,
          200,
          runsRequestCount === 1 ? EMPTY_RUNS_RESPONSE : ACTIVE_RUNS_RESPONSE,
        );
        return;
      default:
        await fulfillJson(route, 500, { detail: `Unhandled mock route: ${key}` });
    }
  });
}

test("projects page shows worker-backed crawl activity after manual recrawl", async ({
  page,
}) => {
  await mockProjectsApp(page);

  await page.goto("/projects");

  await expect(page.getByRole("button", { name: "Crawl ใหม่" })).toBeVisible();

  await page.getByRole("button", { name: "Crawl ใหม่" }).click();

  await expect(page.getByText("เริ่ม crawl 1 งานจาก 1 คำค้นแล้ว")).toBeVisible();
  await expect(page.getByRole("heading", { name: "สถานะการ crawl ล่าสุด" })).toBeVisible();
  await expect(page.getByText("กำลังทำงาน 1 งาน")).toBeVisible();
  await expect(page.getByText("ทริกเกอร์: ด้วยตนเอง")).toBeVisible();
  await expect(
    page.getByText('สแกนหน้าผลลัพธ์ · คำค้น "analytics" · หน้า 2 · พบ 3 โครงการที่เข้าเงื่อนไข'),
  ).toBeVisible();
  await expect(page.getByText("ค้นพบแล้ว 2 โครงการ")).toBeVisible();
  await expect(page.getByRole("link", { name: "ดูหน้าการทำงานทั้งหมด" })).toBeVisible();
});

test("project detail links expired document-download failures to billing", async ({ page }) => {
  await page.route("**/v1/**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const key = `${request.method()} ${url.pathname}`;

    switch (key) {
      case "GET /v1/me":
        await fulfillJson(route, 200, CURRENT_SESSION);
        return;
      case "GET /v1/rules":
        await fulfillJson(route, 200, {
          ...RULES_RESPONSE,
          entitlements: {
            ...RULES_RESPONSE.entitlements,
            plan_code: "one_time_search_pack",
            plan_label: "One-Time Search Pack",
            subscription_status: "expired",
            has_active_subscription: false,
            runs_allowed: false,
            exports_allowed: false,
            document_download_allowed: false,
            notifications_allowed: false,
          },
        });
        return;
      case "GET /v1/projects/project-1":
        await fulfillJson(route, 200, {
          project: PROJECTS_RESPONSE.projects[0],
          aliases: [],
          status_events: [],
        });
        return;
      case "GET /v1/documents/projects/project-1":
        await fulfillJson(route, 200, {
          documents: [
            {
              id: "document-1",
              project_id: "project-1",
              document_type: "tor",
              document_phase: "final",
              source_label: "เอกสารประกวดราคา",
              source_url: null,
              source_status_text: null,
              published_at: null,
              file_name: "tor.pdf",
              mime_type: "application/pdf",
              size_bytes: 1024,
              sha256: "abc123",
              storage_key: "tenant/project/tor.pdf",
              is_current: true,
              supersedes_document_id: null,
              extracted_text_key: null,
              created_at: "2026-05-13T00:00:00Z",
            },
          ],
        });
        return;
      case "GET /v1/projects/project-1/crawl-evidence":
        await fulfillJson(route, 200, { evidence: [] });
        return;
      case "GET /v1/documents/document-1/download-link":
        await fulfillJson(route, 403, {
          detail: "active subscription required for document downloads",
        });
        return;
      default:
        await fulfillJson(route, 500, { detail: `Unhandled mock route: ${key}` });
    }
  });

  await page.goto("/projects/project-1");
  await page.getByRole("button", { name: "ดาวน์โหลดเอกสาร" }).click();

  await expect(
    page.getByText("แพ็กเกจ One-Time Search Pack หมดอายุแล้ว กรุณาต่ออายุเพื่อดาวน์โหลดเอกสาร"),
  ).toBeVisible();
  await expect(page.getByRole("link", { name: "ไปที่หน้าบิลและชำระเงิน" })).toHaveAttribute(
    "href",
    "/billing",
  );
});
