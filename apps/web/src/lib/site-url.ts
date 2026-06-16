const DEFAULT_SITE_BASE_URL = "https://egp.example.com";

function readConfiguredSiteUrl(): string | undefined {
  return typeof process !== "undefined" ? process.env.NEXT_PUBLIC_SITE_URL : undefined;
}

export function getSiteBaseUrl(configured?: string): string {
  const candidate = (configured ?? readConfiguredSiteUrl())?.trim();
  if (!candidate) return DEFAULT_SITE_BASE_URL;

  try {
    const url = new URL(candidate);
    if (url.protocol !== "http:" && url.protocol !== "https:") {
      return DEFAULT_SITE_BASE_URL;
    }
    return url.toString().replace(/\/+$/, "");
  } catch {
    return DEFAULT_SITE_BASE_URL;
  }
}
