import { expect, test, type Page, type Route } from "@playwright/test";

const CURRENT_SESSION = {
  user: {
    id: "user-1",
    subject: "user-1",
    email: "analyst@example.com",
    full_name: "Example Analyst",
    role: "admin",
    status: "active",
    email_verified: false,
    email_verified_at: null,
    mfa_enabled: false,
  },
  tenant: {
    id: "tenant-1",
    name: "Example Tenant",
    slug: "example-tenant",
    plan_code: "pro",
    is_active: true,
    created_at: "2026-04-06T00:00:00Z",
    updated_at: "2026-04-06T00:00:00Z",
  },
};

const DASHBOARD_SUMMARY = {
  kpis: {
    active_projects: 4,
    discovered_today: 1,
    winner_projects_this_week: 0,
    closed_today: 0,
    changed_tor_projects: 0,
    crawl_success_rate_percent: 99.5,
    failed_runs_recent: 0,
    crawl_success_window_runs: 2,
  },
  recent_runs: [],
  recent_changes: [],
  winner_projects: [],
  daily_discovery: [],
  project_state_breakdown: [
    { bucket: "discovered", count: 1 },
    { bucket: "open_invitation", count: 3 },
    { bucket: "open_consulting", count: 0 },
    { bucket: "tor_downloaded", count: 0 },
    { bucket: "winner", count: 0 },
    { bucket: "closed", count: 0 },
  ],
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

async function mockApi(
  page: Page,
  options: {
    authenticated?: boolean;
    onLogin?: (payload: unknown) => void;
    onForgotPassword?: (payload: unknown) => void;
    onAcceptInvite?: (payload: unknown) => void;
    onResetPassword?: (payload: unknown) => void;
    onVerifyEmail?: (payload: unknown) => void;
  } = {},
) {
  let authenticated = options.authenticated ?? false;

  await page.route("**/v1/**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const key = `${request.method()} ${url.pathname}`;

    switch (key) {
      case "GET /v1/me":
        if (!authenticated) {
          await fulfillJson(route, 401, { detail: "authentication required" });
          return;
        }
        await fulfillJson(route, 200, CURRENT_SESSION);
        return;
      case "GET /v1/dashboard/summary":
        await fulfillJson(route, 200, DASHBOARD_SUMMARY);
        return;
      case "POST /v1/auth/login":
        options.onLogin?.(request.postDataJSON());
        authenticated = true;
        await fulfillJson(route, 200, CURRENT_SESSION);
        return;
      case "POST /v1/auth/password/forgot":
        options.onForgotPassword?.(request.postDataJSON());
        await fulfillJson(route, 202, { status: "accepted" });
        return;
      case "POST /v1/auth/invite/accept":
        options.onAcceptInvite?.(request.postDataJSON());
        authenticated = true;
        await fulfillJson(route, 200, CURRENT_SESSION);
        return;
      case "POST /v1/auth/password/reset":
        options.onResetPassword?.(request.postDataJSON());
        await fulfillJson(route, 200, { status: "password_reset" });
        return;
      case "POST /v1/auth/email/verify":
        options.onVerifyEmail?.(request.postDataJSON());
        await fulfillJson(route, 200, { email_verified: true });
        return;
      case "POST /v1/auth/email/verification/send":
        await fulfillJson(route, 202, { status: "accepted" });
        return;
      case "POST /v1/auth/mfa/setup":
        await fulfillJson(route, 200, {
          secret: "JBSWY3DPEHPK3PXP",
          otpauth_uri: "otpauth://totp/EGP:analyst@example.com?secret=JBSWY3DPEHPK3PXP&issuer=EGP",
        });
        return;
      default:
        await fulfillJson(route, 500, { detail: `Unhandled mock route: ${key}` });
    }
  });
}

test("redirects unauthenticated protected pages to login", async ({ page }) => {
  await mockApi(page);

  await page.goto("/security");

  await expect(page).toHaveURL(/\/login\?next=%2Fsecurity$/);
  await expect(page.getByRole("heading", { name: "เข้าสู่ระบบ" })).toBeVisible();
});

