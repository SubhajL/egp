/* ------------------------------------------------------------------ */
/*  Types                                                              */
/* ------------------------------------------------------------------ */

export type ProjectSummary = {
  id: string;
  tenant_id: string;
  canonical_project_id: string;
  project_number: string | null;
  project_name: string;
  organization_name: string;
  procurement_type: string;
  proposal_submission_date: string | null;
  budget_amount: string | null;
  project_state: string;
  closed_reason: string | null;
  source_status_text: string | null;
  has_changed_tor: boolean;
  first_seen_at: string;
  last_seen_at: string;
  last_changed_at: string;
  created_at: string;
  updated_at: string;
};

export type ProjectAlias = {
  id: string;
  project_id: string;
  alias_type: string;
  alias_value: string;
  created_at: string;
};

export type ProjectStatusEvent = {
  id: string;
  project_id: string;
  observed_status_text: string;
  normalized_status: string | null;
  observed_at: string;
  run_id: string | null;
  raw_snapshot: Record<string, unknown> | null;
  created_at: string;
};

export type ProjectDetailResponse = {
  project: ProjectSummary;
  aliases: ProjectAlias[];
  status_events: ProjectStatusEvent[];
};

export type AuthenticatedUser = {
  id: string | null;
  subject: string;
  email: string | null;
  full_name: string | null;
  role: string | null;
  status: string | null;
  email_verified: boolean;
  email_verified_at: string | null;
  mfa_enabled: boolean;
};

export type AuthTenant = {
  id: string;
  name: string;
  slug: string;
  plan_code: string;
  is_active: boolean;
  created_at: string;
  updated_at: string;
};

export type CurrentSessionResponse = {
  user: AuthenticatedUser;
  tenant: AuthTenant;
};

export type ProjectListResponse = {
  projects: ProjectSummary[];
  total: number;
  limit: number;
  offset: number;
};

export type DocumentSummary = {
  id: string;
  project_id: string;
  file_name: string;
  sha256: string;
  storage_key: string;
  document_type: string;
  document_phase: string;
  source_label: string;
  source_status_text: string;
  size_bytes: number;
  is_current: boolean;
  supersedes_document_id: string | null;
  created_at: string;
};

export type DocumentListResponse = {
  documents: DocumentSummary[];
};

export type DocumentDownloadResponse = {
  download_url: string;
};

export type ProjectCrawlEvidence = {
  task_id: string;
  run_id: string;
  trigger_type: string;
  run_status: string;
  task_type: string;
  task_status: string;
  attempts: number;
  keyword: string | null;
  started_at: string | null;
  finished_at: string | null;
  created_at: string;
  payload: Record<string, unknown> | null;
  result_json: Record<string, unknown> | null;
  run_summary_json: Record<string, unknown> | null;
  run_error_count: number;
};

export type ProjectCrawlEvidenceListResponse = {
  evidence: ProjectCrawlEvidence[];
  total: number;
  limit: number;
  offset: number;
};

export type RunSummary = {
  id: string;
  tenant_id: string;
  trigger_type: string;
  status: string;
  profile_id: string | null;
  started_at: string | null;
  finished_at: string | null;
  summary_json: Record<string, unknown> | null;
  error_count: number;
  created_at: string;
};

export type TaskSummary = {
  id: string;
  run_id: string;
  task_type: string;
  project_id: string | null;
  keyword: string | null;
  status: string;
  attempts: number;
  started_at: string | null;
  finished_at: string | null;
  payload: Record<string, unknown> | null;
  result_json: Record<string, unknown> | null;
  created_at: string;
};

export type RunDetailResponse = {
  run: RunSummary;
  tasks: TaskSummary[];
};

export type RunListResponse = {
  runs: RunDetailResponse[];
  total: number;
  limit: number;
  offset: number;
};

export type RuleProfile = {
  id: string;
  name: string;
  profile_type: string;
  is_active: boolean;
  max_pages_per_keyword: number;
  close_consulting_after_days: number;
  close_stale_after_days: number;
  keywords: string[];
  created_at: string;
  updated_at: string;
};

