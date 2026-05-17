import type { components, paths } from "./generated/api-types";

/* ------------------------------------------------------------------ */
/*  Types                                                              */
/* ------------------------------------------------------------------ */

type ProjectListQueryParams = NonNullable<
  paths["/v1/projects"]["get"]["parameters"]["query"]
>;
type ApiQueryInput<T> = Exclude<T, null | undefined>;

export type ProjectSummary = components["schemas"]["ProjectResponse"];
export type ProjectAlias = components["schemas"]["ProjectAliasResponse"];
export type ProjectStatusEvent = components["schemas"]["ProjectStatusEventResponse"];
export type ProjectDetailResponse =
  paths["/v1/projects/{project_id}"]["get"]["responses"][200]["content"]["application/json"];

export type AuthenticatedUser = components["schemas"]["AuthenticatedUserResponse"];
export type AuthTenant = components["schemas"]["AuthTenantResponse"];
export type CurrentSessionResponse = components["schemas"]["CurrentSessionResponse"];

export type ProjectListResponse =
  paths["/v1/projects"]["get"]["responses"][200]["content"]["application/json"];

export type DocumentSummary = components["schemas"]["DocumentResponse"];
export type DocumentListResponse =
  paths["/v1/documents/projects/{project_id}"]["get"]["responses"][200]["content"]["application/json"];
export type DocumentDownloadLinkResponse =
  paths["/v1/documents/{document_id}/download-link"]["get"]["responses"][200]["content"]["application/json"];

export type DocumentDownloadFileResponse = {
  blob: Blob;
  filename: string;
};

export type ProjectCrawlEvidence = components["schemas"]["ProjectCrawlEvidenceResponse"];
export type ProjectCrawlEvidenceListResponse =
  paths["/v1/projects/{project_id}/crawl-evidence"]["get"]["responses"][200]["content"]["application/json"];

export type RunSummary = components["schemas"]["RunResponse"];
export type TaskSummary = components["schemas"]["TaskResponse"];
export type RunDetailResponse = components["schemas"]["RunDetailResponse"];
export type RunListResponse =
  paths["/v1/runs"]["get"]["responses"][200]["content"]["application/json"];

export type RuleProfile = components["schemas"]["RuleProfileResponse"];
export type ClosureRulesSummary = components["schemas"]["ClosureRulesResponse"];
export type NotificationRulesSummary = components["schemas"]["NotificationRulesResponse"];
export type ScheduleRulesSummary = components["schemas"]["ScheduleRulesResponse"];
export type EntitlementSummary = components["schemas"]["EntitlementSummaryResponse"];
export type RulesResponse =
  paths["/v1/rules"]["get"]["responses"][200]["content"]["application/json"];

export type ProjectExportResponse = {
  blob: Blob;
  filename: string;
};

export type DashboardKpis = components["schemas"]["DashboardKpisResponse"];
export type DashboardRecentRun = components["schemas"]["DashboardRecentRunResponse"];
export type DashboardRecentProjectChange =
  components["schemas"]["DashboardRecentProjectChangeResponse"];
export type DashboardWinnerProject =
  components["schemas"]["DashboardWinnerProjectResponse"];
export type DashboardDailyDiscoveryPoint =
  components["schemas"]["DashboardDailyDiscoveryPointResponse"];
export type DashboardStateBreakdownPoint =
  components["schemas"]["DashboardStateBreakdownPointResponse"];
export type DashboardCrawlCostSummary = components["schemas"]["SupportCrawlCostResponse"];
export type DashboardStorageCostSummary = components["schemas"]["SupportStorageCostResponse"];
export type DashboardNotificationCostSummary =
  components["schemas"]["SupportNotificationCostResponse"];
export type DashboardPaymentCostSummary = components["schemas"]["SupportPaymentCostResponse"];
export type DashboardCostSummary = components["schemas"]["SupportCostSummaryResponse"];
export type DashboardSummaryResponse =
  paths["/v1/dashboard/summary"]["get"]["responses"][200]["content"]["application/json"];

export type BillingRecord = components["schemas"]["BillingRecordResponse"];
export type BillingSubscription = components["schemas"]["BillingSubscriptionResponse"];
export type BillingPayment = components["schemas"]["BillingPaymentResponse"];
export type BillingEvent = components["schemas"]["BillingEventResponse"];
export type BillingPaymentRequest = components["schemas"]["BillingPaymentRequestResponse"];
export type BillingRecordDetail = components["schemas"]["BillingRecordDetailResponse"];
export type BillingSummary = components["schemas"]["BillingSummaryResponse"];
export type BillingListResponse =
  paths["/v1/billing/records"]["get"]["responses"][200]["content"]["application/json"];
export type BillingPlan = components["schemas"]["BillingPlanResponse"];
export type BillingPlansResponse =
  paths["/v1/billing/plans"]["get"]["responses"][200]["content"]["application/json"];

export type AdminTenantSummary = components["schemas"]["AdminTenantResponse"];
export type AdminTenantSettings = components["schemas"]["AdminTenantSettingsResponse"];
export type AdminTenantStorageSettings =
  components["schemas"]["AdminTenantStorageSettingsResponse"];
export type AdminUser = components["schemas"]["AdminUserResponse"];
export type ActionStatusResponse = components["schemas"]["ActionStatusResponse"];
export type EmailVerificationResponse = components["schemas"]["EmailVerificationResponse"];
export type MfaSetupResponse = components["schemas"]["MfaSetupResponse"];
export type MfaStatusResponse = components["schemas"]["MfaStatusResponse"];
export type AdminInviteUserResponse = components["schemas"]["AdminInviteUserResponse"];
export type AdminBillingOverview = components["schemas"]["AdminBillingResponse"];
export type AdminSnapshotResponse =
  paths["/v1/admin"]["get"]["responses"][200]["content"]["application/json"];

export type WebhookSubscription = components["schemas"]["WebhookResponse"];
export type WebhookListResponse =
  paths["/v1/webhooks"]["get"]["responses"][200]["content"]["application/json"];

export type AuditLogEvent = components["schemas"]["AuditLogEventResponse"];
export type AuditLogListResponse =
  paths["/v1/admin/audit-log"]["get"]["responses"][200]["content"]["application/json"];

export type SupportTenant = components["schemas"]["SupportTenantResponse"];
export type SupportTenantListResponse =
  paths["/v1/admin/support/tenants"]["get"]["responses"][200]["content"]["application/json"];
export type SupportTriageSummary = components["schemas"]["SupportTriageResponse"];
export type SupportFailedRun = components["schemas"]["SupportFailedRunResponse"];
export type SupportPendingReview = components["schemas"]["SupportPendingReviewResponse"];
export type SupportFailedWebhook = components["schemas"]["SupportFailedWebhookResponse"];
export type SupportBillingIssue = components["schemas"]["SupportBillingIssueResponse"];
export type SupportStorageDiagnostics =
  components["schemas"]["SupportStorageDiagnosticsResponse"];
