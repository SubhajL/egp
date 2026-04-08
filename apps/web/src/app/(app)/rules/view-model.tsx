import { AlertTriangle, Clock3, Mail, Package, Search } from "lucide-react";
import type { ReactNode } from "react";

export type PlanTier =
  | "free_trial"
  | "one_time_search_pack"
  | "monthly_membership"
  | "unknown_plan";

export type RulesTabDef = { key: string; label: string; icon: ReactNode };

export function resolvePlanTier(planCode: string | null): PlanTier {
  if (planCode === null) return "free_trial";
  if (planCode === "one_time_search_pack") return "one_time_search_pack";
  if (planCode === "monthly_membership") return "monthly_membership";
  if (planCode === "free_trial") return "free_trial";
  return "unknown_plan";
}

export function tabsForPlan(tier: PlanTier): RulesTabDef[] {
  switch (tier) {
    case "free_trial":
      return [
        { key: "keywords", label: "คำค้นของฉัน", icon: <Search className="size-4" /> },
        { key: "schedule", label: "ความถี่การติดตาม", icon: <Clock3 className="size-4" /> },
        { key: "entitlements", label: "สิทธิ์แพ็กเกจ", icon: <Package className="size-4" /> },
      ];
    case "one_time_search_pack":
      return [
        { key: "keywords", label: "คำค้นของฉัน", icon: <Search className="size-4" /> },
        { key: "schedule", label: "ความถี่การติดตาม", icon: <Clock3 className="size-4" /> },
        { key: "entitlements", label: "ผลลัพธ์และสิทธิ์", icon: <Package className="size-4" /> },
        { key: "notifications", label: "การแจ้งเตือน", icon: <Mail className="size-4" /> },
      ];
    case "monthly_membership":
      return [
        { key: "keywords", label: "คำค้นของฉัน", icon: <Search className="size-4" /> },
        { key: "schedule", label: "ความถี่การติดตาม", icon: <Clock3 className="size-4" /> },
        { key: "notifications", label: "การแจ้งเตือน", icon: <Mail className="size-4" /> },
        { key: "entitlements", label: "สิทธิ์และการใช้งาน", icon: <Package className="size-4" /> },
      ];
    case "unknown_plan":
      return [
        { key: "keywords", label: "คำค้นของฉัน", icon: <Search className="size-4" /> },
        { key: "schedule", label: "ความถี่การติดตาม", icon: <Clock3 className="size-4" /> },
        { key: "entitlements", label: "สิทธิ์และการใช้งาน", icon: <AlertTriangle className="size-4" /> },
      ];
  }
}

export const PLAN_DISPLAY: Record<
  PlanTier,
  { badge: string; color: string; description: string; headerSubtitle: string }
> = {
  free_trial: {
    badge: "ทดลองใช้ฟรี",
    color: "bg-amber-100 text-amber-800",
    description: "ทดลองใช้งาน 1 คำค้นในช่วง 7 วัน",
    headerSubtitle:
      "จัดการคำค้นที่ต้องการติดตามจาก e-GP และดูความถี่การค้นหาตามสิทธิ์แพ็กเกจทดลองใช้ฟรี",
  },
  one_time_search_pack: {
    badge: "แพ็กเกจค้นหาครั้งเดียว",
    color: "bg-blue-100 text-blue-800",
    description: "ค้นหา 1 คำค้น ใช้งานได้ 3 วัน พร้อม export และดาวน์โหลดเอกสาร",
    headerSubtitle: "จัดการคำค้นและตรวจสอบสิทธิ์ตามแพ็กเกจค้นหาครั้งเดียว",
  },
  monthly_membership: {
    badge: "สมาชิกรายเดือน",
    color: "bg-emerald-100 text-emerald-800",
    description: "ติดตามต่อเนื่องสูงสุด 5 คำค้น พร้อมสิทธิ์ใช้งานครบทุกฟีเจอร์",
    headerSubtitle: "จัดการคำค้น ตั้งค่าการแจ้งเตือน และกำหนดความถี่การติดตามสำหรับสมาชิกรายเดือน",
  },
  unknown_plan: {
    badge: "แพ็กเกจที่กำหนดเอง",
    color: "bg-slate-100 text-slate-800",
    description: "สิทธิ์ของบัญชีนี้ถูกกำหนดจากแพ็กเกจที่ยังไม่รองรับการแสดงผลแบบละเอียดในหน้านี้",
    headerSubtitle: "จัดการคำค้นและตรวจสอบสิทธิ์ปัจจุบันของบัญชีนี้อย่างปลอดภัย แม้แผนใช้งานจะยังไม่มี mapping ในหน้า rules",
  },
};

export function headerSubtitleForPlan(tier: PlanTier): string {
  return PLAN_DISPLAY[tier].headerSubtitle;
}