export type ClosureRulesSummary = {
  close_on_winner_status: boolean;
  close_on_contract_status: boolean;
  winner_status_terms: string[];
  contract_status_terms: string[];
  consulting_timeout_days: number;
  stale_no_tor_days: number;
  stale_eligible_states: string[];
  source: string;
};

export type NotificationRulesSummary = {
  supported_channels: string[];
  supported_types: string[];
  event_wiring_complete: boolean;
  source: string;
};

export type ScheduleRulesSummary = {
  supported_trigger_types: string[];
  schedule_execution_supported: boolean;
  editable_in_product: boolean;
  tenant_crawl_interval_hours: number | null;
  default_crawl_interval_hours: number;
  effective_crawl_interval_hours: number;
  source: string;
};

export type EntitlementSummary = {
  plan_code: string | null;
  plan_label: string | null;
  subscription_status: string | null;
  has_active_subscription: boolean;
  keyword_limit: number | null;
  active_keyword_count: number;
  remaining_keyword_slots: number | null;
  active_keywords: string[];
  over_keyword_limit: boolean;
  runs_allowed: boolean;
  exports_allowed: boolean;
  document_download_allowed: boolean;
  notifications_allowed: boolean;
  source: string;
};

export type RulesResponse = {
  profiles: RuleProfile[];
  entitlements: EntitlementSummary;
  closure_rules: ClosureRulesSummary;
  notification_rules: NotificationRulesSummary;
  schedule_rules: ScheduleRulesSummary;
};

export type ProjectExportResponse = {
  blob: Blob;
  filename: string;
};

export type DashboardKpis = {
  active_projects: number;
  discovered_today: number;
  winner_projects_this_week: number;
  closed_today: number;
  changed_tor_projects: number;
  crawl_success_rate_percent: number;
  failed_runs_recent: number;
  crawl_success_window_runs: number;
};

export type DashboardRecentRun = {
  id: string;
  trigger_type: string;
  status: string;
  profile_id: string | null;
  started_at: string | null;
  finished_at: string | null;
  created_at: string;
  error_count: number;
  discovered_projects: number;
};

export type DashboardRecentProjectChange = {
  project_id: string;
  project_name: string;
  project_state: string;
  last_changed_at: string;
};

export type DashboardWinnerProject = {
  project_id: string;
  project_name: string;
  project_state: string;
  awarded_at: string;
};

export type DashboardDailyDiscoveryPoint = {
  date: string;
  count: number;
};

export type DashboardStateBreakdownPoint = {
  bucket: string;
  count: number;
};

export type DashboardCrawlCostSummary = {
  estimated_cost_thb: string;
  run_count: number;
  task_count: number;
  failed_run_count: number;
};

export type DashboardStorageCostSummary = {
  estimated_cost_thb: string;
  document_count: number;
  total_bytes: number;
};

export type DashboardNotificationCostSummary = {
  estimated_cost_thb: string;
  sent_count: number;
  failed_webhook_delivery_count: number;
};

export type DashboardPaymentCostSummary = {
  estimated_cost_thb: string;
  billing_record_count: number;
  payment_request_count: number;
  collected_amount_thb: string;
};

export type DashboardCostSummary = {
  window_days: number;
  currency: string;
  estimated_total_thb: string;
  crawl: DashboardCrawlCostSummary;
  storage: DashboardStorageCostSummary;
  notifications: DashboardNotificationCostSummary;
  payments: DashboardPaymentCostSummary;
};

export type DashboardSummaryResponse = {
  kpis: DashboardKpis;
  recent_runs: DashboardRecentRun[];
  recent_changes: DashboardRecentProjectChange[];
  winner_projects: DashboardWinnerProject[];
  daily_discovery: DashboardDailyDiscoveryPoint[];
  project_state_breakdown: DashboardStateBreakdownPoint[];
  cost_summary: DashboardCostSummary;
};

export type BillingRecord = {
  id: string;
  tenant_id: string;
  record_number: string;
  plan_code: string;
  status: string;
  billing_period_start: string;
  billing_period_end: string;
  due_at: string | null;
  issued_at: string | null;
  paid_at: string | null;
  currency: string;
  amount_due: string;
  reconciled_total: string;
  outstanding_balance: string;
  notes: string | null;
  created_at: string;
  updated_at: string;
};

