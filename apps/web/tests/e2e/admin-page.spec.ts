import { expect, test, type Page, type Route } from "@playwright/test";

const CURRENT_SESSION = {
  user: {
    id: "user-1",
    subject: "user-1",
    email: "owner@example.com",
    full_name: "Owner User",
    role: "owner",
    status: "active",
    email_verified: true,
    email_verified_at: "2026-04-06T00:00:00Z",
    mfa_enabled: false,
  },
  tenant: {
    id: "tenant-1",
    name: "Example Tenant",
    slug: "example-tenant",
    plan_code: "one_time_search_pack",
    is_active: true,
    created_at: "2026-04-06T00:00:00Z",
    updated_at: "2026-04-06T00:00:00Z",
  },
};

async function fulfillJson(route: Route, status: number, body: unknown) {
  await route.fulfill({
    status,
    contentType: "application/json",
    body: JSON.stringify(body),
  });
}

async function mockAdminApp(page: Page) {
  await page.route("**/v1/**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const key = `${request.method()} ${url.pathname}`;

    switch (key) {
      case "GET /v1/me":
        await fulfillJson(route, 200, CURRENT_SESSION);
        return;
      case "GET /v1/admin":
        await fulfillJson(route, 200, {
          tenant: CURRENT_SESSION.tenant,
          settings: {
            support_email: null,
            billing_contact_email: null,
            timezone: "Asia/Bangkok",
            locale: "th-TH",
            daily_digest_enabled: true,
            weekly_digest_enabled: false,
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
              collected_amount: "1500.00",
            },
            current_subscription: {
              id: "sub-current-1",
              tenant_id: "tenant-1",
              billing_record_id: "record-current-1",
              plan_code: "one_time_search_pack",
              subscription_status: "active",
              billing_period_start: "2026-04-08",
              billing_period_end: "2026-04-10",
              keyword_limit: 1,
              activated_at: "2026-04-08T00:00:00Z",
              activated_by_payment_id: null,
              created_at: "2026-04-08T00:00:00Z",
              updated_at: "2026-04-08T00:00:00Z",
            },
            upcoming_subscription: {
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
            records: [
              {
                id: "record-upgrade-1",
                tenant_id: "tenant-1",
                record_number: "UPG-MONTHLY-CHAIN",
                plan_code: "monthly_membership",
                status: "paid",
                billing_period_start: "2026-04-15",
                billing_period_end: "2026-05-14",
                due_at: null,
                issued_at: "2026-04-08T00:00:00Z",
                paid_at: "2026-04-08T01:00:00Z",
                currency: "THB",
                amount_due: "1500.00",
                reconciled_total: "1500.00",
                outstanding_balance: "0.00",
                upgrade_from_subscription_id: "sub-current-1",
                upgrade_mode: "replace_on_activation",
                notes: "Upgrade to monthly_membership starting 2026-04-15",
                created_at: "2026-04-08T00:00:00Z",
                updated_at: "2026-04-08T01:00:00Z",
              },
            ],
          },
        });
        return;
      case "GET /v1/admin/audit-log":
        await fulfillJson(route, 200, { items: [], total: 0, limit: 50, offset: 0 });
        return;
      case "GET /v1/webhooks":
        await fulfillJson(route, 200, { webhooks: [] });
        return;
      case "GET /v1/admin/support/tenants":
        await fulfillJson(route, 200, {
          tenants: [
            {
              id: "tenant-1",
              name: "Example Tenant",
              slug: "example-tenant",
              plan_code: "one_time_search_pack",
              is_active: true,
              support_email: "support@example.com",
              billing_contact_email: "billing@example.com",
              active_user_count: 2,
            },
          ],
        });
        return;
      case "GET /v1/admin/support/tenants/tenant-1/summary":
        await fulfillJson(route, 200, {
          tenant: {
            id: "tenant-1",
            name: "Example Tenant",
            slug: "example-tenant",
            plan_code: "one_time_search_pack",
            is_active: true,
            support_email: "support@example.com",
            billing_contact_email: "billing@example.com",
            active_user_count: 2,
          },
          triage: {
            failed_runs_recent: 1,
            pending_document_reviews: 0,
            failed_webhook_deliveries: 0,
            outstanding_billing_records: 0,
          },
          cost_summary: {
            window_days: 30,
            currency: "THB",
            estimated_total_thb: "0.35",
            crawl: {
              estimated_cost_thb: "0.35",
              run_count: 1,
              task_count: 1,
              failed_run_count: 1,
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
            provider: "google_drive",
            connection_status: "error",
            account_email: "ops@example.com",
            provider_folder_id: "provider-folder-id",
            provider_folder_url: "https://example.com/provider-folder",
            managed_fallback_enabled: true,
            has_credentials: false,
            last_validated_at: null,
            last_validation_error: "google refresh token expired",
          },
          alerts: [
            {
              severity: "error",
              code: "storage_connection_error",
              title: "External storage needs attention",
              detail: "google_drive is in error state: google refresh token expired",
            },
            {
              severity: "warning",
              code: "storage_credentials_missing",
              title: "Storage credentials are missing",
              detail: "Support should reconnect google_drive credentials for this tenant",
            },
          ],
          recent_failed_runs: [],
          pending_reviews: [],
          failed_webhooks: [],
          billing_issues: [],
        });
        return;
      default:
        await fulfillJson(route, 500, { detail: `Unhandled mock route: ${key}` });
    }
  });
}

test("admin billing tab shows current and upcoming upgrade chain", async ({ page }) => {
  await mockAdminApp(page);

  await page.goto("/admin");
  await page.getByRole("button", { name: "แผนและบิล" }).click();

  await expect(page.getByText("สิทธิ์ปัจจุบัน", { exact: true })).toBeVisible();
  await expect(page.getByText("สิทธิ์ที่กำลังรอเริ่มใช้งาน", { exact: true })).toBeVisible();
  await expect(page.getByText("one_time_search_pack ถึง", { exact: false })).toBeVisible();
  await expect(page.getByText("monthly_membership เริ่ม", { exact: false })).toBeVisible();
  await expect(page.getByText("replace_on_activation", { exact: true })).toBeVisible();
  await expect(page.getByText("from sub-curr", { exact: false })).toBeVisible();
});

test("admin support tab shows storage diagnostics and alerts", async ({ page }) => {
  await mockAdminApp(page);

  await page.goto("/admin");
  await page.getByRole("button", { name: "Support" }).click();
  await page.getByPlaceholder("ค้นหาจากชื่อ tenant, slug, support email หรือ user email").fill(
    "example",
  );
  await page.getByRole("button", { name: "ค้นหา Support" }).click();
  await page.getByRole("button", { name: /Example Tenant/ }).click();

  await expect(page.getByText("Storage Health", { exact: true })).toBeVisible();
  await expect(page.getByText("Support Alerts", { exact: true })).toBeVisible();
  await expect(page.getByText("External storage needs attention", { exact: true })).toBeVisible();
  await expect(page.getByText("Storage credentials are missing", { exact: true })).toBeVisible();
  await expect(
    page.getByText("google_drive is in error state: google refresh token expired", {
      exact: true,
    }),
  ).toBeVisible();
});
