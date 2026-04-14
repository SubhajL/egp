"use client";

import Link from "next/link";
import { FormEvent, useEffect, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, HardDrive, ShieldCheck } from "lucide-react";

import { PageHeader } from "@/components/layout/page-header";
import { QueryState } from "@/components/ui/query-state";
import { localizeApiError, updateTenantStorageSettings } from "@/lib/api";
import { useTenantStorageSettings } from "@/lib/hooks";

const PROVIDER_LABELS: Record<string, string> = {
  managed: "Managed by our platform",
  google_drive: "Google Drive",
  onedrive: "OneDrive",
  local_agent: "Local device agent",
};

const STATUS_LABELS: Record<string, string> = {
  managed: "ใช้ที่เก็บข้อมูลฝั่งเรา",
  pending_setup: "รอเชื่อมต่อผู้ให้บริการ",
  connected: "เชื่อมต่อแล้ว",
  error: "มีปัญหาการเชื่อมต่อ",
  disconnected: "ยังไม่ได้เชื่อมต่อ",
};

function InfoCard({
  title,
  description,
}: {
  title: string;
  description: string;
}) {
  return (
    <div className="rounded-3xl border border-[var(--border-default)] bg-[var(--bg-surface)] p-6 shadow-[var(--shadow-soft)]">
      <h2 className="text-lg font-semibold text-[var(--text-primary)]">{title}</h2>
      <p className="mt-2 text-sm text-[var(--text-muted)]">{description}</p>
    </div>
  );
}

