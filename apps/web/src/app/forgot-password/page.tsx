"use client";

import Link from "next/link";
import { FormEvent, useState } from "react";

import { requestPasswordReset } from "@/lib/api";

export default function ForgotPasswordPage() {
  const [tenantSlug, setTenantSlug] = useState("");
  const [email, setEmail] = useState("");
  const [busy, setBusy] = useState(false);
  const [statusMessage, setStatusMessage] = useState<string | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setStatusMessage(null);
    setErrorMessage(null);
    try {
      await requestPasswordReset({
        tenant_slug: tenantSlug.trim(),
        email: email.trim(),
      });
      setStatusMessage("หากบัญชีนี้มีอยู่ในระบบ เราได้ส่งลิงก์รีเซ็ตรหัสผ่านให้แล้ว");
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : "ไม่สามารถส่งคำขอรีเซ็ตรหัสผ่านได้");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-[var(--bg-page)] px-6 py-10">
      <div className="w-full max-w-lg rounded-[28px] border border-[var(--border-default)] bg-[var(--bg-surface)] p-8 shadow-[var(--shadow-soft)]">
        <h1 className="text-2xl font-bold text-[var(--text-primary)]">ลืมรหัสผ่าน</h1>
        <p className="mt-2 text-sm text-[var(--text-muted)]">
          ระบุ tenant slug และอีเมลของคุณ เราจะส่งลิงก์รีเซ็ตรหัสผ่านให้หากบัญชีนี้มีอยู่จริง
        </p>

        {statusMessage ? (
          <div className="mt-6 rounded-2xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-700">
            {statusMessage}
          </div>
        ) : null}

        {errorMessage ? (
          <div className="mt-6 rounded-2xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
            {errorMessage}
          </div>
        ) : null}

        <form className="mt-6 space-y-4" onSubmit={handleSubmit}>
          <input
            value={tenantSlug}
            onChange={(event) => setTenantSlug(event.target.value)}
            placeholder="tenant slug"
            required
            className="h-12 w-full rounded-xl border border-[var(--border-default)] bg-transparent px-4 text-sm outline-none"
          />
          <input
            value={email}
            onChange={(event) => setEmail(event.target.value)}
            type="email"
            placeholder="name@company.com"
            required
            className="h-12 w-full rounded-xl border border-[var(--border-default)] bg-transparent px-4 text-sm outline-none"
          />
          <button
            type="submit"
            disabled={busy}
            className="h-12 w-full rounded-xl bg-primary text-sm font-semibold text-white disabled:opacity-60"
          >
            ส่งลิงก์รีเซ็ตรหัสผ่าน
          </button>
        </form>

        <div className="mt-6 text-sm text-[var(--text-muted)]">
          <Link href="/login" className="font-semibold text-primary">
            กลับไปหน้าเข้าสู่ระบบ
          </Link>
        </div>
      </div>
    </div>
  );
}
