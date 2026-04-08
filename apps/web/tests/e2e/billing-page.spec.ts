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
      billing_record_count: 1,
      payment_request_count: 0,
      collected_amount_thb: "0.00",
    },
  },
};

function buildPlansResponse() {
  return {
    plans: [
      {
        code: "free_trial",
        label: "Free Trial",
        description: "ทดลองใช้ฟรี 7 วัน",
        currency: "THB",
        amount_due: "0.00",
        billing_interval: "trial",
        keyword_limit: 1,
        duration_days: 7,
        duration_months: null,
      },
      {
        code: "one_time_search_pack",
        label: "One-Time Search Pack",
        description: "ค้นหาแบบจ่ายครั้งเดียว",
        currency: "THB",
        amount_due: "300.00",
        billing_interval: "one_time",
        keyword_limit: 1,
        duration_days: 3,
        duration_months: null,
      },
      {
        code: "monthly_membership",
        label: "Monthly Membership",
        description: "สมาชิกรายเดือน",
        currency: "THB",
        amount_due: "1500.00",
        billing_interval: "monthly",
        keyword_limit: 5,
        duration_days: null,
        duration_months: 1,
      },
    ],
  };
}

function buildRulesResponse(planCode: "free_trial" | "one_time_search_pack" | "monthly_membership") {
  const isMonthly = planCode === "monthly_membership";
  const isFreeTrial = planCode === "free_trial";
  return {
    profiles: [],
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
      keyword_limit: isMonthly ? 5 : 1,
      active_keyword_count: 1,
      remaining_keyword_slots: isMonthly ? 4 : 0,
      active_keywords: ["analytics"],
      over_keyword_limit: false,
      runs_allowed: true,
      exports_allowed: !isFreeTrial,
      document_download_allowed: !isFreeTrial,
      notifications_allowed: !isFreeTrial,
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
      tenant_crawl_interval_hours: isMonthly ? 6 : null,
      default_crawl_interval_hours: 24,
      effective_crawl_interval_hours: isMonthly ? 6 : 24,
      source: "tenant_settings + default schedule policy",
    },
  };
}

function buildBillingRecordsResponse() {
  return {
    records: [
      {
        record: {
          id: "record-trial-1",
          tenant_id: "tenant-1",
          record_number: "TRIAL-2026-0001",
          plan_code: "free_trial",
          status: "paid",
          billing_period_start: "2026-04-06",
          billing_period_end: "2026-04-12",
          due_at: null,
          issued_at: "2026-04-06T00:00:00Z",
          paid_at: "2026-04-06T00:00:00Z",
          currency: "THB",
          amount_due: "0.00",
          reconciled_total: "0.00",
          outstanding_balance: "0.00",
          upgrade_from_subscription_id: null,
          upgrade_mode: "none",
          notes: "trial started",
          created_at: "2026-04-06T00:00:00Z",
          updated_at: "2026-04-06T00:00:00Z",
        },
        payment_requests: [],
        payments: [],
        events: [],
        subscription: {
          id: "sub-trial-1",
          tenant_id: "tenant-1",
          billing_record_id: "record-trial-1",
          plan_code: "free_trial",
          subscription_status: "active",
          billing_period_start: "2026-04-06",
          billing_period_end: "2026-04-12",
          keyword_limit: 1,
          activated_at: "2026-04-06T00:00:00Z",
          activated_by_payment_id: null,
          created_at: "2026-04-06T00:00:00Z",
          updated_at: "2026-04-06T00:00:00Z",
        },
      },
    ],
    total: 1,
    limit: 50,
    offset: 0,
    summary: {
      open_records: 0,
      awaiting_reconciliation: 0,
      outstanding_amount: "0.00",
      collected_amount: "0.00",
    },
  };
}

function buildUpgradeResponse() {
  return {
    record: {
      id: "record-upgrade-1",
      tenant_id: "tenant-1",
      record_number: "UPG-MONTHLY-20260408",
      plan_code: "monthly_membership",
      status: "awaiting_payment",
      billing_period_start: "2026-04-08",
      billing_period_end: "2026-05-07",
      due_at: null,
      issued_at: "2026-04-08T00:00:00Z",
      paid_at: null,
      currency: "THB",
      amount_due: "1500.00",
      reconciled_total: "0.00",
      outstanding_balance: "1500.00",
      upgrade_from_subscription_id: "sub-trial-1",
      upgrade_mode: "replace_now",
      notes: null,
      created_at: "2026-04-08T00:00:00Z",
      updated_at: "2026-04-08T00:00:00Z",
    },
    payment_requests: [],
    payments: [],
    events: [],
    subscription: null,
  };
}