export type SupportAlert = components["schemas"]["SupportAlertResponse"];
export type SupportSummaryResponse =
  paths["/v1/admin/support/tenants/{tenant_id}/summary"]["get"]["responses"][200]["content"]["application/json"];

/* ------------------------------------------------------------------ */
/*  Config                                                             */
/* ------------------------------------------------------------------ */

const DEFAULT_API_PORT = "8010";

function isLoopbackHostname(hostname: string): boolean {
  return hostname === "localhost" || hostname === "127.0.0.1";
}

function readRuntimeEnv(name: string): string | undefined {
  if (name === "NEXT_PUBLIC_EGP_API_BASE_URL") {
    return typeof process !== "undefined" ? process.env.NEXT_PUBLIC_EGP_API_BASE_URL : undefined;
  }
  if (name === "NEXT_PUBLIC_EGP_TENANT_ID") {
    return typeof process !== "undefined" ? process.env.NEXT_PUBLIC_EGP_TENANT_ID : undefined;
  }
  if (name === "NEXT_PUBLIC_SITE_URL") {
    return typeof process !== "undefined" ? process.env.NEXT_PUBLIC_SITE_URL : undefined;
  }
  if (typeof globalThis === "undefined") return undefined;
  const envSource = (globalThis as { process?: { env?: Record<string, string | undefined> } })
    .process?.env;
  return envSource?.[name];
}

export function getApiBaseUrl(): string {
  if (typeof window === "undefined") return `http://127.0.0.1:${DEFAULT_API_PORT}`;
  const configured = readRuntimeEnv("NEXT_PUBLIC_EGP_API_BASE_URL")?.trim();
  const fallback = `${window.location.protocol}//${window.location.hostname}:${DEFAULT_API_PORT}`;
  const resolved = configured || fallback;

  try {
    const url = new URL(resolved, window.location.origin);
    if (isLoopbackHostname(window.location.hostname) && isLoopbackHostname(url.hostname)) {
      url.hostname = window.location.hostname;
    }
    return url.toString().replace(/\/+$/, "");
  } catch {
    return resolved.replace(/\/+$/, "");
  }
}

export function getTenantId(): string {
  if (typeof window === "undefined") return "";
  return readRuntimeEnv("NEXT_PUBLIC_EGP_TENANT_ID")?.trim() ?? "";
}

function getApiHeaders(accept = "application/json"): HeadersInit {
  return {
    Accept: accept,
  };
}

type QueryParamValue =
  | string
  | number
  | boolean
  | Array<string | number | boolean>
  | undefined;

function buildUrl(path: string, params: Record<string, QueryParamValue>): string {
  const searchParams = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (Array.isArray(value)) {
      for (const entry of value) {
        if (entry !== undefined && entry !== "") {
          searchParams.append(key, String(entry));
        }
      }
      continue;
    }
    if (value !== undefined && value !== "") {
      searchParams.set(key, String(value));
    }
  }
  const query = searchParams.toString();
  return query ? `${getApiBaseUrl()}${path}?${query}` : `${getApiBaseUrl()}${path}`;
}

export class ApiError extends Error {
  status: number;

  detail: string;

  code?: string;

  constructor(status: number, detail: string, code?: string) {
    super(detail);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
    this.code = code;
  }
}

export function normalizeSignupApiError(error: ApiError): string {
  if (error.code === "account_already_exists") {
    return "อีเมลนี้มีบัญชีอยู่แล้ว กรุณาเข้าสู่ระบบแทนการสมัครใหม่";
  }
  if (error.code === "validation_password_too_short") {
    return "รหัสผ่านต้องมีอย่างน้อย 12 ตัวอักษร";
  }
  if (error.code === "validation_company_name_required") {
    return "กรุณาระบุชื่อบริษัท / องค์กร";
  }
  if (error.code === "validation_email_required") {
    return "กรุณาระบุอีเมล";
  }
  if (error.status === 422) {
    return "กรุณาตรวจสอบข้อมูลที่กรอก";
  }
  return localizeApiError(error, "สมัครใช้งานไม่สำเร็จ กรุณาลองใหม่อีกครั้ง");
}

export function shouldShowSignupLoginLink(error: ApiError): boolean {
  return error.code === "account_already_exists";
}

const API_ERROR_CODE_TRANSLATIONS: Record<string, string> = {
  account_already_exists: "อีเมลนี้มีบัญชีอยู่แล้ว กรุณาเข้าสู่ระบบ",
  account_not_active: "บัญชีถูกระงับ กรุณาติดต่อผู้ดูแลระบบ",
  active_keyword_limit_exceeded: "จำนวนคำค้นเกินสิทธิ์ของแพ็กเกจปัจจุบัน",
  authentication_required: "กรุณาเข้าสู่ระบบก่อนใช้งาน",
  invalid_credentials: "อีเมลหรือรหัสผ่านไม่ถูกต้อง",
  payment_overdue: "กรุณาอัปเดตการชำระเงินก่อนดำเนินการต่อ",
  invalid_email_verification_token: "ลิงก์ยืนยันอีเมลไม่ถูกต้องหรือหมดอายุแล้ว",
  invalid_invite_token: "ลิงก์คำเชิญไม่ถูกต้องหรือหมดอายุแล้ว",
  invalid_mfa_code: "รหัส MFA ไม่ถูกต้อง กรุณาลองอีกครั้ง",
  invalid_password_reset_token: "ลิงก์รีเซ็ตรหัสผ่านไม่ถูกต้องหรือหมดอายุแล้ว",
  keywords_required: "กรุณาใส่อย่างน้อย 1 คำค้น",
  mfa_code_required: "บัญชีนี้เปิดใช้ MFA กรุณากรอกรหัส 6 หลักจากแอปยืนยันตัวตน",
  profile_name_required: "กรุณาระบุชื่อโปรไฟล์",
  registration_required: "ไม่พบข้อมูลการลงทะเบียนสำหรับอีเมลนี้ กรุณาสมัครใช้งานก่อน",
  unsupported_profile_type: "ประเภทโปรไฟล์ไม่รองรับ",
  validation_company_name_required: "กรุณาระบุชื่อบริษัท / องค์กร",
  validation_email_required: "กรุณาระบุอีเมล",
  validation_keywords_required: "กรุณาใส่อย่างน้อย 1 คำค้น",
  validation_password_required: "กรุณาระบุรหัสผ่าน",
  validation_password_too_short: "รหัสผ่านต้องมีอย่างน้อย 12 ตัวอักษร",
  workspace_slug_required:
    "อีเมลนี้ถูกใช้ในหลาย workspace กรุณาระบุ Workspace slug เพื่อเข้าสู่ระบบ",
};

// ---------------------------------------------------------------------------
// English API error detail → Thai user-facing message translation
// ---------------------------------------------------------------------------

