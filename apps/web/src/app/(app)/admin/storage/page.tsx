"use client";

import Link from "next/link";
import { FormEvent, useEffect, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, HardDrive, KeyRound, ShieldCheck } from "lucide-react";

import { PageHeader } from "@/components/layout/page-header";
import { QueryState } from "@/components/ui/query-state";
import {
  connectTenantStorage,
  disconnectTenantStorage,
  localizeApiError,
  testTenantStorageWrite,
  updateTenantStorageSettings,
} from "@/lib/api";
import { useTenantStorageSettings } from "@/lib/hooks";
import { formatThaiDate } from "@/lib/utils";

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
  const [credentialType, setCredentialType] = useState("oauth_tokens");
  const [accessToken, setAccessToken] = useState("");
  const [refreshToken, setRefreshToken] = useState("");
  const [statusMessage, setStatusMessage] = useState<string | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [busyAction, setBusyAction] = useState<string | null>(null);

  useEffect(() => {
    if (!data) return;
    setProvider(data.provider);
    setAccountEmail(data.account_email ?? "");
    setFolderLabel(data.folder_label ?? "");
    setFolderPathHint(data.folder_path_hint ?? "");
    setManagedFallbackEnabled(data.managed_fallback_enabled);
    setCredentialType(data.credential_type ?? "oauth_tokens");
  }, [data]);

  const externalProviderSelected = provider !== "managed";

  async function refreshStorageSettings() {
    await queryClient.invalidateQueries({ queryKey: ["tenant-storage-settings"] });
    await queryClient.invalidateQueries({ queryKey: ["admin-snapshot"] });
    await queryClient.invalidateQueries({ queryKey: ["audit-log"] });
  }

  async function handleSave(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusyAction("save");
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
        last_validation_error: provider === "managed" ? "" : null,
      });
      await refreshStorageSettings();
      setStatusMessage("บันทึกการตั้งค่าปลายทางจัดเก็บเอกสารแล้ว");
    } catch (mutationError) {
      setErrorMessage(
        localizeApiError(mutationError, "ไม่สามารถบันทึกการตั้งค่าที่เก็บเอกสารได้"),
      );
    } finally {
      setBusyAction(null);
    }
  }

  async function handleConnect() {
    if (!externalProviderSelected) {
      setErrorMessage("เลือกผู้ให้บริการภายนอกก่อนบันทึก credentials");
      return;
    }
    setBusyAction("connect");
    setStatusMessage(null);
    setErrorMessage(null);
    try {
      const credentials: Record<string, string> = {};
      if (accessToken.trim()) credentials.access_token = accessToken.trim();
      if (refreshToken.trim()) credentials.refresh_token = refreshToken.trim();
      await connectTenantStorage({
        provider,
        credential_type: credentialType.trim() || "oauth_tokens",
        credentials,
      });
      setAccessToken("");
      setRefreshToken("");
      await refreshStorageSettings();
      setStatusMessage("บันทึก credentials แบบเข้ารหัสแล้ว");
    } catch (mutationError) {
      setErrorMessage(
        localizeApiError(mutationError, "ไม่สามารถบันทึก credentials สำหรับ storage ได้"),
      );
    } finally {
      setBusyAction(null);
    }
  }

  async function handleDisconnect() {
    if (!externalProviderSelected) {
      setErrorMessage("Managed storage ไม่มี credentials ให้ตัดการเชื่อมต่อ");
      return;
    }
    setBusyAction("disconnect");
    setStatusMessage(null);
    setErrorMessage(null);
    try {
      await disconnectTenantStorage({ provider });
      setAccessToken("");
      setRefreshToken("");
      await refreshStorageSettings();
      setStatusMessage("ลบ credentials ของปลายทางนี้แล้ว");
    } catch (mutationError) {
      setErrorMessage(localizeApiError(mutationError, "ไม่สามารถยกเลิกการเชื่อมต่อ storage ได้"));
    } finally {
      setBusyAction(null);
    }
  }

  async function handleValidate() {
    setBusyAction("validate");
    setStatusMessage(null);
    setErrorMessage(null);
    try {
      await testTenantStorageWrite();
      await refreshStorageSettings();
      setStatusMessage("ทดสอบการเชื่อมต่อฝั่งเซิร์ฟเวอร์ผ่านแล้ว");
    } catch (mutationError) {
      setErrorMessage(localizeApiError(mutationError, "การทดสอบปลายทางจัดเก็บเอกสารไม่ผ่าน"));
      await refreshStorageSettings();
    } finally {
      setBusyAction(null);
    }
  }

  return (
    <div className="space-y-6">
      <PageHeader
        title="ที่เก็บเอกสาร"
        subtitle="ตั้งค่าปลายทางจัดเก็บ TOR แยกจากฐานข้อมูลสถานะโครงการและบันทึกการติดตาม"
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
            <div className="space-y-6">
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
                      ส่วนนี้เก็บเฉพาะปลายทางของไฟล์ TOR และเอกสาร ส่วนฐานข้อมูลโครงการ,
                      status history, crawl runs/tasks, metadata, audit log และสิทธิ์ใช้งาน
                      ยังเป็น system of record ฝั่งเรา
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
                      disabled={!externalProviderSelected}
                      className="h-12 w-full rounded-xl border border-[var(--border-default)] bg-transparent px-4 text-sm outline-none disabled:opacity-60"
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
                      disabled={!externalProviderSelected}
                      className="h-12 w-full rounded-xl border border-[var(--border-default)] bg-transparent px-4 text-sm outline-none disabled:opacity-60"
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
                    disabled={!externalProviderSelected}
                    className="h-12 w-full rounded-xl border border-[var(--border-default)] bg-transparent px-4 text-sm outline-none disabled:opacity-60"
                  />
                </label>

                <label className="flex items-start gap-3 rounded-2xl border border-[var(--border-default)] bg-[var(--bg-surface-secondary)] p-4">
                  <input
                    type="checkbox"
                    checked={managedFallbackEnabled}
                    onChange={(event) => setManagedFallbackEnabled(event.target.checked)}
                    disabled={!externalProviderSelected}
                    className="mt-1 size-4 rounded border border-[var(--border-default)]"
                  />
                  <span className="text-sm text-[var(--text-secondary)]">
                    อนุญาตให้ใช้ managed storage เป็น fallback ชั่วคราวหากปลายทางภายนอกมีปัญหา
                  </span>
                </label>

                <div className="flex flex-wrap gap-3">
                  <button
                    type="submit"
                    disabled={busyAction !== null}
                    className="rounded-xl bg-primary px-4 py-2 text-sm font-semibold text-white disabled:opacity-60"
                  >
                    {busyAction === "save" ? "กำลังบันทึก..." : "บันทึกการตั้งค่า"}
                  </button>
                  <span className="rounded-xl border border-[var(--border-default)] px-4 py-2 text-sm text-[var(--text-muted)]">
                    สถานะปัจจุบัน: {STATUS_LABELS[data.connection_status] ?? data.connection_status}
                  </span>
                </div>
              </form>

              <section className="space-y-5 rounded-3xl border border-[var(--border-default)] bg-[var(--bg-surface)] p-6 shadow-[var(--shadow-soft)]">
                <div className="flex items-start gap-4">
                  <div className="flex size-12 items-center justify-center rounded-2xl bg-[var(--badge-blue-bg)] text-[var(--badge-blue-text)]">
                    <KeyRound className="size-5" />
                  </div>
                  <div>
                    <h2 className="text-lg font-semibold text-[var(--text-primary)]">
                      Credentials และ validation
                    </h2>
                    <p className="mt-1 text-sm text-[var(--text-muted)]">
                      Slice นี้ยังไม่เปิด OAuth flow จริง แต่รองรับการบันทึก credentials แบบเข้ารหัส,
                      การตัดการเชื่อมต่อ, และ server-side validation เพื่อเตรียมต่อไปยัง Google Drive,
                      OneDrive และ local agent
                    </p>
                  </div>
                </div>

                <div className="grid gap-4 md:grid-cols-2">
                  <label className="block space-y-2">
                    <span className="text-sm font-medium text-[var(--text-secondary)]">
                      Credential type
                    </span>
                    <input
                      value={credentialType}
                      onChange={(event) => setCredentialType(event.target.value)}
                      disabled={!externalProviderSelected || busyAction !== null}
                      className="h-12 w-full rounded-xl border border-[var(--border-default)] bg-transparent px-4 text-sm outline-none disabled:opacity-60"
                    />
                  </label>
                  <label className="block space-y-2">
                    <span className="text-sm font-medium text-[var(--text-secondary)]">
                      Access token
                    </span>
                    <input
                      type="password"
                      value={accessToken}
                      onChange={(event) => setAccessToken(event.target.value)}
                      disabled={!externalProviderSelected || busyAction !== null}
                      placeholder="access-token"
                      className="h-12 w-full rounded-xl border border-[var(--border-default)] bg-transparent px-4 text-sm outline-none disabled:opacity-60"
                    />
                  </label>
                </div>

                <label className="block space-y-2">
                  <span className="text-sm font-medium text-[var(--text-secondary)]">
                    Refresh token / agent secret
                  </span>
                  <input
                    type="password"
                    value={refreshToken}
                    onChange={(event) => setRefreshToken(event.target.value)}
                    disabled={!externalProviderSelected || busyAction !== null}
                    placeholder="refresh-token"
                    className="h-12 w-full rounded-xl border border-[var(--border-default)] bg-transparent px-4 text-sm outline-none disabled:opacity-60"
                  />
                </label>

                <div className="flex flex-wrap gap-3">
                  <button
                    type="button"
                    disabled={!externalProviderSelected || busyAction !== null}
                    onClick={handleConnect}
                    className="rounded-xl bg-primary px-4 py-2 text-sm font-semibold text-white disabled:opacity-60"
                  >
                    {busyAction === "connect" ? "กำลังบันทึก..." : "บันทึก credentials"}
                  </button>
                  <button
                    type="button"
                    disabled={!externalProviderSelected || busyAction !== null}
                    onClick={handleValidate}
                    className="rounded-xl border border-[var(--border-default)] px-4 py-2 text-sm font-semibold text-[var(--text-secondary)] disabled:opacity-60"
                  >
                    {busyAction === "validate" ? "กำลังทดสอบ..." : "ทดสอบการเชื่อมต่อ"}
                  </button>
                  <button
                    type="button"
                    disabled={!externalProviderSelected || busyAction !== null || !data.has_credentials}
                    onClick={handleDisconnect}
                    className="rounded-xl border border-red-200 px-4 py-2 text-sm font-semibold text-red-700 disabled:opacity-60"
                  >
                    {busyAction === "disconnect" ? "กำลังลบ..." : "ตัดการเชื่อมต่อ"}
                  </button>
                </div>
              </section>
            </div>

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
                  <div className="space-y-3">
                    <div>
                      <h2 className="text-lg font-semibold text-[var(--text-primary)]">
                        สถานะ integration
                      </h2>
                      <p className="mt-2 text-sm text-[var(--text-muted)]">
                        ผู้ให้บริการ: {PROVIDER_LABELS[data.provider] ?? data.provider}
                      </p>
                      <p className="mt-1 text-sm text-[var(--text-muted)]">
                        Connection status: {STATUS_LABELS[data.connection_status] ?? data.connection_status}
                      </p>
                    </div>
                    <div className="rounded-2xl border border-[var(--border-default)] bg-[var(--bg-surface-secondary)] p-4 text-sm text-[var(--text-secondary)]">
                      <p>Credentials ถูกบันทึกแล้ว: {data.has_credentials ? "ใช่" : "ไม่ใช่"}</p>
                      <p className="mt-1">
                        Credential type: {data.credential_type ?? "ยังไม่มี"}
                      </p>
                      <p className="mt-1">
                        อัปเดตล่าสุด:{" "}
                        {data.credential_updated_at ? formatThaiDate(data.credential_updated_at) : "-"}
                      </p>
                      <p className="mt-1">
                        ตรวจสอบล่าสุด:{" "}
                        {data.last_validated_at ? formatThaiDate(data.last_validated_at) : "-"}
                      </p>
                    </div>
                    {data.last_validation_error ? (
                      <p className="rounded-2xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800">
                        {data.last_validation_error}
                      </p>
                    ) : null}
                    <p className="text-sm text-[var(--text-muted)]">
                      OAuth จริง, provider folder picker, token refresh, และ runtime artifact upload
                      per tenant จะตามมาใน slice ถัดไป
                    </p>
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
