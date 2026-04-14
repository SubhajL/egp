"use client";

import Link from "next/link";
import { FormEvent, useEffect, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { Building2, CreditCard, LifeBuoy, Mail, ScrollText, Search, Users, Webhook } from "lucide-react";

import { PageHeader } from "@/components/layout/page-header";
import { QueryState } from "@/components/ui/query-state";
import { StatusBadge } from "@/components/ui/status-badge";
import {
  createAdminUser,
  createWebhook,
  deleteWebhook,
  inviteAdminUser,
  localizeApiError,
  updateAdminUser,
  updateAdminUserNotificationPreferences,
  updateTenantSettings,
  type AdminUser,
  type AuditLogEvent,
  type SupportTenant,
  type WebhookSubscription,
} from "@/lib/api";
import { useAdminSnapshot, useAuditLog, useSupportSummary, useSupportTenants, useWebhooks } from "@/lib/hooks";
import { formatBudget, formatThaiDate } from "@/lib/utils";

const TABS = [
  { key: "support", label: "Support", icon: LifeBuoy },
  { key: "users", label: "ผู้ใช้และบทบาท", icon: Users },
  { key: "notifications", label: "การแจ้งเตือน", icon: Mail },
  { key: "audit", label: "Audit Log", icon: ScrollText },
  { key: "webhooks", label: "Webhook", icon: Webhook },
  { key: "billing", label: "แผนและบิล", icon: CreditCard },
  { key: "settings", label: "ตั้งค่าองค์กร", icon: Building2 },
] as const;

const NOTIFICATION_TYPES = [
  { key: "new_project", label: "โครงการใหม่" },
  { key: "winner_announced", label: "ประกาศผู้ชนะ" },
  { key: "contract_signed", label: "ลงนามสัญญา" },
  { key: "tor_changed", label: "TOR เปลี่ยนแปลง" },
  { key: "run_failed", label: "รันล้มเหลว" },
  { key: "export_ready", label: "ไฟล์ส่งออกพร้อมใช้งาน" },
] as const;

function SummaryCard({
  label,
  value,
  hint,
}: {
  label: string;
  value: string | number;
  hint: string;
}) {
  return (
    <div className="rounded-2xl bg-[var(--bg-surface)] p-5 shadow-[var(--shadow-soft)]">
      <p className="text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">
        {label}
      </p>
      <p className="mt-2 text-3xl font-bold text-[var(--text-primary)]">{value}</p>
      <p className="mt-1 text-sm text-[var(--text-muted)]">{hint}</p>
    </div>
  );
}

function UserRow({
  user,
  onSave,
  onInvite,
  busy,
}: {
  user: AdminUser;
  onSave: (userId: string, role: string, status: string, fullName: string) => Promise<void>;
  onInvite: (userId: string) => Promise<void>;
  busy: boolean;
}) {
  const [role, setRole] = useState(user.role);
  const [status, setStatus] = useState(user.status);
  const [fullName, setFullName] = useState(user.full_name ?? "");

  return (
    <div className="grid gap-3 rounded-2xl border border-[var(--border-default)] bg-[var(--bg-surface)] p-4 lg:grid-cols-[1.5fr_1fr_1fr_auto]">
      <div>
        <p className="font-semibold text-[var(--text-primary)]">{user.email}</p>
        <p className="text-sm text-[var(--text-muted)]">สร้างเมื่อ {formatThaiDate(user.created_at)}</p>
        <div className="mt-2 flex flex-wrap gap-2 text-xs">
          <span className="rounded-full bg-[var(--badge-gray-bg)] px-3 py-1 font-semibold text-[var(--badge-gray-text)]">
            {user.email_verified_at ? "ยืนยันอีเมลแล้ว" : "ยังไม่ยืนยันอีเมล"}
          </span>
          <span className="rounded-full bg-[var(--badge-blue-bg)] px-3 py-1 font-semibold text-[var(--badge-blue-text)]">
            {user.mfa_enabled ? "MFA เปิดใช้" : "MFA ยังไม่เปิดใช้"}
          </span>
        </div>
      </div>
      <input
        value={fullName}
        onChange={(event) => setFullName(event.target.value)}
        className="rounded-xl border border-[var(--border-default)] bg-transparent px-3 py-2 text-sm outline-none"
      />
      <div className="grid grid-cols-2 gap-2">
        <select
          value={role}
          onChange={(event) => setRole(event.target.value)}
          className="rounded-xl border border-[var(--border-default)] bg-transparent px-3 py-2 text-sm outline-none"
        >
          <option value="owner">owner</option>
          <option value="admin">admin</option>
          <option value="analyst">analyst</option>
          <option value="viewer">viewer</option>
        </select>
        <select
          value={status}
          onChange={(event) => setStatus(event.target.value)}
          className="rounded-xl border border-[var(--border-default)] bg-transparent px-3 py-2 text-sm outline-none"
        >
          <option value="active">active</option>
          <option value="suspended">suspended</option>
          <option value="deactivated">deactivated</option>
        </select>
      </div>
      <div className="flex flex-wrap items-center justify-end gap-2">
        <button
          type="button"
          disabled={busy}
          onClick={() => onInvite(user.id)}
          className="rounded-xl border border-[var(--border-default)] px-4 py-2 text-sm font-semibold text-[var(--text-secondary)] disabled:opacity-60"
        >
          ส่ง Invite
        </button>
        <button
          type="button"
          disabled={busy}
          onClick={() => onSave(user.id, role, status, fullName)}
          className="rounded-xl bg-primary px-4 py-2 text-sm font-semibold text-white disabled:opacity-60"
        >
          บันทึก
        </button>
      </div>
    </div>
  );
}

function WebhookRow({
  webhook,
  onDelete,
  busy,
}: {
  webhook: WebhookSubscription;
  onDelete: (webhookId: string) => Promise<void>;
  busy: boolean;
}) {
  return (
    <div className="grid gap-3 rounded-2xl border border-[var(--border-default)] bg-[var(--bg-surface)] p-4 lg:grid-cols-[1.3fr_1fr_auto]">
      <div>
        <p className="font-semibold text-[var(--text-primary)]">{webhook.name}</p>
        <p className="text-sm text-[var(--text-muted)]">{webhook.url}</p>
        <div className="mt-3 flex flex-wrap gap-2">
          {webhook.notification_types.map((type) => (
            <span
              key={type}
              className="rounded-full bg-[var(--badge-blue-bg)] px-3 py-1 text-xs font-semibold text-[var(--badge-blue-text)]"
            >
              {type}
            </span>
          ))}
        </div>
      </div>
      <div className="space-y-2 text-sm text-[var(--text-secondary)]">
        <p>
          สถานะล่าสุด:{" "}
          <span className="font-semibold text-[var(--text-primary)]">
            {webhook.last_delivery_status ?? "ยังไม่เคยส่ง"}
          </span>
        </p>
        <p>
          ส่งล่าสุด:{" "}
          {webhook.last_delivery_attempted_at
            ? formatThaiDate(webhook.last_delivery_attempted_at)
            : "-"}
        </p>
        <p>HTTP ล่าสุด: {webhook.last_response_status_code ?? "-"}</p>
      </div>
      <div className="flex items-start justify-end">
        <button
          type="button"
          disabled={busy}
          onClick={() => onDelete(webhook.id)}
          className="rounded-xl border border-[var(--badge-red-bg)] px-4 py-2 text-sm font-semibold text-[var(--badge-red-text)] disabled:opacity-60"
        >
          ลบ
        </button>
      </div>
    </div>
  );
}

function AuditLogRow({ event }: { event: AuditLogEvent }) {
  return (
    <div className="rounded-2xl border border-[var(--border-default)] bg-[var(--bg-surface)] p-4 shadow-[var(--shadow-soft)]">
      <div className="flex flex-wrap items-center gap-2">
        <span className="rounded-full bg-[var(--badge-blue-bg)] px-3 py-1 text-xs font-semibold text-[var(--badge-blue-text)]">
          {event.source}
        </span>
        <span className="rounded-full bg-[var(--badge-gray-bg)] px-3 py-1 text-xs font-semibold text-[var(--badge-gray-text)]">
          {event.entity_type}
        </span>
        <span className="text-xs text-[var(--text-muted)]">{event.event_type}</span>
      </div>
      <p className="mt-3 text-sm font-semibold text-[var(--text-primary)]">{event.summary}</p>
      <div className="mt-2 grid gap-1 text-xs text-[var(--text-muted)] md:grid-cols-3">
        <p>ผู้กระทำ: {event.actor_subject ?? "system"}</p>
        <p>เวลา: {formatThaiDate(event.occurred_at)}</p>
        <p>อ้างอิง: {event.entity_id}</p>
      </div>
    </div>
  );
}

export default function AdminPage() {
  const queryClient = useQueryClient();
  const [selectedTenantId, setSelectedTenantId] = useState<string | undefined>(undefined);
  const [supportQuery, setSupportQuery] = useState("");
  const [submittedSupportQuery, setSubmittedSupportQuery] = useState("");
  const activeTenantId = selectedTenantId;
  const { data, isLoading, isError, error } = useAdminSnapshot({ tenant_id: activeTenantId });
  const {
    data: webhookData,
    isLoading: webhooksLoading,
    isError: webhooksError,
    error: webhookError,
  } = useWebhooks({ tenant_id: activeTenantId });
  const [auditSource, setAuditSource] = useState("all");
  const [auditEntityType, setAuditEntityType] = useState("all");
  const {
    data: auditData,
    isLoading: auditLoading,
    isError: auditError,
    error: auditQueryError,
  } = useAuditLog({
    tenant_id: activeTenantId,
    source: auditSource !== "all" ? auditSource : undefined,
    entity_type: auditEntityType !== "all" ? auditEntityType : undefined,
    limit: 50,
    offset: 0,
  });
  const {
    data: supportTenantData,
    isLoading: supportSearchLoading,
    isError: supportSearchError,
    error: supportSearchQueryError,
  } = useSupportTenants({
    query: submittedSupportQuery,
    limit: 8,
  });
  const {
    data: supportSummaryData,
    isLoading: supportSummaryLoading,
    isError: supportSummaryError,
    error: supportSummaryQueryError,
  } = useSupportSummary(activeTenantId ? { tenant_id: activeTenantId } : null);
  const [activeTab, setActiveTab] = useState<(typeof TABS)[number]["key"]>("users");
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [submitNotice, setSubmitNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [newEmail, setNewEmail] = useState("");
  const [newFullName, setNewFullName] = useState("");
  const [newRole, setNewRole] = useState("viewer");
  const [supportEmail, setSupportEmail] = useState("");
  const [billingEmail, setBillingEmail] = useState("");
  const [timezone, setTimezone] = useState("Asia/Bangkok");
  const [locale, setLocale] = useState("th-TH");
  const [dailyDigestEnabled, setDailyDigestEnabled] = useState(true);
  const [weeklyDigestEnabled, setWeeklyDigestEnabled] = useState(false);
  const [webhookName, setWebhookName] = useState("");
  const [webhookUrl, setWebhookUrl] = useState("");
  const [webhookSecret, setWebhookSecret] = useState("");
  const [selectedWebhookTypes, setSelectedWebhookTypes] = useState<string[]>([
    "new_project",
  ]);

  const users = data?.users ?? [];
  const billingRecords = data?.billing.records ?? [];
  const webhooks = webhookData?.webhooks ?? [];
  const auditItems = auditData?.items ?? [];
  const supportResults = supportTenantData?.tenants ?? [];
  const currentSubscription = data?.billing.current_subscription ?? null;
  const upcomingSubscription = data?.billing.upcoming_subscription ?? null;
  const summary = data?.billing.summary ?? {
    open_records: 0,
    awaiting_reconciliation: 0,
    outstanding_amount: "0.00",
    collected_amount: "0.00",
  };

  useEffect(() => {
    if (!data) return;
    setSupportEmail(data.settings.support_email ?? "");
    setBillingEmail(data.settings.billing_contact_email ?? "");
    setTimezone(data.settings.timezone);
    setLocale(data.settings.locale);
    setDailyDigestEnabled(data.settings.daily_digest_enabled);
    setWeeklyDigestEnabled(data.settings.weekly_digest_enabled);
  }, [data]);

  async function refreshSnapshot() {
    await queryClient.invalidateQueries({ queryKey: ["admin-snapshot"] });
    await queryClient.invalidateQueries({ queryKey: ["audit-log"] });
  }

  async function refreshWebhooks() {
    await queryClient.invalidateQueries({ queryKey: ["webhooks"] });
    await queryClient.invalidateQueries({ queryKey: ["audit-log"] });
  }

  async function handleCreateUser(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSubmitError(null);
    setSubmitNotice(null);
    setBusy(true);
    try {
      await createAdminUser({
        tenant_id: activeTenantId,
        email: newEmail.trim(),
        full_name: newFullName.trim() || undefined,
        role: newRole,
      });
      setNewEmail("");
      setNewFullName("");
      setNewRole("viewer");
      await refreshSnapshot();
    } catch (mutationError) {
      setSubmitError(
        localizeApiError(mutationError, "ไม่สามารถสร้างผู้ใช้ได้"),
      );
    } finally {
      setBusy(false);
    }
  }

  async function handleSaveUser(userId: string, role: string, status: string, fullName: string) {
    setSubmitError(null);
    setSubmitNotice(null);
    setBusy(true);
    try {
      await updateAdminUser(userId, {
        tenant_id: activeTenantId,
        role,
        status,
        full_name: fullName.trim() || undefined,
      });
      await refreshSnapshot();
    } catch (mutationError) {
      setSubmitError(
        localizeApiError(mutationError, "ไม่สามารถอัปเดตผู้ใช้ได้"),
      );
    } finally {
      setBusy(false);
    }
  }

  async function handleInviteUser(userId: string) {
    setSubmitError(null);
    setSubmitNotice(null);
    setBusy(true);
    try {
      const invited = await inviteAdminUser(userId, activeTenantId);
      setSubmitNotice(`ส่งคำเชิญไปยัง ${invited.delivery_email} แล้ว`);
    } catch (mutationError) {
      setSubmitError(
        localizeApiError(mutationError, "ไม่สามารถส่งคำเชิญได้"),
      );
    } finally {
      setBusy(false);
    }
  }

  async function handleTogglePreference(user: AdminUser, notificationType: string) {
    setSubmitError(null);
    setSubmitNotice(null);
    setBusy(true);
    try {
      await updateAdminUserNotificationPreferences(user.id, {
        tenant_id: activeTenantId,
        email_preferences: {
          [notificationType]: !user.notification_preferences[notificationType],
        },
      });
      await refreshSnapshot();
    } catch (mutationError) {
      setSubmitError(
        localizeApiError(mutationError, "ไม่สามารถอัปเดตการแจ้งเตือนได้"),
      );
    } finally {
      setBusy(false);
    }
  }

  async function handleSaveSettings(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSubmitError(null);
    setSubmitNotice(null);
    setBusy(true);
    try {
      await updateTenantSettings({
        tenant_id: activeTenantId,
        support_email: supportEmail.trim() || undefined,
        billing_contact_email: billingEmail.trim() || undefined,
        timezone,
        locale,
        daily_digest_enabled: dailyDigestEnabled,
        weekly_digest_enabled: weeklyDigestEnabled,
      });
      await refreshSnapshot();
    } catch (mutationError) {
      setSubmitError(
        localizeApiError(mutationError, "ไม่สามารถบันทึกการตั้งค่าได้"),
      );
    } finally {
      setBusy(false);
    }
  }

  function toggleWebhookType(notificationType: string) {
    setSelectedWebhookTypes((current) =>
      current.includes(notificationType)
        ? current.filter((item) => item !== notificationType)
        : [...current, notificationType],
    );
  }

  async function handleCreateWebhook(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSubmitError(null);
    setSubmitNotice(null);
    setBusy(true);
    try {
      await createWebhook({
        tenant_id: activeTenantId,
        name: webhookName.trim(),
        url: webhookUrl.trim(),
        notification_types: selectedWebhookTypes,
        signing_secret: webhookSecret,
      });
      setWebhookName("");
      setWebhookUrl("");
      setWebhookSecret("");
      setSelectedWebhookTypes(["new_project"]);
      await refreshWebhooks();
    } catch (mutationError) {
      setSubmitError(
        localizeApiError(mutationError, "ไม่สามารถสร้าง webhook ได้"),
      );
    } finally {
      setBusy(false);
    }
  }

  async function handleDeleteWebhook(webhookId: string) {
    setSubmitError(null);
    setSubmitNotice(null);
    setBusy(true);
    try {
      await deleteWebhook(webhookId, activeTenantId);
      await refreshWebhooks();
    } catch (mutationError) {
      setSubmitError(
        localizeApiError(mutationError, "ไม่สามารถลบ webhook ได้"),
      );
    } finally {
      setBusy(false);
    }
  }

  function handleSearchSupport(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSubmittedSupportQuery(supportQuery.trim());
  }

  function handleSelectSupportTenant(tenant: SupportTenant) {
    setSelectedTenantId(tenant.id);
    setActiveTab("support");
  }

  function renderTabContent() {
    if (!data) return null;

    if (activeTab === "support") {
      return (
        <div className="space-y-6">
          <form
            onSubmit={handleSearchSupport}
            className="rounded-2xl bg-[var(--bg-surface)] p-5 shadow-[var(--shadow-soft)]"
          >
            <div className="flex flex-col gap-3 lg:flex-row">
              <div className="relative flex-1">
                <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-[var(--text-muted)]" />
                <input
                  value={supportQuery}
                  onChange={(event) => setSupportQuery(event.target.value)}
                  placeholder="ค้นหาจากชื่อ tenant, slug, support email หรือ user email"
                  className="w-full rounded-xl border border-[var(--border-default)] bg-transparent py-2 pl-9 pr-3 text-sm outline-none"
                />
              </div>
              <button
                type="submit"
                className="rounded-xl bg-primary px-4 py-2 text-sm font-semibold text-white"
              >
                ค้นหา Support
              </button>
              {activeTenantId ? (
                <button
                  type="button"
                  onClick={() => setSelectedTenantId(undefined)}
                  className="rounded-xl border border-[var(--border-default)] px-4 py-2 text-sm font-semibold text-[var(--text-secondary)]"
                >
                  กลับสู่ tenant ปัจจุบัน
                </button>
              ) : null}
            </div>
            <p className="mt-3 text-sm text-[var(--text-muted)]">
              เมื่อเลือก tenant แล้ว แท็บ Users, Notifications, Audit, Webhooks, Billing และ Settings จะทำงานกับ tenant นั้นทันที
            </p>
          </form>

          <QueryState
            isLoading={supportSearchLoading}
            isError={supportSearchError}
            error={supportSearchQueryError}
          >
            <div className="grid gap-3">
              {submittedSupportQuery && supportResults.length === 0 ? (
                <div className="rounded-2xl bg-[var(--bg-surface)] p-5 text-sm text-[var(--text-muted)] shadow-[var(--shadow-soft)]">
                  ไม่พบ tenant ที่ตรงกับคำค้นนี้
                </div>
              ) : null}
              {supportResults.map((tenant) => (
                <button
                  key={tenant.id}
                  type="button"
                  onClick={() => handleSelectSupportTenant(tenant)}
                  className={`grid gap-3 rounded-2xl border p-4 text-left shadow-[var(--shadow-soft)] ${
                    activeTenantId === tenant.id
                      ? "border-primary bg-[var(--bg-surface-secondary)]"
                      : "border-[var(--border-default)] bg-[var(--bg-surface)]"
                  }`}
                >
                  <div className="flex flex-col gap-2 lg:flex-row lg:items-center lg:justify-between">
                    <div>
                      <p className="font-semibold text-[var(--text-primary)]">{tenant.name}</p>
                      <p className="text-sm text-[var(--text-muted)]">
                        {tenant.slug} • {tenant.plan_code}
                      </p>
                    </div>
                    <div className="flex flex-wrap gap-2">
                      <StatusBadge state={tenant.is_active ? "active" : "deactivated"} />
                      <span className="rounded-full bg-[var(--badge-blue-bg)] px-3 py-1 text-xs font-semibold text-[var(--badge-blue-text)]">
                        {tenant.active_user_count} active users
                      </span>
                    </div>
                  </div>
                  <div className="grid gap-1 text-sm text-[var(--text-secondary)] md:grid-cols-2">
                    <p>Support: {tenant.support_email ?? "-"}</p>
                    <p>Billing: {tenant.billing_contact_email ?? "-"}</p>
                  </div>
                </button>
              ))}
            </div>
          </QueryState>

          {activeTenantId ? (
            <QueryState
              isLoading={supportSummaryLoading}
              isError={supportSummaryError}
              error={supportSummaryQueryError}
            >
              {supportSummaryData ? (
                <div className="space-y-6">
                  <div className="grid gap-4 md:grid-cols-4">
                    <SummaryCard
                      label="Failed Runs"
                      value={supportSummaryData.triage.failed_runs_recent}
                      hint="การรันที่ล้มเหลวในช่วงล่าสุด"
                    />
                    <SummaryCard
                      label="Pending Reviews"
                      value={supportSummaryData.triage.pending_document_reviews}
                      hint="Document reviews ที่ยังรอการตัดสินใจ"
                    />
                    <SummaryCard
                      label="Webhook Failures"
                      value={supportSummaryData.triage.failed_webhook_deliveries}
                      hint="ปลายทาง webhook ที่ต้องตามต่อ"
                    />
                    <SummaryCard
                      label="Open Billing Issues"
                      value={supportSummaryData.triage.outstanding_billing_records}
                      hint="บิลที่ยังไม่เข้าสถานะสิ้นสุด"
                    />
                  </div>

                  <div className="rounded-2xl bg-[var(--bg-surface)] p-5 shadow-[var(--shadow-soft)]">
                    <div className="flex flex-col gap-3 lg:flex-row lg:items-end lg:justify-between">
                      <div>
                        <p className="text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">
                          Cost Report
                        </p>
                        <h3 className="mt-2 text-2xl font-bold text-[var(--text-primary)]">
                          {supportSummaryData.tenant.name}
                        </h3>
                        <p className="mt-1 text-sm text-[var(--text-muted)]">
                          {supportSummaryData.tenant.slug} • {supportSummaryData.cost_summary.window_days} วันย้อนหลัง
                        </p>
                      </div>
                      <div className="rounded-2xl bg-[var(--bg-surface-secondary)] px-4 py-3">
                        <p className="text-xs uppercase tracking-wider text-[var(--text-muted)]">
                          Estimated Total
                        </p>
                        <p className="mt-1 text-2xl font-bold text-[var(--text-primary)]">
                          {formatBudget(supportSummaryData.cost_summary.estimated_total_thb)}
                        </p>
                      </div>
                    </div>
                    <div className="mt-4 grid gap-4 md:grid-cols-4">
                      <SummaryCard
                        label="Crawl"
                        value={formatBudget(supportSummaryData.cost_summary.crawl.estimated_cost_thb)}
                        hint={`${supportSummaryData.cost_summary.crawl.run_count} runs / ${supportSummaryData.cost_summary.crawl.task_count} tasks`}
                      />
                      <SummaryCard
                        label="Storage"
                        value={formatBudget(supportSummaryData.cost_summary.storage.estimated_cost_thb)}
                        hint={`${supportSummaryData.cost_summary.storage.document_count} docs / ${supportSummaryData.cost_summary.storage.total_bytes.toLocaleString()} bytes`}
                      />
                      <SummaryCard
                        label="Notifications"
                        value={formatBudget(supportSummaryData.cost_summary.notifications.estimated_cost_thb)}
                        hint={`${supportSummaryData.cost_summary.notifications.sent_count} sent / ${supportSummaryData.cost_summary.notifications.failed_webhook_delivery_count} failed`}
                      />
                      <SummaryCard
                        label="Payments"
                        value={formatBudget(supportSummaryData.cost_summary.payments.estimated_cost_thb)}
                        hint={`${supportSummaryData.cost_summary.payments.billing_record_count} bills / ${supportSummaryData.cost_summary.payments.payment_request_count} requests`}
                      />
                    </div>
                  </div>

                  <div className="grid gap-6 lg:grid-cols-2">
                    <div className="rounded-2xl bg-[var(--bg-surface)] p-5 shadow-[var(--shadow-soft)]">
                      <h3 className="text-sm font-semibold text-[var(--text-primary)]">Failed Runs</h3>
                      <div className="mt-3 space-y-3">
                        {supportSummaryData.recent_failed_runs.length > 0 ? supportSummaryData.recent_failed_runs.map((run) => (
                          <div key={run.id} className="rounded-2xl border border-[var(--border-default)] p-4">
                            <div className="flex items-center justify-between gap-3">
                              <p className="font-mono text-xs text-[var(--text-primary)]">{run.id.slice(0, 12)}</p>
                              <StatusBadge state={run.status} variant="run" />
                            </div>
                            <p className="mt-2 text-sm text-[var(--text-secondary)]">
                              {run.trigger_type} • errors {run.error_count}
                            </p>
                          </div>
                        )) : (
                          <p className="text-sm text-[var(--text-muted)]">ไม่มี failed runs ในช่วงนี้</p>
                        )}
                      </div>
                    </div>

                    <div className="rounded-2xl bg-[var(--bg-surface)] p-5 shadow-[var(--shadow-soft)]">
                      <h3 className="text-sm font-semibold text-[var(--text-primary)]">Pending Reviews</h3>
                      <div className="mt-3 space-y-3">
                        {supportSummaryData.pending_reviews.length > 0 ? supportSummaryData.pending_reviews.map((review) => (
                          <div key={review.id} className="rounded-2xl border border-[var(--border-default)] p-4">
                            <div className="flex items-center justify-between gap-3">
                              <p className="font-mono text-xs text-[var(--text-primary)]">{review.id.slice(0, 12)}</p>
                              <StatusBadge state={review.status} />
                            </div>
                            <p className="mt-2 text-sm text-[var(--text-secondary)]">
                              project {review.project_id.slice(0, 12)}
                            </p>
                          </div>
                        )) : (
                          <p className="text-sm text-[var(--text-muted)]">ไม่มี review ที่ค้างอยู่</p>
                        )}
                      </div>
                    </div>

                    <div className="rounded-2xl bg-[var(--bg-surface)] p-5 shadow-[var(--shadow-soft)]">
                      <h3 className="text-sm font-semibold text-[var(--text-primary)]">Failed Webhooks</h3>
                      <div className="mt-3 space-y-3">
                        {supportSummaryData.failed_webhooks.length > 0 ? supportSummaryData.failed_webhooks.map((webhook) => (
                          <div key={webhook.id} className="rounded-2xl border border-[var(--border-default)] p-4">
                            <div className="flex items-center justify-between gap-3">
                              <p className="font-mono text-xs text-[var(--text-primary)]">{webhook.id.slice(0, 12)}</p>
                              <StatusBadge state={webhook.delivery_status} />
                            </div>
                            <p className="mt-2 text-sm text-[var(--text-secondary)]">
                              HTTP {webhook.last_response_status_code ?? "-"}
                            </p>
                          </div>
                        )) : (
                          <p className="text-sm text-[var(--text-muted)]">ไม่มี webhook failures ในช่วงนี้</p>
                        )}
                      </div>
                    </div>

                    <div className="rounded-2xl bg-[var(--bg-surface)] p-5 shadow-[var(--shadow-soft)]">
                      <h3 className="text-sm font-semibold text-[var(--text-primary)]">Billing Issues</h3>
                      <div className="mt-3 space-y-3">
                        {supportSummaryData.billing_issues.length > 0 ? supportSummaryData.billing_issues.map((issue) => (
                          <div key={issue.id} className="rounded-2xl border border-[var(--border-default)] p-4">
                            <div className="flex items-center justify-between gap-3">
                              <p className="font-semibold text-[var(--text-primary)]">{issue.record_number}</p>
                              <StatusBadge state={issue.status} variant="billing" />
                            </div>
                            <p className="mt-2 text-sm text-[var(--text-secondary)]">
                              {formatBudget(issue.amount_due)}
                            </p>
                          </div>
                        )) : (
                          <p className="text-sm text-[var(--text-muted)]">ไม่มี billing issue ที่ต้องติดตาม</p>
                        )}
                      </div>
                    </div>
                  </div>
                </div>
              ) : null}
            </QueryState>
          ) : (
            <div className="rounded-2xl bg-[var(--bg-surface)] p-6 text-sm text-[var(--text-muted)] shadow-[var(--shadow-soft)]">
              เริ่มจากการค้นหา tenant เพื่อเปิด support summary และสลับบริบทของแท็บอื่นให้ทำงานกับ tenant ที่เลือก
            </div>
          )}
        </div>
      );
    }

    if (activeTab === "users") {
      return (
        <div className="space-y-6">
          <form
            onSubmit={handleCreateUser}
            className="grid gap-3 rounded-2xl bg-[var(--bg-surface)] p-5 shadow-[var(--shadow-soft)] lg:grid-cols-[1.4fr_1fr_1fr_auto]"
          >
            <input
              required
              value={newEmail}
              onChange={(event) => setNewEmail(event.target.value)}
              placeholder="อีเมลผู้ใช้"
              className="rounded-xl border border-[var(--border-default)] bg-transparent px-3 py-2 text-sm outline-none"
            />
            <input
              value={newFullName}
              onChange={(event) => setNewFullName(event.target.value)}
              placeholder="ชื่อที่แสดง"
              className="rounded-xl border border-[var(--border-default)] bg-transparent px-3 py-2 text-sm outline-none"
            />
            <select
              value={newRole}
              onChange={(event) => setNewRole(event.target.value)}
              className="rounded-xl border border-[var(--border-default)] bg-transparent px-3 py-2 text-sm outline-none"
            >
              <option value="viewer">viewer</option>
              <option value="analyst">analyst</option>
              <option value="admin">admin</option>
              <option value="owner">owner</option>
            </select>
            <button
              type="submit"
              disabled={busy}
              className="rounded-xl bg-primary px-4 py-2 text-sm font-semibold text-white disabled:opacity-60"
            >
              เพิ่มผู้ใช้
            </button>
          </form>

          <div className="space-y-3">
            {users.map((user) => (
              <UserRow
                key={user.id}
                user={user}
                onSave={handleSaveUser}
                onInvite={handleInviteUser}
                busy={busy}
              />
            ))}
          </div>
        </div>
      );
    }

    if (activeTab === "notifications") {
      return (
        <div className="overflow-hidden rounded-2xl bg-[var(--bg-surface)] shadow-[var(--shadow-soft)]">
          <div className="overflow-x-auto">
            <table className="min-w-full divide-y divide-[var(--border-default)] text-sm">
              <thead className="bg-[var(--bg-surface-secondary)]">
                <tr>
                  <th className="px-4 py-3 text-left">ผู้ใช้</th>
                  {NOTIFICATION_TYPES.map((item) => (
                    <th key={item.key} className="px-4 py-3 text-left">
                      {item.label}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-[var(--border-default)]">
                {users.map((user) => (
                  <tr key={user.id}>
                    <td className="px-4 py-3">
                      <p className="font-medium text-[var(--text-primary)]">{user.email}</p>
                      <p className="text-xs text-[var(--text-muted)]">{user.role}</p>
                    </td>
                    {NOTIFICATION_TYPES.map((item) => {
                      const enabled = user.notification_preferences[item.key];
                      return (
                        <td key={item.key} className="px-4 py-3">
                          <button
                            type="button"
                            onClick={() => handleTogglePreference(user, item.key)}
                            className={`rounded-full px-3 py-1 text-xs font-semibold ${
                              enabled
                                ? "bg-[var(--badge-green-bg)] text-[var(--badge-green-text)]"
                                : "bg-[var(--badge-gray-bg)] text-[var(--badge-gray-text)]"
                            }`}
                          >
                            {enabled ? "เปิด" : "ปิด"}
                          </button>
                        </td>
                      );
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      );
    }

    if (activeTab === "webhooks") {
      return (
        <div className="space-y-6">
          <form
            onSubmit={handleCreateWebhook}
            className="grid gap-4 rounded-2xl bg-[var(--bg-surface)] p-5 shadow-[var(--shadow-soft)]"
          >
            <div className="grid gap-3 lg:grid-cols-2">
              <input
                required
                value={webhookName}
                onChange={(event) => setWebhookName(event.target.value)}
                placeholder="ชื่อ endpoint"
                className="rounded-xl border border-[var(--border-default)] bg-transparent px-3 py-2 text-sm outline-none"
              />
              <input
                required
                type="url"
                value={webhookUrl}
                onChange={(event) => setWebhookUrl(event.target.value)}
                placeholder="https://hooks.example.com/egp"
                className="rounded-xl border border-[var(--border-default)] bg-transparent px-3 py-2 text-sm outline-none"
              />
            </div>
            <input
              required
              value={webhookSecret}
              onChange={(event) => setWebhookSecret(event.target.value)}
              placeholder="shared secret สำหรับลงลายเซ็น"
              className="rounded-xl border border-[var(--border-default)] bg-transparent px-3 py-2 text-sm outline-none"
            />
            <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
              {NOTIFICATION_TYPES.map((item) => {
                const checked = selectedWebhookTypes.includes(item.key);
                return (
                  <label
                    key={item.key}
                    className="flex items-center gap-3 rounded-xl border border-[var(--border-default)] p-3"
                  >
                    <input
                      type="checkbox"
                      checked={checked}
                      onChange={() => toggleWebhookType(item.key)}
                    />
                    <span className="text-sm text-[var(--text-secondary)]">{item.label}</span>
                  </label>
                );
              })}
            </div>
            <div className="flex justify-end">
              <button
                type="submit"
                disabled={busy || selectedWebhookTypes.length === 0}
                className="rounded-xl bg-primary px-4 py-2 text-sm font-semibold text-white disabled:opacity-60"
              >
                เพิ่ม webhook
              </button>
            </div>
          </form>

          <QueryState isLoading={webhooksLoading} isError={webhooksError} error={webhookError}>
            <div className="space-y-3">
              {webhooks.length > 0 ? (
                webhooks.map((webhook) => (
                  <WebhookRow
                    key={webhook.id}
                    webhook={webhook}
                    onDelete={handleDeleteWebhook}
                    busy={busy}
                  />
                ))
              ) : (
                <div className="rounded-2xl bg-[var(--bg-surface)] p-6 text-sm text-[var(--text-muted)] shadow-[var(--shadow-soft)]">
                  ยังไม่มี webhook endpoint สำหรับ tenant นี้
                </div>
              )}
            </div>
          </QueryState>
        </div>
      );
    }

    if (activeTab === "audit") {
      return (
        <div className="space-y-6">
          <div className="grid gap-3 rounded-2xl bg-[var(--bg-surface)] p-5 shadow-[var(--shadow-soft)] md:grid-cols-2">
            <label className="space-y-2">
              <span className="text-sm font-medium text-[var(--text-secondary)]">Source</span>
              <select
                value={auditSource}
                onChange={(event) => setAuditSource(event.target.value)}
                className="w-full rounded-xl border border-[var(--border-default)] bg-transparent px-3 py-2 text-sm outline-none"
              >
                <option value="all">ทั้งหมด</option>
                <option value="admin">admin</option>
                <option value="document">document</option>
                <option value="review">review</option>
                <option value="billing">billing</option>
                <option value="project">project</option>
              </select>
            </label>
            <label className="space-y-2">
              <span className="text-sm font-medium text-[var(--text-secondary)]">Entity</span>
              <select
                value={auditEntityType}
                onChange={(event) => setAuditEntityType(event.target.value)}
                className="w-full rounded-xl border border-[var(--border-default)] bg-transparent px-3 py-2 text-sm outline-none"
              >
                <option value="all">ทั้งหมด</option>
                <option value="user">user</option>
                <option value="tenant_settings">tenant_settings</option>
                <option value="webhook">webhook</option>
                <option value="document">document</option>
                <option value="document_review">document_review</option>
                <option value="billing_record">billing_record</option>
                <option value="project">project</option>
              </select>
            </label>
          </div>

          <QueryState isLoading={auditLoading} isError={auditError} error={auditQueryError}>
            <div className="space-y-3">
              {auditItems.length > 0 ? (
                auditItems.map((event) => <AuditLogRow key={event.id} event={event} />)
              ) : (
                <div className="rounded-2xl bg-[var(--bg-surface)] p-6 text-sm text-[var(--text-muted)] shadow-[var(--shadow-soft)]">
                  ยังไม่มีเหตุการณ์ใน audit log สำหรับตัวกรองนี้
                </div>
              )}
            </div>
          </QueryState>
        </div>
      );
    }

    if (activeTab === "billing") {
      return (
        <div className="space-y-6">
          <div className="grid gap-4 md:grid-cols-3">
            <SummaryCard
              label="บิลที่ยังเปิด"
              value={summary.open_records}
              hint="จำนวนใบแจ้งหนี้ที่ยังไม่ปิด"
            />
            <SummaryCard
              label="ยอดคงค้าง"
              value={formatBudget(summary.outstanding_amount)}
              hint="ยอดคงเหลือที่ยังต้องติดตาม"
            />
            <SummaryCard
              label="ยอดเก็บแล้ว"
              value={formatBudget(summary.collected_amount)}
              hint="ยอดชำระที่กระทบยอดแล้ว"
            />
          </div>

          <div className="rounded-2xl bg-[var(--bg-surface)] p-5 shadow-[var(--shadow-soft)]">
            <div className="flex items-center justify-between gap-4">
              <div>
                <p className="text-sm font-semibold text-[var(--text-primary)]">สิทธิ์ปัจจุบัน</p>
                {currentSubscription ? (
                  <p className="mt-1 text-sm text-[var(--text-muted)]">
                    {currentSubscription.plan_code} ถึง {formatThaiDate(currentSubscription.billing_period_end)}
                  </p>
                ) : (
                  <p className="mt-1 text-sm text-[var(--text-muted)]">ยังไม่มี subscription ที่เปิดอยู่</p>
                )}
              </div>
              {currentSubscription ? (
                <StatusBadge
                  state={currentSubscription.subscription_status}
                  variant="subscription"
                />
              ) : null}
            </div>
          </div>

          {upcomingSubscription ? (
            <div className="rounded-2xl border border-amber-200 bg-amber-50 p-5 shadow-[var(--shadow-soft)]">
              <div className="flex items-center justify-between gap-4">
                <div>
                  <p className="text-sm font-semibold text-amber-900">สิทธิ์ที่กำลังรอเริ่มใช้งาน</p>
                  <p className="mt-1 text-sm text-amber-800">
                    {upcomingSubscription.plan_code} เริ่ม {formatThaiDate(upcomingSubscription.billing_period_start)}
                  </p>
                  <p className="mt-1 text-sm text-amber-700">
                    ใช้งานจริงถึง {formatThaiDate(upcomingSubscription.billing_period_end)}
                  </p>
                </div>
                <StatusBadge
                  state={upcomingSubscription.subscription_status}
                  variant="subscription"
                />
              </div>
            </div>
          ) : null}

          <div className="overflow-hidden rounded-2xl bg-[var(--bg-surface)] shadow-[var(--shadow-soft)]">
            <table className="min-w-full divide-y divide-[var(--border-default)] text-sm">
              <thead className="bg-[var(--bg-surface-secondary)]">
                <tr>
                  <th className="px-4 py-3 text-left">เลขที่บิล</th>
                  <th className="px-4 py-3 text-left">แผน</th>
                  <th className="px-4 py-3 text-left">สถานะ</th>
                  <th className="px-4 py-3 text-left">Upgrade Chain</th>
                  <th className="px-4 py-3 text-left">จำนวนเงิน</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[var(--border-default)]">
                {billingRecords.map((record) => (
                  <tr key={record.id}>
                    <td className="px-4 py-3 font-medium text-[var(--text-primary)]">
                      {record.record_number}
                    </td>
                    <td className="px-4 py-3 text-[var(--text-secondary)]">{record.plan_code}</td>
                    <td className="px-4 py-3">
                      <StatusBadge state={record.status} variant="billing" />
                    </td>
                    <td className="px-4 py-3 text-[var(--text-secondary)]">
                      {record.upgrade_from_subscription_id ? (
                        <div className="space-y-1">
                          <p>{record.upgrade_mode}</p>
                          <p className="font-mono text-xs text-[var(--text-muted)]">
                            from {record.upgrade_from_subscription_id.slice(0, 8)}
                          </p>
                        </div>
                      ) : (
                        <span className="text-[var(--text-muted)]">-</span>
                      )}
                    </td>
                    <td className="px-4 py-3 text-[var(--text-secondary)]">
                      {formatBudget(record.amount_due)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      );
    }

    return (
      <form
        onSubmit={handleSaveSettings}
        className="grid gap-4 rounded-2xl bg-[var(--bg-surface)] p-6 shadow-[var(--shadow-soft)] lg:grid-cols-2"
      >
        <label className="space-y-2">
          <span className="text-sm font-medium text-[var(--text-secondary)]">ชื่อองค์กร</span>
          <input
            value={data.tenant.name}
            disabled
            className="w-full rounded-xl border border-[var(--border-default)] bg-[var(--bg-surface-secondary)] px-3 py-2 text-sm outline-none"
          />
        </label>
        <label className="space-y-2">
          <span className="text-sm font-medium text-[var(--text-secondary)]">slug</span>
          <input
            value={data.tenant.slug}
            disabled
            className="w-full rounded-xl border border-[var(--border-default)] bg-[var(--bg-surface-secondary)] px-3 py-2 text-sm outline-none"
          />
        </label>
        <label className="space-y-2">
          <span className="text-sm font-medium text-[var(--text-secondary)]">อีเมลซัพพอร์ต</span>
          <input
            value={supportEmail}
            onChange={(event) => setSupportEmail(event.target.value)}
            className="w-full rounded-xl border border-[var(--border-default)] bg-transparent px-3 py-2 text-sm outline-none"
          />
        </label>
        <label className="space-y-2">
          <span className="text-sm font-medium text-[var(--text-secondary)]">อีเมลฝ่ายบัญชี</span>
          <input
            value={billingEmail}
            onChange={(event) => setBillingEmail(event.target.value)}
            className="w-full rounded-xl border border-[var(--border-default)] bg-transparent px-3 py-2 text-sm outline-none"
          />
        </label>
        <label className="space-y-2">
          <span className="text-sm font-medium text-[var(--text-secondary)]">เขตเวลา</span>
          <input
            value={timezone}
            onChange={(event) => setTimezone(event.target.value)}
            className="w-full rounded-xl border border-[var(--border-default)] bg-transparent px-3 py-2 text-sm outline-none"
          />
        </label>
        <label className="space-y-2">
          <span className="text-sm font-medium text-[var(--text-secondary)]">Locale</span>
          <input
            value={locale}
            onChange={(event) => setLocale(event.target.value)}
            className="w-full rounded-xl border border-[var(--border-default)] bg-transparent px-3 py-2 text-sm outline-none"
          />
        </label>
        <label className="flex items-center gap-3 rounded-xl border border-[var(--border-default)] p-3">
          <input
            type="checkbox"
            checked={dailyDigestEnabled}
            onChange={(event) => setDailyDigestEnabled(event.target.checked)}
          />
          <span className="text-sm text-[var(--text-secondary)]">สรุปรายวันทางอีเมล</span>
        </label>
        <label className="flex items-center gap-3 rounded-xl border border-[var(--border-default)] p-3">
          <input
            type="checkbox"
            checked={weeklyDigestEnabled}
            onChange={(event) => setWeeklyDigestEnabled(event.target.checked)}
          />
          <span className="text-sm text-[var(--text-secondary)]">สรุปรายสัปดาห์ทางอีเมล</span>
        </label>
        <div className="lg:col-span-2">
          <button
            type="submit"
            disabled={busy}
            className="rounded-xl bg-primary px-4 py-2 text-sm font-semibold text-white disabled:opacity-60"
          >
            บันทึกการตั้งค่าองค์กร
          </button>
        </div>
      </form>
    );
  }

  return (
    <>
      <PageHeader
        title="แอดมินองค์กร"
        subtitle="จัดการผู้ใช้ การแจ้งเตือน สิทธิ์ใช้งาน การตั้งค่าองค์กร และ support context"
        actions={
          <Link
            href="/admin/storage"
            className="rounded-xl border border-[var(--border-default)] px-4 py-2 text-sm font-semibold text-[var(--text-secondary)] hover:bg-[var(--bg-surface-hover)]"
          >
            ตั้งค่าที่เก็บเอกสาร
          </Link>
        }
      />

      {submitError ? (
        <div className="mb-4 rounded-2xl border border-[var(--badge-red-bg)] bg-[var(--bg-surface)] p-4 text-sm text-[var(--badge-red-text)]">
          {submitError}
        </div>
      ) : null}

      {submitNotice ? (
        <div className="mb-4 rounded-2xl border border-emerald-200 bg-emerald-50 p-4 text-sm text-emerald-700">
          {submitNotice}
        </div>
      ) : null}

      <QueryState isLoading={isLoading} isError={isError} error={error}>
        {data ? (
          <>
            {activeTenantId ? (
              <div className="mb-4 rounded-2xl border border-[var(--badge-blue-bg)] bg-[var(--bg-surface)] p-4 text-sm text-[var(--text-secondary)]">
                กำลังทำงานใน support context ของ <span className="font-semibold text-[var(--text-primary)]">{data.tenant.name}</span> ({data.tenant.slug})
              </div>
            ) : null}

            <div className="mb-6 grid gap-4 md:grid-cols-3">
              <SummaryCard
                label="ผู้ใช้ในระบบ"
                value={users.length}
                hint="รวมสมาชิกที่ผูกกับ tenant นี้"
              />
              <SummaryCard
                label="แพ็กเกจปัจจุบัน"
                value={currentSubscription?.plan_code ?? data.tenant.plan_code}
                hint="แสดงแผนจาก billing หรือ tenant"
              />
              <SummaryCard
                label="สถานะองค์กร"
                value={data.tenant.is_active ? "Active" : "Inactive"}
                hint="สถานะ tenant ปัจจุบัน"
              />
            </div>

            <div className="mb-6 flex gap-1 rounded-xl bg-[var(--bg-surface-secondary)] p-1">
              {TABS.map((tab) => {
                const Icon = tab.icon;
                return (
                  <button
                    key={tab.key}
                    type="button"
                    onClick={() => setActiveTab(tab.key)}
                    className={`flex items-center gap-2 rounded-lg px-4 py-2 text-sm font-medium transition-colors ${
                      activeTab === tab.key
                        ? "bg-[var(--bg-surface)] text-primary shadow-sm"
                        : "text-[var(--text-muted)] hover:text-[var(--text-secondary)]"
                    }`}
                  >
                    <Icon className="size-4" />
                    {tab.label}
                  </button>
                );
              })}
            </div>

            {renderTabContent()}
          </>
        ) : null}
      </QueryState>
    </>
  );
}
