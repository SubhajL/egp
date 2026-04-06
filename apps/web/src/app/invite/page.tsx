"use client";

import { useQueryClient } from "@tanstack/react-query";
import { useRouter, useSearchParams } from "next/navigation";
import { FormEvent, Suspense, startTransition, useMemo, useState } from "react";

import { ApiError, acceptInvite } from "@/lib/api";
import { normalizeToken } from "@/lib/auth";

function InvitePageContent() {
  const router = useRouter();
  const queryClient = useQueryClient();
  const searchParams = useSearchParams();
  const token = useMemo(() => normalizeToken(searchParams.get("token")), [searchParams]);
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!token) {
      setErrorMessage("ไม่พบ token สำหรับคำเชิญนี้");
      return;
    }
    setBusy(true);
    setErrorMessage(null);
    try {
      const currentSession = await acceptInvite({ token, password });
      queryClient.setQueryData(["me"], currentSession);
      startTransition(() => {
        router.replace("/dashboard");
      });
    } catch (error) {
      if (error instanceof ApiError) {
        setErrorMessage(error.detail);
      } else if (error instanceof Error) {
        setErrorMessage(error.message);
      } else {
        setErrorMessage("ไม่สามารถรับคำเชิญได้");
      }
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-[var(--bg-page)] px-6 py-10">
      <div className="w-full max-w-lg rounded-[28px] border border-[var(--border-default)] bg-[var(--bg-surface)] p-8 shadow-[var(--shadow-soft)]">
        <h1 className="text-2xl font-bold text-[var(--text-primary)]">ตั้งรหัสผ่านจากคำเชิญ</h1>
        <p className="mt-2 text-sm text-[var(--text-muted)]">
          สร้างรหัสผ่านใหม่เพื่อเปิดใช้งานบัญชีและเข้าสู่ระบบทันที
        </p>

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
            รับคำเชิญและเข้าสู่ระบบ
          </button>
        </form>
      </div>
    </div>
  );
}

export default function InvitePage() {
  return (
    <Suspense fallback={<div className="min-h-screen bg-[var(--bg-page)]" />}>
      <InvitePageContent />
    </Suspense>
  );
}
