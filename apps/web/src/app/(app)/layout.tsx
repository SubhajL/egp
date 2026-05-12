"use client";

import type { ReactNode } from "react";
import { startTransition, useEffect } from "react";
import { usePathname, useRouter } from "next/navigation";

import { AppShell } from "@/components/layout/app-shell";
import { ApiError } from "@/lib/api";
import { buildCurrentPath } from "@/lib/auth";
import { hasAdminAccessRole, isAdminOnlyPath } from "@/lib/authorization";
import { useMe } from "@/lib/hooks";

export default function AppLayout({ children }: { children: ReactNode }) {
  const router = useRouter();
  const pathname = usePathname() ?? "/dashboard";
  const { data: currentSession, error, isLoading } = useMe();
  const currentPath = buildCurrentPath(pathname);
  const isUnauthorized = error instanceof ApiError && error.status === 401;

  useEffect(() => {
    if (isLoading || !isUnauthorized) {
      return;
    }
    startTransition(() => {
      router.replace(`/login?next=${encodeURIComponent(currentPath)}`);
    });
  }, [currentPath, isLoading, isUnauthorized, router]);

  useEffect(() => {
    if (
      isLoading ||
      isUnauthorized ||
      !currentSession ||
      pathname.startsWith("/billing")
    ) {
      return;
    }
    if (currentSession.requires_billing_update) {
      startTransition(() => {
        router.replace("/billing?notice=payment_overdue");
      });
    }
  }, [currentSession, isLoading, isUnauthorized, pathname, router]);

  if (isLoading || isUnauthorized) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-[var(--bg-page)] px-6">
        <div className="w-full max-w-md rounded-3xl border border-[var(--border-default)] bg-[var(--bg-surface)] px-6 py-8 text-center shadow-sm">
          <p className="text-sm font-medium text-[var(--text-secondary)]">กำลังตรวจสอบสิทธิ์การใช้งาน...</p>
        </div>
      </div>
    );
  }

  if (!currentSession && error) {
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

  if (isAdminOnlyPath(pathname) && !hasAdminAccessRole(currentSession.user.role)) {
    return (
      <AppShell>
        <div className="flex min-h-[60vh] items-center justify-center">
          <div className="w-full max-w-2xl rounded-3xl border border-amber-200 bg-amber-50 px-8 py-10 text-center shadow-sm">
            <p className="text-xs font-semibold uppercase tracking-[0.18em] text-amber-700">
              Restricted Area
            </p>
            <h1 className="mt-3 text-3xl font-bold text-amber-950">เฉพาะผู้ดูแลระบบ</h1>
            <p className="mt-4 text-sm leading-7 text-amber-900">
              ส่วนบิล การชำระเงิน และแอดมิน ใช้งานได้เฉพาะ owner, admin, หรือ support
              เท่านั้น
            </p>
          </div>
        </div>
      </AppShell>
    );
  }

  return <AppShell>{children}</AppShell>;
}
