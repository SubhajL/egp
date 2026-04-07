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
    plan_code: "free_trial",
    is_active: true,
    created_at: "2026-04-06T00:00:00Z",
    updated_at: "2026-04-06T00:00:00Z",
  },
};

const EMPTY_DASHBOARD_SUMMARY = {
  kpis: {
    active_projects: 0,
    discovered_today: 0,
    winner_projects_this_week: 0,
    closed_today: 0,
    changed_tor_projects: 0,
    crawl_success_rate_percent: 100,
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

async function fulfillJson(route: Route, status: number, body: unknown) {
  await route.fulfill({
    status,
    contentType: "application/json",
    body: JSON.stringify(body),
  });
}

function buildRulesResponse(planCode: "free_trial" | "one_time_search_pack" | "monthly_membership") {
  const keywordLimit = planCode === "monthly_membership" ? 5 : 1;
  return {
    profiles: [
      {
        id: "profile-1",
        name: "Keyword Watchlist",
        profile_type: "custom",
        is_active: true,
        max_pages_per_keyword: 15,
        close_consulting_after_days: 30,
        close_stale_after_days: 45,
        keywords: ["analytics"],
        created_at: "2026-04-06T00:00:00Z",
        updated_at: "2026-04-06T00:00:00Z",
      },
    ],
    entitlements: {
      plan_code: planCode,
      plan_label:
        planCode === "free_trial"
          ? "Free Trial"
          : planCode === "one_time_search_pack"
            ? "One-Time Search Pack"
            : "Monthly Membership",
      subscription_status: "active",
      has_active_subscription: true,
      keyword_limit: keywordLimit,
      active_keyword_count: 1,
      remaining_keyword_slots: Math.max(keywordLimit - 1, 0),
      active_keywords: ["analytics"],
      over_keyword_limit: false,
      runs_allowed: true,
      exports_allowed: planCode !== "free_trial",
      document_download_allowed: planCode !== "free_trial",
      notifications_allowed: planCode !== "free_trial",
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
      tenant_crawl_interval_hours: planCode === "monthly_membership" ? 6 : null,
      default_crawl_interval_hours: 24,
      effective_crawl_interval_hours: planCode === "monthly_membership" ? 6 : 24,
      source: "tenant_settings + default schedule policy",
    },
  };
}

async function mockApp(page: Page, rulesBody: ReturnType<typeof buildRulesResponse>) {
  await page.route("**/v1/**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const key = `${request.method()} ${url.pathname}`;

    switch (key) {
      case "GET /v1/me":
        await fulfillJson(route, 200, CURRENT_SESSION);
        return;
      case "GET /v1/rules":
        await fulfillJson(route, 200, rulesBody);
        return;
      case "GET /v1/dashboard/summary":
        await fulfillJson(route, 200, EMPTY_DASHBOARD_SUMMARY);
        return;
      default:
        await fulfillJson(route, 500, { detail: `Unhandled mock route: ${key}` });
    }
  });
}

test("free trial rules page shows limited tabs and upgrade copy", async ({ page }) => {
  await mockApp(page, buildRulesResponse("free_trial"));

  await page.goto("/rules");

  await expect(page.getByRole("heading", { name: "คำค้นติดตาม" })).toBeVisible();
  await expect(page.getByText("ทดลองใช้ฟรี", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "คำค้นของฉัน" })).toBeVisible();
  await expect(page.getByRole("button", { name: "ความถี่การติดตาม" })).toBeVisible();
  await expect(page.getByRole("button", { name: "สิทธิ์แพ็กเกจ" })).toBeVisible();
  await expect(page.getByRole("button", { name: "การแจ้งเตือน" })).toHaveCount(0);

  await page.getByRole("button", { name: "สิทธิ์แพ็กเกจ" }).click();
  await expect(page.getByText("อัปเกรดเพื่อปลดล็อกฟีเจอร์เพิ่มเติม")).toBeVisible();
});

test("one-time plan rules page exposes notifications tab", async ({ page }) => {
  await mockApp(page, buildRulesResponse("one_time_search_pack"));

  await page.goto("/rules");

  await expect(page.getByText("แพ็กเกจค้นหาครั้งเดียว", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "การแจ้งเตือน" })).toBeVisible();
  await expect(page.getByRole("button", { name: "ผลลัพธ์และสิทธิ์" })).toBeVisible();
});

test("monthly plan rules page allows editable schedule flow", async ({ page }) => {
  await mockApp(page, buildRulesResponse("monthly_membership"));

  await page.goto("/rules");
  await page.getByRole("button", { name: "ความถี่การติดตาม" }).click();

  await expect(page.getByText("สมาชิกรายเดือน", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "บันทึก" })).toBeVisible();
  await expect(page.getByLabel("ความถี่การติดตาม")).toBeVisible();
  await expect(page.getByText("ใช้งานจริง: ทุก 6 ชั่วโมง")).toBeVisible();
});
