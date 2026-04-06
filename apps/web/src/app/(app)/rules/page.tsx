"use client";

import { useState } from "react";
import { Clock3, Mail, Search, ShieldCheck } from "lucide-react";
import { PageHeader } from "@/components/layout/page-header";
import { QueryState } from "@/components/ui/query-state";
import { useRules } from "@/lib/hooks";
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
          {entitlements.plan_code === "free_trial" ? (
            <p className="mt-2 max-w-2xl text-sm font-medium text-primary">
              Free Trial อนุญาตให้ทดลองรันงานจริง 1 คำค้น แต่จะยังไม่เปิด export, ดาวน์โหลดเอกสาร, และการแจ้งเตือน
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
          การตั้งเวลาในระบบ backend รองรับอยู่ แต่หน้านี้ยังเป็น surface สำหรับอ่านและตรวจสอบ configuration เท่านั้น
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
        <p className="mt-4 text-sm text-[var(--text-muted)]">
          แหล่งอ้างอิง schema และ trigger type:{" "}
          <span className="font-mono text-[var(--text-secondary)]">{rules.source}</span>
        </p>
      </div>
    </div>
  );
}

export default function RulesPage() {
  const [activeTab, setActiveTab] = useState<(typeof TABS)[number]["key"]>("profiles");
  const { data, isLoading, isError, error } = useRules();

  function renderTabContent() {
    if (!data) return null;

    if (activeTab === "profiles") {
      if (data.profiles.length === 0) {
        return (
          <div className="rounded-2xl bg-[var(--bg-surface)] p-10 text-center shadow-[var(--shadow-soft)]">
            <p className="text-lg font-semibold text-[var(--text-primary)]">
              ยังไม่มีโปรไฟล์คำค้นสำหรับ tenant นี้
            </p>
            <p className="mt-2 text-sm text-[var(--text-muted)]">
              API พร้อมแล้วและจะแสดงข้อมูลทันทีเมื่อมีการบันทึก `crawl_profiles` และ `crawl_profile_keywords`
            </p>
          </div>
        );
      }

      return (
        <div className="grid grid-cols-1 gap-6 xl:grid-cols-2">
          {data.profiles.map((profile) => (
            <ProfileCard key={profile.id} profile={profile} />
          ))}
        </div>
      );
    }

    if (activeTab === "closure") {
      return <ClosureTab rules={data.closure_rules} />;
    }

    if (activeTab === "notifications") {
      return <NotificationsTab rules={data.notification_rules} />;
    }

    return <ScheduleTab rules={data.schedule_rules} />;
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
