"use client";

import { type FormEvent, useEffect, useMemo, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import {
  Clock3,
  Mail,
  Pause,
  Pencil,
  Play,
  Plus,
  Search,
  ShieldCheck,
  Sparkles,
  Tag,
  X,
} from "lucide-react";
import { PageHeader } from "@/components/layout/page-header";
import { QueryState } from "@/components/ui/query-state";
import { useRules } from "@/lib/hooks";
import {
  createRuleProfile,
  localizeApiError,
  updateRuleProfile,
  updateTenantSettings,
} from "@/lib/api";
import type {
  EntitlementSummary,
  NotificationRulesSummary,
  RuleProfile,
  ScheduleRulesSummary,
} from "@/lib/api";
import {
  PLAN_DISPLAY,
  headerSubtitleForPlan,
  resolvePlanTier,
  tabsForPlan,
  type PlanTier,
} from "./view-model";
import {
  CRAWL_INTERVAL_OPTIONS,
  ensureActiveTab,
  formatCrawlInterval,
  keywordGroupStatusPresentation,
  parseKeywordDraft,
  suggestKeywordGroupName,
  validateKeywordGroupName,
  type KeywordGroupEffectiveStatus,
  type KeywordGroupStatusReason,
} from "./page-helpers";

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

function formatKeywordLimit(limit: number | null): string {
  return limit === null ? "ไม่จำกัด" : String(limit);
}

function formatKeywordQuota(entitlements: EntitlementSummary): string {
  return `${entitlements.runnable_keyword_count} / ${formatKeywordLimit(
    entitlements.keyword_limit,
  )}`;
}

function formatRemainingKeywordSlots(entitlements: EntitlementSummary): string {
  return entitlements.remaining_keyword_slots === null
    ? "ไม่จำกัด"
    : `${entitlements.remaining_keyword_slots} คำค้น`;
}

/* ------------------------------------------------------------------ */
/*  Profile Card — customer-facing version                            */
/* ------------------------------------------------------------------ */

function WatchlistCard({
  profile,
  existingNames,
  busy,
  onRename,
  onUpdateKeywords,
  onToggle,
}: {
  profile: RuleProfile;
  existingNames: string[];
  busy: boolean;
  onRename: (profile: RuleProfile, name: string) => Promise<void>;
  onUpdateKeywords: (profile: RuleProfile, keywords: string[]) => Promise<void>;
  onToggle: (profile: RuleProfile) => Promise<void>;
}) {
  const [editMode, setEditMode] = useState<"name" | "keywords" | null>(null);
  const [nameDraft, setNameDraft] = useState(profile.name);
  const [keywordsDraft, setKeywordsDraft] = useState(profile.keywords.join("\n"));
  const [nameError, setNameError] = useState<string | null>(null);
  const presentation = keywordGroupStatusPresentation(
    profile.effective_status as KeywordGroupEffectiveStatus,
    profile.status_reason as KeywordGroupStatusReason,
  );
  const updatedAt = profile.updated_at
    ? new Date(profile.updated_at).toLocaleDateString("th-TH", {
        year: "numeric",
        month: "short",
        day: "numeric",
      })
    : null;
  const uniqueKeywordCount = new Set(
    profile.keywords.map((keyword) => keyword.trim().toLocaleLowerCase()),
  ).size;

  async function submitRename(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const validationError = validateKeywordGroupName(
      nameDraft,
      existingNames,
      profile.name,
    );
    setNameError(validationError);
    if (validationError) return;
    await onRename(profile, nameDraft.trim());
    setEditMode(null);
  }

  async function submitKeywords(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    await onUpdateKeywords(profile, parseKeywordDraft(keywordsDraft));
    setEditMode(null);
  }

  return (
    <div className="rounded-2xl bg-[var(--bg-surface)] p-6 shadow-[var(--shadow-soft)]">
      <div className="mb-4 flex items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <h3 className="text-lg font-bold text-[var(--text-primary)]">{profile.name}</h3>
          <span className={`rounded-full px-2.5 py-1 text-xs font-semibold ${presentation.className}`}>
            {presentation.label}
          </span>
        </div>
        {updatedAt ? (
          <p className="text-xs text-[var(--text-muted)]">อัปเดตล่าสุด {updatedAt}</p>
        ) : null}
      </div>

      {presentation.guidance ? (
        <p className="mb-4 rounded-xl bg-[var(--bg-surface-secondary)] px-3 py-2 text-xs text-[var(--text-muted)]">
          {presentation.guidance}
        </p>
      ) : null}

      {editMode === "name" ? (
        <form className="mb-4 flex flex-col gap-2" onSubmit={submitRename}>
          <label className="text-sm text-[var(--text-secondary)]" htmlFor={`rename-${profile.id}`}>
            ชื่อกลุ่มคำค้น
          </label>
          <div className="flex gap-2">
            <input
              id={`rename-${profile.id}`}
              value={nameDraft}
              onChange={(event) => setNameDraft(event.target.value)}
              className="min-w-0 flex-1 rounded-xl border border-[var(--border-default)] px-3 py-2 text-sm"
            />
            <button type="submit" disabled={busy} className="rounded-xl bg-primary px-3 py-2 text-sm font-semibold text-white">
              บันทึกชื่อ
            </button>
          </div>
          {nameError ? <p className="text-xs text-[var(--badge-red-text)]">{nameError}</p> : null}
        </form>
      ) : null}

      {editMode === "keywords" ? (
        <form className="mb-4 flex flex-col gap-2" onSubmit={submitKeywords}>
          <label className="text-sm text-[var(--text-secondary)]" htmlFor={`keywords-${profile.id}`}>
            แก้ไขคำค้น
          </label>
          <textarea
            id={`keywords-${profile.id}`}
            value={keywordsDraft}
            onChange={(event) => setKeywordsDraft(event.target.value)}
            rows={4}
            className="rounded-xl border border-[var(--border-default)] px-3 py-2 text-sm"
          />
          <button type="submit" disabled={busy} className="self-end rounded-xl bg-primary px-3 py-2 text-sm font-semibold text-white">
            บันทึกคำค้น
          </button>
        </form>
      ) : null}

      <div>
        <p className="mb-2 text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">
          คำค้นที่บันทึก ({uniqueKeywordCount})
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
                className="inline-flex items-center rounded-full border border-primary/20 bg-primary/5 px-2.5 py-1 text-xs font-medium text-primary"
              >
                {keyword}
              </span>
            ))}
          </div>
        )}
      </div>

      <div className="mt-5 flex flex-wrap items-center gap-2 text-sm text-[var(--text-muted)]">
        <span className="inline-flex items-center gap-1">
          <Tag className="size-3.5" />
          {uniqueKeywordCount} คำค้นไม่ซ้ำ
        </span>
        <div className="ml-auto flex flex-wrap gap-2">
          <button type="button" disabled={busy} onClick={() => setEditMode("name")} className="inline-flex items-center gap-1 rounded-lg px-2 py-1 text-xs font-semibold text-primary">
            <Pencil className="size-3.5" /> เปลี่ยนชื่อ
          </button>
          <button type="button" disabled={busy} onClick={() => setEditMode("keywords")} className="inline-flex items-center gap-1 rounded-lg px-2 py-1 text-xs font-semibold text-primary">
            <Pencil className="size-3.5" /> แก้ไขคำค้น
          </button>
          <button type="button" disabled={busy} onClick={() => void onToggle(profile)} className="inline-flex items-center gap-1 rounded-lg px-2 py-1 text-xs font-semibold text-[var(--text-secondary)]">
            {profile.enabled_by_user ? <Pause className="size-3.5" /> : <Play className="size-3.5" />}
            {profile.enabled_by_user ? "หยุดติดตาม" : "เริ่มติดตาม"}
          </button>
        </div>
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
            {formatKeywordQuota(entitlements)}
          </p>
        </div>
        <div className="rounded-2xl bg-[var(--bg-surface)] px-4 py-4">
          <p className="text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">
            เพิ่มได้อีก
          </p>
          <p className="mt-1 text-2xl font-bold text-[var(--text-primary)]">
            {formatRemainingKeywordSlots(entitlements)}
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
  name,
  keywordDraft,
  suggestedName,
  busy,
  error,
  notice,
  onClose,
  onNameChange,
  onKeywordDraftChange,
  onSubmit,
}: {
  name: string;
  keywordDraft: string;
  suggestedName: string;
  busy: boolean;
  error: string | null;
  notice: string | null;
  onClose: () => void;
  onNameChange: (value: string) => void;
  onKeywordDraftChange: (value: string) => void;
  onSubmit: (event: FormEvent<HTMLFormElement>) => Promise<void>;
}) {
  const parsedKeywords = parseKeywordDraft(keywordDraft);

  return (
    <div className="mb-6 rounded-2xl bg-[var(--bg-surface)] p-6 shadow-[var(--shadow-soft)]">
      <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
        <div>
          <h3 className="text-lg font-bold text-[var(--text-primary)]">สร้างกลุ่มคำค้น</h3>
          <p className="mt-2 max-w-2xl text-sm text-[var(--text-muted)]">
            ตั้งชื่อที่สื่อความหมายและใส่คำค้นเริ่มต้น กลุ่มจะถูกเก็บไว้แม้สิทธิ์ค้นหาจะพักอยู่
          </p>
        </div>
        <button type="button" onClick={onClose} aria-label="ปิดแบบฟอร์มสร้างกลุ่ม" className="rounded-lg p-2 text-[var(--text-muted)] hover:bg-[var(--bg-surface-secondary)]">
          <X className="size-4" />
        </button>
      </div>

      <form className="mt-5 grid grid-cols-1 gap-4 lg:grid-cols-[1fr,1.4fr]" onSubmit={onSubmit}>
          <label className="flex flex-col gap-2 text-sm text-[var(--text-secondary)]">
            ชื่อกลุ่มคำค้น
            <input
              required
              value={name}
              onChange={(event) => onNameChange(event.target.value)}
              placeholder={suggestedName}
              className="rounded-xl border border-[var(--border-default)] bg-transparent px-3 py-2 text-sm text-[var(--text-primary)] outline-none ring-0 transition focus:border-primary"
            />
          </label>

          <label className="flex flex-col gap-2 text-sm text-[var(--text-secondary)]">
            คำค้น
            <textarea
              required
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
              {busy ? "กำลังบันทึก..." : "สร้างกลุ่ม"}
            </button>
          </div>
      </form>
      <p className="mt-3 text-xs text-[var(--text-muted)]">
        คำค้นเดียวกันอยู่ได้หลายกลุ่มเพื่อการจัดระเบียบ แต่โควต้าและการค้นหาจะนับเพียงครั้งเดียว
      </p>
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
  const [composerOpen, setComposerOpen] = useState(false);
  const [profileName, setProfileName] = useState("");
  const [keywordDraft, setKeywordDraft] = useState("");
  const [profileBusy, setProfileBusy] = useState(false);
  const [profileActionBusyId, setProfileActionBusyId] = useState<string | null>(null);
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
    const nextActiveTab = ensureActiveTab(activeTab, tabs);
    if (nextActiveTab !== activeTab) {
      setActiveTab(nextActiveTab);
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
    const nameError = validateKeywordGroupName(
      profileName,
      data?.profiles.map((profile) => profile.name) ?? [],
    );
    if (nameError) {
      setProfileError(nameError);
      return;
    }
    if (keywords.length === 0) {
      setProfileError("กรุณาใส่อย่างน้อย 1 คำค้น");
      return;
    }

    setProfileBusy(true);
    try {
      await createRuleProfile({
        name: profileName.trim(),
        profile_type: "custom",
        enabled_by_user: true,
        keywords,
      });
      setProfileName("");
      setKeywordDraft("");
      setComposerOpen(false);
      setProfileNotice(`สร้างกลุ่มคำค้นพร้อม ${keywords.length} คำค้นแล้ว`);
      await refreshRules();
    } catch (mutationError) {
      setProfileError(
        localizeApiError(mutationError, "ไม่สามารถบันทึกคำค้นได้"),
      );
    } finally {
      setProfileBusy(false);
    }
  }

  async function handleRenameProfile(profile: RuleProfile, name: string) {
    setProfileError(null);
    setProfileNotice(null);
    setProfileActionBusyId(profile.id);
    try {
      await updateRuleProfile(profile.id, { name });
      setProfileNotice("เปลี่ยนชื่อกลุ่มคำค้นแล้ว");
      await refreshRules();
    } catch (mutationError) {
      setProfileError(localizeApiError(mutationError, "ไม่สามารถอัปเดตคำค้นได้"));
    } finally {
      setProfileActionBusyId(null);
    }
  }

  async function handleUpdateKeywords(profile: RuleProfile, keywords: string[]) {
    setProfileError(null);
    setProfileNotice(null);
    setProfileActionBusyId(profile.id);
    try {
      await updateRuleProfile(profile.id, { keywords });
      setProfileNotice("อัปเดตคำค้นแล้ว");
      await refreshRules();
    } catch (mutationError) {
      setProfileError(localizeApiError(mutationError, "ไม่สามารถอัปเดตคำค้นได้"));
    } finally {
      setProfileActionBusyId(null);
    }
  }

  async function handleToggleProfile(profile: RuleProfile) {
    setProfileError(null);
    setProfileNotice(null);
    setProfileActionBusyId(profile.id);
    try {
      await updateRuleProfile(profile.id, {
        enabled_by_user: !profile.enabled_by_user,
      });
      setProfileNotice(
        profile.enabled_by_user ? "หยุดติดตามกลุ่มแล้ว โดยคำค้นยังอยู่ครบ" : "เริ่มติดตามกลุ่มแล้ว",
      );
      await refreshRules();
    } catch (mutationError) {
      setProfileError(localizeApiError(mutationError, "ไม่สามารถเปลี่ยนสถานะกลุ่มได้"));
    } finally {
      setProfileActionBusyId(null);
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
        localizeApiError(mutationError, "ไม่สามารถบันทึกความถี่การติดตามได้"),
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
          <div className="mb-6 flex flex-col gap-4 rounded-2xl bg-[var(--bg-surface)] p-6 shadow-[var(--shadow-soft)] sm:flex-row sm:items-center sm:justify-between">
            <div>
              <h2 className="text-xl font-bold text-[var(--text-primary)]">กลุ่มคำค้น</h2>
              <p className="mt-1 text-sm text-[var(--text-muted)]">
                จัดคำค้นเป็นหลายกลุ่ม เปลี่ยนชื่อ และหยุดหรือเริ่มติดตามได้โดยไม่สูญเสียคำค้น
              </p>
            </div>
            <button
              type="button"
              onClick={() => {
                setComposerOpen(true);
                setProfileError(null);
              }}
              className="inline-flex items-center justify-center gap-2 rounded-xl bg-primary px-4 py-2 text-sm font-semibold text-white"
            >
              <Plus className="size-4" /> สร้างกลุ่มคำค้น
            </button>
          </div>

          {composerOpen ? (
            <KeywordComposer
              name={profileName}
              keywordDraft={keywordDraft}
              suggestedName={suggestKeywordGroupName(
                data.profiles.map((profile) => profile.name),
              )}
              busy={profileBusy}
              error={profileError}
              notice={profileNotice}
              onClose={() => setComposerOpen(false)}
              onNameChange={setProfileName}
              onKeywordDraftChange={setKeywordDraft}
              onSubmit={handleCreateProfile}
            />
          ) : null}

          {!composerOpen && profileError ? (
            <p className="mb-4 text-sm font-medium text-[var(--badge-red-text)]">{profileError}</p>
          ) : null}
          {!composerOpen && profileNotice ? (
            <p className="mb-4 text-sm font-medium text-primary">{profileNotice}</p>
          ) : null}

          {data.profiles.length === 0 ? (
            <div className="rounded-2xl bg-[var(--bg-surface)] p-10 text-center shadow-[var(--shadow-soft)]">
              <Search className="mx-auto mb-3 size-8 text-[var(--text-muted)]" />
              <p className="text-lg font-semibold text-[var(--text-primary)]">
                ยังไม่มีคำค้นที่ติดตาม
              </p>
              <p className="mt-2 text-sm text-[var(--text-muted)]">
                สร้างกลุ่มแรกเพื่อจัดเก็บคำค้นที่ต้องการติดตามจาก e-GP
              </p>
            </div>
          ) : (
            <div className="grid grid-cols-1 gap-6 xl:grid-cols-2">
              {data.profiles.map((profile) => (
                <WatchlistCard
                  key={profile.id}
                  profile={profile}
                  existingNames={data.profiles.map((entry) => entry.name)}
                  busy={profileActionBusyId === profile.id}
                  onRename={handleRenameProfile}
                  onUpdateKeywords={handleUpdateKeywords}
                  onToggle={handleToggleProfile}
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
  const headerTitle = "กลุ่มคำค้น";

  const headerSubtitle = headerSubtitleForPlan(tier);

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
            {formatKeywordQuota(data.entitlements)} คำค้นที่ใช้อยู่
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
