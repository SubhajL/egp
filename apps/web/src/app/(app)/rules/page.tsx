"use client";

import { type FormEvent, useEffect, useMemo, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import {
  Clock3,
  Mail,
  Package,
  Search,
  ShieldCheck,
  Sparkles,
  Tag,
} from "lucide-react";
import { PageHeader } from "@/components/layout/page-header";
import { QueryState } from "@/components/ui/query-state";
import { useRules } from "@/lib/hooks";
import { createRuleProfile, updateTenantSettings } from "@/lib/api";
import type {
  EntitlementSummary,
  NotificationRulesSummary,
  RuleProfile,
  ScheduleRulesSummary,
} from "@/lib/api";

/* ------------------------------------------------------------------ */
/*  Plan-tier helpers                                                  */
/* ------------------------------------------------------------------ */

type PlanTier = "free_trial" | "one_time_search_pack" | "monthly_membership";

type TabDef = { key: string; label: string; icon: React.ReactNode };

function resolvePlanTier(planCode: string | null): PlanTier {
  if (planCode === "one_time_search_pack") return "one_time_search_pack";
  if (planCode === "monthly_membership") return "monthly_membership";
  return "free_trial"; // default / null / unknown → safest
}

function tabsForPlan(tier: PlanTier): TabDef[] {
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
  }
}

const PLAN_DISPLAY: Record<PlanTier, { badge: string; color: string; description: string }> = {
  free_trial: {
    badge: "ทดลองใช้ฟรี",
    color: "bg-amber-100 text-amber-800",
    description: "ทดลองใช้งาน 1 คำค้นในช่วง 7 วัน",
  },
  one_time_search_pack: {
    badge: "แพ็กเกจค้นหาครั้งเดียว",
    color: "bg-blue-100 text-blue-800",
    description: "ค้นหา 1 คำค้น ใช้งานได้ 3 วัน พร้อม export และดาวน์โหลดเอกสาร",
  },
  monthly_membership: {
    badge: "สมาชิกรายเดือน",
    color: "bg-emerald-100 text-emerald-800",
    description: "ติดตามต่อเนื่องสูงสุด 5 คำค้น พร้อมสิทธิ์ใช้งานครบทุกฟีเจอร์",
  },
};

/* ------------------------------------------------------------------ */
/*  Shared helpers                                                     */
/* ------------------------------------------------------------------ */

const CRAWL_INTERVAL_OPTIONS = [
  { value: "default", label: "ใช้ค่าเริ่มต้นของระบบ (วันละครั้ง)" },
  { value: "1", label: "ทุก 1 ชั่วโมง" },
  { value: "6", label: "ทุก 6 ชั่วโมง" },
  { value: "12", label: "ทุก 12 ชั่วโมง" },
  { value: "24", label: "ทุก 24 ชั่วโมง" },
] as const;

