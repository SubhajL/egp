"use client";

import type { ReactNode } from "react";
import { startTransition, useEffect } from "react";
import { usePathname, useRouter } from "next/navigation";

import { AppShell } from "@/components/layout/app-shell";
import { ApiError } from "@/lib/api";
import { buildCurrentPath } from "@/lib/auth";
import { useMe } from "@/lib/hooks";

export default function AppLayout({ children }: { children: ReactNode }) {
  const router = useRouter();
  const pathname = usePathname() ?? "/dashboard";
  const { data: currentSession, error, isLoading } = useMe();
  const currentPath = buildCurrentPath(pathname);

  useEffect(() => {
    if (isLoading || currentSession) {
      return;
    }
    if (error instanceof ApiError && error.status === 401) {
      startTransition(() => {
        router.replace(`/login?next=${encodeURIComponent(currentPath)}`);
      });
    }
  }, [currentPath, currentSession, error, isLoading, router]);

  useEffect(() => {
    if (isLoading || !currentSession || pathname.startsWith("/billing")) {
      return;
    }
    if (currentSession.requires_billing_update) {
      startTransition(() => {
        router.replace("/billing?notice=payment_overdue");
      });
    }
  }, [currentSession, isLoading, pathname, router]);

  if (isLoading || (error instanceof ApiError && error.status === 401)) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-[var(--bg-page)] px-6">
        <div className="w-full max-w-md rounded-3xl border border-[var(--border-default)] bg-[var(--bg-surface)] px-6 py-8 text-center shadow-sm">
          <p className="text-sm font-medium text-[var(--text-secondary)]">กำลังตรวจสอบสิทธิ์การใช้งาน...</p>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-[var(--bg-page)] px-6">
        <div className="w-full max-w-lg rounded-3xl border border-red-200 bg-red-50 px-6 py-8 text-center text-sm text-red-700 shadow-sm">
          ไม่สามารถโหลดข้อมูลผู้ใช้งานได้ในขณะนี้ กรุณารีเฟรชหน้าอีกครั้ง
        </div>
      </div>
    );
  }

  if (!currentSession) {
    return null;
  }

  return <AppShell>{children}</AppShell>;
}