const API_ERROR_TRANSLATIONS: Array<{ pattern: string; thai: string }> = [
  // Auth
  { pattern: "authentication required", thai: "กรุณาเข้าสู่ระบบก่อนใช้งาน" },
  { pattern: "invalid credentials", thai: "อีเมลหรือรหัสผ่านไม่ถูกต้อง" },
  { pattern: "registration required", thai: "ไม่พบข้อมูลการลงทะเบียนสำหรับอีเมลนี้ กรุณาสมัครใช้งานก่อน" },
  { pattern: "payment overdue", thai: "กรุณาอัปเดตการชำระเงินก่อนดำเนินการต่อ" },
  { pattern: "account already exists", thai: "อีเมลนี้มีบัญชีอยู่แล้ว กรุณาเข้าสู่ระบบ" },
  { pattern: "registration failed", thai: "สมัครใช้งานไม่สำเร็จ กรุณาลองใหม่อีกครั้ง" },
  { pattern: "invalid token", thai: "ลิงก์ไม่ถูกต้องหรือหมดอายุแล้ว" },
  { pattern: "invalid invite token", thai: "ลิงก์คำเชิญไม่ถูกต้องหรือหมดอายุแล้ว" },
  { pattern: "invalid or expired invite token", thai: "ลิงก์คำเชิญไม่ถูกต้องหรือหมดอายุแล้ว" },
  { pattern: "invalid or expired password reset token", thai: "ลิงก์รีเซ็ตรหัสผ่านไม่ถูกต้องหรือหมดอายุแล้ว" },
  { pattern: "invalid or expired email verification token", thai: "ลิงก์ยืนยันอีเมลไม่ถูกต้องหรือหมดอายุแล้ว" },
  { pattern: "mfa code required", thai: "บัญชีนี้เปิดใช้ MFA กรุณากรอกรหัส 6 หลักจากแอปยืนยันตัวตน" },
  { pattern: "invalid mfa code", thai: "รหัส MFA ไม่ถูกต้อง กรุณาลองอีกครั้ง" },
  { pattern: "workspace slug required", thai: "อีเมลนี้ถูกใช้ในหลาย workspace กรุณาระบุ Workspace slug เพื่อเข้าสู่ระบบ" },
  { pattern: "account is not active", thai: "บัญชีถูกระงับ กรุณาติดต่อผู้ดูแลระบบ" },
  { pattern: "missing bearer token", thai: "กรุณาเข้าสู่ระบบก่อนใช้งาน" },
  { pattern: "invalid bearer token", thai: "เซสชันหมดอายุ กรุณาเข้าสู่ระบบอีกครั้ง" },
  { pattern: "invalid session", thai: "เซสชันหมดอายุ กรุณาเข้าสู่ระบบอีกครั้ง" },
  { pattern: "missing authentication", thai: "กรุณาเข้าสู่ระบบก่อนใช้งาน" },
  { pattern: "admin role required", thai: "คุณไม่มีสิทธิ์เข้าถึงส่วนนี้ (ต้องเป็นแอดมิน)" },
  { pattern: "support role required", thai: "คุณไม่มีสิทธิ์เข้าถึงส่วนนี้ (ต้องเป็น support)" },
  { pattern: "tenant mismatch", thai: "ไม่สามารถเข้าถึงข้อมูลขององค์กรอื่นได้" },
  { pattern: "email delivery is not configured", thai: "ระบบส่งอีเมลยังไม่ได้ตั้งค่า กรุณาติดต่อผู้ดูแลระบบ" },
  { pattern: "user not found", thai: "ไม่พบผู้ใช้นี้ในระบบ" },
  { pattern: "user does not belong to tenant", thai: "ผู้ใช้นี้ไม่ได้อยู่ในองค์กรนี้" },

  // Billing
  { pattern: "billing record not found", thai: "ไม่พบรายการเรียกเก็บนี้" },
  { pattern: "billing payment not found", thai: "ไม่พบรายการชำระเงินนี้" },
  { pattern: "payment request not found", thai: "ไม่พบคำขอชำระเงินนี้" },
  { pattern: "invalid json payload", thai: "ข้อมูลที่ส่งมาไม่ถูกต้อง กรุณาลองใหม่" },
  { pattern: "manual payment endpoint only accepts bank_transfer", thai: "การบันทึกยอดโอนรองรับเฉพาะการโอนผ่านธนาคารเท่านั้น" },
  { pattern: "payment provider is not configured", thai: "ระบบชำระเงินยังไม่ได้ตั้งค่า กรุณาติดต่อผู้ดูแลระบบ" },
  { pattern: "billing record is not payable", thai: "ใบแจ้งหนี้นี้ยังไม่อยู่ในสถานะที่ชำระได้" },
  { pattern: "billing record has no outstanding balance", thai: "ใบแจ้งหนี้นี้ไม่มียอดคงค้าง" },
  { pattern: "opn api request failed", thai: "ไม่สามารถเชื่อมต่อระบบชำระเงิน OPN ได้ กรุณาตรวจสอบการตั้งค่าและลองใหม่" },
  { pattern: "payment provider request failed", thai: "ไม่สามารถเชื่อมต่อระบบชำระเงินได้ กรุณาลองใหม่อีกครั้ง" },
  { pattern: "invalid billing date", thai: "วันที่เรียกเก็บไม่ถูกต้อง" },
  { pattern: "unsupported subscription upgrade", thai: "แพ็กเกจปัจจุบันยังอัปเกรดไปตัวเลือกนี้ไม่ได้" },
  { pattern: "upgrade already in progress for subscription", thai: "มีคำขออัปเกรดที่กำลังรอชำระอยู่แล้ว" },
  { pattern: "active or pending subscription required for upgrade", thai: "ต้องมีประวัติแพ็กเกจเดิมก่อนจึงจะสร้างคำขออัปเกรดได้" },
  { pattern: "active, pending, or expired subscription required for upgrade", thai: "ต้องมีประวัติแพ็กเกจเดิมก่อนจึงจะสร้างคำขออัปเกรดได้" },
  { pattern: "future-start upgrades are not supported", thai: "การอัปเกรดแบบเริ่มใช้ภายหลังยังไม่รองรับ" },
  { pattern: "callback currency does not match", thai: "สกุลเงินไม่ตรงกับคำขอชำระเงิน" },
  { pattern: "callback amount does not match", thai: "จำนวนเงินไม่ตรงกับคำขอชำระเงิน" },
  { pattern: "payment callback secret not configured", thai: "ระบบยังไม่ได้ตั้งค่า callback สำหรับชำระเงิน" },
  { pattern: "invalid payment callback secret", thai: "การยืนยันจากระบบชำระเงินไม่ถูกต้อง" },

  // Projects / Documents
  { pattern: "project not found", thai: "ไม่พบโครงการนี้" },
  { pattern: "document not found", thai: "ไม่พบเอกสารนี้" },
  { pattern: "document diff not found", thai: "ไม่พบผลเปรียบเทียบเอกสารนี้" },
  { pattern: "document review not found", thai: "ไม่พบรายการตรวจสอบเอกสารนี้" },
  { pattern: "storage credentials missing", thai: "การเชื่อมต่อที่เก็บเอกสารยังไม่สมบูรณ์ กรุณาให้ผู้ดูแลตรวจสอบ" },
  { pattern: "refresh token is missing", thai: "โทเค็นของปลายทางจัดเก็บเอกสารไม่ครบ กรุณาเชื่อมต่อใหม่" },
  { pattern: "oauth is not configured", thai: "ระบบยังไม่ได้ตั้งค่า OAuth สำหรับปลายทางจัดเก็บเอกสาร" },
  { pattern: "client is not configured", thai: "ระบบยังไม่ได้ตั้งค่า client สำหรับปลายทางจัดเก็บเอกสาร" },
  { pattern: "did not include access_token", thai: "ไม่สามารถต่ออายุการเชื่อมต่อปลายทางจัดเก็บเอกสารได้" },

  // Tenant / Webhooks
  { pattern: "tenant not found", thai: "ไม่พบองค์กรนี้ในระบบ" },
  { pattern: "webhook not found", thai: "ไม่พบ webhook นี้" },

  // Rules / Entitlements
  { pattern: "profile name is required", thai: "กรุณาระบุชื่อโปรไฟล์" },
  { pattern: "unsupported profile type", thai: "ประเภทโปรไฟล์ไม่รองรับ" },
  { pattern: "at least one keyword is required", thai: "กรุณาใส่อย่างน้อย 1 คำค้น" },
  { pattern: "active keyword configuration exceeds plan limit", thai: "จำนวนคำค้นเกินสิทธิ์ของแพ็กเกจปัจจุบัน" },
  { pattern: "active subscription required", thai: "ต้องมีแพ็กเกจที่เปิดใช้งานอยู่จึงจะใช้ฟีเจอร์นี้ได้" },
  { pattern: "discover keyword is not entitled", thai: "แพ็กเกจปัจจุบันไม่รองรับคำค้นแบบ discover" },

  // Generic API errors
  { pattern: "api request failed", thai: "เชื่อมต่อเซิร์ฟเวอร์ไม่สำเร็จ กรุณาลองใหม่อีกครั้ง" },
];

