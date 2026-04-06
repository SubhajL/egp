"use client";

import Link from "next/link";
import { useQueryClient } from "@tanstack/react-query";
import { useSearchParams } from "next/navigation";
import { Suspense, useEffect, useMemo, useState } from "react";

import { ApiError, verifyEmail } from "@/lib/api";
import { normalizeToken } from "@/lib/auth";

function VerifyEmailPageContent() {
  const queryClient = useQueryClient();
  const searchParams = useSearchParams();
  const token = useMemo(() => normalizeToken(searchParams.get("token")), [searchParams]);
  const [statusMessage, setStatusMessage] = useState("กำลังยืนยันอีเมล...");
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    async function run() {
      if (!token) {
        setStatusMessage("");
        setErrorMessage("ไม่พบ token สำหรับยืนยันอีเมล");
        return;
      }
      try {
        await verifyEmail(token);
        await queryClient.invalidateQueries({ queryKey: ["me"] });
        if (!active) return;
        setStatusMessage("ยืนยันอีเมลเรียบร้อยแล้ว");
        setErrorMessage(null);
      } catch (error) {
        if (!active) return;
        setStatusMessage("");
        if (error instanceof ApiError) {
          setErrorMessage(error.detail);
        } else if (error instanceof Error) {
          setErrorMessage(error.message);
        } else {
          setErrorMessage("ไม่สามารถยืนยันอีเมลได้");
        }
      }
    }
    void run();
    return () => {
      active = false;
    };
  }, [queryClient, token]);

  return (
    <div className="flex min-h-screen items-center justify-center bg-[var(--bg-page)] px-6 py-10">
      <div className="w-full max-w-lg rounded-[28px] border border-[var(--border-default)] bg-[var(--bg-surface)] p-8 shadow-[var(--shadow-soft)]">
        <h1 className="text-2xl font-bold text-[var(--text-primary)]">ยืนยันอีเมล</h1>
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
        <div className="mt-6 text-sm text-[var(--text-muted)]">
          <Link href="/login" className="font-semibold text-primary">
            กลับไปหน้าเข้าสู่ระบบ
          </Link>
        </div>
      </div>
    </div>
  );
}

export default function VerifyEmailPage() {
  return (
    <Suspense fallback={<div className="min-h-screen bg-[var(--bg-page)]" />}>
      <VerifyEmailPageContent />
    </Suspense>
  );
}
