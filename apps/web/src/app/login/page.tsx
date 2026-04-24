"use client";

import { useQueryClient } from "@tanstack/react-query";
import { Bell, FileText, Search } from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { FormEvent, Suspense, startTransition, useEffect, useMemo, useState } from "react";

import { ApiError, localizeApiError, login } from "@/lib/api";
import { normalizeNextPath } from "@/lib/auth";
import { useMe } from "@/lib/hooks";

function normalizeLoginErrorMessage(error: ApiError): string {
  if (error.code === "workspace_slug_required") {
    return "อีเมลนี้ถูกใช้ในหลาย workspace กรุณาระบุ Workspace slug เพื่อเข้าสู่ระบบ";
  }
  if (error.code === "mfa_code_required") {
    return "บัญชีนี้เปิดใช้ MFA กรุณากรอกรหัส 6 หลักจากแอปยืนยันตัวตน";
  }
  if (error.code === "invalid_mfa_code") {
    return "รหัส MFA ไม่ถูกต้อง กรุณาลองอีกครั้ง";
  }
  if (error.code === "invalid_credentials") {
    return "อีเมลหรือรหัสผ่านไม่ถูกต้อง";
  }
  return localizeApiError(error, "เข้าสู่ระบบไม่สำเร็จ กรุณาลองใหม่อีกครั้ง");
}