function parseKeywordDraft(value: string): string[] {
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

function formatCrawlInterval(hours: number): string {
  if (hours === 24) return "วันละครั้ง";
  if (hours % 24 === 0) return `ทุก ${hours / 24} วัน`;
  return `ทุก ${hours} ชั่วโมง`;
}

function StatusChip({
  active,
  activeLabel,
  inactiveLabel,
}: {
  active: boolean;
  activeLabel: string;
  inactiveLabel: string;
}) {
  return (
    <span
      className={`rounded-full px-2.5 py-1 text-xs font-semibold ${
        active
          ? "bg-[var(--badge-green-bg)] text-[var(--badge-green-text)]"
          : "bg-[var(--badge-gray-bg)] text-[var(--badge-gray-text)]"
      }`}
    >
      {active ? activeLabel : inactiveLabel}
    </span>
  );
}

function CapabilityBadge({
  allowed,
  label,
}: {
  allowed: boolean;
  label: string;
}) {
  return (
    <span
      className={`inline-flex items-center gap-1 rounded-full px-2.5 py-1 text-xs font-medium ${
        allowed
          ? "bg-[var(--badge-green-bg)] text-[var(--badge-green-text)]"
          : "bg-[var(--badge-gray-bg)] text-[var(--badge-gray-text)] line-through opacity-60"
      }`}
    >
      {label}
    </span>
  );
}

/* ------------------------------------------------------------------ */
/*  Profile Card — customer-facing version                            */
/* ------------------------------------------------------------------ */

function WatchlistCard({
  profile,
  entitlements,
}: {
  profile: RuleProfile;
  entitlements: EntitlementSummary;
}) {
  const updatedAt = profile.updated_at
    ? new Date(profile.updated_at).toLocaleDateString("th-TH", {
        year: "numeric",
        month: "short",
        day: "numeric",
      })
    : null;

  return (
    <div
      className={`rounded-2xl bg-[var(--bg-surface)] p-6 shadow-[var(--shadow-soft)] ${
        !profile.is_active ? "opacity-70" : ""
      }`}
    >
      <div className="mb-4 flex items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <h3 className="text-lg font-bold text-[var(--text-primary)]">{profile.name}</h3>
          <StatusChip active={profile.is_active} activeLabel="ใช้งาน" inactiveLabel="ปิดใช้งาน" />
        </div>
        {updatedAt ? (
          <p className="text-xs text-[var(--text-muted)]">อัปเดตล่าสุด {updatedAt}</p>
        ) : null}
      </div>

      {/* Keyword list */}
      <div>
        <p className="mb-2 text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">
          คำค้นที่ติดตาม ({profile.keywords.length})
        </p>
        {profile.keywords.length === 0 ? (
          <div className="rounded-xl border border-dashed border-[var(--border-default)] px-4 py-5 text-sm text-[var(--text-muted)]">
            ยังไม่มีคำค้นในรายการนี้
          </div>
        ) : (
          <div className="flex flex-wrap gap-2">
            {profile.keywords.map((keyword) => (
              <span
                key={keyword}
                className="rounded-full border border-primary/20 bg-primary/5 px-2.5 py-1 text-xs font-medium text-primary"
              >
                {keyword}
              </span>
            ))}
          </div>
        )}
      </div>

      {/* Quota usage summary */}
      <div className="mt-4 flex items-center gap-4 text-sm text-[var(--text-muted)]">
        <span className="inline-flex items-center gap-1">
          <Tag className="size-3.5" />
          {profile.keywords.length} / {entitlements.keyword_limit ?? "ไม่จำกัด"} คำค้น
        </span>
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Entitlement / Plan Card — customer-facing version                 */
/* ------------------------------------------------------------------ */

function PlanSummaryCard({
  entitlements,
  tier,
}: {
  entitlements: EntitlementSummary;
  tier: PlanTier;
}) {
  const planDisplay = PLAN_DISPLAY[tier];
  const statusLabel = entitlements.has_active_subscription
    ? "ใช้งานได้"
    : entitlements.subscription_status === "pending_activation"
      ? "รอเริ่มสิทธิ์"
      : entitlements.subscription_status === "expired"
        ? "หมดอายุแล้ว"
        : "ยังไม่มีสิทธิ์ใช้งาน";

  return (
    <div className="mb-6 rounded-[28px] border border-primary/15 bg-[linear-gradient(135deg,rgba(22,163,74,0.08),rgba(14,116,144,0.08))] p-6 shadow-[var(--shadow-soft)]">
      <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
        <div>
          <div className="flex items-center gap-2">
            <span className={`rounded-full px-3 py-1 text-xs font-bold ${planDisplay.color}`}>
              {planDisplay.badge}
            </span>
            <StatusChip
              active={entitlements.has_active_subscription}
              activeLabel={statusLabel}
              inactiveLabel={statusLabel}
            />
          </div>
          <h2 className="mt-3 text-2xl font-bold text-[var(--text-primary)]">
            {entitlements.plan_label ?? "ยังไม่มีแพ็กเกจที่เปิดใช้งาน"}
          </h2>
          <p className="mt-2 max-w-2xl text-sm text-[var(--text-muted)]">
            {planDisplay.description}
          </p>
        </div>
      </div>

      {/* Key metrics */}
      <div className="mt-5 grid grid-cols-2 gap-3 lg:grid-cols-4">
        <div className="rounded-2xl bg-[var(--bg-surface)] px-4 py-4">
          <p className="text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">
            คำค้นที่ใช้ได้
          </p>
          <p className="mt-1 text-2xl font-bold text-[var(--text-primary)]">
            {entitlements.active_keyword_count} / {entitlements.keyword_limit ?? "—"}
          </p>
        </div>
        <div className="rounded-2xl bg-[var(--bg-surface)] px-4 py-4">
          <p className="text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">
            เพิ่มได้อีก
          </p>
          <p className="mt-1 text-2xl font-bold text-[var(--text-primary)]">
            {entitlements.remaining_keyword_slots ?? "—"} คำค้น
          </p>
        </div>
        <div className="rounded-2xl bg-[var(--bg-surface)] px-4 py-4 lg:col-span-2">
          <p className="text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">
            สิทธิ์การใช้งาน
          </p>
          <div className="mt-2 flex flex-wrap gap-2">
            <CapabilityBadge allowed={entitlements.runs_allowed} label="ค้นหาอัตโนมัติ" />
            <CapabilityBadge allowed={entitlements.exports_allowed} label="ส่งออก Excel" />
            <CapabilityBadge allowed={entitlements.document_download_allowed} label="ดาวน์โหลดเอกสาร" />
            <CapabilityBadge allowed={entitlements.notifications_allowed} label="แจ้งเตือน" />
          </div>
        </div>
      </div>

      {/* Active keywords chips */}
      <div className="mt-5 flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
        <div className="flex flex-wrap gap-2">
          {entitlements.active_keywords.length === 0 ? (
            <span className="rounded-full border border-dashed border-[var(--border-default)] px-3 py-1.5 text-xs text-[var(--text-muted)]">
              ยังไม่มีคำค้นที่ติดตามอยู่
            </span>
          ) : (
            entitlements.active_keywords.map((keyword) => (
              <span
                key={keyword}
                className="rounded-full border border-primary/20 bg-[var(--bg-surface)] px-3 py-1.5 text-xs font-medium text-primary"
              >
                {keyword}
              </span>
            ))
          )}
        </div>
        {entitlements.over_keyword_limit ? (
          <span className="text-sm font-semibold text-[var(--badge-red-text)]">
            คำค้นเกินโควต้า — ระบบจะหยุดค้นหาอัตโนมัติ
          </span>
        ) : null}
      </div>

      {/* Upgrade CTA for free_trial */}
      {tier === "free_trial" ? (
        <div className="mt-5 rounded-xl border border-amber-200 bg-amber-50 px-4 py-3">
          <div className="flex items-center gap-2 text-sm text-amber-900">
            <Sparkles className="size-4" />
            <span className="font-semibold">อัปเกรดเพื่อปลดล็อกฟีเจอร์เพิ่มเติม</span>
          </div>
          <p className="mt-1 text-xs text-amber-700">
            แพ็กเกจ One-Time Search Pack หรือ Monthly Membership เปิดให้ส่งออก Excel ดาวน์โหลดเอกสาร
            และรับการแจ้งเตือนได้
          </p>
        </div>
      ) : null}
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Keyword Composer — customer-facing version                        */
/* ------------------------------------------------------------------ */

function KeywordComposer({
  entitlements,
  name,
  keywordDraft,
  busy,
  error,
  notice,
  onNameChange,
  onKeywordDraftChange,
  onSubmit,
}: {
  entitlements: EntitlementSummary;
  name: string;
  keywordDraft: string;
  busy: boolean;
  error: string | null;
  notice: string | null;
  onNameChange: (value: string) => void;
  onKeywordDraftChange: (value: string) => void;
  onSubmit: (event: FormEvent<HTMLFormElement>) => Promise<void>;
}) {
  const parsedKeywords = parseKeywordDraft(keywordDraft);
  const slotsLeft = entitlements.remaining_keyword_slots;
  const atLimit = slotsLeft !== null && slotsLeft <= 0;

  return (
    <div className="mb-6 rounded-2xl bg-[var(--bg-surface)] p-6 shadow-[var(--shadow-soft)]">
      <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
        <div>
          <h3 className="text-lg font-bold text-[var(--text-primary)]">
            เพิ่มคำค้นที่ต้องการติดตาม
          </h3>
          <p className="mt-2 max-w-2xl text-sm text-[var(--text-muted)]">
            ใส่คำค้นที่ต้องการให้ระบบติดตามจาก e-GP โดยอัตโนมัติ ระบบจะตรวจสอบโควต้าตามแพ็กเกจปัจจุบัน
          </p>
          <p className="mt-1 flex items-center gap-1.5 text-xs text-primary">
            <Clock3 className="size-3.5" />
            ระบบจะเริ่มค้นหาทันทีเมื่อเพิ่มคำค้นใหม่ หลังจากนั้นจะค้นหาซ้ำตามความถี่ที่ตั้งไว้
          </p>
        </div>
        <div className="rounded-2xl bg-[var(--bg-surface-secondary)] px-4 py-3 text-sm text-[var(--text-secondary)]">
          เหลือโควต้าเพิ่มได้อีก {slotsLeft ?? "ไม่จำกัด"} คำค้น
        </div>
      </div>

      {atLimit ? (
        <div className="mt-4 rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800">
          คำค้นครบโควต้าแล้ว — อัปเกรดแพ็กเกจเพื่อเพิ่มคำค้นเพิ่มเติม
        </div>
      ) : (
        <form className="mt-5 grid grid-cols-1 gap-4 lg:grid-cols-[1fr,1.4fr]" onSubmit={onSubmit}>
          <label className="flex flex-col gap-2 text-sm text-[var(--text-secondary)]">
            ชื่อกลุ่มคำค้น
            <input
              value={name}
              onChange={(event) => onNameChange(event.target.value)}
              placeholder="เช่น คำค้นหลัก"
              className="rounded-xl border border-[var(--border-default)] bg-transparent px-3 py-2 text-sm text-[var(--text-primary)] outline-none ring-0 transition focus:border-primary"
            />
          </label>

          <label className="flex flex-col gap-2 text-sm text-[var(--text-secondary)]">
            คำค้น
            <textarea
              value={keywordDraft}
              onChange={(event) => onKeywordDraftChange(event.target.value)}
              placeholder="ใส่ทีละบรรทัด หรือคั่นด้วย comma"
              rows={5}
              className="rounded-xl border border-[var(--border-default)] bg-transparent px-3 py-2 text-sm text-[var(--text-primary)] outline-none ring-0 transition focus:border-primary"
            />
            <span className="text-xs text-[var(--text-muted)]">
              ระบบจะตัดคำซ้ำให้อัตโนมัติ ตอนนี้เตรียมบันทึก {parsedKeywords.length} คำค้น
            </span>
          </label>

          <div className="flex flex-col gap-3 text-sm lg:col-span-2 sm:flex-row sm:items-center sm:justify-between">
            <div>
              {error ? <p className="font-medium text-[var(--badge-red-text)]">{error}</p> : null}
              {notice ? <p className="font-medium text-primary">{notice}</p> : null}
            </div>
            <button
              type="submit"
              disabled={busy}
              className="rounded-xl bg-primary px-4 py-2 text-sm font-semibold text-white transition hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-60"
            >
              {busy ? "กำลังบันทึก..." : "เพิ่มคำค้น"}
            </button>
          </div>
        </form>
      )}
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Notifications Tab — same content, customer-facing language        */
/* ------------------------------------------------------------------ */

function NotificationsTab({ rules }: { rules: NotificationRulesSummary }) {
  return (
    <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
      <div className="rounded-2xl bg-[var(--bg-surface)] p-6 shadow-[var(--shadow-soft)]">
        <div className="mb-3 flex items-center gap-3">
          <Mail className="size-5 text-primary" />
          <h3 className="text-lg font-bold text-[var(--text-primary)]">
            ช่องทางการแจ้งเตือน
          </h3>
        </div>
        <div className="flex flex-wrap gap-2">
          {rules.supported_channels.map((channel) => (
            <span
              key={channel}
              className="rounded-full bg-[var(--badge-indigo-bg)] px-2.5 py-1 text-xs font-medium text-[var(--badge-indigo-text)]"
            >
              {channel}
            </span>
          ))}
        </div>
      </div>

      <div className="rounded-2xl bg-[var(--bg-surface)] p-6 shadow-[var(--shadow-soft)]">
        <div className="mb-3 flex items-center gap-3">
          <ShieldCheck className="size-5 text-primary" />
          <h3 className="text-lg font-bold text-[var(--text-primary)]">
            สถานะระบบแจ้งเตือน
          </h3>
        </div>
        <StatusChip
          active={rules.event_wiring_complete}
          activeLabel="พร้อมใช้งาน"
          inactiveLabel="กำลังเตรียมระบบ"
        />
        <p className="mt-3 text-sm text-[var(--text-muted)]">
          การแจ้งเตือนจะส่งถึงคุณเมื่อพบโครงการใหม่หรือมีการเปลี่ยนแปลงสถานะ
        </p>
      </div>

      <div className="rounded-2xl bg-[var(--bg-surface)] p-6 shadow-[var(--shadow-soft)] lg:col-span-2">
        <h3 className="text-lg font-bold text-[var(--text-primary)]">
          เหตุการณ์ที่แจ้งเตือนได้
        </h3>
        <div className="mt-4 flex flex-wrap gap-2">
          {rules.supported_types.map((type) => (
            <span
              key={type}
              className="rounded-full border border-[var(--border-default)] px-2.5 py-1 text-xs font-medium text-[var(--text-secondary)]"
            >
              {type}
            </span>
          ))}
        </div>
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Schedule Tab — customer-facing "ความถี่การติดตาม"                    */
/* ------------------------------------------------------------------ */

function ScheduleTab({ rules }: { rules: ScheduleRulesSummary }) {
  return (
    <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
      <div className="rounded-xl bg-[var(--bg-surface-secondary)] px-4 py-3">
        <p className="text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">
          ค่าเริ่มต้น
        </p>
        <p className="mt-1 text-lg font-bold text-[var(--text-primary)]">
          {formatCrawlInterval(rules.default_crawl_interval_hours)}
        </p>
      </div>
      <div className="rounded-xl bg-[var(--bg-surface-secondary)] px-4 py-3">
        <p className="text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">
          ค่าที่คุณตั้งไว้
        </p>
        <p className="mt-1 text-lg font-bold text-[var(--text-primary)]">
          {rules.tenant_crawl_interval_hours === null
            ? "ใช้ค่าเริ่มต้น"
            : formatCrawlInterval(rules.tenant_crawl_interval_hours)}
        </p>
      </div>
      <div className="rounded-xl bg-[var(--bg-surface-secondary)] px-4 py-3">
        <p className="text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">
          ความถี่ที่ใช้จริง
        </p>
        <p className="mt-1 text-lg font-bold text-primary">
          {formatCrawlInterval(rules.effective_crawl_interval_hours)}
        </p>
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Main Page                                                          */
/* ------------------------------------------------------------------ */

export default function RulesPage() {
  const queryClient = useQueryClient();
  const { data, isLoading, isError, error } = useRules();

  const tier = useMemo(() => resolvePlanTier(data?.entitlements.plan_code ?? null), [data]);
  const tabs = useMemo(() => tabsForPlan(tier), [tier]);

  const [activeTab, setActiveTab] = useState<string>("keywords");
  const [profileName, setProfileName] = useState("คำค้นหลัก");
  const [keywordDraft, setKeywordDraft] = useState("");
  const [profileBusy, setProfileBusy] = useState(false);
  const [profileError, setProfileError] = useState<string | null>(null);
  const [profileNotice, setProfileNotice] = useState<string | null>(null);
  const [scheduleChoice, setScheduleChoice] = useState<string>("default");
  const [scheduleBusy, setScheduleBusy] = useState(false);
  const [scheduleError, setScheduleError] = useState<string | null>(null);
  const [scheduleNotice, setScheduleNotice] = useState<string | null>(null);

  // Sync schedule selector when data loads
  useEffect(() => {
    if (!data) return;
    setScheduleChoice(
      data.schedule_rules.tenant_crawl_interval_hours === null
        ? "default"
        : String(data.schedule_rules.tenant_crawl_interval_hours),
    );
  }, [data]);

  // Ensure active tab is valid for the current plan tier
  useEffect(() => {
    if (tabs.length > 0 && !tabs.some((t) => t.key === activeTab)) {
      setActiveTab(tabs[0].key);
    }
  }, [tabs, activeTab]);

  async function refreshRules() {
    await queryClient.invalidateQueries({ queryKey: ["rules"] });
    await queryClient.invalidateQueries({ queryKey: ["admin-snapshot"] });
  }

  async function handleCreateProfile(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setProfileError(null);
    setProfileNotice(null);

    const keywords = parseKeywordDraft(keywordDraft);
    if (keywords.length === 0) {
      setProfileError("กรุณาใส่อย่างน้อย 1 คำค้น");
      return;
    }

    setProfileBusy(true);
    try {
      await createRuleProfile({
        name: profileName.trim() || "คำค้นหลัก",
        profile_type: "custom",
        is_active: true,
        keywords,
      });
      setKeywordDraft("");
      setProfileNotice(`บันทึกคำค้น ${keywords.length} รายการเรียบร้อยแล้ว`);
      await refreshRules();
    } catch (mutationError) {
      setProfileError(
        mutationError instanceof Error ? mutationError.message : "ไม่สามารถบันทึกคำค้นได้",
      );
    } finally {
      setProfileBusy(false);
    }
  }

  async function handleSaveSchedule(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setScheduleError(null);
    setScheduleNotice(null);
    setScheduleBusy(true);
    try {
      await updateTenantSettings({
        crawl_interval_hours: scheduleChoice === "default" ? null : Number(scheduleChoice),
      });
      setScheduleNotice("บันทึกความถี่การติดตามแล้ว");
      await refreshRules();
    } catch (mutationError) {
      setScheduleError(
        mutationError instanceof Error
          ? mutationError.message
          : "ไม่สามารถบันทึกความถี่การติดตามได้",
      );
    } finally {
      setScheduleBusy(false);
    }
  }

  function renderTabContent() {
    if (!data) return null;

    if (activeTab === "keywords") {
      return (
        <>
          <KeywordComposer
            entitlements={data.entitlements}
            name={profileName}
            keywordDraft={keywordDraft}
            busy={profileBusy}
            error={profileError}
            notice={profileNotice}
            onNameChange={setProfileName}
            onKeywordDraftChange={setKeywordDraft}
            onSubmit={handleCreateProfile}
          />

          {data.profiles.length === 0 ? (
            <div className="rounded-2xl bg-[var(--bg-surface)] p-10 text-center shadow-[var(--shadow-soft)]">
              <Search className="mx-auto mb-3 size-8 text-[var(--text-muted)]" />
              <p className="text-lg font-semibold text-[var(--text-primary)]">
                ยังไม่มีคำค้นที่ติดตาม
              </p>
              <p className="mt-2 text-sm text-[var(--text-muted)]">
                ใช้ฟอร์มด้านบนเพื่อเพิ่มคำค้นที่ต้องการติดตามจาก e-GP
              </p>
            </div>
          ) : (
            <div className="grid grid-cols-1 gap-6 xl:grid-cols-2">
              {data.profiles.map((profile) => (
                <WatchlistCard
                  key={profile.id}
                  profile={profile}
                  entitlements={data.entitlements}
                />
              ))}
            </div>
          )}
        </>
      );
    }

    if (activeTab === "notifications") {
      return <NotificationsTab rules={data.notification_rules} />;
    }

    if (activeTab === "schedule") {
      // Monthly membership: full editable schedule controls
      if (tier === "monthly_membership") {
        return (
          <div className="space-y-6">
            <div className="rounded-2xl bg-[var(--bg-surface)] p-6 shadow-[var(--shadow-soft)]">
              <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
                <div>
                  <h3 className="text-lg font-bold text-[var(--text-primary)]">
                    ตั้งค่าความถี่การติดตาม
                  </h3>
                  <p className="mt-2 max-w-2xl text-sm text-[var(--text-muted)]">
                    กำหนดว่าระบบจะค้นหาข้อมูลใหม่จาก e-GP บ่อยแค่ไหน ค่าแนะนำคือวันละครั้ง
                  </p>
                </div>
                <div className="rounded-2xl bg-[var(--bg-surface-secondary)] px-4 py-3 text-sm text-[var(--text-secondary)]">
                  ใช้งานจริง: {formatCrawlInterval(data.schedule_rules.effective_crawl_interval_hours)}
                </div>
              </div>

              <form
                className="mt-5 flex flex-col gap-3 md:flex-row md:items-end"
                onSubmit={handleSaveSchedule}
              >
                <label className="flex min-w-[280px] flex-col gap-2 text-sm text-[var(--text-secondary)]">
                  ความถี่การติดตาม
                  <select
                    value={scheduleChoice}
                    onChange={(event) => setScheduleChoice(event.target.value)}
                    className="rounded-xl border border-[var(--border-default)] bg-transparent px-3 py-2 text-sm text-[var(--text-primary)] outline-none transition focus:border-primary"
                  >
                    {CRAWL_INTERVAL_OPTIONS.map((option) => (
                      <option key={option.value} value={option.value}>
                        {option.label}
                      </option>
                    ))}
                  </select>
                </label>
                <button
                  type="submit"
                  disabled={scheduleBusy}
                  className="rounded-xl bg-primary px-4 py-2 text-sm font-semibold text-white transition hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-60"
                >
                  {scheduleBusy ? "กำลังบันทึก..." : "บันทึก"}
                </button>
              </form>

              {scheduleError ? (
                <p className="mt-3 text-sm font-medium text-[var(--badge-red-text)]">
                  {scheduleError}
                </p>
              ) : null}
              {scheduleNotice ? (
                <p className="mt-3 text-sm font-medium text-primary">{scheduleNotice}</p>
              ) : null}
            </div>

            <ScheduleTab rules={data.schedule_rules} />
          </div>
        );
      }

      // Free trial & one-time: read-only schedule info
      return (
        <div className="space-y-6">
          <div className="rounded-2xl bg-[var(--bg-surface)] p-6 shadow-[var(--shadow-soft)]">
            <div className="flex items-center gap-3 mb-3">
              <Clock3 className="size-5 text-primary" />
              <h3 className="text-lg font-bold text-[var(--text-primary)]">
                ความถี่การติดตาม
              </h3>
            </div>
            <p className="max-w-2xl text-sm text-[var(--text-muted)]">
              ระบบจะเริ่มค้นหาจาก e-GP ทันทีเมื่อคุณเพิ่มคำค้นใหม่ หลังจากนั้นจะค้นหาซ้ำอัตโนมัติตามความถี่ด้านล่าง
            </p>

            <div className="mt-5 grid grid-cols-1 gap-3 md:grid-cols-2">
              <div className="rounded-xl bg-[var(--bg-surface-secondary)] px-4 py-4">
                <p className="text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">
                  ความถี่ที่ใช้กับบัญชีของคุณ
                </p>
                <p className="mt-1 text-2xl font-bold text-primary">
                  {formatCrawlInterval(data.schedule_rules.effective_crawl_interval_hours)}
                </p>
              </div>
              <div className="rounded-xl bg-[var(--bg-surface-secondary)] px-4 py-4">
                <p className="text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">
                  การค้นหาครั้งแรก
                </p>
                <p className="mt-1 text-2xl font-bold text-[var(--text-primary)]">
                  ทันที
                </p>
                <p className="mt-1 text-xs text-[var(--text-muted)]">
                  เมื่อเพิ่มคำค้นใหม่
                </p>
              </div>
            </div>

            {tier === "free_trial" ? (
              <div className="mt-5 rounded-xl border border-amber-200 bg-amber-50 px-4 py-3">
                <div className="flex items-center gap-2 text-sm text-amber-900">
                  <Sparkles className="size-4" />
                  <span className="font-semibold">
                    อัปเกรดเป็นสมาชิกรายเดือนเพื่อปรับความถี่การติดตามได้เอง
                  </span>
                </div>
              </div>
            ) : null}
          </div>
        </div>
      );
    }

    // entitlements tab (all tiers have this, just labeled differently)
    if (activeTab === "entitlements") {
      return <PlanSummaryCard entitlements={data.entitlements} tier={tier} />;
    }

    return null;
  }

  /* Page-level header text */
  const headerTitle = "คำค้นติดตาม";

  const headerSubtitle =
    tier === "free_trial"
      ? "จัดการคำค้นที่ต้องการติดตามจาก e-GP และดูความถี่การค้นหาตามสิทธิ์แพ็กเกจทดลองใช้ฟรี"
      : tier === "one_time_search_pack"
        ? "จัดการคำค้นและตรวจสอบสิทธิ์ตามแพ็กเกจค้นหาครั้งเดียว"
        : "จัดการคำค้น ตั้งค่าการแจ้งเตือน และกำหนดความถี่การติดตามสำหรับสมาชิกรายเดือน";

  return (
    <>
      <PageHeader title={headerTitle} subtitle={headerSubtitle} />

      {/* Plan summary — always visible above tabs */}
      {data ? (
        <div className="mb-6 flex items-center gap-3">
          <span
            className={`rounded-full px-3 py-1 text-xs font-bold ${PLAN_DISPLAY[tier].color}`}
          >
            {PLAN_DISPLAY[tier].badge}
          </span>
          <span className="text-sm text-[var(--text-muted)]">
            {data.entitlements.active_keyword_count} / {data.entitlements.keyword_limit ?? "—"}{" "}
            คำค้นที่ใช้อยู่
          </span>
          {data.entitlements.over_keyword_limit ? (
            <span className="text-xs font-semibold text-[var(--badge-red-text)]">
              เกินโควต้า
            </span>
          ) : null}
        </div>
      ) : null}

      {/* Tab bar — underline style, same visual weight as page title */}
      <div className="mb-8 border-b border-[var(--border-default)]">
        <nav className="-mb-px flex gap-6" aria-label="Tabs">
          {tabs.map((tab) => (
            <button
              key={tab.key}
              type="button"
              onClick={() => setActiveTab(tab.key)}
              className={`inline-flex items-center gap-2 border-b-2 pb-3 text-base font-semibold transition-colors ${
                activeTab === tab.key
                  ? "border-primary text-primary"
                  : "border-transparent text-[var(--text-muted)] hover:border-[var(--border-default)] hover:text-[var(--text-secondary)]"
              }`}
            >
              {tab.icon}
              {tab.label}
            </button>
          ))}
        </nav>
      </div>

      <QueryState isLoading={isLoading} isError={isError} error={error}>
        {renderTabContent()}
      </QueryState>
    </>
  );
}
