"use client";

import { type FormEvent, useEffect, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { Clock3, Mail, Search, ShieldCheck } from "lucide-react";
import { PageHeader } from "@/components/layout/page-header";
import { QueryState } from "@/components/ui/query-state";
import { useRules } from "@/lib/hooks";
import { createRuleProfile, updateTenantSettings } from "@/lib/api";
import type {
  ClosureRulesSummary,
  EntitlementSummary,
  NotificationRulesSummary,
  RuleProfile,
  ScheduleRulesSummary,
} from "@/lib/api";

const TABS = [
  { key: "profiles", label: "โปรไฟล์คำค้น" },
  { key: "closure", label: "กฎการปิด" },
  { key: "notifications", label: "การแจ้งเตือน" },
  { key: "schedule", label: "กำหนดเวลา" },
] as const;

const PROFILE_DESCRIPTIONS: Record<string, string> = {
  tor: "ค้นหาเอกสาร TOR และงานประกวดราคาที่เกี่ยวข้อง",
  toe: "ค้นหาเอกสารข้อกำหนดทางเทคนิคและไฟล์ประกอบ",
  lue: "ค้นหาเงื่อนไขและเอกสารแนบท้ายสัญญา",
  custom: "โปรไฟล์ที่ปรับแต่งคำค้นเฉพาะ tenant",
};

const PLAN_EXPLAINERS: Record<string, string> = {
  free_trial:
    "Free Trial ทดลองใช้งานได้ 1 คำค้นในช่วง 7 วัน และตั้งใจปิด export, ดาวน์โหลดเอกสาร, และการแจ้งเตือนไว้ก่อน",
  one_time_search_pack:
    "One-Time Search Pack เหมาะกับโจทย์แบบยิงครั้งเดียว 1 คำค้น แต่ยังเปิดสิทธิ์ export, ดาวน์โหลดเอกสาร, และการแจ้งเตือนแบบแพ็กเกจเสียเงิน",
  monthly_membership:
    "Monthly Membership เป็นแพ็กเกจติดตามต่อเนื่อง รองรับได้สูงสุด 5 คำค้น และเปิดสิทธิ์การใช้งานครบสำหรับการเฝ้าระวังระยะยาว",
};

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

function ProfileCard({ profile }: { profile: RuleProfile }) {
  const description = PROFILE_DESCRIPTIONS[profile.profile_type] ?? "โปรไฟล์คำค้นของระบบ";

  return (
    <div
      className={`rounded-2xl bg-[var(--bg-surface)] p-6 shadow-[var(--shadow-soft)] ${
        !profile.is_active ? "opacity-70" : ""
      }`}
    >
      <div className="mb-3 flex items-center justify-between gap-3">
        <div>
          <div className="flex items-center gap-2">
            <h3 className="text-lg font-bold text-[var(--text-primary)]">{profile.name}</h3>
            <StatusChip active={profile.is_active} activeLabel="ใช้งาน" inactiveLabel="ปิดใช้งาน" />
          </div>
          <p className="mt-1 text-sm text-[var(--text-muted)]">{description}</p>
        </div>
        <div className="rounded-xl bg-[var(--bg-surface-secondary)] px-3 py-2 text-right">
          <p className="text-[10px] font-semibold uppercase tracking-wider text-[var(--text-muted)]">
            ชนิดโปรไฟล์
          </p>
          <p className="text-sm font-medium uppercase text-[var(--text-secondary)]">
            {profile.profile_type}
          </p>
        </div>
      </div>

      <div className="grid grid-cols-3 gap-3 text-sm">
        <div className="rounded-xl bg-[var(--bg-surface-secondary)] px-3 py-3">
          <p className="text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">
            หน้า/คำค้น
          </p>
          <p className="mt-1 font-mono text-lg font-bold text-[var(--text-primary)]">
            {profile.max_pages_per_keyword}
          </p>
        </div>
        <div className="rounded-xl bg-[var(--bg-surface-secondary)] px-3 py-3">
          <p className="text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">
            ที่ปรึกษา
          </p>
          <p className="mt-1 font-mono text-lg font-bold text-[var(--text-primary)]">
            {profile.close_consulting_after_days} วัน
          </p>
        </div>
        <div className="rounded-xl bg-[var(--bg-surface-secondary)] px-3 py-3">
          <p className="text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">
            Stale
          </p>
          <p className="mt-1 font-mono text-lg font-bold text-[var(--text-primary)]">
            {profile.close_stale_after_days} วัน
          </p>
        </div>
      </div>

      <div className="mt-4">
        <p className="mb-2 text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">
          คำค้นที่ใช้
        </p>
        {profile.keywords.length === 0 ? (
          <div className="rounded-xl border border-dashed border-[var(--border-default)] px-4 py-5 text-sm text-[var(--text-muted)]">
            ยังไม่มีคำค้นในโปรไฟล์นี้
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
    </div>
  );
}

function EntitlementCard({ entitlements }: { entitlements: EntitlementSummary }) {
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
          <p className="text-xs font-semibold uppercase tracking-[0.24em] text-[var(--text-muted)]">
            Entitlements
          </p>
          <h2 className="mt-2 text-2xl font-bold text-[var(--text-primary)]">
            {entitlements.plan_label ?? "ยังไม่มีแพ็กเกจที่เปิดใช้งาน"}
          </h2>
          <p className="mt-2 max-w-2xl text-sm text-[var(--text-muted)]">
            ตรวจสอบสิทธิ์ใช้งานจริงจาก subscription และคำค้นที่เปิดอยู่ใน tenant นี้ เพื่อให้รู้ทันทีว่าระบบจะอนุญาตให้รันงาน ส่งออกข้อมูล ดาวน์โหลดเอกสาร และส่งแจ้งเตือนได้หรือไม่
          </p>
          {entitlements.plan_code && PLAN_EXPLAINERS[entitlements.plan_code] ? (
            <p className="mt-2 max-w-2xl text-sm font-medium text-primary">
              {PLAN_EXPLAINERS[entitlements.plan_code]}
            </p>
          ) : null}
        </div>
        <div className="rounded-2xl bg-[var(--bg-surface)] px-4 py-3">
          <p className="text-[10px] font-semibold uppercase tracking-wider text-[var(--text-muted)]">
            สถานะ subscription
          </p>
          <div className="mt-2 flex items-center gap-2">
            <StatusChip active={entitlements.has_active_subscription} activeLabel={statusLabel} inactiveLabel={statusLabel} />
            {entitlements.plan_code ? (
              <span className="font-mono text-xs text-[var(--text-secondary)]">
                {entitlements.plan_code}
              </span>
            ) : null}
          </div>
        </div>
      </div>

      <div className="mt-5 grid grid-cols-2 gap-3 lg:grid-cols-5">
        <div className="rounded-2xl bg-[var(--bg-surface)] px-4 py-4">
          <p className="text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">
            Keyword limit
          </p>
          <p className="mt-1 text-2xl font-bold text-[var(--text-primary)]">
            {entitlements.keyword_limit ?? "—"}
          </p>
        </div>
        <div className="rounded-2xl bg-[var(--bg-surface)] px-4 py-4">
          <p className="text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">
            Active keywords
          </p>
          <p className="mt-1 text-2xl font-bold text-[var(--text-primary)]">
            {entitlements.active_keyword_count}
          </p>
        </div>
        <div className="rounded-2xl bg-[var(--bg-surface)] px-4 py-4">
          <p className="text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">
            Remaining slots
          </p>
          <p className="mt-1 text-2xl font-bold text-[var(--text-primary)]">
            {entitlements.remaining_keyword_slots ?? "—"}
          </p>
        </div>
        <div className="rounded-2xl bg-[var(--bg-surface)] px-4 py-4">
          <p className="text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">
            Runs / Exports
          </p>
          <p className="mt-1 text-sm font-semibold text-[var(--text-primary)]">
            {entitlements.runs_allowed ? "อนุญาตรัน" : "บล็อกรัน"} / {entitlements.exports_allowed ? "ส่งออกได้" : "งดส่งออก"}
          </p>
        </div>
        <div className="rounded-2xl bg-[var(--bg-surface)] px-4 py-4">
          <p className="text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">
            Documents / Notify
          </p>
          <p className="mt-1 text-sm font-semibold text-[var(--text-primary)]">
            {entitlements.document_download_allowed ? "ดาวน์โหลดได้" : "งดดาวน์โหลด"} / {entitlements.notifications_allowed ? "แจ้งเตือนได้" : "งดแจ้งเตือน"}
          </p>
        </div>
      </div>

      <div className="mt-5 flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
        <div className="flex flex-wrap gap-2">
          {entitlements.active_keywords.length === 0 ? (
            <span className="rounded-full border border-dashed border-[var(--border-default)] px-3 py-1.5 text-xs text-[var(--text-muted)]">
              ยังไม่มี active keywords
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
        <div className="text-sm text-[var(--text-muted)]">
          {entitlements.over_keyword_limit ? (
            <span className="font-semibold text-[var(--badge-red-text)]">
              active keyword เกิน quota ของแพ็กเกจและจะบล็อก discover task ใหม่
            </span>
          ) : (
            <span>source: <span className="font-mono text-[var(--text-secondary)]">{entitlements.source}</span></span>
          )}
        </div>
      </div>
    </div>
  );
}

function KeywordProfileComposer({
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

  return (
    <div className="mb-6 rounded-2xl bg-[var(--bg-surface)] p-6 shadow-[var(--shadow-soft)]">
      <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
        <div>
          <h3 className="text-lg font-bold text-[var(--text-primary)]">เพิ่มคำค้นสำหรับการ crawl</h3>
          <p className="mt-2 max-w-2xl text-sm text-[var(--text-muted)]">
            ฟอร์มนี้จะสร้างโปรไฟล์แบบ `custom` ใหม่ทันที พร้อมคำค้นที่ต้องการติดตามจริง โดยระบบจะเช็ก quota จากแพ็กเกจปัจจุบันก่อนบันทึก
          </p>
        </div>
        <div className="rounded-2xl bg-[var(--bg-surface-secondary)] px-4 py-3 text-sm text-[var(--text-secondary)]">
          เหลือ quota เพิ่มได้อีก {entitlements.remaining_keyword_slots ?? "ไม่จำกัด"} คำค้น
        </div>
      </div>

      <form className="mt-5 grid grid-cols-1 gap-4 lg:grid-cols-[1fr,1.4fr]" onSubmit={onSubmit}>
        <label className="flex flex-col gap-2 text-sm text-[var(--text-secondary)]">
          ชื่อโปรไฟล์
          <input
            value={name}
            onChange={(event) => onNameChange(event.target.value)}
            placeholder="เช่น Strategic Keywords"
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
    </div>
  );
}

function ClosureTab({ rules }: { rules: ClosureRulesSummary }) {
  return (
    <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
      <div className="rounded-2xl bg-[var(--bg-surface)] p-6 shadow-[var(--shadow-soft)]">
        <div className="mb-3 flex items-center gap-3">
          <ShieldCheck className="size-5 text-primary" />
          <h3 className="text-lg font-bold text-[var(--text-primary)]">
            ปิดเมื่อพบสถานะผู้ชนะ
          </h3>
        </div>
        <StatusChip active={rules.close_on_winner_status} activeLabel="เปิดใช้งาน" inactiveLabel="ปิดใช้งาน" />
        <p className="mt-3 text-sm text-[var(--text-muted)]">สถานะที่ใช้จับคู่:</p>
        <div className="mt-2 flex flex-wrap gap-2">
          {rules.winner_status_terms.map((term) => (
            <span
              key={term}
              className="rounded-full bg-[var(--badge-indigo-bg)] px-2.5 py-1 text-xs font-medium text-[var(--badge-indigo-text)]"
            >
              {term}
            </span>
          ))}
        </div>
      </div>

      <div className="rounded-2xl bg-[var(--bg-surface)] p-6 shadow-[var(--shadow-soft)]">
        <div className="mb-3 flex items-center gap-3">
          <ShieldCheck className="size-5 text-primary" />
          <h3 className="text-lg font-bold text-[var(--text-primary)]">
            ปิดเมื่อพบการลงนามสัญญา
          </h3>
        </div>
        <StatusChip
          active={rules.close_on_contract_status}
          activeLabel="เปิดใช้งาน"
          inactiveLabel="ปิดใช้งาน"
        />
        <p className="mt-3 text-sm text-[var(--text-muted)]">สถานะที่ใช้จับคู่:</p>
        <div className="mt-2 flex flex-wrap gap-2">
          {rules.contract_status_terms.map((term) => (
            <span
              key={term}
              className="rounded-full bg-[var(--badge-green-bg)] px-2.5 py-1 text-xs font-medium text-[var(--badge-green-text)]"
            >
              {term}
            </span>
          ))}
        </div>
      </div>

      <div className="rounded-2xl bg-[var(--bg-surface)] p-6 shadow-[var(--shadow-soft)]">
        <div className="mb-3 flex items-center gap-3">
          <Clock3 className="size-5 text-primary" />
          <h3 className="text-lg font-bold text-[var(--text-primary)]">
            Timeout สำหรับงานที่ปรึกษา
          </h3>
        </div>
        <p className="font-mono text-3xl font-bold text-[var(--text-primary)]">
          {rules.consulting_timeout_days} วัน
        </p>
        <p className="mt-2 text-sm text-[var(--text-muted)]">
          ใช้กับโครงการประเภทที่ปรึกษาตาม logic ปัจจุบันของ worker
        </p>
      </div>

      <div className="rounded-2xl bg-[var(--bg-surface)] p-6 shadow-[var(--shadow-soft)]">
        <div className="mb-3 flex items-center gap-3">
          <Clock3 className="size-5 text-primary" />
          <h3 className="text-lg font-bold text-[var(--text-primary)]">
            ปิดเมื่อไม่มี TOR ต่อเนื่อง
          </h3>
        </div>
        <p className="font-mono text-3xl font-bold text-[var(--text-primary)]">
          {rules.stale_no_tor_days} วัน
        </p>
        <p className="mt-2 text-sm text-[var(--text-muted)]">สถานะที่เข้าเกณฑ์ stale:</p>
        <div className="mt-2 flex flex-wrap gap-2">
          {rules.stale_eligible_states.map((state) => (
            <span
              key={state}
              className="rounded-full bg-[var(--badge-gray-bg)] px-2.5 py-1 text-xs font-medium text-[var(--badge-gray-text)]"
            >
              {state}
            </span>
          ))}
        </div>
      </div>

      <div className="rounded-2xl border border-dashed border-[var(--border-default)] bg-[var(--bg-surface)] p-5 text-sm text-[var(--text-muted)] lg:col-span-2">
        แหล่งอ้างอิง logic:{" "}
        <span className="font-mono text-[var(--text-secondary)]">{rules.source}</span>
      </div>
    </div>
  );
}

function NotificationsTab({ rules }: { rules: NotificationRulesSummary }) {
  return (
    <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
      <div className="rounded-2xl bg-[var(--bg-surface)] p-6 shadow-[var(--shadow-soft)]">
        <div className="mb-3 flex items-center gap-3">
          <Mail className="size-5 text-primary" />
          <h3 className="text-lg font-bold text-[var(--text-primary)]">
            ช่องทางที่แพลตฟอร์มรองรับ
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
            สถานะการเชื่อม event
          </h3>
        </div>
        <StatusChip
          active={rules.event_wiring_complete}
          activeLabel="เชื่อมครบแล้ว"
          inactiveLabel="ยังไม่เชื่อมครบ"
        />
        <p className="mt-3 text-sm text-[var(--text-muted)]">
          หน้านี้แสดงสิ่งที่แพลตฟอร์มรองรับเชิงโครงสร้างในตอนนี้ แต่การยิงแจ้งเตือนจริงจะอยู่ในงานถัดไปของ Phase 2.5
        </p>
      </div>

      <div className="rounded-2xl bg-[var(--bg-surface)] p-6 shadow-[var(--shadow-soft)] lg:col-span-2">
        <h3 className="text-lg font-bold text-[var(--text-primary)]">เหตุการณ์ที่รองรับ</h3>
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
        <p className="mt-4 text-sm text-[var(--text-muted)]">
          แหล่งอ้างอิง implementation:{" "}
          <span className="font-mono text-[var(--text-secondary)]">{rules.source}</span>
        </p>
      </div>
    </div>
  );
}

function ScheduleTab({ rules }: { rules: ScheduleRulesSummary }) {
  const overrideLabel =
    rules.tenant_crawl_interval_hours === null
      ? "ใช้ค่าเริ่มต้นของระบบ"
      : formatCrawlInterval(rules.tenant_crawl_interval_hours);

  return (
    <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
      <div className="rounded-2xl bg-[var(--bg-surface)] p-6 shadow-[var(--shadow-soft)]">
        <div className="mb-3 flex items-center gap-3">
          <Clock3 className="size-5 text-primary" />
          <h3 className="text-lg font-bold text-[var(--text-primary)]">
            Trigger ที่ระบบบันทึกได้
          </h3>
        </div>
        <div className="flex flex-wrap gap-2">
          {rules.supported_trigger_types.map((triggerType) => (
            <span
              key={triggerType}
              className="rounded-full bg-[var(--badge-green-bg)] px-2.5 py-1 text-xs font-medium text-[var(--badge-green-text)]"
            >
              {triggerType}
            </span>
          ))}
        </div>
      </div>

      <div className="rounded-2xl bg-[var(--bg-surface)] p-6 shadow-[var(--shadow-soft)]">
        <div className="mb-3 flex items-center gap-3">
          <ShieldCheck className="size-5 text-primary" />
          <h3 className="text-lg font-bold text-[var(--text-primary)]">
            ขอบเขตการควบคุมจากหน้า Product
          </h3>
        </div>
        <StatusChip
          active={rules.editable_in_product}
          activeLabel="แก้ไขได้จาก UI"
          inactiveLabel="อ่านอย่างเดียว"
        />
        <p className="mt-3 text-sm text-[var(--text-muted)]">
          ตอนนี้หน้า Product สามารถบันทึก cadence policy ต่อ tenant ได้แล้ว แต่ยังต้องมี scheduler หรือ cron ภายนอกมาอ่านค่านี้เพื่อสร้าง run แบบ `schedule` จริง
        </p>
      </div>

      <div className="rounded-2xl bg-[var(--bg-surface)] p-6 shadow-[var(--shadow-soft)] lg:col-span-2">
        <div className="mb-2 flex items-center gap-3">
          <Search className="size-5 text-primary" />
          <h3 className="text-lg font-bold text-[var(--text-primary)]">
            สถานะการทำงานตามเวลา
          </h3>
        </div>
        <StatusChip
          active={rules.schedule_execution_supported}
          activeLabel="รองรับ trigger แบบกำหนดเวลา"
          inactiveLabel="ยังไม่รองรับ"
        />
        <div className="mt-4 grid grid-cols-1 gap-3 md:grid-cols-3">
          <div className="rounded-xl bg-[var(--bg-surface-secondary)] px-4 py-3">
            <p className="text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">
              ค่าเริ่มต้นระบบ
            </p>
            <p className="mt-1 text-lg font-bold text-[var(--text-primary)]">
              {formatCrawlInterval(rules.default_crawl_interval_hours)}
            </p>
          </div>
          <div className="rounded-xl bg-[var(--bg-surface-secondary)] px-4 py-3">
            <p className="text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">
              ค่า override ของ tenant
            </p>
            <p className="mt-1 text-lg font-bold text-[var(--text-primary)]">{overrideLabel}</p>
          </div>
          <div className="rounded-xl bg-[var(--bg-surface-secondary)] px-4 py-3">
            <p className="text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">
              ค่าที่ใช้งานจริง
            </p>
            <p className="mt-1 text-lg font-bold text-[var(--text-primary)]">
              {formatCrawlInterval(rules.effective_crawl_interval_hours)}
            </p>
          </div>
        </div>
        <p className="mt-4 text-sm text-[var(--text-muted)]">
          แหล่งอ้างอิง policy:{" "}
          <span className="font-mono text-[var(--text-secondary)]">{rules.source}</span>
        </p>
      </div>
    </div>
  );
}

export default function RulesPage() {
  const queryClient = useQueryClient();
  const [activeTab, setActiveTab] = useState<(typeof TABS)[number]["key"]>("profiles");
  const { data, isLoading, isError, error } = useRules();
  const [profileName, setProfileName] = useState("Keyword Watchlist");
  const [keywordDraft, setKeywordDraft] = useState("");
  const [profileBusy, setProfileBusy] = useState(false);
  const [profileError, setProfileError] = useState<string | null>(null);
  const [profileNotice, setProfileNotice] = useState<string | null>(null);
  const [scheduleChoice, setScheduleChoice] = useState<string>("default");
  const [scheduleBusy, setScheduleBusy] = useState(false);
  const [scheduleError, setScheduleError] = useState<string | null>(null);
  const [scheduleNotice, setScheduleNotice] = useState<string | null>(null);

  useEffect(() => {
    if (!data) return;
    setScheduleChoice(
      data.schedule_rules.tenant_crawl_interval_hours === null
        ? "default"
        : String(data.schedule_rules.tenant_crawl_interval_hours),
    );
  }, [data]);

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
        name: profileName.trim() || "Keyword Watchlist",
        profile_type: "custom",
        is_active: true,
        keywords,
      });
      setKeywordDraft("");
      setProfileNotice(`บันทึกโปรไฟล์พร้อม ${keywords.length} คำค้นแล้ว`);
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
      setScheduleNotice("บันทึก cadence สำหรับการ crawl แล้ว");
      await refreshRules();
    } catch (mutationError) {
      setScheduleError(
        mutationError instanceof Error
          ? mutationError.message
          : "ไม่สามารถบันทึกความถี่การ crawl ได้",
      );
    } finally {
      setScheduleBusy(false);
    }
  }

  function renderTabContent() {
    if (!data) return null;

    if (activeTab === "profiles") {
      return (
        <>
          <KeywordProfileComposer
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
              <p className="text-lg font-semibold text-[var(--text-primary)]">
                ยังไม่มีโปรไฟล์คำค้นสำหรับ tenant นี้
              </p>
              <p className="mt-2 text-sm text-[var(--text-muted)]">
                ใช้ฟอร์มด้านบนเพื่อสร้างโปรไฟล์ `custom` และเริ่มเพิ่มคำค้นตาม quota ของแพ็กเกจปัจจุบัน
              </p>
            </div>
          ) : (
            <div className="grid grid-cols-1 gap-6 xl:grid-cols-2">
              {data.profiles.map((profile) => (
                <ProfileCard key={profile.id} profile={profile} />
              ))}
            </div>
          )}
        </>
      );
    }

    if (activeTab === "closure") {
      return <ClosureTab rules={data.closure_rules} />;
    }

    if (activeTab === "notifications") {
      return <NotificationsTab rules={data.notification_rules} />;
    }

    return (
      <div className="space-y-6">
        <div className="rounded-2xl bg-[var(--bg-surface)] p-6 shadow-[var(--shadow-soft)]">
          <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
            <div>
              <h3 className="text-lg font-bold text-[var(--text-primary)]">
                ตั้งค่าความถี่การ crawl
              </h3>
              <p className="mt-2 max-w-2xl text-sm text-[var(--text-muted)]">
                ตอนนี้เราบันทึก cadence ต่อ tenant ได้แล้ว ค่าแนะนำเริ่มต้นคือวันละครั้ง เพราะ e-GP มักไม่ได้เปลี่ยนถี่ระดับนาที และช่วยคุมต้นทุนการ crawl ได้ดี
              </p>
            </div>
            <div className="rounded-2xl bg-[var(--bg-surface-secondary)] px-4 py-3 text-sm text-[var(--text-secondary)]">
              ใช้งานจริง: {formatCrawlInterval(data.schedule_rules.effective_crawl_interval_hours)}
            </div>
          </div>

          <form className="mt-5 flex flex-col gap-3 md:flex-row md:items-end" onSubmit={handleSaveSchedule}>
            <label className="flex min-w-[280px] flex-col gap-2 text-sm text-[var(--text-secondary)]">
              Crawl cadence
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
              {scheduleBusy ? "กำลังบันทึก..." : "บันทึก cadence"}
            </button>
          </form>

          {scheduleError ? (
            <p className="mt-3 text-sm font-medium text-[var(--badge-red-text)]">{scheduleError}</p>
          ) : null}
          {scheduleNotice ? (
            <p className="mt-3 text-sm font-medium text-primary">{scheduleNotice}</p>
          ) : null}
        </div>

        <ScheduleTab rules={data.schedule_rules} />
      </div>
    );
  }

  return (
    <>
      <PageHeader
        title="กฎและโปรไฟล์"
        subtitle="แสดงคำค้น กฎการปิด และการตั้งค่าระบบจาก logic ที่แพลตฟอร์มใช้อยู่จริง"
      />

      {data ? <EntitlementCard entitlements={data.entitlements} /> : null}

      <div className="mb-6 flex gap-1 rounded-xl bg-[var(--bg-surface-secondary)] p-1">
        {TABS.map((tab) => (
          <button
            key={tab.key}
            type="button"
            onClick={() => setActiveTab(tab.key)}
            className={`rounded-lg px-4 py-2 text-sm font-medium transition-colors ${
              activeTab === tab.key
                ? "bg-[var(--bg-surface)] text-primary shadow-sm"
                : "text-[var(--text-muted)] hover:text-[var(--text-secondary)]"
            }`}
          >
            {tab.label}
          </button>
        ))}
      </div>

      <QueryState isLoading={isLoading} isError={isError} error={error}>
        {renderTabContent()}
      </QueryState>
    </>
  );
}
