export type BadgeColor = "indigo" | "teal" | "green" | "purple" | "amber" | "red" | "gray";

export type BadgeConfig = {
  label: string;
  color: BadgeColor;
};

export const STATE_BADGE_CONFIG: Record<string, BadgeConfig> = {
  discovered: { label: "ค้นพบใหม่", color: "indigo" },
  open_invitation: { label: "เปิดรับข้อเสนอ", color: "teal" },
  open_consulting: { label: "เปิดรับที่ปรึกษา", color: "teal" },
  open_public_hearing: { label: "ประชาพิจารณ์", color: "amber" },
  tor_downloaded: { label: "ดาวน์โหลด TOR", color: "green" },
  prelim_pricing_seen: { label: "เห็นราคากลาง", color: "green" },
  winner_announced: { label: "ประกาศผู้ชนะ", color: "purple" },
  contract_signed: { label: "ลงนามสัญญา", color: "purple" },
  closed_timeout_consulting: { label: "ปิด-หมดเวลาที่ปรึกษา", color: "gray" },
  closed_stale_no_tor: { label: "ปิด-ไม่มี TOR", color: "gray" },
  closed_manual: { label: "ปิด-ด้วยตนเอง", color: "gray" },
  error: { label: "ข้อผิดพลาด", color: "red" },
};

export const RUN_STATUS_CONFIG: Record<string, BadgeConfig> = {
  queued: { label: "รอคิว", color: "gray" },
  running: { label: "กำลังทำงาน", color: "indigo" },
  succeeded: { label: "สำเร็จ", color: "green" },
  partial: { label: "บางส่วน", color: "amber" },
  failed: { label: "ล้มเหลว", color: "red" },
  cancelled: { label: "ยกเลิก", color: "gray" },
};

export const TASK_STATUS_CONFIG: Record<string, BadgeConfig> = {
  queued: { label: "รอคิว", color: "gray" },
  running: { label: "กำลังทำงาน", color: "indigo" },
  succeeded: { label: "สำเร็จ", color: "green" },
  failed: { label: "ล้มเหลว", color: "red" },
  skipped: { label: "ข้าม", color: "gray" },
};

export const BILLING_STATUS_CONFIG: Record<string, BadgeConfig> = {
  draft: { label: "ร่าง", color: "gray" },
  issued: { label: "ออกบิลแล้ว", color: "indigo" },
  awaiting_payment: { label: "รอชำระ", color: "amber" },
  payment_detected: { label: "พบยอดชำระ", color: "teal" },
  paid: { label: "ชำระครบ", color: "green" },
  failed: { label: "ล้มเหลว", color: "red" },
  overdue: { label: "เกินกำหนด", color: "red" },
  cancelled: { label: "ยกเลิก", color: "gray" },
  refunded: { label: "คืนเงิน", color: "purple" },
};

export const BILLING_PAYMENT_STATUS_CONFIG: Record<string, BadgeConfig> = {
  pending_reconciliation: { label: "รอตรวจสอบ", color: "amber" },
  reconciled: { label: "กระทบยอดแล้ว", color: "green" },
  rejected: { label: "ไม่ผ่าน", color: "red" },
};

export const BILLING_SUBSCRIPTION_STATUS_CONFIG: Record<string, BadgeConfig> = {
  pending_activation: { label: "รอเริ่มสิทธิ์", color: "amber" },
  active: { label: "สิทธิ์ใช้งานเปิดอยู่", color: "green" },
  expired: { label: "สิทธิ์หมดอายุ", color: "gray" },
  cancelled: { label: "สิทธิ์ถูกยกเลิก", color: "red" },
};

export const PROCUREMENT_TYPE_LABELS: Record<string, string> = {
  goods: "สินค้า",
  services: "บริการ",
  consulting: "ที่ปรึกษา",
  unknown: "ไม่ระบุ",
};

export const DOCUMENT_PHASE_LABELS: Record<string, string> = {
  public_hearing: "รับฟังความเห็น",
  final: "ฉบับจริง",
  unknown: "ไม่ระบุ",
};

export type NavItem = {
  label: string;
  href: string;
};

export const NAV_ITEMS: NavItem[] = [
  { label: "แดชบอร์ด", href: "/dashboard" },
  { label: "สำรวจโครงการ", href: "/projects" },
  { label: "การทำงาน", href: "/runs" },
  { label: "คำค้นติดตาม", href: "/rules" },
  { label: "บิลและชำระเงิน", href: "/billing" },
  { label: "ความปลอดภัย", href: "/security" },
  { label: "แอดมิน", href: "/admin" },
];

export const BADGE_STYLE_MAP: Record<BadgeColor, string> = {
  indigo: "bg-[var(--badge-indigo-bg)] text-[var(--badge-indigo-text)]",
  teal: "bg-[var(--badge-teal-bg)] text-[var(--badge-teal-text)]",
  green: "bg-[var(--badge-green-bg)] text-[var(--badge-green-text)]",
  purple: "bg-[var(--badge-purple-bg)] text-[var(--badge-purple-text)]",
  amber: "bg-[var(--badge-amber-bg)] text-[var(--badge-amber-text)]",
  red: "bg-[var(--badge-red-bg)] text-[var(--badge-red-text)]",
  gray: "bg-[var(--badge-gray-bg)] text-[var(--badge-gray-text)]",
};
