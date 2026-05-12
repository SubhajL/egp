import type { AuthenticatedUser, CurrentSessionResponse } from "./api";

const CURRENT_SESSION_STORAGE_KEY = "egp.currentSession";

export function normalizeNextPath(value: string | null | undefined, fallback = "/dashboard"): string {
  if (!value) {
    return fallback;
  }
  if (!value.startsWith("/") || value.startsWith("//")) {
    return fallback;
  }
  return value;
}

export function buildCurrentPath(pathname: string, search = ""): string {
  const normalizedPath = pathname.startsWith("/") ? pathname : "/dashboard";
  return `${normalizedPath}${search}`;
}

export function normalizeToken(value: string | null | undefined): string | null {
  const normalized = value?.trim();
  return normalized ? normalized : null;
}

export function readStoredCurrentSession(): CurrentSessionResponse | undefined {
  if (typeof window === "undefined") {
    return undefined;
  }
  const rawValue = window.sessionStorage.getItem(CURRENT_SESSION_STORAGE_KEY);
  if (!rawValue) {
    return undefined;
  }
  try {
    return JSON.parse(rawValue) as CurrentSessionResponse;
  } catch {
    window.sessionStorage.removeItem(CURRENT_SESSION_STORAGE_KEY);
    return undefined;
  }
}

export function writeStoredCurrentSession(session: CurrentSessionResponse): void {
  if (typeof window === "undefined") {
    return;
  }
  window.sessionStorage.setItem(CURRENT_SESSION_STORAGE_KEY, JSON.stringify(session));
}

export function clearStoredCurrentSession(): void {
  if (typeof window === "undefined") {
    return;
  }
  window.sessionStorage.removeItem(CURRENT_SESSION_STORAGE_KEY);
}

export function getUserDisplayName(user: AuthenticatedUser): string {
  if (user.full_name?.trim()) {
    return user.full_name.trim();
  }
  if (user.email?.trim()) {
    return user.email.trim();
  }
  return user.subject;
}

export function getUserInitials(user: AuthenticatedUser): string {
  const displayName = getUserDisplayName(user);
  const parts = displayName.split(/\s+/).filter(Boolean);
  if (parts.length === 0) {
    return "?";
  }
  if (parts.length === 1) {
    return parts[0].slice(0, 1).toUpperCase();
  }
  return `${parts[0].slice(0, 1)}${parts[parts.length - 1].slice(0, 1)}`.toUpperCase();
}
