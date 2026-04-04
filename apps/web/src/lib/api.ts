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

export type ProjectExportResponse = {
  blob: Blob;
  filename: string;
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

export async function fetchRuns(
  params: FetchRunsParams = {},
): Promise<RunListResponse> {
  const url = buildUrl("/v1/runs", {
    limit: params.limit ?? 50,
    offset: params.offset ?? 0,
  });
  return apiFetch<RunListResponse>(url);
}
