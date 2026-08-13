import type { AuthenticatedUser, CurrentSessionResponse } from "./api";

const CURRENT_SESSION_STORAGE_KEY = "egp.currentSession";
const SAFE_NEXT_PATH_BASES = ["https://safe-next-path.invalid/", "https://safe-next-path.test/"];
const ENCODED_SEPARATOR_PATTERN = /%(?:2f|5c)/i;

function safeAppDestination(value: string | null | undefined): string | null {
  if (!value?.startsWith("/")) {
    return null;
  }

  const queryIndex = value.indexOf("?");
  const fragmentIndex = value.indexOf("#");
  const boundaryIndexes = [queryIndex, fragmentIndex].filter((index) => index >= 0);
  const pathnameEnd = boundaryIndexes.length > 0 ? Math.min(...boundaryIndexes) : value.length;
  const pathname = value.slice(0, pathnameEnd);
  if (pathname.includes("\\") || ENCODED_SEPARATOR_PATTERN.test(pathname)) {
    return null;
  }

  try {
    const isSameOriginForEveryBase = SAFE_NEXT_PATH_BASES.every((base) => {
      const parsed = new URL(value, base);
      const trusted = new URL(base);
      return (
        parsed.origin === trusted.origin &&
        parsed.username === "" &&
        parsed.password === ""
      );
    });
    return isSameOriginForEveryBase ? value : null;
  } catch {
    return null;
  }
}

export function normalizeNextPath(value: string | null | undefined, fallback = "/dashboard"): string {
  return safeAppDestination(value) ?? safeAppDestination(fallback) ?? "/dashboard";
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