test("login submits tenant credentials and MFA code", async ({ page }) => {
  let loginPayload: unknown;
  await mockApi(page, {
    onLogin: (payload) => {
      loginPayload = payload;
    },
  });

  await page.goto("/login?next=%2Fsecurity");
  await page.getByLabel("Tenant slug").fill("example-tenant");
  await page.getByLabel("อีเมล").fill("analyst@example.com");
  await page.getByLabel("รหัสผ่าน").fill("super-secret-password");
  await page.getByLabel("MFA code").fill("123456");
  await page.getByRole("button", { name: "เข้าสู่ระบบ" }).click();

  await expect(page).toHaveURL(/\/security$/);
  await expect(page.getByRole("heading", { name: "ความปลอดภัยของบัญชี" })).toBeVisible();
  expect(loginPayload).toEqual({
    tenant_slug: "example-tenant",
    email: "analyst@example.com",
    password: "super-secret-password",
    mfa_code: "123456",
  });
});

test("forgot-password page submits a generic reset request", async ({ page }) => {
  let forgotPayload: unknown;
  await mockApi(page, {
    onForgotPassword: (payload) => {
      forgotPayload = payload;
    },
  });

  await page.goto("/forgot-password");
  await page.getByPlaceholder("tenant slug").fill("example-tenant");
  await page.getByPlaceholder("name@company.com").fill("analyst@example.com");
  await page.getByRole("button", { name: "ส่งลิงก์รีเซ็ตรหัสผ่าน" }).click();

  await expect(page.getByText("หากบัญชีนี้มีอยู่ในระบบ เราได้ส่งลิงก์รีเซ็ตรหัสผ่านให้แล้ว")).toBeVisible();
  expect(forgotPayload).toEqual({
    tenant_slug: "example-tenant",
    email: "analyst@example.com",
  });
});

test("invite page accepts a token and enters the app", async ({ page }) => {
  let invitePayload: unknown;
  await mockApi(page, {
    onAcceptInvite: (payload) => {
      invitePayload = payload;
    },
  });

  await page.goto("/invite?token=invite-token");
  await page.getByPlaceholder("รหัสผ่านใหม่อย่างน้อย 12 ตัวอักษร").fill("super-secret-password");
  await page.getByRole("button", { name: "รับคำเชิญและเข้าสู่ระบบ" }).click();

  await expect(page).toHaveURL(/\/dashboard$/);
  await expect(page.getByRole("heading", { name: "แดชบอร์ด" })).toBeVisible();
  expect(invitePayload).toEqual({
    token: "invite-token",
    password: "super-secret-password",
  });
});

test("reset-password page consumes a token and returns to login", async ({ page }) => {
  let resetPayload: unknown;
  await mockApi(page, {
    onResetPassword: (payload) => {
      resetPayload = payload;
    },
  });

  await page.goto("/reset-password?token=reset-token");
  await page.getByPlaceholder("รหัสผ่านใหม่อย่างน้อย 12 ตัวอักษร").fill("super-secret-password");
  await page.getByRole("button", { name: "บันทึกรหัสผ่านใหม่" }).click();

  await expect(page).toHaveURL(/\/login$/);
  expect(resetPayload).toEqual({
    token: "reset-token",
    password: "super-secret-password",
  });
});

test("verify-email page consumes the verification token", async ({ page }) => {
  let verificationPayload: unknown;
  await mockApi(page, {
    onVerifyEmail: (payload) => {
      verificationPayload = payload;
    },
  });

  await page.goto("/verify-email?token=verify-token");

  await expect(page.getByText("ยืนยันอีเมลเรียบร้อยแล้ว")).toBeVisible();
  expect(verificationPayload).toEqual({
    token: "verify-token",
  });
});

test("security page supports verification resend and MFA setup", async ({ page }) => {
  await mockApi(page, { authenticated: true });

  await page.goto("/security");
  await expect(page.getByRole("heading", { name: "ความปลอดภัยของบัญชี" })).toBeVisible();

  await page.getByRole("button", { name: "ส่งลิงก์ยืนยันอีกครั้ง" }).click();
  await expect(page.getByText("ส่งลิงก์ยืนยันอีเมลแล้ว กรุณาตรวจสอบกล่องจดหมายของคุณ")).toBeVisible();

  await page.getByRole("button", { name: "เริ่มตั้งค่า MFA" }).click();
  await expect(page.getByText("JBSWY3DPEHPK3PXP", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "เปิดใช้ MFA" })).toBeVisible();
});
