"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { FormEvent, Suspense, startTransition, useMemo, useState } from "react";

import { localizeApiError, resetPassword } from "@/lib/api";
import { normalizeToken } from "@/lib/auth";

function ResetPasswordPageContent() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const token = useMemo(() => normalizeToken(searchParams.get("token")), [searchParams]);
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [statusMessage, setStatusMessage] = useState<string | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!token) {
      setErrorMessage("ไม่พบ token สำหรับรีเซ็ตรหัสผ่าน");
      return;
    }
    setBusy(true);
    setStatusMessage(null);
    setErrorMessage(null);
    try {
      await resetPassword({ token, password });
      setStatusMessage("รีเซ็ตรหัสผ่านเรียบร้อยแล้ว กำลังพาคุณกลับไปหน้าเข้าสู่ระบบ");
      startTransition(() => {
        router.replace("/login");
      });
    } catch (error) {
      setErrorMessage(localizeApiError(error, "ไม่สามารถรีเซ็ตรหัสผ่านได้"));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-[var(--bg-page)] px-6 py-10">
      <div className="w-full max-w-lg rounded-[28px] border border-[var(--border-default)] bg-[var(--bg-surface)] p-8 shadow-[var(--shadow-soft)]">
        <h1 className="text-2xl font-bold text-[var(--text-primary)]">รีเซ็ตรหัสผ่าน</h1>
        <p className="mt-2 text-sm text-[var(--text-muted)]">
          ตั้งรหัสผ่านใหม่เพื่อใช้เข้าสู่ระบบในการเข้าสู่ระบบครั้งถัดไป
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
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            type="password"
            placeholder="รหัสผ่านใหม่อย่างน้อย 12 ตัวอักษร"
            required
            className="h-12 w-full rounded-xl border border-[var(--border-default)] bg-transparent px-4 text-sm outline-none"
          />
          <button
            type="submit"
            disabled={busy || !token}
            className="h-12 w-full rounded-xl bg-primary text-sm font-semibold text-white disabled:opacity-60"
          >
            บันทึกรหัสผ่านใหม่
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

export default function ResetPasswordPage() {
  return (
    <Suspense fallback={<div className="min-h-screen bg-[var(--bg-page)]" />}>
      <ResetPasswordPageContent />
    </Suspense>
  );
}