/**
 * Translate an API error into a Thai user-facing message.
 *
 * Checks the error's `detail` (for `ApiError`) or `message` (for plain `Error`)
 * against known English API error strings and returns the Thai translation.
 * If no match is found, returns the provided `fallback` string instead of
 * exposing raw English technical details to Thai-speaking users.
 */
export function localizeApiError(error: unknown, fallback: string): string {
  let detail = "";
  let code = "";
  if (error instanceof ApiError) {
    detail = error.detail;
    code = error.code?.trim().toLowerCase() ?? "";
  } else if (error instanceof Error) {
    detail = error.message;
  }

  if (code) {
    const thai = API_ERROR_CODE_TRANSLATIONS[code];
    if (thai) {
      return thai;
    }
  }

  if (!detail) return fallback;

  const lower = detail.toLowerCase();
  for (const entry of API_ERROR_TRANSLATIONS) {
    if (lower.includes(entry.pattern)) {
      return entry.thai;
    }
  }
  return fallback;
}

async function throwApiError(response: Response): Promise<never> {
  let detail = `API request failed: ${response.status} ${response.statusText}`;
  let code: string | undefined;
  try {
    const payload = (await response.json()) as {
      code?: string;
      detail?: string | Array<{ loc?: Array<string | number>; msg?: string }>;
    };
    if (typeof payload.code === "string" && payload.code.trim()) {
      code = payload.code.trim();
    }
    if (typeof payload.detail === "string" && payload.detail.trim()) {
      detail = payload.detail;
    } else if (Array.isArray(payload.detail) && payload.detail.length > 0) {
      // Pydantic 422 validation errors — extract human-readable messages
      detail = payload.detail
        .map((err) => {
          const field = err.loc?.filter((s) => s !== "body").join(".") ?? "";
          const msg = err.msg ?? "invalid";
          return field ? `${field}: ${msg}` : msg;
        })
        .join("; ");
    }
  } catch {}
  throw new ApiError(response.status, detail, code);
}

async function apiFetch<T>(url: string): Promise<T> {
  const response = await fetch(url, {
    headers: getApiHeaders(),
    cache: "no-store",
    credentials: "include",
  });
  if (!response.ok) {
    await throwApiError(response);
  }
  return response.json() as Promise<T>;
}

async function apiJsonRequest<T>(url: string, init: RequestInit): Promise<T> {
  const response = await fetch(url, {
    ...init,
    headers: {
      ...getApiHeaders(),
      "Content-Type": "application/json",
      ...(init.headers ?? {}),
    },
    cache: "no-store",
    credentials: "include",
  });
  if (!response.ok) {
    await throwApiError(response);
  }
  return response.json() as Promise<T>;
}

async function apiEmptyRequest(url: string, init: RequestInit): Promise<void> {
  const response = await fetch(url, {
    ...init,
    headers: {
      ...getApiHeaders(),
      ...(init.headers ?? {}),
    },
    cache: "no-store",
    credentials: "include",
  });
  if (!response.ok) {
    await throwApiError(response);
  }
}

function parseDownloadFilename(
  contentDisposition: string | null,
  fallback = "download.bin",
): string {
  if (!contentDisposition) return fallback;

  const encodedMatch = contentDisposition.match(/filename\*=UTF-8''([^;]+)/i);
  if (encodedMatch?.[1]) {
    return decodeURIComponent(encodedMatch[1]);
  }

  const plainMatch = contentDisposition.match(/filename="?([^";]+)"?/i);
  if (plainMatch?.[1]) {
    return plainMatch[1];
  }

  return fallback;
}

/* ------------------------------------------------------------------ */
/*  Fetch Functions                                                    */
/* ------------------------------------------------------------------ */

export type FetchProjectsParams = {
  [Key in keyof Omit<ProjectListQueryParams, "tenant_id">]?: ApiQueryInput<
    Omit<ProjectListQueryParams, "tenant_id">[Key]
  >;
};

export type ExportProjectsParams = Omit<FetchProjectsParams, "limit" | "offset">;

export async function fetchProjects(
  params: FetchProjectsParams = {},
): Promise<ProjectListResponse> {
  const url = buildUrl("/v1/projects", {
    project_state: params.project_state,
    procurement_type: params.procurement_type,
    closed_reason: params.closed_reason,
    organization: params.organization,
    keyword: params.keyword,
    budget_min: params.budget_min,
    budget_max: params.budget_max,
    updated_after: params.updated_after,
    has_changed_tor: params.has_changed_tor,
    has_winner: params.has_winner,
    limit: params.limit ?? 50,
    offset: params.offset ?? 0,
  });
  return apiFetch<ProjectListResponse>(url);
}

