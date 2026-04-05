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

export type DashboardSummaryResponse = {
  kpis: DashboardKpis;
  recent_runs: DashboardRecentRun[];
  recent_changes: DashboardRecentProjectChange[];
  winner_projects: DashboardWinnerProject[];
  daily_discovery: DashboardDailyDiscoveryPoint[];
  project_state_breakdown: DashboardStateBreakdownPoint[];
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
  created_at: string | null;
  updated_at: string | null;
};

export type AdminUser = {
  id: string;
  email: string;
  full_name: string | null;
  role: string;
  status: string;
  created_at: string;
  updated_at: string;
  notification_preferences: Record<string, boolean>;
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

/* ------------------------------------------------------------------ */
/*  Config                                                             */
/* ------------------------------------------------------------------ */

const DEFAULT_API_BASE_URL = "http://localhost:8000";

function readRuntimeEnv(name: string): string | undefined {
  if (typeof globalThis === "undefined") return undefined;
  const envSource = (globalThis as { process?: { env?: Record<string, string | undefined> } })
    .process?.env;
  return envSource?.[name];
}

export function getApiBaseUrl(): string {
  if (typeof window === "undefined") return DEFAULT_API_BASE_URL;
  const configured =
    readRuntimeEnv("NEXT_PUBLIC_EGP_API_BASE_URL")?.trim() ?? DEFAULT_API_BASE_URL;
  return configured.replace(/\/+$/, "");
}

export function getTenantId(): string {
  if (typeof window === "undefined") return "";
  return readRuntimeEnv("NEXT_PUBLIC_EGP_TENANT_ID")?.trim() ?? "";
}

export function getApiBearerToken(): string {
  if (typeof window === "undefined") return "";
  return readRuntimeEnv("NEXT_PUBLIC_EGP_API_BEARER_TOKEN")?.trim() ?? "";
}

function getApiHeaders(accept = "application/json"): HeadersInit {
  const token = getApiBearerToken();
  return {
    Accept: accept,
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
  };
}

type QueryParamValue =
  | string
  | number
  | boolean
  | Array<string | number | boolean>
  | undefined;

function buildUrl(path: string, params: Record<string, QueryParamValue>): string {
  const tenantId = getTenantId();
  const searchParams = new URLSearchParams();
  if (tenantId) searchParams.set("tenant_id", tenantId);
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
  return `${getApiBaseUrl()}${path}?${searchParams.toString()}`;
}

async function apiFetch<T>(url: string): Promise<T> {
  const response = await fetch(url, {
    headers: getApiHeaders(),
    cache: "no-store",
  });
  if (!response.ok) {
    throw new Error(`API request failed: ${response.status} ${response.statusText}`);
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
  });
  if (!response.ok) {
    throw new Error(`API request failed: ${response.status} ${response.statusText}`);
  }
  return response.json() as Promise<T>;
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
  });
  if (!response.ok) {
    throw new Error(`API request failed: ${response.status} ${response.statusText}`);
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

export type CreateBillingRecordInput = {
  tenant_id?: string;
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
  tenant_id?: string;
  payment_method?: string;
  amount: string;
  currency?: string;
  reference_code?: string;
  received_at: string;
  note?: string;
};

export type ReconcileBillingPaymentInput = {
  tenant_id?: string;
  status: string;
  note?: string;
};

export type TransitionBillingRecordInput = {
  tenant_id?: string;
  status: string;
  note?: string;
};

export type CreateBillingPaymentRequestInput = {
  tenant_id?: string;
  provider?: string;
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

export async function fetchDashboardSummary(): Promise<DashboardSummaryResponse> {
  const url = buildUrl("/v1/dashboard/summary", {});
  return apiFetch<DashboardSummaryResponse>(url);
}

export async function fetchRules(): Promise<RulesResponse> {
  const url = buildUrl("/v1/rules", {});
  return apiFetch<RulesResponse>(url);
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

export async function fetchAdminSnapshot(): Promise<AdminSnapshotResponse> {
  const url = buildUrl("/v1/admin", {});
  return apiFetch<AdminSnapshotResponse>(url);
}

export async function createBillingRecord(
  payload: CreateBillingRecordInput,
): Promise<BillingRecordDetail> {
  const url = buildUrl("/v1/billing/records", {});
  return apiJsonRequest<BillingRecordDetail>(url, {
    method: "POST",
    body: JSON.stringify({
      ...payload,
      tenant_id: payload.tenant_id ?? (getTenantId() || undefined),
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
      tenant_id: payload.tenant_id ?? (getTenantId() || undefined),
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
      tenant_id: payload.tenant_id ?? (getTenantId() || undefined),
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
      tenant_id: payload.tenant_id ?? (getTenantId() || undefined),
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
      tenant_id: payload.tenant_id ?? (getTenantId() || undefined),
      provider: payload.provider ?? "mock_promptpay",
      expires_in_minutes: payload.expires_in_minutes ?? 30,
    }),
  });
}

export async function createAdminUser(payload: CreateAdminUserInput): Promise<AdminUser> {
  const url = buildUrl("/v1/admin/users", {});
  return apiJsonRequest<AdminUser>(url, {
    method: "POST",
    body: JSON.stringify({
      tenant_id: payload.tenant_id ?? (getTenantId() || undefined),
      email: payload.email,
      full_name: payload.full_name,
      role: payload.role ?? "viewer",
      status: payload.status ?? "active",
    }),
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
      tenant_id: payload.tenant_id ?? (getTenantId() || undefined),
      full_name: payload.full_name,
      role: payload.role,
      status: payload.status,
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
      tenant_id: payload.tenant_id ?? (getTenantId() || undefined),
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
      tenant_id: payload.tenant_id ?? (getTenantId() || undefined),
      ...payload,
    }),
  });
}
