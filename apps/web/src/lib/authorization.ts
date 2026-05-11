export function hasAdminAccessRole(role: string | null | undefined): boolean {
  const normalizedRole = (role ?? "").trim();
  return normalizedRole === "owner" || normalizedRole === "admin" || normalizedRole === "support";
}

export function isAdminOnlyPath(pathname: string): boolean {
  return (
    pathname === "/billing" ||
    pathname.startsWith("/billing/") ||
    pathname === "/admin" ||
    pathname.startsWith("/admin/")
  );
}
