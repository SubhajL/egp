"use client";

import { useQuery } from "@tanstack/react-query";
import {
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
  fetchWebhooks,
  type FetchBillingParams,
  type FetchProjectsParams,
  type FetchRunsParams,
} from "./api";

export function useProjects(params: FetchProjectsParams = {}) {
  return useQuery({
    queryKey: ["projects", params],
    queryFn: () => fetchProjects(params),
  });
}

export function useDashboardSummary() {
  return useQuery({
    queryKey: ["dashboard-summary"],
    queryFn: () => fetchDashboardSummary(),
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

export function useAdminSnapshot() {
  return useQuery({
    queryKey: ["admin-snapshot"],
    queryFn: () => fetchAdminSnapshot(),
  });
}

export function useWebhooks() {
  return useQuery({
    queryKey: ["webhooks"],
    queryFn: () => fetchWebhooks(),
  });
}