export async function fetchProjectExport(
  params: ExportProjectsParams = {},
): Promise<ProjectExportResponse> {
  const url = buildUrl("/v1/exports/excel", {
    project_state: params.project_state,
    procurement_type: params.procurement_type,
    closed_reason: params.closed_reason,
    organization: params.organization,
    keyword: params.keyword,
    budget_min: params.budget_min,
    budget_max: params.budget_max,
    updated_after: params.updated_after,
    has_changed_tor: params.has_changed_tor,
    has_winner: params.has_winner,
  });
  const response = await fetch(url, {
    headers: getApiHeaders(
      "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ),
    cache: "no-store",
    credentials: "include",
  });
  if (!response.ok) {
    await throwApiError(response);
  }
  return {
    blob: await response.blob(),
    filename: parseDownloadFilename(
      response.headers.get("content-disposition"),
      "egp_projects.xlsx",
    ),
  };
}

export async function fetchProjectDetail(
  projectId: string,
): Promise<ProjectDetailResponse> {
  const url = buildUrl(`/v1/projects/${encodeURIComponent(projectId)}`, {});
  return apiFetch<ProjectDetailResponse>(url);
}

export async function fetchDocuments(
  projectId: string,
): Promise<DocumentListResponse> {
  const url = buildUrl(`/v1/documents/projects/${encodeURIComponent(projectId)}`, {});
  return apiFetch<DocumentListResponse>(url);
}

export async function fetchDocumentDownloadLink(
  documentId: string,
): Promise<DocumentDownloadLinkResponse> {
  const url = buildUrl(
    `/v1/documents/${encodeURIComponent(documentId)}/download-link`,
    {},
  );
  return apiFetch<DocumentDownloadLinkResponse>(url);
}

export async function fetchDocumentDownloadFile(
  documentId: string,
) : Promise<DocumentDownloadFileResponse> {
  const url = buildUrl(`/v1/documents/${encodeURIComponent(documentId)}/download`, {});
  const response = await fetch(url, {
    headers: getApiHeaders("application/octet-stream"),
    cache: "no-store",
    credentials: "include",
  });
  if (!response.ok) {
    await throwApiError(response);
  }
  return {
    blob: await response.blob(),
    filename: parseDownloadFilename(
      response.headers.get("content-disposition"),
      "document.bin",
    ),
  };
}

export async function fetchProjectCrawlEvidence(
  projectId: string,
): Promise<ProjectCrawlEvidenceListResponse> {
  const url = buildUrl(`/v1/projects/${encodeURIComponent(projectId)}/crawl-evidence`, {});
  return apiFetch<ProjectCrawlEvidenceListResponse>(url);
}

export type FetchRunsParams = {
  [Key in keyof NonNullable<
    paths["/v1/runs"]["get"]["parameters"]["query"]
  >]?: ApiQueryInput<NonNullable<paths["/v1/runs"]["get"]["parameters"]["query"]>[Key]>;
};

export type FetchBillingParams = {
  [Key in keyof NonNullable<
    paths["/v1/billing/records"]["get"]["parameters"]["query"]
  >]?: ApiQueryInput<
    NonNullable<paths["/v1/billing/records"]["get"]["parameters"]["query"]>[Key]
  >;
};

export type FetchAuditLogParams = {
  [Key in keyof NonNullable<
    paths["/v1/admin/audit-log"]["get"]["parameters"]["query"]
  >]?: ApiQueryInput<
    NonNullable<paths["/v1/admin/audit-log"]["get"]["parameters"]["query"]>[Key]
  >;
};

export type FetchDashboardSummaryParams = {
};

export type FetchAdminSnapshotParams = {
  [Key in keyof NonNullable<
    paths["/v1/admin"]["get"]["parameters"]["query"]
  >]?: ApiQueryInput<NonNullable<paths["/v1/admin"]["get"]["parameters"]["query"]>[Key]>;
};

export type FetchWebhooksParams = {
  [Key in keyof NonNullable<
    paths["/v1/webhooks"]["get"]["parameters"]["query"]
  >]?: ApiQueryInput<
    NonNullable<paths["/v1/webhooks"]["get"]["parameters"]["query"]>[Key]
  >;
};

export type FetchSupportTenantsParams = {
  query: string;
  limit?: NonNullable<
    paths["/v1/admin/support/tenants"]["get"]["parameters"]["query"]
  >["limit"];
};

export type FetchSupportSummaryParams = {
  tenant_id: string;
  window_days?: NonNullable<
    paths["/v1/admin/support/tenants/{tenant_id}/summary"]["get"]["parameters"]["query"]
  >["window_days"];
};

export type RegisterInput = components["schemas"]["RegisterRequest"];
export type LoginInput = components["schemas"]["LoginRequest"];
export type AcceptInviteInput = components["schemas"]["AcceptInviteRequest"];
export type ForgotPasswordInput = components["schemas"]["ForgotPasswordRequest"];
export type ResetPasswordInput = components["schemas"]["ResetPasswordRequest"];

type CreateBillingRecordRequest = components["schemas"]["CreateBillingRecordRequest"];
export type CreateBillingRecordInput = Omit<CreateBillingRecordRequest, "status"> & {
  status?: CreateBillingRecordRequest["status"] | string;
};

export type CreateBillingUpgradeInput = components["schemas"]["CreateBillingUpgradeRequest"];

type CreateBillingPaymentRequest = components["schemas"]["CreateBillingPaymentRequest"];
export type RecordBillingPaymentInput = Omit<
  CreateBillingPaymentRequest,
  "currency" | "payment_method"
> & {
  currency?: CreateBillingPaymentRequest["currency"];
  payment_method?: CreateBillingPaymentRequest["payment_method"] | string;
};

export type ReconcileBillingPaymentInput =
  components["schemas"]["ReconcileBillingPaymentRequest"];

type TransitionBillingRecordRequest = components["schemas"]["TransitionBillingRecordRequest"];
export type TransitionBillingRecordInput = Omit<
  TransitionBillingRecordRequest,
  "status"
> & {
  status: TransitionBillingRecordRequest["status"] | string;
};

type CreateBillingPaymentRequestRequest =
  components["schemas"]["CreateBillingPaymentRequestRequest"];
export type CreateBillingPaymentRequestInput = Omit<
  CreateBillingPaymentRequestRequest,
  "provider" | "payment_method" | "expires_in_minutes"
> & {
  provider: CreateBillingPaymentRequestRequest["provider"] | string;
  payment_method?: CreateBillingPaymentRequestRequest["payment_method"] | string;
  expires_in_minutes?: CreateBillingPaymentRequestRequest["expires_in_minutes"];
};

type CreateAdminUserRequest = components["schemas"]["CreateAdminUserRequest"];
export type CreateAdminUserInput = Omit<CreateAdminUserRequest, "role" | "status"> & {
  role?: CreateAdminUserRequest["role"] | string;
  status?: CreateAdminUserRequest["status"];
};

type UpdateAdminUserRequest = components["schemas"]["UpdateAdminUserRequest"];
export type UpdateAdminUserInput = Omit<UpdateAdminUserRequest, "role"> & {
  role?: NonNullable<UpdateAdminUserRequest["role"]> | string;
};

export type UpdateAdminUserNotificationPreferencesInput =
  components["schemas"]["UpdateUserNotificationPreferencesRequest"];

export type UpdateTenantSettingsInput =
  components["schemas"]["UpdateTenantSettingsRequest"];

export type FetchTenantStorageSettingsParams = {
  [Key in keyof NonNullable<
    paths["/v1/admin/storage"]["get"]["parameters"]["query"]
  >]?: ApiQueryInput<
    NonNullable<paths["/v1/admin/storage"]["get"]["parameters"]["query"]>[Key]
  >;
};

export type UpdateTenantStorageSettingsInput =
  components["schemas"]["UpdateTenantStorageSettingsRequest"];
export type ConnectTenantStorageInput = components["schemas"]["ConnectTenantStorageRequest"];
export type DisconnectTenantStorageInput =
  components["schemas"]["DisconnectTenantStorageRequest"];
export type TestTenantStorageWriteInput = components["schemas"]["TestTenantStorageRequest"];
export type GoogleDriveOAuthStartResponse =
  components["schemas"]["GoogleDriveOAuthStartResponse"];
export type StartGoogleDriveOAuthInput =
  components["schemas"]["StartGoogleDriveOAuthRequest"];
export type OneDriveOAuthStartResponse =
  components["schemas"]["OneDriveOAuthStartResponse"];
export type StartOneDriveOAuthInput = components["schemas"]["StartOneDriveOAuthRequest"];
export type SelectGoogleDriveFolderInput =
  components["schemas"]["SelectGoogleDriveFolderRequest"];
export type SelectOneDriveFolderInput =
  components["schemas"]["SelectOneDriveFolderRequest"];

type CreateRuleProfileRequest = components["schemas"]["CreateRuleProfileRequest"];

export type CreateRuleProfileInput = Pick<CreateRuleProfileRequest, "name" | "keywords"> &
  Partial<Omit<CreateRuleProfileRequest, "name" | "keywords">>;

export type TriggerManualRecrawlInput = Partial<
  components["schemas"]["ManualRecrawlRequest"]
>;

export type TriggerManualRecrawlResponse =
  paths["/v1/rules/recrawl"]["post"]["responses"][200]["content"]["application/json"];

type CreateWebhookRequest = components["schemas"]["CreateWebhookRequest"];
export type CreateWebhookInput = Omit<CreateWebhookRequest, "notification_types"> & {
  notification_types: string[];
};

export async function fetchRuns(
  params: FetchRunsParams = {},
): Promise<RunListResponse> {
  const url = buildUrl("/v1/runs", {
    limit: params.limit ?? 50,
    offset: params.offset ?? 0,
  });
  return apiFetch<RunListResponse>(url);
}

export async function fetchRunLog(runId: string): Promise<string | null> {
  const url = buildUrl(`/v1/runs/${runId}/log`, {});
  const response = await fetch(url, {
    headers: getApiHeaders("text/plain"),
    cache: "no-store",
    credentials: "include",
  });
  if (response.status === 404) {
    return null;
  }
  if (!response.ok) {
    await throwApiError(response);
  }
  return response.text();
}

export async function fetchDashboardSummary(
  params: FetchDashboardSummaryParams = {},
): Promise<DashboardSummaryResponse> {
  const url = buildUrl("/v1/dashboard/summary", {});
  return apiFetch<DashboardSummaryResponse>(url);
}

export async function fetchRules(): Promise<RulesResponse> {
  const url = buildUrl("/v1/rules", {});
  return apiFetch<RulesResponse>(url);
}

export async function createRuleProfile(
  payload: CreateRuleProfileInput,
): Promise<RuleProfile> {
  const url = buildUrl("/v1/rules/profiles", {});
  return apiJsonRequest<RuleProfile>(url, {
    method: "POST",
    body: JSON.stringify({
      tenant_id: payload.tenant_id,
      name: payload.name,
      profile_type: payload.profile_type ?? "custom",
      is_active: payload.is_active ?? true,
      keywords: payload.keywords,
      max_pages_per_keyword: payload.max_pages_per_keyword,
      close_consulting_after_days: payload.close_consulting_after_days,
      close_stale_after_days: payload.close_stale_after_days,
    }),
  });
}

export async function triggerManualRecrawl(
  payload: TriggerManualRecrawlInput = {},
): Promise<TriggerManualRecrawlResponse> {
  const url = buildUrl("/v1/rules/recrawl", {});
  return apiJsonRequest<TriggerManualRecrawlResponse>(url, {
    method: "POST",
    body: JSON.stringify({
      tenant_id: payload.tenant_id,
    }),
  });
}

export async function fetchBillingRecords(
  params: FetchBillingParams = {},
): Promise<BillingListResponse> {
  const url = buildUrl("/v1/billing/records", {
    limit: params.limit ?? 50,
    offset: params.offset ?? 0,
    include_stale_unpaid: params.include_stale_unpaid,
    stale_unpaid_only: params.stale_unpaid_only,
  });
  return apiFetch<BillingListResponse>(url);
}

export async function fetchBillingPlans(): Promise<BillingPlansResponse> {
  const url = buildUrl("/v1/billing/plans", {});
  return apiFetch<BillingPlansResponse>(url);
}

export async function fetchAdminSnapshot(
  params: FetchAdminSnapshotParams = {},
): Promise<AdminSnapshotResponse> {
  const url = buildUrl("/v1/admin", {
    tenant_id: params.tenant_id,
  });
  return apiFetch<AdminSnapshotResponse>(url);
}

export async function fetchWebhooks(
  params: FetchWebhooksParams = {},
): Promise<WebhookListResponse> {
  const url = buildUrl("/v1/webhooks", {
    tenant_id: params.tenant_id,
  });
  return apiFetch<WebhookListResponse>(url);
}

export async function fetchAuditLog(
  params: FetchAuditLogParams = {},
): Promise<AuditLogListResponse> {
  const url = buildUrl("/v1/admin/audit-log", {
    tenant_id: params.tenant_id,
    source: params.source,
    entity_type: params.entity_type,
    limit: params.limit ?? 50,
    offset: params.offset ?? 0,
  });
  return apiFetch<AuditLogListResponse>(url);
}

export async function fetchSupportTenants(
  params: FetchSupportTenantsParams,
): Promise<SupportTenantListResponse> {
  const url = buildUrl("/v1/admin/support/tenants", {
    query: params.query,
    limit: params.limit ?? 20,
  });
  return apiFetch<SupportTenantListResponse>(url);
}

export async function fetchSupportSummary(
  params: FetchSupportSummaryParams,
): Promise<SupportSummaryResponse> {
  const url = buildUrl(`/v1/admin/support/tenants/${encodeURIComponent(params.tenant_id)}/summary`, {
    window_days: params.window_days ?? 30,
  });
  return apiFetch<SupportSummaryResponse>(url);
}

export async function register(
  payload: RegisterInput,
): Promise<CurrentSessionResponse> {
  const url = buildUrl("/v1/auth/register", {});
  return apiJsonRequest<CurrentSessionResponse>(url, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function fetchTenantStorageSettings(
  params: FetchTenantStorageSettingsParams = {},
): Promise<AdminTenantStorageSettings> {
  const url = buildUrl("/v1/admin/storage", {
    tenant_id: params.tenant_id,
  });
  return apiJsonRequest<AdminTenantStorageSettings>(url, { method: "GET" });
}

export async function login(
  payload: LoginInput,
): Promise<CurrentSessionResponse> {
  const url = buildUrl("/v1/auth/login", {});
  return apiJsonRequest<CurrentSessionResponse>(url, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function acceptInvite(
  payload: AcceptInviteInput,
): Promise<CurrentSessionResponse> {
  const url = buildUrl("/v1/auth/invite/accept", {});
  return apiJsonRequest<CurrentSessionResponse>(url, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function requestPasswordReset(
  payload: ForgotPasswordInput,
): Promise<ActionStatusResponse> {
  const url = buildUrl("/v1/auth/password/forgot", {});
  return apiJsonRequest<ActionStatusResponse>(url, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function resetPassword(
  payload: ResetPasswordInput,
): Promise<ActionStatusResponse> {
  const url = buildUrl("/v1/auth/password/reset", {});
  return apiJsonRequest<ActionStatusResponse>(url, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function sendEmailVerification(): Promise<ActionStatusResponse> {
  const url = buildUrl("/v1/auth/email/verification/send", {});
  return apiJsonRequest<ActionStatusResponse>(url, {
    method: "POST",
    body: JSON.stringify({}),
  });
}

export async function verifyEmail(
  token: string,
): Promise<EmailVerificationResponse> {
  const url = buildUrl("/v1/auth/email/verify", {});
  return apiJsonRequest<EmailVerificationResponse>(url, {
    method: "POST",
    body: JSON.stringify({ token }),
  });
}

export async function setupMfa(): Promise<MfaSetupResponse> {
  const url = buildUrl("/v1/auth/mfa/setup", {});
  return apiJsonRequest<MfaSetupResponse>(url, {
    method: "POST",
    body: JSON.stringify({}),
  });
}

export async function enableMfa(code: string): Promise<MfaStatusResponse> {
  const url = buildUrl("/v1/auth/mfa/enable", {});
  return apiJsonRequest<MfaStatusResponse>(url, {
    method: "POST",
    body: JSON.stringify({ code }),
  });
}

export async function disableMfa(code: string): Promise<MfaStatusResponse> {
  const url = buildUrl("/v1/auth/mfa/disable", {});
  return apiJsonRequest<MfaStatusResponse>(url, {
    method: "POST",
    body: JSON.stringify({ code }),
  });
}

export async function logout(): Promise<void> {
  const url = buildUrl("/v1/auth/logout", {});
  return apiEmptyRequest(url, { method: "POST" });
}

export async function fetchMe(): Promise<CurrentSessionResponse> {
  const url = buildUrl("/v1/me", {});
  return apiFetch<CurrentSessionResponse>(url);
}

export async function createBillingRecord(
  payload: CreateBillingRecordInput,
): Promise<BillingRecordDetail> {
  const url = buildUrl("/v1/billing/records", {});
  return apiJsonRequest<BillingRecordDetail>(url, {
    method: "POST",
    body: JSON.stringify({
      ...payload,
      status: payload.status ?? "awaiting_payment",
      currency: payload.currency ?? "THB",
    }),
  });
}

export async function createBillingUpgrade(
  payload: CreateBillingUpgradeInput,
): Promise<BillingRecordDetail> {
  const url = buildUrl("/v1/billing/upgrades", {});
  return apiJsonRequest<BillingRecordDetail>(url, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function recordBillingPayment(
  recordId: string,
  payload: RecordBillingPaymentInput,
): Promise<BillingPayment> {
  const url = buildUrl(`/v1/billing/records/${encodeURIComponent(recordId)}/payments`, {});
  return apiJsonRequest<BillingPayment>(url, {
    method: "POST",
    body: JSON.stringify({
      ...payload,
      payment_method: payload.payment_method ?? "bank_transfer",
      currency: payload.currency ?? "THB",
    }),
  });
}

export async function reconcileBillingPayment(
  paymentId: string,
  payload: ReconcileBillingPaymentInput,
): Promise<BillingRecordDetail> {
  const url = buildUrl(`/v1/billing/payments/${encodeURIComponent(paymentId)}/reconcile`, {});
  return apiJsonRequest<BillingRecordDetail>(url, {
    method: "POST",
    body: JSON.stringify({
      ...payload,
    }),
  });
}

export async function transitionBillingRecord(
  recordId: string,
  payload: TransitionBillingRecordInput,
): Promise<BillingRecordDetail> {
  const url = buildUrl(`/v1/billing/records/${encodeURIComponent(recordId)}/transition`, {});
  return apiJsonRequest<BillingRecordDetail>(url, {
    method: "POST",
    body: JSON.stringify({
      ...payload,
    }),
  });
}

export async function createBillingPaymentRequest(
  recordId: string,
  payload: CreateBillingPaymentRequestInput,
): Promise<BillingRecordDetail> {
  const url = buildUrl(`/v1/billing/records/${encodeURIComponent(recordId)}/payment-requests`, {});
  return apiJsonRequest<BillingRecordDetail>(url, {
    method: "POST",
    body: JSON.stringify({
      provider: payload.provider,
      payment_method: payload.payment_method ?? "promptpay_qr",
      expires_in_minutes: payload.expires_in_minutes ?? 30,
    }),
  });
}

export async function startFreeTrial(): Promise<BillingSubscription> {
  const url = buildUrl("/v1/billing/trial/start", {});
  return apiJsonRequest<BillingSubscription>(url, {
    method: "POST",
    body: JSON.stringify({}),
  });
}

export async function createAdminUser(payload: CreateAdminUserInput): Promise<AdminUser> {
  const url = buildUrl("/v1/admin/users", {});
  return apiJsonRequest<AdminUser>(url, {
    method: "POST",
    body: JSON.stringify({
      tenant_id: payload.tenant_id,
      email: payload.email,
      full_name: payload.full_name,
      role: payload.role ?? "viewer",
      status: payload.status ?? "active",
    }),
  });
}

export async function inviteAdminUser(
  userId: string,
  tenantId?: string,
): Promise<AdminInviteUserResponse> {
  const url = buildUrl(`/v1/admin/users/${encodeURIComponent(userId)}/invite`, {});
  return apiJsonRequest<AdminInviteUserResponse>(url, {
    method: "POST",
    body: JSON.stringify(
      tenantId
        ? {
            tenant_id: tenantId,
          }
        : {},
    ),
  });
}

export async function updateAdminUser(
  userId: string,
  payload: UpdateAdminUserInput,
): Promise<AdminUser> {
  const url = buildUrl(`/v1/admin/users/${encodeURIComponent(userId)}`, {});
  return apiJsonRequest<AdminUser>(url, {
    method: "PATCH",
    body: JSON.stringify({
      tenant_id: payload.tenant_id,
      full_name: payload.full_name,
      role: payload.role,
      status: payload.status,
      password: payload.password,
    }),
  });
}

export async function updateAdminUserNotificationPreferences(
  userId: string,
  payload: UpdateAdminUserNotificationPreferencesInput,
): Promise<AdminUser> {
  const url = buildUrl(`/v1/admin/users/${encodeURIComponent(userId)}/notification-preferences`, {});
  return apiJsonRequest<AdminUser>(url, {
    method: "PUT",
    body: JSON.stringify({
      tenant_id: payload.tenant_id,
      email_preferences: payload.email_preferences,
    }),
  });
}

export async function updateTenantSettings(
  payload: UpdateTenantSettingsInput,
): Promise<AdminTenantSettings> {
  const url = buildUrl("/v1/admin/settings", {});
  return apiJsonRequest<AdminTenantSettings>(url, {
    method: "PATCH",
    body: JSON.stringify({
      tenant_id: payload.tenant_id,
      ...payload,
    }),
  });
}

export async function updateTenantStorageSettings(
  payload: UpdateTenantStorageSettingsInput,
): Promise<AdminTenantStorageSettings> {
  const url = buildUrl("/v1/admin/storage", {});
  return apiJsonRequest<AdminTenantStorageSettings>(url, {
    method: "PATCH",
    body: JSON.stringify({
      tenant_id: payload.tenant_id,
      provider: payload.provider,
      connection_status: payload.connection_status,
      account_email: payload.account_email,
      folder_label: payload.folder_label,
      folder_path_hint: payload.folder_path_hint,
      provider_folder_id: payload.provider_folder_id,
      provider_folder_url: payload.provider_folder_url,
      managed_fallback_enabled: payload.managed_fallback_enabled,
      managed_backup_enabled: payload.managed_backup_enabled,
      last_validated_at: payload.last_validated_at,
      last_validation_error: payload.last_validation_error,
    }),
  });
}

export async function connectTenantStorage(
  payload: ConnectTenantStorageInput,
): Promise<AdminTenantStorageSettings> {
  const url = buildUrl("/v1/admin/storage/connect", {});
  return apiJsonRequest<AdminTenantStorageSettings>(url, {
    method: "POST",
    body: JSON.stringify({
      tenant_id: payload.tenant_id,
      provider: payload.provider,
      credential_type: payload.credential_type,
      credentials: payload.credentials,
    }),
  });
}

export async function startGoogleDriveOAuth(
  payload: StartGoogleDriveOAuthInput = {},
): Promise<GoogleDriveOAuthStartResponse> {
  const url = buildUrl("/v1/admin/storage/google-drive/oauth/start", {});
  return apiJsonRequest<GoogleDriveOAuthStartResponse>(url, {
    method: "POST",
    body: JSON.stringify({
      tenant_id: payload.tenant_id,
    }),
  });
}

export async function selectGoogleDriveFolder(
  payload: SelectGoogleDriveFolderInput,
): Promise<AdminTenantStorageSettings> {
  const url = buildUrl("/v1/admin/storage/google-drive/folder", {});
  return apiJsonRequest<AdminTenantStorageSettings>(url, {
    method: "POST",
    body: JSON.stringify({
      tenant_id: payload.tenant_id,
      folder_id: payload.folder_id,
      folder_label: payload.folder_label,
      folder_url: payload.folder_url,
    }),
  });
}

export async function startOneDriveOAuth(
  payload: StartOneDriveOAuthInput = {},
): Promise<OneDriveOAuthStartResponse> {
  const url = buildUrl("/v1/admin/storage/onedrive/oauth/start", {});
  return apiJsonRequest<OneDriveOAuthStartResponse>(url, {
    method: "POST",
    body: JSON.stringify({
      tenant_id: payload.tenant_id,
    }),
  });
}

export async function selectOneDriveFolder(
  payload: SelectOneDriveFolderInput,
): Promise<AdminTenantStorageSettings> {
  const url = buildUrl("/v1/admin/storage/onedrive/folder", {});
  return apiJsonRequest<AdminTenantStorageSettings>(url, {
    method: "POST",
    body: JSON.stringify({
      tenant_id: payload.tenant_id,
      folder_id: payload.folder_id,
      folder_label: payload.folder_label,
      folder_url: payload.folder_url,
    }),
  });
}

export async function disconnectTenantStorage(
  payload: DisconnectTenantStorageInput,
): Promise<AdminTenantStorageSettings> {
  const url = buildUrl("/v1/admin/storage/disconnect", {});
  return apiJsonRequest<AdminTenantStorageSettings>(url, {
    method: "POST",
    body: JSON.stringify({
      tenant_id: payload.tenant_id,
      provider: payload.provider,
    }),
  });
}

export async function testTenantStorageWrite(
  payload: TestTenantStorageWriteInput = {},
): Promise<AdminTenantStorageSettings> {
  const url = buildUrl("/v1/admin/storage/test-write", {});
  return apiJsonRequest<AdminTenantStorageSettings>(url, {
    method: "POST",
    body: JSON.stringify({
      tenant_id: payload.tenant_id,
    }),
  });
}

export async function createWebhook(
  payload: CreateWebhookInput,
): Promise<WebhookSubscription> {
  const url = buildUrl("/v1/webhooks", {});
  return apiJsonRequest<WebhookSubscription>(url, {
    method: "POST",
    body: JSON.stringify({
      tenant_id: payload.tenant_id,
      name: payload.name,
      url: payload.url,
      notification_types: payload.notification_types,
      signing_secret: payload.signing_secret,
    }),
  });
}

export async function deleteWebhook(
  webhookId: string,
  tenantId?: string,
): Promise<void> {
  const url = buildUrl(`/v1/webhooks/${encodeURIComponent(webhookId)}`, {
    tenant_id: tenantId,
  });
  return apiEmptyRequest(url, { method: "DELETE" });
}