export type BillingSubscription = {
  id: string;
  tenant_id: string;
  billing_record_id: string;
  plan_code: string;
  subscription_status: string;
  billing_period_start: string;
  billing_period_end: string;
  keyword_limit: number | null;
  activated_at: string;
  activated_by_payment_id: string | null;
  created_at: string;
  updated_at: string;
};

export type BillingPayment = {
  id: string;
  billing_record_id: string;
  payment_method: string;
  payment_status: string;
  amount: string;
  currency: string;
  reference_code: string | null;
  received_at: string;
  recorded_at: string;
  reconciled_at: string | null;
  note: string | null;
  recorded_by: string | null;
  reconciled_by: string | null;
};

export type BillingEvent = {
  id: string;
  billing_record_id: string;
  payment_id: string | null;
  event_type: string;
  actor_subject: string | null;
  note: string | null;
  from_status: string | null;
  to_status: string | null;
  created_at: string;
};

export type BillingPaymentRequest = {
  id: string;
  billing_record_id: string;
  provider: string;
  payment_method: string;
  status: string;
  provider_reference: string;
  payment_url: string;
  qr_payload: string;
  qr_svg: string;
  amount: string;
  currency: string;
  expires_at: string | null;
  settled_at: string | null;
  created_at: string;
  updated_at: string;
};

export type BillingRecordDetail = {
  record: BillingRecord;
  payment_requests: BillingPaymentRequest[];
  payments: BillingPayment[];
  events: BillingEvent[];
  subscription: BillingSubscription | null;
};

export type BillingSummary = {
  open_records: number;
  awaiting_reconciliation: number;
  outstanding_amount: string;
  collected_amount: string;
};

export type BillingListResponse = {
  records: BillingRecordDetail[];
  total: number;
  limit: number;
  offset: number;
  summary: BillingSummary;
};

export type BillingPlan = {
  code: string;
  label: string;
  description: string;
  currency: string;
  amount_due: string;
  billing_interval: string;
  keyword_limit: number;
  duration_days: number | null;
  duration_months: number | null;
};

export type BillingPlansResponse = {
  plans: BillingPlan[];
};

export type AdminTenantSummary = {
  id: string;
  name: string;
  slug: string;
  plan_code: string;
  is_active: boolean;
  created_at: string;
  updated_at: string;
};

export type AdminTenantSettings = {
  support_email: string | null;
  billing_contact_email: string | null;
  timezone: string;
  locale: string;
  daily_digest_enabled: boolean;
  weekly_digest_enabled: boolean;
  crawl_interval_hours: number | null;
  created_at: string | null;
  updated_at: string | null;
};

export type AdminUser = {
  id: string;
  email: string;
  full_name: string | null;
  role: string;
  status: string;
  email_verified_at: string | null;
  mfa_enabled: boolean;
  created_at: string;
  updated_at: string;
  notification_preferences: Record<string, boolean>;
};

export type ActionStatusResponse = {
  status: string;
};

export type EmailVerificationResponse = {
  email_verified: boolean;
};

export type MfaSetupResponse = {
  secret: string;
  otpauth_uri: string;
};

export type MfaStatusResponse = {
  mfa_enabled: boolean;
};

export type AdminInviteUserResponse = {
  status: string;
  delivery_email: string;
};

export type AdminBillingOverview = {
  summary: BillingSummary;
  current_subscription: BillingSubscription | null;
  records: BillingRecord[];
};

export type AdminSnapshotResponse = {
  tenant: AdminTenantSummary;
  settings: AdminTenantSettings;
  users: AdminUser[];
  billing: AdminBillingOverview;
};

export type WebhookSubscription = {
  id: string;
  name: string;
  url: string;
  notification_types: string[];
  is_active: boolean;
  created_at: string;
  updated_at: string;
  last_delivery_status: string | null;
  last_delivery_attempted_at: string | null;
  last_delivered_at: string | null;
  last_response_status_code: number | null;
};

