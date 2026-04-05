"use client";

import { useQuery } from "@tanstack/react-query";
import {
  fetchAuditLog,
  fetchAdminSnapshot,
  fetchBillingPlans,
  fetchBillingRecords,
  fetchDashboardSummary,
  fetchProjectCrawlEvidence,
  fetchProjectDetail,
  fetchProjects,
  fetchDocuments,
  fetchRules,
  fetchRuns,
  fetchSupportSummary,
  fetchSupportTenants,
  fetchWebhooks,
  type FetchAdminSnapshotParams,
  type FetchAuditLogParams,
  type FetchBillingParams,
  type FetchDashboardSummaryParams,
  type FetchProjectsParams,
  type FetchRunsParams,
  type FetchSupportSummaryParams,
  type FetchSupportTenantsParams,
  type FetchWebhooksParams,
} from "./api";

export function useProjects(params: FetchProjectsParams = {}) {
  return useQuery({
    queryKey: ["projects", params],
    queryFn: () => fetchProjects(params),
  });
}

export function useDashboardSummary(params: FetchDashboardSummaryParams = {}) {
  return useQuery({
    queryKey: ["dashboard-summary", params],
    queryFn: () => fetchDashboardSummary(params),
  });
}

export function useProjectDetail(projectId: string) {
  return useQuery({
    queryKey: ["project", projectId],
    queryFn: () => fetchProjectDetail(projectId),
    enabled: !!projectId,
  });
}

export function useDocuments(projectId: string) {
  return useQuery({
    queryKey: ["documents", projectId],
    queryFn: () => fetchDocuments(projectId),
    enabled: !!projectId,
  });
}

export function useProjectCrawlEvidence(projectId: string) {
  return useQuery({
    queryKey: ["project-crawl-evidence", projectId],
    queryFn: () => fetchProjectCrawlEvidence(projectId),
    enabled: !!projectId,
  });
}

export function useRuns(params: FetchRunsParams = {}) {
  return useQuery({
    queryKey: ["runs", params],
    queryFn: () => fetchRuns(params),
  });
}

export function useRules() {
  return useQuery({
    queryKey: ["rules"],
    queryFn: () => fetchRules(),
  });
}

export function useBillingRecords(params: FetchBillingParams = {}) {
  return useQuery({
    queryKey: ["billing-records", params],
    queryFn: () => fetchBillingRecords(params),
  });
}

export function useBillingPlans() {
  return useQuery({
    queryKey: ["billing-plans"],
    queryFn: () => fetchBillingPlans(),
  });
}

export function useAdminSnapshot(params: FetchAdminSnapshotParams = {}) {
  return useQuery({
    queryKey: ["admin-snapshot", params],
    queryFn: () => fetchAdminSnapshot(params),
  });
}

export function useWebhooks(params: FetchWebhooksParams = {}) {
  return useQuery({
    queryKey: ["webhooks", params],
    queryFn: () => fetchWebhooks(params),
  });
}

export function useAuditLog(params: FetchAuditLogParams = {}) {
  return useQuery({
    queryKey: ["audit-log", params],
    queryFn: () => fetchAuditLog(params),
  });
}

export function useSupportTenants(params: FetchSupportTenantsParams) {
  const normalizedQuery = params.query.trim();
  return useQuery({
    queryKey: ["support-tenants", normalizedQuery, params.limit ?? 20],
    queryFn: () => fetchSupportTenants({ ...params, query: normalizedQuery }),
    enabled: normalizedQuery.length > 0,
  });
}

export function useSupportSummary(params: FetchSupportSummaryParams | null) {
  return useQuery({
    queryKey: ["support-summary", params],
    queryFn: () =>
      fetchSupportSummary(
        params ?? {
          tenant_id: "",
        },
      ),
    enabled: !!params?.tenant_id,
  });
}