export default function AdminStoragePage() {
  const queryClient = useQueryClient();
  const { data, isLoading, isError, error } = useTenantStorageSettings();
  const [provider, setProvider] = useState("managed");
  const [accountEmail, setAccountEmail] = useState("");
  const [folderLabel, setFolderLabel] = useState("");
  const [folderPathHint, setFolderPathHint] = useState("");
  const [managedFallbackEnabled, setManagedFallbackEnabled] = useState(false);
  const [statusMessage, setStatusMessage] = useState<string | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!data) return;
    setProvider(data.provider);
    setAccountEmail(data.account_email ?? "");
    setFolderLabel(data.folder_label ?? "");
    setFolderPathHint(data.folder_path_hint ?? "");
    setManagedFallbackEnabled(data.managed_fallback_enabled);
  }, [data]);

  async function refreshStorageSettings() {
    await queryClient.invalidateQueries({ queryKey: ["tenant-storage-settings"] });
    await queryClient.invalidateQueries({ queryKey: ["admin-snapshot"] });
    await queryClient.invalidateQueries({ queryKey: ["audit-log"] });
  }

  async function handleSave(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setStatusMessage(null);
    setErrorMessage(null);

    const trimmedAccountEmail = accountEmail.trim();
    const trimmedFolderLabel = folderLabel.trim();
    const trimmedFolderPathHint = folderPathHint.trim();
    const nextConnectionStatus =
      provider === "managed"
        ? "managed"
        : trimmedAccountEmail || trimmedFolderLabel || trimmedFolderPathHint
          ? "pending_setup"
          : "disconnected";

    try {
      await updateTenantStorageSettings({
        provider,
        connection_status: nextConnectionStatus,
        account_email: trimmedAccountEmail,
        folder_label: trimmedFolderLabel,
        folder_path_hint: trimmedFolderPathHint,
        managed_fallback_enabled: managedFallbackEnabled,
        last_validation_error:
          provider === "managed"
            ? ""
            : "Provider OAuth and folder validation will be completed in the next integration slice.",
      });
      await refreshStorageSettings();
      setStatusMessage("บันทึกการตั้งค่าที่เก็บเอกสารแล้ว");
    } catch (mutationError) {
      setErrorMessage(
        localizeApiError(mutationError, "ไม่สามารถบันทึกการตั้งค่าที่เก็บเอกสารได้"),
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-6">
      <PageHeader
        title="ที่เก็บเอกสาร"
        subtitle="แยกการตั้งค่าปลายทางของไฟล์ TOR และเอกสารออกจากหน้าแอดมินหลัก"
        actions={
          <Link
            href="/admin"
            className="inline-flex items-center gap-2 rounded-xl border border-[var(--border-default)] px-4 py-2 text-sm font-semibold text-[var(--text-secondary)] hover:bg-[var(--bg-surface-hover)]"
          >
            <ArrowLeft className="size-4" />
            กลับไปหน้าแอดมิน
          </Link>
        }
      />

      {statusMessage ? (
        <div className="rounded-2xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-700">
          {statusMessage}
        </div>
      ) : null}

      {errorMessage ? (
        <div className="rounded-2xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          {errorMessage}
        </div>
      ) : null}

      <QueryState isLoading={isLoading} isError={isError} error={error}>
        {data ? (
          <div className="grid gap-6 xl:grid-cols-[1.3fr_0.7fr]">
            <form
              onSubmit={handleSave}
              className="space-y-6 rounded-3xl border border-[var(--border-default)] bg-[var(--bg-surface)] p-6 shadow-[var(--shadow-soft)]"
            >
              <div className="flex items-start gap-4">
                <div className="flex size-12 items-center justify-center rounded-2xl bg-primary/10 text-primary">
                  <HardDrive className="size-5" />
                </div>
                <div>
                  <h2 className="text-lg font-semibold text-[var(--text-primary)]">
                    ปลายทางจัดเก็บไฟล์
                  </h2>
                  <p className="mt-1 text-sm text-[var(--text-muted)]">
                    ตอนนี้ระบบยังเก็บสถานะโครงการ ประวัติการเปลี่ยนแปลง และบันทึกการรันไว้ในฐานข้อมูลฝั่งเรา ส่วนหน้านี้ใช้กำหนดปลายทางของไฟล์เอกสารเท่านั้น
                  </p>
                </div>
              </div>

              <label className="block space-y-2">
                <span className="text-sm font-medium text-[var(--text-secondary)]">
                  ผู้ให้บริการจัดเก็บไฟล์
                </span>
                <select
                  value={provider}
                  onChange={(event) => {
                    const nextProvider = event.target.value;
                    setProvider(nextProvider);
                    if (nextProvider === "managed") {
                      setAccountEmail("");
                      setFolderLabel("");
                      setFolderPathHint("");
                      setManagedFallbackEnabled(false);
                    }
                  }}
                  className="h-12 w-full rounded-xl border border-[var(--border-default)] bg-transparent px-4 text-sm outline-none"
                >
                  <option value="managed">Managed by our platform</option>
                  <option value="google_drive">Google Drive</option>
                  <option value="onedrive">OneDrive</option>
                  <option value="local_agent">Local device agent</option>
                </select>
              </label>

              <div className="grid gap-4 md:grid-cols-2">
                <label className="block space-y-2">
                  <span className="text-sm font-medium text-[var(--text-secondary)]">
                    บัญชีปลายทาง
                  </span>
                  <input
                    value={accountEmail}
                    onChange={(event) => setAccountEmail(event.target.value)}
                    placeholder="ops@example.com"
                    className="h-12 w-full rounded-xl border border-[var(--border-default)] bg-transparent px-4 text-sm outline-none"
                  />
                </label>
                <label className="block space-y-2">
                  <span className="text-sm font-medium text-[var(--text-secondary)]">
                    ชื่อโฟลเดอร์
                  </span>
                  <input
                    value={folderLabel}
                    onChange={(event) => setFolderLabel(event.target.value)}
                    placeholder="Acme Procurement TOR"
                    className="h-12 w-full rounded-xl border border-[var(--border-default)] bg-transparent px-4 text-sm outline-none"
                  />
                </label>
              </div>

              <label className="block space-y-2">
                <span className="text-sm font-medium text-[var(--text-secondary)]">
                  Path หรือคำอธิบายตำแหน่งที่ผู้ใช้คาดหวัง
                </span>
                <input
                  value={folderPathHint}
                  onChange={(event) => setFolderPathHint(event.target.value)}
                  placeholder="Google Drive/Acme Procurement TOR"
                  className="h-12 w-full rounded-xl border border-[var(--border-default)] bg-transparent px-4 text-sm outline-none"
                />
              </label>

              <label className="flex items-start gap-3 rounded-2xl border border-[var(--border-default)] bg-[var(--bg-surface-secondary)] p-4">
                <input
                  type="checkbox"
                  checked={managedFallbackEnabled}
                  onChange={(event) => setManagedFallbackEnabled(event.target.checked)}
                  className="mt-1 size-4 rounded border border-[var(--border-default)]"
                />
                <span className="text-sm text-[var(--text-secondary)]">
                  อนุญาตให้ใช้ managed storage เป็น fallback ชั่วคราวหากการเชื่อมต่อปลายทางภายนอกมีปัญหา
                </span>
              </label>

              <div className="flex flex-wrap gap-3">
                <button
                  type="submit"
                  disabled={busy}
                  className="rounded-xl bg-primary px-4 py-2 text-sm font-semibold text-white disabled:opacity-60"
                >
                  บันทึกการตั้งค่า
                </button>
                <span className="rounded-xl border border-[var(--border-default)] px-4 py-2 text-sm text-[var(--text-muted)]">
                  สถานะปัจจุบัน: {STATUS_LABELS[data.connection_status] ?? data.connection_status}
                </span>
              </div>
            </form>

            <div className="space-y-6">
              <InfoCard
                title="สถานะที่บันทึกไว้"
                description={`ปลายทางปัจจุบัน: ${PROVIDER_LABELS[data.provider] ?? data.provider}`}
              />
              <InfoCard
                title="สิ่งที่ยังอยู่ในระบบของเรา"
                description="ฐานข้อมูลโครงการ, project status history, crawl runs/tasks, เอกสาร metadata, audit log และสิทธิ์การใช้งาน ยังคงเป็น system of record ฝั่งเรา"
              />
              <div className="rounded-3xl border border-[var(--border-default)] bg-[var(--bg-surface)] p-6 shadow-[var(--shadow-soft)]">
                <div className="flex items-start gap-3">
                  <ShieldCheck className="mt-0.5 size-5 text-primary" />
                  <div>
                    <h2 className="text-lg font-semibold text-[var(--text-primary)]">
                      ขอบเขตของ slice นี้
                    </h2>
                    <p className="mt-2 text-sm text-[var(--text-muted)]">
                      หน้านี้และ API ชุดนี้เก็บ configuration ของปลายทางไว้ก่อน ส่วน OAuth จริงของ Google Drive / OneDrive และ local agent จะตามมาใน slice ถัดไป
                    </p>
                    {data.last_validation_error ? (
                      <p className="mt-3 rounded-2xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800">
                        {data.last_validation_error}
                      </p>
                    ) : null}
                  </div>
                </div>
              </div>
            </div>
          </div>
        ) : null}
      </QueryState>
    </div>
  );
}