export type WebhookListResponse = {
  webhooks: WebhookSubscription[];
};

export type AuditLogEvent = {
  id: string;
  tenant_id: string;
  source: string;
  entity_type: string;
  entity_id: string;
  project_id: string | null;
  document_id: string | null;
  actor_subject: string | null;
  event_type: string;
  summary: string;
  metadata_json: Record<string, unknown> | null;
  occurred_at: string;
  created_at: string;
};

export type AuditLogListResponse = {
  items: AuditLogEvent[];
  total: number;
  limit: number;
  offset: number;
};

export type SupportTenant = {
  id: string;
  name: string;
  slug: string;
  plan_code: string;
  is_active: boolean;
  support_email: string | null;
  billing_contact_email: string | null;
  active_user_count: number;
};

export type SupportTenantListResponse = {
  tenants: SupportTenant[];
};

export type SupportTriageSummary = {
  failed_runs_recent: number;
  pending_document_reviews: number;
  failed_webhook_deliveries: number;
  outstanding_billing_records: number;
};

export type SupportFailedRun = {
  id: string;
  trigger_type: string;
  status: string;
  error_count: number;
  created_at: string;
};

export type SupportPendingReview = {
  id: string;
  project_id: string;
  status: string;
  created_at: string;
};

export type SupportFailedWebhook = {
  id: string;
  webhook_subscription_id: string;
  delivery_status: string;
  last_response_status_code: number | null;
  last_attempted_at: string | null;
};

export type SupportBillingIssue = {
  id: string;
  record_number: string;
  status: string;
  amount_due: string;
  due_at: string | null;
  created_at: string;
};

export type SupportSummaryResponse = {
  tenant: SupportTenant;
  triage: SupportTriageSummary;
  cost_summary: DashboardCostSummary;
  recent_failed_runs: SupportFailedRun[];
  pending_reviews: SupportPendingReview[];
  failed_webhooks: SupportFailedWebhook[];
  billing_issues: SupportBillingIssue[];
};

/* ------------------------------------------------------------------ */
/*  Config                                                             */
/* ------------------------------------------------------------------ */

const DEFAULT_API_PORT = "8000";

function isLoopbackHostname(hostname: string): boolean {
  return hostname === "localhost" || hostname === "127.0.0.1";
}

function readRuntimeEnv(name: string): string | undefined {
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

  constructor(status: number, detail: string) {
    super(detail);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
  }
}

async function throwApiError(response: Response): Promise<never> {
  let detail = `API request failed: ${response.status} ${response.statusText}`;
  try {
    const payload = (await response.json()) as { detail?: string };
    if (typeof payload.detail === "string" && payload.detail.trim()) {
      detail = payload.detail;
    }
  } catch {}
  throw new ApiError(response.status, detail);
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

function parseDownloadFilename(contentDisposition: string | null): string {
  if (!contentDisposition) return "egp_projects.xlsx";

  const encodedMatch = contentDisposition.match(/filename\*=UTF-8''([^;]+)/i);
  if (encodedMatch?.[1]) {
    return decodeURIComponent(encodedMatch[1]);
  }

  const plainMatch = contentDisposition.match(/filename="?([^";]+)"?/i);
  if (plainMatch?.[1]) {
    return plainMatch[1];
  }

  return "egp_projects.xlsx";
}

/* ------------------------------------------------------------------ */
/*  Fetch Functions                                                    */
/* ------------------------------------------------------------------ */

