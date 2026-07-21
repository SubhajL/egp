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

export type KeywordGroupEffectiveStatus =
  | "running"
  | "paused_by_user"
  | "paused_by_plan"
  | "blocked_quota";

export type KeywordGroupStatusReason =
  | "subscription_inactive"
  | "outside_current_plan_cycle"
  | "keyword_limit_exceeded"
  | null;

export function keywordGroupStatusPresentation(
  status: KeywordGroupEffectiveStatus,
  reason: KeywordGroupStatusReason,
): { label: string; className: string; guidance: string | null } {
  switch (status) {
    case "running":
      return {
        label: "กำลังติดตาม",
        className: "bg-[var(--badge-green-bg)] text-[var(--badge-green-text)]",
        guidance: null,
      };
    case "paused_by_user":
      return {
        label: "หยุดโดยคุณ",
        className: "bg-[var(--badge-gray-bg)] text-[var(--badge-gray-text)]",
        guidance: "กลุ่มนี้จะไม่ค้นหาจนกว่าคุณจะเริ่มติดตามอีกครั้ง",
      };
    case "blocked_quota":
      return {
        label: "ต้องจัดการโควต้า",
        className: "bg-red-100 text-red-800",
        guidance: "หยุดบางกลุ่มหรือลดคำค้นก่อน ระบบจึงจะเริ่มติดตามต่อ",
      };
    case "paused_by_plan":
      return {
        label: "พักไว้ตามแพ็กเกจ",
        className: "bg-amber-100 text-amber-800",
        guidance:
          reason === "subscription_inactive"
            ? "กลุ่มและคำค้นยังถูกบันทึกไว้ และจะกลับมาทำงานเมื่อสิทธิ์รายเดือนเปิดใช้งาน"
            : reason === "outside_current_plan_cycle"
              ? "กลุ่มนี้อยู่นอกช่วงสิทธิ์ค้นหาปัจจุบัน แต่ข้อมูลยังถูกเก็บไว้ครบถ้วน"
              : "เพิ่มคำค้นอย่างน้อยหนึ่งคำเพื่อเริ่มติดตามกลุ่มนี้",
      };
  }
}

export function validateKeywordGroupName(
  value: string,
  existingNames: string[],
  currentName?: string,
): string | null {
  const normalized = value.trim().toLocaleLowerCase();
  if (!normalized) return "กรุณาตั้งชื่อกลุ่มคำค้น";
  const current = currentName?.trim().toLocaleLowerCase();
  if (
    normalized !== current &&
    existingNames.some((name) => name.trim().toLocaleLowerCase() === normalized)
  ) {
    return "ชื่อกลุ่มคำค้นนี้ถูกใช้แล้ว";
  }
  return null;
}

export function suggestKeywordGroupName(existingNames: string[]): string {
  const used = new Set(existingNames.map((name) => name.trim().toLocaleLowerCase()));
  let index = 1;
  while (used.has(`กลุ่มคำค้น ${index}`.toLocaleLowerCase())) index += 1;
  return `กลุ่มคำค้น ${index}`;
}
