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

/* ------------------------------------------------------------------ */
/*  Config                                                             */
/* ------------------------------------------------------------------ */

const DEFAULT_API_BASE_URL = "http://localhost:8000";

export function getApiBaseUrl(): string {
  if (typeof window === "undefined") return DEFAULT_API_BASE_URL;
  const configured =
    process.env.NEXT_PUBLIC_EGP_API_BASE_URL?.trim() ?? DEFAULT_API_BASE_URL;
  return configured.replace(/\/+$/, "");
}

export function getTenantId(): string {
  if (typeof window === "undefined") return "";
  return process.env.NEXT_PUBLIC_EGP_TENANT_ID?.trim() ?? "";
}

export function getApiBearerToken(): string {
  if (typeof window === "undefined") return "";
  return process.env.NEXT_PUBLIC_EGP_API_BEARER_TOKEN?.trim() ?? "";
}

function getApiHeaders(): HeadersInit {
  const token = getApiBearerToken();
  return {
    Accept: "application/json",
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
  };
}

function buildUrl(path: string, params: Record<string, string | number | undefined>): string {
  const tenantId = getTenantId();
  const searchParams = new URLSearchParams();
  if (tenantId) searchParams.set("tenant_id", tenantId);
  for (const [key, value] of Object.entries(params)) {
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

/* ------------------------------------------------------------------ */
/*  Fetch Functions                                                    */
/* ------------------------------------------------------------------ */

export type FetchProjectsParams = {
  project_state?: string;
  limit?: number;
  offset?: number;
};

export async function fetchProjects(
  params: FetchProjectsParams = {},
): Promise<ProjectListResponse> {
  const url = buildUrl("/v1/projects", {
    project_state: params.project_state,
    limit: params.limit ?? 50,
    offset: params.offset ?? 0,
  });
  return apiFetch<ProjectListResponse>(url);
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

export type FetchRunsParams = {
  limit?: number;
  offset?: number;
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