export type FetchProjectsParams = {
  project_state?: string[];
  procurement_type?: string[];
  closed_reason?: string[];
  organization?: string;
  keyword?: string;
  budget_min?: string;
  budget_max?: string;
  updated_after?: string;
  has_changed_tor?: boolean;
  has_winner?: boolean;
  limit?: number;
  offset?: number;
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
    filename: parseDownloadFilename(response.headers.get("content-disposition")),
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

export async function fetchDocumentDownloadUrl(
  documentId: string,
): Promise<DocumentDownloadResponse> {
  const url = buildUrl(`/v1/documents/${encodeURIComponent(documentId)}/download`, {});
  return apiFetch<DocumentDownloadResponse>(url);
}

export async function fetchProjectCrawlEvidence(
  projectId: string,
): Promise<ProjectCrawlEvidenceListResponse> {
  const url = buildUrl(`/v1/projects/${encodeURIComponent(projectId)}/crawl-evidence`, {});
  return apiFetch<ProjectCrawlEvidenceListResponse>(url);
}

export type FetchRunsParams = {
  limit?: number;
  offset?: number;
};

export type FetchBillingParams = {
  limit?: number;
  offset?: number;
};

export type FetchAuditLogParams = {
  tenant_id?: string;
  source?: string;
  entity_type?: string;
  limit?: number;
  offset?: number;
};

export type FetchDashboardSummaryParams = {
};

export type FetchAdminSnapshotParams = {
  tenant_id?: string;
};

export type FetchWebhooksParams = {
  tenant_id?: string;
};

export type FetchSupportTenantsParams = {
  query: string;
  limit?: number;
};

export type FetchSupportSummaryParams = {
  tenant_id: string;
  window_days?: number;
};

export type RegisterInput = {
  company_name: string;
  email: string;
  password: string;
};

export type LoginInput = {
  tenant_slug?: string;
  email: string;
  password: string;
  mfa_code?: string;
};

export type AcceptInviteInput = {
  token: string;
  password: string;
};

export type ForgotPasswordInput = {
  tenant_slug: string;
  email: string;
};

export type ResetPasswordInput = {
  token: string;
  password: string;
};

export type CreateBillingRecordInput = {
  record_number: string;
  plan_code: string;
  status?: string;
  billing_period_start: string;
  billing_period_end?: string;
  due_at?: string;
  issued_at?: string;
  amount_due?: string;
  currency?: string;
  notes?: string;
};

export type RecordBillingPaymentInput = {
  payment_method?: string;
  amount: string;
  currency?: string;
  reference_code?: string;
  received_at: string;
  note?: string;
};

export type ReconcileBillingPaymentInput = {
  status: string;
  note?: string;
};

export type TransitionBillingRecordInput = {
  status: string;
  note?: string;
};

export type CreateBillingPaymentRequestInput = {
  provider?: string;
  payment_method?: string;
  expires_in_minutes?: number;
};

export type CreateAdminUserInput = {
  tenant_id?: string;
  email: string;
  full_name?: string;
  role?: string;
  status?: string;
};

export type UpdateAdminUserInput = {
  tenant_id?: string;
  full_name?: string;
  role?: string;
  status?: string;
  password?: string;
};

export type UpdateAdminUserNotificationPreferencesInput = {
  tenant_id?: string;
  email_preferences: Record<string, boolean>;
};

export type UpdateTenantSettingsInput = {
  tenant_id?: string;
  support_email?: string;
  billing_contact_email?: string;
  timezone?: string;
  locale?: string;
  daily_digest_enabled?: boolean;
  weekly_digest_enabled?: boolean;
  crawl_interval_hours?: number | null;
};

export type CreateRuleProfileInput = {
  tenant_id?: string;
  name: string;
  profile_type?: string;
  is_active?: boolean;
  keywords: string[];
  max_pages_per_keyword?: number;
  close_consulting_after_days?: number;
  close_stale_after_days?: number;
};

export type CreateWebhookInput = {
  tenant_id?: string;
  name: string;
  url: string;
  notification_types: string[];
  signing_secret: string;
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

export async function fetchBillingRecords(
  params: FetchBillingParams = {},
): Promise<BillingListResponse> {
  const url = buildUrl("/v1/billing/records", {
    limit: params.limit ?? 50,
    offset: params.offset ?? 0,
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
  payload: CreateBillingPaymentRequestInput = {},
): Promise<BillingRecordDetail> {
  const url = buildUrl(`/v1/billing/records/${encodeURIComponent(recordId)}/payment-requests`, {});
  return apiJsonRequest<BillingRecordDetail>(url, {
    method: "POST",
    body: JSON.stringify({
      provider: payload.provider ?? "mock_promptpay",
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
