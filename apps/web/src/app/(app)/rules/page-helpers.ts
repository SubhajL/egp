export const CRAWL_INTERVAL_OPTIONS = [
  { value: "default", label: "ใช้ค่าเริ่มต้นของระบบ (วันละครั้ง)" },
  { value: "1", label: "ทุก 1 ชั่วโมง" },
  { value: "6", label: "ทุก 6 ชั่วโมง" },
  { value: "12", label: "ทุก 12 ชั่วโมง" },
  { value: "24", label: "ทุก 24 ชั่วโมง" },
] as const;

export function parseKeywordDraft(value: string): string[] {
  const chunks = value
    .split(/[\n,]/)
    .map((item) => item.trim())
    .filter(Boolean);
  const ordered: string[] = [];
  const seen = new Set<string>();
  for (const chunk of chunks) {
    const key = chunk.toLocaleLowerCase();
    if (seen.has(key)) continue;
    seen.add(key);
    ordered.push(chunk);
  }
  return ordered;
}

export function formatCrawlInterval(hours: number): string {
  if (hours === 24) return "วันละครั้ง";
  if (hours % 24 === 0) return `ทุก ${hours / 24} วัน`;
  return `ทุก ${hours} ชั่วโมง`;
}

export function ensureActiveTab(currentTab: string, allowedTabs: Array<{ key: string }>): string {
  if (allowedTabs.some((tab) => tab.key === currentTab)) {
    return currentTab;
  }
  return allowedTabs[0]?.key ?? currentTab;
}
