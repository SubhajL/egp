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
  requires_billing_update: false,
};

const BILLING_RECORDS = {
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

const BILLING_PLANS = {
  plans: [
    {
      code: "monthly_membership",
      label: "Monthly Membership",
      description: "Monthly plan",
      currency: "THB",
      amount_due: "1500.00",
      billing_interval: "monthly",
      keyword_limit: 5,
      duration_days: null,
      duration_months: 1,
    },
  ],
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
    active_keywords: ["example"],
    over_keyword_limit: false,
    runs_allowed: true,
    exports_allowed: true,
    document_download_allowed: true,
    notifications_allowed: true,
    source: "mock",
  },
  closure_rules: {
    close_on_winner_status: true,
    close_on_contract_status: true,
    winner_status_terms: [],
    contract_status_terms: [],
    consulting_timeout_days: 14,
    stale_no_tor_days: 7,
    stale_eligible_states: [],
    source: "mock",
  },
  notification_rules: {
    supported_channels: [],
    supported_types: [],
    event_wiring_complete: true,
    source: "mock",
  },
  schedule_rules: {
    supported_trigger_types: [],
    schedule_execution_supported: true,
    editable_in_product: true,
    tenant_crawl_interval_hours: 24,
    default_crawl_interval_hours: 24,
    effective_crawl_interval_hours: 24,
    source: "mock",
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
    onRegister?: (payload: unknown) => void;
    onLogin?: (payload: unknown) => void;
    loginResponses?: Array<{ status: number; body: unknown }>;
    onForgotPassword?: (payload: unknown) => void;
    onAcceptInvite?: (payload: unknown) => void;
    onResetPassword?: (payload: unknown) => void;
    onVerifyEmail?: (payload: unknown) => void;
  } = {},
) {
  let authenticated = options.authenticated ?? false;
  const loginResponses = [...(options.loginResponses ?? [])];

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
      case "GET /v1/billing/records":
        await fulfillJson(route, 200, BILLING_RECORDS);
        return;
      case "GET /v1/billing/plans":
        await fulfillJson(route, 200, BILLING_PLANS);
        return;
      case "GET /v1/rules":
        await fulfillJson(route, 200, RULES_RESPONSE);
        return;
      case "POST /v1/auth/login":
        options.onLogin?.(request.postDataJSON());
        if (loginResponses.length > 0) {
          const next = loginResponses.shift()!;
          if (next.status === 200) {
            authenticated = true;
          }
          await fulfillJson(route, next.status, next.body);
          return;
        }
        authenticated = true;
        await fulfillJson(route, 200, CURRENT_SESSION);
        return;
      case "POST /v1/auth/register":
        options.onRegister?.(request.postDataJSON());
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
    loginResponses: [
      {
        status: 401,
        body: { detail: "mfa code required", code: "mfa_code_required" },
      },
      {
        status: 200,
        body: CURRENT_SESSION,
      },
    ],
  });

  await page.goto("/login?next=%2Fsecurity");
  await page.getByLabel("อีเมล").fill("analyst@example.com");
  await page.getByLabel("รหัสผ่าน").fill("super-secret-password");
  await page.getByRole("button", { name: "เข้าสู่ระบบ" }).click();

  await expect(
    page.getByText("บัญชีนี้เปิดใช้ MFA กรุณากรอกรหัส 6 หลักจากแอปยืนยันตัวตน"),
  ).toBeVisible();
  await page.getByLabel("MFA code").fill("123456");
  await page.getByRole("button", { name: "เข้าสู่ระบบ" }).click();

  await expect(page).toHaveURL(/\/security$/);
  await expect(page.getByRole("heading", { name: "ความปลอดภัยของบัญชี" })).toBeVisible();
  expect(loginPayload).toEqual({
    email: "analyst@example.com",
    password: "super-secret-password",
    mfa_code: "123456",
  });
});

test("login reveals workspace field after ambiguous email response and retries", async ({ page }) => {
  const loginPayloads: unknown[] = [];
  await mockApi(page, {
    onLogin: (payload) => {
      loginPayloads.push(payload);
    },
    loginResponses: [
      {
        status: 409,
        body: {
          detail: "workspace slug required",
          code: "workspace_slug_required",
        },
      },
      {
        status: 200,
        body: CURRENT_SESSION,
      },
    ],
  });

  await page.goto("/login?next=%2Fsecurity");
  await expect(page.getByLabel("Workspace slug")).toHaveCount(0);

  await page.getByLabel("อีเมล").fill("shared@example.com");
  await page.getByLabel("รหัสผ่าน").fill("super-secret-password");
  await page.getByRole("button", { name: "เข้าสู่ระบบ" }).click();

  await expect(page.getByText("อีเมลนี้ถูกใช้ในหลาย workspace กรุณาระบุ Workspace slug เพื่อเข้าสู่ระบบ")).toBeVisible();
  await expect(page.getByLabel("Workspace slug")).toBeVisible();

  await page.getByLabel("Workspace slug").fill("example-tenant");
  await page.getByRole("button", { name: "เข้าสู่ระบบ" }).click();

  await expect(page).toHaveURL(/\/security$/);
  expect(loginPayloads).toEqual([
    {
      email: "shared@example.com",
      password: "super-secret-password",
    },
    {
      tenant_slug: "example-tenant",
      email: "shared@example.com",
      password: "super-secret-password",
    },
  ]);
});

