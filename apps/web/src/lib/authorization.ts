export function hasAdminAccessRole(role: string | null | undefined): boolean {
  const normalizedRole = (role ?? "").trim();
  return normalizedRole === "owner" || normalizedRole === "admin" || normalizedRole === "support";
}

export function hasRunOperatorRole(role: string | null | undefined): boolean {
  const normalizedRole = (role ?? "").trim();
  return (
    normalizedRole === "owner" ||
    normalizedRole === "admin" ||
    normalizedRole === "support" ||
    normalizedRole === "analyst"
  );
}

export function isAdminOnlyPath(pathname: string): boolean {
  return (
    pathname === "/billing" ||
    pathname.startsWith("/billing/") ||
    pathname === "/admin" ||
    pathname.startsWith("/admin/")
  );
}
