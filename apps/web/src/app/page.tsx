"use client";

import { startTransition, useEffect } from "react";
import { useRouter } from "next/navigation";

import { ApiError } from "@/lib/api";
import { useMe } from "@/lib/hooks";

export default function HomePage() {
  const router = useRouter();
  const { data: currentSession, error, isLoading } = useMe();

  useEffect(() => {
    if (isLoading) {
      return;
    }
    if (currentSession) {
      startTransition(() => {
        router.replace("/dashboard");
      });
      return;
    }
    if (error instanceof ApiError && error.status === 401) {
      startTransition(() => {
        router.replace("/login");
      });
    }
  }, [currentSession, error, isLoading, router]);

  return (
    <div className="flex min-h-screen items-center justify-center bg-[var(--bg-page)] px-6">
      <div className="w-full max-w-md rounded-3xl border border-[var(--border-default)] bg-[var(--bg-surface)] px-6 py-8 text-center shadow-sm">
        <p className="text-sm font-medium text-[var(--text-secondary)]">กำลังตรวจสอบสิทธิ์การใช้งาน...</p>
      </div>
    </div>
  );
}