test("login redirects to signup when no registration record exists", async ({ page }) => {
  await mockApi(page, {
    loginResponses: [
      {
        status: 401,
        body: {
          detail: "registration required",
          code: "registration_required",
        },
      },
    ],
  });

  await page.goto("/login?next=%2Fsecurity");
  await page.getByLabel("อีเมล").fill("new-user@example.com");
  await page.getByLabel("รหัสผ่าน").fill("super-secret-password");
  await page.getByRole("button", { name: "เข้าสู่ระบบ" }).click();

  await expect(page).toHaveURL(/\/signup\?email=new-user%40example\.com/);
  await expect(
    page.getByText("ไม่พบข้อมูลการลงทะเบียนสำหรับอีเมลนี้ กรุณาสมัครใช้งานก่อน"),
  ).toBeVisible();
});

test("login redirects overdue accounts to billing with a payment notice", async ({ page }) => {
  await mockApi(page, {
    loginResponses: [
      {
        status: 200,
        body: {
          ...CURRENT_SESSION,
          requires_billing_update: true,
        },
      },
    ],
  });

  await page.goto("/login?next=%2Fdashboard");
  await page.getByLabel("อีเมล").fill("analyst@example.com");
  await page.getByLabel("รหัสผ่าน").fill("super-secret-password");
  await page.getByRole("button", { name: "เข้าสู่ระบบ" }).click();

  await expect(page).toHaveURL(/\/billing\?notice=payment_overdue$/);
  await expect(
    page.getByText("กรุณาอัปเดตการชำระเงินก่อนดำเนินการต่อ", { exact: true }),
  ).toBeVisible();
});

test("signup creates a workspace and continues to the requested page", async ({ page }) => {
  let registerPayload: unknown;
  await mockApi(page, {
    onRegister: (payload) => {
      registerPayload = payload;
    },
  });

  await page.goto("/signup?next=%2Fsecurity");
  await page.getByLabel("ชื่อบริษัท / องค์กร").fill("Example Company Ltd");
  await page.getByLabel("อีเมล").fill("owner@example.com");
  await page.getByLabel("รหัสผ่าน").fill("super-secret-password");
  await page.getByRole("button", { name: "เริ่มทดลองใช้งานฟรี" }).click();

  await expect(page).toHaveURL(/\/security$/);
  await expect(page.getByRole("heading", { name: "ความปลอดภัยของบัญชี" })).toBeVisible();
  expect(registerPayload).toEqual({
    company_name: "Example Company Ltd",
    email: "owner@example.com",
    password: "super-secret-password",
  });
});

test("signup shows Thai duplicate-account and validation messages from stable codes", async ({ page }) => {
  let registerAttempt = 0;

  await mockApi(page);
  await page.route("**/v1/auth/register", async (route) => {
    registerAttempt += 1;
    if (registerAttempt === 1) {
      await fulfillJson(route, 409, {
        detail: "account already exists for this email; please sign in",
        code: "account_already_exists",
      });
      return;
    }
    await fulfillJson(route, 422, {
      detail: [{ loc: ["body", "password"], msg: "String should have at least 12 characters" }],
      code: "validation_password_too_short",
    });
  });

  await page.goto("/signup");
  await page.getByLabel("ชื่อบริษัท / องค์กร").fill("Example Company Ltd");
  await page.getByLabel("อีเมล").fill("owner@example.com");
  await page.getByLabel("รหัสผ่าน").fill("super-secret-password");
  await page.getByRole("button", { name: "เริ่มทดลองใช้งานฟรี" }).click();

  await expect(page.getByText("อีเมลนี้มีบัญชีอยู่แล้ว กรุณาเข้าสู่ระบบแทนการสมัครใหม่")).toBeVisible();
  await expect(page.getByRole("link", { name: "ไปหน้าเข้าสู่ระบบ" })).toBeVisible();

  await page.getByLabel("รหัสผ่าน").evaluate((element) => {
    element.removeAttribute("minlength");
  });
  await page.getByLabel("รหัสผ่าน").fill("short");
  await page.getByRole("button", { name: "เริ่มทดลองใช้งานฟรี" }).click();

  await expect(page.getByText("รหัสผ่านต้องมีอย่างน้อย 12 ตัวอักษร")).toBeVisible();
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
