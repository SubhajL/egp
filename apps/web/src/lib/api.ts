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

type ProjectListResponse = {
  projects: ProjectSummary[];
};

const DEFAULT_API_BASE_URL = "http://localhost:8000";

export function getApiBaseUrl(): string {
  const configured =
    process.env.NEXT_PUBLIC_EGP_API_BASE_URL?.trim() ?? DEFAULT_API_BASE_URL;
  return configured.replace(/\/+$/, "");
}

export function getTenantId(): string {
  return process.env.NEXT_PUBLIC_EGP_TENANT_ID?.trim() ?? "";
}

export function getApiBearerToken(): string {
  return process.env.NEXT_PUBLIC_EGP_API_BEARER_TOKEN?.trim() ?? "";
}

function getApiHeaders(): HeadersInit {
  const token = getApiBearerToken();
  return {
    Accept: "application/json",
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
  };
}

export async function fetchProjects(): Promise<ProjectSummary[]> {
  const tenantId = getTenantId();
  if (!tenantId) {
    return [];
  }

  const response = await fetch(
    `${getApiBaseUrl()}/v1/projects?tenant_id=${encodeURIComponent(tenantId)}`,
    {
      headers: getApiHeaders(),
      cache: "no-store",
    },
  );

  if (!response.ok) {
    throw new Error(`Project request failed with ${response.status}`);
  }

  const payload = (await response.json()) as ProjectListResponse;
  return payload.projects;
}
