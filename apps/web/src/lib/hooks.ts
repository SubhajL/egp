"use client";

import { useQuery } from "@tanstack/react-query";
import {
  fetchProjects,
  fetchProjectDetail,
  fetchProjectCrawlEvidence,
  fetchDocuments,
  fetchRules,
  fetchRuns,
  type FetchProjectsParams,
  type FetchRunsParams,
} from "./api";

export function useProjects(params: FetchProjectsParams = {}) {
  return useQuery({
    queryKey: ["projects", params],
    queryFn: () => fetchProjects(params),
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
