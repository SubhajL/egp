"use client";

import { FormEvent, useEffect, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { Building2, CreditCard, Mail, Users, Webhook } from "lucide-react";

import { PageHeader } from "@/components/layout/page-header";
import { QueryState } from "@/components/ui/query-state";
import { StatusBadge } from "@/components/ui/status-badge";
import {
  createAdminUser,
  createWebhook,
  deleteWebhook,
  updateAdminUser,
  updateAdminUserNotificationPreferences,
  updateTenantSettings,
  type AdminUser,
  type WebhookSubscription,
} from "@/lib/api";
import { useAdminSnapshot, useWebhooks } from "@/lib/hooks";
import { formatBudget, formatThaiDate } from "@/lib/utils";

const TABS = [
  { key: "users", label: "ผู้ใช้และบทบาท", icon: Users },
  { key: "notifications", label: "การแจ้งเตือน", icon: Mail },
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
  busy,
}: {
  user: AdminUser;
  onSave: (userId: string, role: string, status: string, fullName: string) => Promise<void>;
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
      <button
        type="button"
        disabled={busy}
        onClick={() => onSave(user.id, role, status, fullName)}
        className="rounded-xl bg-primary px-4 py-2 text-sm font-semibold text-white disabled:opacity-60"
      >
        บันทึก
      </button>
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

export default function AdminPage() {
  const queryClient = useQueryClient();
  const { data, isLoading, isError, error } = useAdminSnapshot();
  const {
    data: webhookData,
    isLoading: webhooksLoading,
    isError: webhooksError,
    error: webhookError,
  } = useWebhooks();
  const [activeTab, setActiveTab] = useState<(typeof TABS)[number]["key"]>("users");
  const [submitError, setSubmitError] = useState<string | null>(null);
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
  const currentSubscription = data?.billing.current_subscription ?? null;
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
  }

  async function refreshWebhooks() {
    await queryClient.invalidateQueries({ queryKey: ["webhooks"] });
  }

  async function handleCreateUser(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSubmitError(null);
    setBusy(true);
    try {
      await createAdminUser({
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
        mutationError instanceof Error ? mutationError.message : "ไม่สามารถสร้างผู้ใช้ได้",
      );
    } finally {
      setBusy(false);
    }
  }

  async function handleSaveUser(userId: string, role: string, status: string, fullName: string) {
    setSubmitError(null);
    setBusy(true);
    try {
      await updateAdminUser(userId, {
        role,
        status,
        full_name: fullName.trim() || undefined,
      });
      await refreshSnapshot();
    } catch (mutationError) {
      setSubmitError(
        mutationError instanceof Error ? mutationError.message : "ไม่สามารถอัปเดตผู้ใช้ได้",
      );
    } finally {
      setBusy(false);
    }
  }

  async function handleTogglePreference(user: AdminUser, notificationType: string) {
    setSubmitError(null);
    setBusy(true);
    try {
      await updateAdminUserNotificationPreferences(user.id, {
        email_preferences: {
          [notificationType]: !user.notification_preferences[notificationType],
        },
      });
      await refreshSnapshot();
    } catch (mutationError) {
      setSubmitError(
        mutationError instanceof Error
          ? mutationError.message
          : "ไม่สามารถอัปเดตการแจ้งเตือนได้",
      );
    } finally {
      setBusy(false);
    }
  }

  async function handleSaveSettings(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSubmitError(null);
    setBusy(true);
    try {
      await updateTenantSettings({
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
        mutationError instanceof Error ? mutationError.message : "ไม่สามารถบันทึกการตั้งค่าได้",
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
    setBusy(true);
    try {
      await createWebhook({
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
        mutationError instanceof Error ? mutationError.message : "ไม่สามารถสร้าง webhook ได้",
      );
    } finally {
      setBusy(false);
    }
  }

  async function handleDeleteWebhook(webhookId: string) {
    setSubmitError(null);
    setBusy(true);
    try {
      await deleteWebhook(webhookId);
      await refreshWebhooks();
    } catch (mutationError) {
      setSubmitError(
        mutationError instanceof Error ? mutationError.message : "ไม่สามารถลบ webhook ได้",
      );
    } finally {
      setBusy(false);
    }
  }

  function renderTabContent() {
    if (!data) return null;

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
              <UserRow key={user.id} user={user} onSave={handleSaveUser} busy={busy} />
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

          <div className="overflow-hidden rounded-2xl bg-[var(--bg-surface)] shadow-[var(--shadow-soft)]">
            <table className="min-w-full divide-y divide-[var(--border-default)] text-sm">
              <thead className="bg-[var(--bg-surface-secondary)]">
                <tr>
                  <th className="px-4 py-3 text-left">เลขที่บิล</th>
                  <th className="px-4 py-3 text-left">แผน</th>
                  <th className="px-4 py-3 text-left">สถานะ</th>
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
        subtitle="จัดการผู้ใช้ การแจ้งเตือน สิทธิ์ใช้งาน และการตั้งค่าองค์กรภายใต้ tenant เดียวกัน"
      />

      {submitError ? (
        <div className="mb-4 rounded-2xl border border-[var(--badge-red-bg)] bg-[var(--bg-surface)] p-4 text-sm text-[var(--badge-red-text)]">
          {submitError}
        </div>
      ) : null}

      <QueryState isLoading={isLoading} isError={isError} error={error}>
        {data ? (
          <>
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