function buildUpgradeWithQrResponse() {
  return {
    record: {
      id: "record-upgrade-1",
      tenant_id: "tenant-1",
      record_number: "UPG-MONTHLY-20260408",
      plan_code: "monthly_membership",
      status: "awaiting_payment",
      billing_period_start: "2026-04-08",
      billing_period_end: "2026-05-07",
      due_at: null,
      issued_at: "2026-04-08T00:00:00Z",
      paid_at: null,
      currency: "THB",
      amount_due: "1500.00",
      reconciled_total: "0.00",
      outstanding_balance: "1500.00",
      upgrade_from_subscription_id: "sub-trial-1",
      upgrade_mode: "replace_now",
      notes: null,
      created_at: "2026-04-08T00:00:00Z",
      updated_at: "2026-04-08T00:00:00Z",
    },
    payment_requests: [
      {
        id: "request-upgrade-1",
        billing_record_id: "record-upgrade-1",
        provider: "opn",
        payment_method: "promptpay_qr",
        status: "pending",
        provider_reference: "chrg_upgrade_promptpay_001",
        payment_url: "https://api.omise.co/charges/chrg_upgrade_promptpay_001/qrcode.svg",
        qr_payload: "0002010102121234",
        qr_svg: "<svg></svg>",
        amount: "1500.00",
        currency: "THB",
        expires_at: "2026-04-08T01:00:00Z",
        settled_at: null,
        created_at: "2026-04-08T00:00:00Z",
        updated_at: "2026-04-08T00:00:00Z",
      },
    ],
    payments: [],
    events: [],
    subscription: null,
  };
}

async function fulfillJson(route: Route, status: number, body: unknown) {
  await route.fulfill({
    status,
    contentType: "application/json",
    body: JSON.stringify(body),
  });
}

async function mockBillingApp(page: Page, planCode: "free_trial" | "one_time_search_pack" | "monthly_membership") {
  let latestBillingRecords = buildBillingRecordsResponse();
  let latestRules = buildRulesResponse(planCode);
  let upgradePayload: unknown;
  let paymentRequestPayload: unknown;

  await page.route("**/v1/**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const key = `${request.method()} ${url.pathname}`;

    switch (key) {
      case "GET /v1/me":
        await fulfillJson(route, 200, CURRENT_SESSION);
        return;
      case "GET /v1/dashboard/summary":
        await fulfillJson(route, 200, EMPTY_DASHBOARD_SUMMARY);
        return;
      case "GET /v1/billing/plans":
        await fulfillJson(route, 200, buildPlansResponse());
        return;
      case "GET /v1/billing/records":
        await fulfillJson(route, 200, latestBillingRecords);
        return;
      case "GET /v1/rules":
        await fulfillJson(route, 200, latestRules);
        return;
      case "POST /v1/billing/upgrades":
        upgradePayload = request.postDataJSON();
        latestBillingRecords = {
          ...latestBillingRecords,
          records: [buildUpgradeWithQrResponse(), ...latestBillingRecords.records],
          total: 2,
          summary: {
            open_records: 1,
            awaiting_reconciliation: 0,
            outstanding_amount: "1500.00",
            collected_amount: "0.00",
          },
        };
        latestRules = buildRulesResponse(planCode);
        await fulfillJson(route, 201, buildUpgradeResponse());
        return;
      case "POST /v1/billing/records/record-upgrade-1/payment-requests":
        paymentRequestPayload = request.postDataJSON();
        await fulfillJson(route, 201, buildUpgradeWithQrResponse());
        return;
      default:
        await fulfillJson(route, 500, { detail: `Unhandled mock route: ${key}` });
    }
  });

  return {
    getUpgradePayload: () => upgradePayload,
    getPaymentRequestPayload: () => paymentRequestPayload,
  };
}

test("billing page shows free-trial upgrade CTA and auto-creates PromptPay QR", async ({ page }) => {
  const mocks = await mockBillingApp(page, "free_trial");

  await page.goto("/billing");

  await expect(page.getByText("อัปเกรดจาก Free Trial", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "อัปเกรดเป็น Monthly Membership" })).toBeVisible();
  await expect(
    page.getByText("เมื่อชำระสำเร็จ ระบบจะเพิ่มสิทธิ์เป็นแพ็กเกจรายเดือนและปลดล็อกทุกช่องทางทันที", {
      exact: true,
    }),
  ).toBeVisible();
  await expect(
    page.getByText("หากต้องการใช้ Free Trial ต่อก่อน กรุณารอจนกว่าจะสิ้นสุดแล้วค่อยอัปเกรด", {
      exact: true,
    }),
  ).toHaveCount(2);

  await page.getByRole("button", { name: "อัปเกรดเป็น Monthly Membership" }).click();

  await expect(page.getByText("PromptPay Request", { exact: true })).toBeVisible();
  await expect(page.getByText("สิ่งที่จะเปลี่ยนทันทีหลังชำระสำเร็จ", { exact: true })).toBeVisible();
  await expect(page.getByText("ปลดล็อกส่งออก Excel ดาวน์โหลดเอกสาร และการแจ้งเตือนทันที", { exact: true })).toBeVisible();
  await expect(page.getByText("แพ็กเกจเดิมจะถูกแทนที่เมื่อการชำระเงินสำเร็จ", { exact: true })).toBeVisible();

  expect(mocks.getUpgradePayload()).toEqual({
    target_plan_code: "monthly_membership",
    billing_period_start: "2026-04-08",
  });
  expect(mocks.getPaymentRequestPayload()).toEqual({
    provider: "opn",
    payment_method: "promptpay_qr",
    expires_in_minutes: 30,
  });
});

