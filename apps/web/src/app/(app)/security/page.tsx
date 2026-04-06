"use client";

import { useQueryClient } from "@tanstack/react-query";
import { FormEvent, type ReactNode, useState } from "react";

import { PageHeader } from "@/components/layout/page-header";
import { QueryState } from "@/components/ui/query-state";
import { ApiError, disableMfa, enableMfa, sendEmailVerification, setupMfa } from "@/lib/api";
import { useMe } from "@/lib/hooks";

function SecurityCard({
  title,
  description,
  children,
}: {
  title: string;
  description: string;
  children: ReactNode;
}) {
  return (
    <section className="rounded-3xl border border-[var(--border-default)] bg-[var(--bg-surface)] p-6 shadow-[var(--shadow-soft)]">
      <div className="max-w-2xl">
        <h2 className="text-lg font-semibold text-[var(--text-primary)]">{title}</h2>
        <p className="mt-1 text-sm text-[var(--text-muted)]">{description}</p>
      </div>
      <div className="mt-6">{children}</div>
    </section>
  );
}

export default function SecurityPage() {
  const queryClient = useQueryClient();
  const { data: currentSession, isLoading, isError, error } = useMe();
  const [statusMessage, setStatusMessage] = useState<string | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [mfaCode, setMfaCode] = useState("");
  const [setupSecret, setSetupSecret] = useState<string | null>(null);
  const [setupUri, setSetupUri] = useState<string | null>(null);

  async function refreshMe() {
    await queryClient.invalidateQueries({ queryKey: ["me"] });
  }

  async function handleSendVerification() {
    setBusy(true);
    setErrorMessage(null);
    setStatusMessage(null);
    try {
      await sendEmailVerification();
      setStatusMessage("ส่งลิงก์ยืนยันอีเมลแล้ว กรุณาตรวจสอบกล่องจดหมายของคุณ");
    } catch (mutationError) {
      setErrorMessage(
        mutationError instanceof Error ? mutationError.message : "ไม่สามารถส่งลิงก์ยืนยันอีเมลได้",
      );
    } finally {
      setBusy(false);
    }
  }

  async function handleBeginMfa() {
    setBusy(true);
    setErrorMessage(null);
    setStatusMessage(null);
    try {
      const setup = await setupMfa();
      setSetupSecret(setup.secret);
      setSetupUri(setup.otpauth_uri);
      setStatusMessage("สแกนหรือคัดลอก secret ไปยังแอป authenticator แล้วกรอกรหัส 6 หลักเพื่อเปิดใช้");
    } catch (mutationError) {
      setErrorMessage(
        mutationError instanceof Error ? mutationError.message : "ไม่สามารถเริ่มตั้งค่า MFA ได้",
      );
    } finally {
      setBusy(false);
    }
  }

  async function handleEnableMfa(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setErrorMessage(null);
    setStatusMessage(null);
    try {
      await enableMfa(mfaCode.trim());
      setMfaCode("");
      setSetupSecret(null);
      setSetupUri(null);
      await refreshMe();
      setStatusMessage("เปิดใช้ MFA เรียบร้อยแล้ว");
    } catch (mutationError) {
      setErrorMessage(
        mutationError instanceof Error ? mutationError.message : "ไม่สามารถเปิดใช้ MFA ได้",
      );
    } finally {
      setBusy(false);
    }
  }

  async function handleDisableMfa(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setErrorMessage(null);
    setStatusMessage(null);
    try {
      await disableMfa(mfaCode.trim());
      setMfaCode("");
      await refreshMe();
      setStatusMessage("ปิดใช้ MFA เรียบร้อยแล้ว");
    } catch (mutationError) {
      setErrorMessage(
        mutationError instanceof Error ? mutationError.message : "ไม่สามารถปิดใช้ MFA ได้",
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-6">
      <PageHeader
        title="ความปลอดภัยของบัญชี"
        subtitle="จัดการการยืนยันอีเมลและการยืนยันตัวตนหลายชั้นของผู้ใช้ปัจจุบัน"
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
        {currentSession ? (
          <div className="space-y-6">
            <SecurityCard
              title="ยืนยันอีเมล"
              description="คำเชิญและรีเซ็ตรหัสผ่านทำงานได้โดยไม่ต้องยืนยันอีเมล แต่บัญชีที่ยืนยันแล้วจะตรวจสอบย้อนหลังได้ง่ายกว่า"
            >
              <div className="flex flex-col gap-4 md:flex-row md:items-center md:justify-between">
                <div>
                  <p className="text-sm font-semibold text-[var(--text-primary)]">
                    {currentSession.user.email ?? currentSession.user.subject}
                  </p>
                  <p className="mt-1 text-sm text-[var(--text-muted)]">
                    {currentSession.user.email_verified
                      ? `ยืนยันแล้วเมื่อ ${currentSession.user.email_verified_at ?? "-"}`
                      : "ยังไม่ได้ยืนยันอีเมล"}
                  </p>
                </div>
                {!currentSession.user.email_verified ? (
                  <button
                    type="button"
                    disabled={busy}
                    onClick={handleSendVerification}
                    className="rounded-xl bg-primary px-4 py-2 text-sm font-semibold text-white disabled:opacity-60"
                  >
                    ส่งลิงก์ยืนยันอีกครั้ง
                  </button>
                ) : null}
              </div>
            </SecurityCard>

            <SecurityCard
              title="Multi-Factor Authentication"
              description="ใช้แอป authenticator มาตรฐาน TOTP เช่น 1Password, Google Authenticator หรือ Authy"
            >
              {!currentSession.user.mfa_enabled && !setupSecret ? (
                <div className="flex flex-col gap-4 md:flex-row md:items-center md:justify-between">
                  <p className="text-sm text-[var(--text-muted)]">
                    บัญชีนี้ยังไม่ได้เปิดใช้ MFA เมื่อเปิดใช้แล้ว การเข้าสู่ระบบจะต้องใช้รหัส 6 หลักเพิ่มเติม
                  </p>
                  <button
                    type="button"
                    disabled={busy}
                    onClick={handleBeginMfa}
                    className="rounded-xl bg-primary px-4 py-2 text-sm font-semibold text-white disabled:opacity-60"
                  >
                    เริ่มตั้งค่า MFA
                  </button>
                </div>
              ) : null}

              {!currentSession.user.mfa_enabled && setupSecret ? (
                <form className="space-y-4" onSubmit={handleEnableMfa}>
                  <div className="rounded-2xl border border-[var(--border-default)] bg-[var(--bg-surface-secondary)] p-4">
                    <p className="text-xs font-semibold uppercase tracking-[0.14em] text-[var(--text-muted)]">
                      Secret
                    </p>
                    <p className="mt-2 break-all text-sm font-semibold text-[var(--text-primary)]">
                      {setupSecret}
                    </p>
                    {setupUri ? (
                      <p className="mt-3 break-all text-xs text-[var(--text-muted)]">{setupUri}</p>
                    ) : null}
                  </div>
                  <input
                    value={mfaCode}
                    onChange={(event) => setMfaCode(event.target.value)}
                    inputMode="numeric"
                    autoComplete="one-time-code"
                    placeholder="กรอกรหัส 6 หลักจากแอป"
                    className="h-12 w-full rounded-xl border border-[var(--border-default)] bg-transparent px-4 text-sm outline-none"
                  />
                  <button
                    type="submit"
                    disabled={busy}
                    className="rounded-xl bg-primary px-4 py-2 text-sm font-semibold text-white disabled:opacity-60"
                  >
                    เปิดใช้ MFA
                  </button>
                </form>
              ) : null}

              {currentSession.user.mfa_enabled ? (
                <form className="space-y-4" onSubmit={handleDisableMfa}>
                  <p className="text-sm text-[var(--text-muted)]">
                    MFA เปิดใช้งานอยู่ หากต้องการปิดใช้งาน ให้กรอกรหัส 6 หลักล่าสุดจากแอป authenticator
                  </p>
                  <input
                    value={mfaCode}
                    onChange={(event) => setMfaCode(event.target.value)}
                    inputMode="numeric"
                    autoComplete="one-time-code"
                    placeholder="กรอกรหัส 6 หลัก"
                    className="h-12 w-full rounded-xl border border-[var(--border-default)] bg-transparent px-4 text-sm outline-none"
                  />
                  <button
                    type="submit"
                    disabled={busy}
                    className="rounded-xl border border-red-200 px-4 py-2 text-sm font-semibold text-red-700 disabled:opacity-60"
                  >
                    ปิดใช้ MFA
                  </button>
                </form>
              ) : null}
            </SecurityCard>
          </div>
        ) : null}
      </QueryState>
    </div>
  );
}