function LoginPageContent() {
  const router = useRouter();
  const queryClient = useQueryClient();
  const searchParams = useSearchParams();
  const nextPath = useMemo(
    () => normalizeNextPath(searchParams.get("next")),
    [searchParams],
  );
  const { data: currentSession, isLoading: sessionLoading } = useMe();
  const prefilledEmail = searchParams.get("email")?.trim() ?? "";
  const [email, setEmail] = useState(prefilledEmail);
  const [password, setPassword] = useState("");
  const [tenantSlug, setTenantSlug] = useState("");
  const [mfaCode, setMfaCode] = useState("");
  const [requiresMfa, setRequiresMfa] = useState(false);
  const [requiresWorkspaceSlug, setRequiresWorkspaceSlug] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    setEmail(prefilledEmail);
  }, [prefilledEmail]);

  useEffect(() => {
    if (currentSession) {
      const destination = currentSession.requires_billing_update
        ? "/billing?notice=payment_overdue"
        : nextPath;
      startTransition(() => {
        router.replace(destination);
      });
    }
  }, [currentSession, nextPath, router]);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSubmitting(true);
    setErrorMessage(null);
    try {
      const currentSession = await login({
        tenant_slug: requiresWorkspaceSlug ? tenantSlug.trim() || undefined : undefined,
        email: email.trim(),
        password,
        mfa_code: requiresMfa ? mfaCode.trim() || undefined : undefined,
      });
      queryClient.setQueryData(["me"], currentSession);
      if (currentSession.requires_billing_update) {
        window.location.assign("/billing?notice=payment_overdue");
        return;
      }
      window.location.assign(nextPath);
    } catch (error) {
      if (error instanceof ApiError) {
        if (error.code === "registration_required") {
          const params = new URLSearchParams();
          params.set("email", email.trim());
          params.set("notice", "registration_required");
          if (nextPath) {
            params.set("next", nextPath);
          }
          startTransition(() => {
            router.replace(`/signup?${params.toString()}`);
          });
          return;
        }
        if (error.code === "workspace_slug_required") {
          setRequiresWorkspaceSlug(true);
        }
        if (error.code === "mfa_code_required") {
          setRequiresMfa(true);
        }
        setErrorMessage(normalizeLoginErrorMessage(error));
      } else {
        setErrorMessage(localizeApiError(error, "เข้าสู่ระบบไม่สำเร็จ"));
      }
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="flex min-h-screen">
      <div className="hidden w-3/5 flex-col justify-between bg-gradient-to-br from-[#4F46E5] to-[#3730A3] p-12 lg:flex">
        <div>
          <div className="flex items-center gap-3">
            <div className="flex size-10 items-center justify-center rounded-xl bg-white/20">
              <Search className="size-6 text-white" />
            </div>
            <span className="text-2xl font-bold uppercase tracking-wider text-white">
              e-GP Intelligence Platform
            </span>
          </div>
          <p className="mt-2 text-lg text-white/70">
            ระบบติดตามการจัดซื้อจัดจ้างภาครัฐอัจฉริยะ
          </p>
        </div>

        <div className="space-y-8">
          <div className="flex items-start gap-4">
            <div className="flex size-10 shrink-0 items-center justify-center rounded-xl bg-white/10">
              <Search className="size-5 text-white" />
            </div>
            <div>
              <h3 className="font-semibold text-white">ค้นพบโครงการใหม่อัตโนมัติ</h3>
              <p className="mt-1 text-sm text-white/60">
                ติดตามประกาศจัดซื้อจัดจ้างจาก e-GP แบบ real-time ไม่พลาดทุกโครงการ
              </p>
            </div>
          </div>
          <div className="flex items-start gap-4">
            <div className="flex size-10 shrink-0 items-center justify-center rounded-xl bg-white/10">
              <FileText className="size-5 text-white" />
            </div>
            <div>
              <h3 className="font-semibold text-white">เปรียบเทียบเอกสาร TOR</h3>
              <p className="mt-1 text-sm text-white/60">
                ตรวจจับการเปลี่ยนแปลงระหว่างร่างและฉบับสุดท้ายอัตโนมัติ
              </p>
            </div>
          </div>
          <div className="flex items-start gap-4">
            <div className="flex size-10 shrink-0 items-center justify-center rounded-xl bg-white/10">
              <Bell className="size-5 text-white" />
            </div>
            <div>
              <h3 className="font-semibold text-white">แจ้งเตือนอัตโนมัติ</h3>
              <p className="mt-1 text-sm text-white/60">
                รับการแจ้งเตือนเมื่อพบผู้ชนะหรือ TOR เปลี่ยนแปลง
              </p>
            </div>
          </div>
        </div>

        <p className="text-sm text-white/40">
          © 2569 e-GP Intelligence Platform สงวนลิขสิทธิ์
        </p>
      </div>

      <div className="flex w-full items-center justify-center bg-[var(--bg-surface)] px-8 lg:w-2/5">
        <div className="w-full max-w-[420px] space-y-6">
          <div>
            <h1 className="text-2xl font-bold text-[var(--text-primary)]">เข้าสู่ระบบ</h1>
            <p className="mt-1 text-sm text-[var(--text-muted)]">
              ระบุอีเมลและรหัสผ่านเพื่อเข้าสู่ระบบบัญชีของคุณ
            </p>
          </div>

          {errorMessage ? (
            <div className="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
              {errorMessage}
            </div>
          ) : null}

          <form className="space-y-4" onSubmit={handleSubmit}>
            <div className="space-y-2">
              <label htmlFor="email" className="text-sm font-medium text-[var(--text-primary)]">
                อีเมล
              </label>
              <input
                id="email"
                value={email}
                onChange={(event) => setEmail(event.target.value)}
                type="email"
                autoComplete="email"
                placeholder="name@company.com"
                required
                className="h-12 w-full rounded-xl border border-[var(--border-default)] bg-[var(--bg-surface)] px-4 text-sm focus:border-primary focus:outline-none focus:ring-2 focus:ring-primary/20"
              />
            </div>

            {requiresWorkspaceSlug ? (
              <div className="space-y-2">
                <label htmlFor="tenantSlug" className="text-sm font-medium text-[var(--text-primary)]">
                  Workspace slug
                </label>
                <input
                  id="tenantSlug"
                  value={tenantSlug}
                  onChange={(event) => setTenantSlug(event.target.value)}
                  autoComplete="organization"
                  placeholder="example-tenant"
                  required
                  className="h-12 w-full rounded-xl border border-[var(--border-default)] bg-[var(--bg-surface)] px-4 text-sm focus:border-primary focus:outline-none focus:ring-2 focus:ring-primary/20"
                />
              </div>
            ) : null}

            <div className="space-y-2">
              <label htmlFor="password" className="text-sm font-medium text-[var(--text-primary)]">
                รหัสผ่าน
              </label>
              <input
                id="password"
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                type="password"
                autoComplete="current-password"
                placeholder="••••••••••••"
                required
                className="h-12 w-full rounded-xl border border-[var(--border-default)] bg-[var(--bg-surface)] px-4 text-sm focus:border-primary focus:outline-none focus:ring-2 focus:ring-primary/20"
              />
            </div>

            {requiresMfa ? (
              <div className="space-y-2">
                <div className="flex items-center justify-between">
                  <label htmlFor="mfaCode" className="text-sm font-medium text-[var(--text-primary)]">
                    MFA code
                  </label>
                  <Link href="/forgot-password" className="text-xs font-semibold text-primary">
                    ลืมรหัสผ่าน?
                  </Link>
                </div>
                <input
                  id="mfaCode"
                  value={mfaCode}
                  onChange={(event) => setMfaCode(event.target.value)}
                  inputMode="numeric"
                  autoComplete="one-time-code"
                  placeholder="กรอกรหัส 6 หลักจากแอปยืนยันตัวตน"
                  required
                  className="h-12 w-full rounded-xl border border-[var(--border-default)] bg-[var(--bg-surface)] px-4 text-sm focus:border-primary focus:outline-none focus:ring-2 focus:ring-primary/20"
                />
              </div>
            ) : (
              <div className="flex justify-end">
                <Link href="/forgot-password" className="text-xs font-semibold text-primary">
                  ลืมรหัสผ่าน?
                </Link>
              </div>
            )}

            <button
              type="submit"
              disabled={submitting || sessionLoading}
              className="h-12 w-full rounded-xl bg-primary text-sm font-bold text-white hover:bg-primary-hover disabled:cursor-not-allowed disabled:opacity-60"
            >
              {submitting ? "กำลังเข้าสู่ระบบ..." : "เข้าสู่ระบบ"}
            </button>
          </form>

          <div className="rounded-2xl border border-[var(--border-default)] bg-[var(--bg-surface)] px-4 py-3 text-xs text-[var(--text-muted)]">
            หากยังไม่มี workspace ของคุณ สามารถเริ่มทดลองใช้ฟรี 7 วันได้ทันที
          </div>

          <p className="text-center text-sm text-[var(--text-muted)]">
            ยังไม่มีบัญชี?{" "}
            <Link href="/signup" className="font-semibold text-primary">
              ทดลองใช้ฟรี 7 วัน
            </Link>
          </p>
        </div>
      </div>
    </div>
  );
}

export default function LoginPage() {
  return (
    <Suspense fallback={<div className="min-h-screen bg-[var(--bg-surface)]" />}>
      <LoginPageContent />
    </Suspense>
  );
}