test("billing page shows one-time upgrade CTA only for monthly membership", async ({ page }) => {
  await mockBillingApp(page, "one_time_search_pack");

  await page.goto("/billing");

  await expect(page.getByText("อัปเกรดจาก One-Time Search Pack", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "อัปเกรดเป็น Monthly Membership" })).toBeVisible();
  await expect(
    page.getByText("เมื่อชำระสำเร็จ ระบบจะเปลี่ยนจากแพ็กเกจ one-shot เป็นสมาชิกรายเดือนทันที และโควต้าคำค้นจะเพิ่มเป็น 5", {
      exact: true,
    }),
  ).toBeVisible();
  await expect(
    page.getByText("หากต้องการใช้แพ็กเกจ one-shot ปัจจุบันต่อก่อน กรุณารอจนกว่าจะสิ้นสุดแล้วค่อยอัปเกรด", {
      exact: true,
    }),
  ).toBeVisible();
  await expect(page.getByRole("button", { name: "อัปเกรดเป็น One-Time Search Pack" })).toHaveCount(0);
});

test("billing page hides upgrade CTA for monthly membership", async ({ page }) => {
  await mockBillingApp(page, "monthly_membership");

  await page.goto("/billing");

  await expect(page.getByText("อัปเกรดจาก Free Trial", { exact: true })).toHaveCount(0);
  await expect(page.getByText("อัปเกรดจาก One-Time Search Pack", { exact: true })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "อัปเกรดเป็น Monthly Membership" })).toHaveCount(0);
});

test("billing page shows pending activation copy for future-start upgrades", async ({ page }) => {
  await page.route("**/v1/**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const key = `${request.method()} ${url.pathname}`;

    switch (key) {
      case "GET /v1/me":
        await fulfillJson(route, 200, CURRENT_SESSION);
        return;
      case "GET /v1/dashboard/summary":
        await fulfillJson(route, 200, EMPTY_DASHBOARD_SUMMARY);
        return;
      case "GET /v1/billing/plans":
        await fulfillJson(route, 200, buildPlansResponse());
        return;
      case "GET /v1/rules":
        await fulfillJson(route, 200, buildRulesResponse("one_time_search_pack"));
        return;
      case "GET /v1/billing/records":
        await fulfillJson(route, 200, {
          records: [
            {
              ...buildUpgradeWithQrResponse(),
              record: {
                ...buildUpgradeWithQrResponse().record,
                upgrade_mode: "replace_on_activation",
                billing_period_start: "2026-04-15",
                billing_period_end: "2026-05-14",
              },
              subscription: {
                id: "sub-upcoming-1",
                tenant_id: "tenant-1",
                billing_record_id: "record-upgrade-1",
                plan_code: "monthly_membership",
                subscription_status: "pending_activation",
                billing_period_start: "2026-04-15",
                billing_period_end: "2026-05-14",
                keyword_limit: 5,
                activated_at: "2026-04-08T00:00:00Z",
                activated_by_payment_id: "payment-1",
                created_at: "2026-04-08T00:00:00Z",
                updated_at: "2026-04-08T00:00:00Z",
              },
            },
          ],
          total: 1,
          limit: 50,
          offset: 0,
          summary: {
            open_records: 0,
            awaiting_reconciliation: 0,
            outstanding_amount: "0.00",
            collected_amount: "1500.00",
          },
        });
        return;
      default:
        await fulfillJson(route, 500, { detail: `Unhandled mock route: ${key}` });
    }
  });

  await page.goto("/billing");

  await expect(page.getByText("รอเริ่มใช้งานตามรอบใหม่", { exact: true })).toBeVisible();
  await expect(
    page.getByText("ชำระเงินสำเร็จแล้ว ระบบจะเปิดแพ็กเกจใหม่ตามวันเริ่มรอบที่กำหนดไว้", {
      exact: true,
    }),
  ).toBeVisible();
  await expect(
    page.getByText("แพ็กเกจปัจจุบันยังใช้งานได้ต่อจนกว่าจะถึงวันเริ่มของแพ็กเกจใหม่", {
      exact: true,
    }),
  ).toBeVisible();
});
