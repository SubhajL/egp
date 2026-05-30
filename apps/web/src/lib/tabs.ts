// Resolve a tab key from a URL query param (e.g. the LINE admin deep link
// /admin?tab=slips), falling back when the value is missing or unknown.
export function resolveTabKey<T extends string>(
  param: string | null | undefined,
  validKeys: readonly T[],
  fallback: T,
): T {
  const candidate = (param ?? "").trim();
  return (validKeys as readonly string[]).includes(candidate) ? (candidate as T) : fallback;
}
