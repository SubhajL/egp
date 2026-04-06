"use client";

import { useQueryClient } from "@tanstack/react-query";
import { Bell, FileText, Search } from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { FormEvent, Suspense, startTransition, useEffect, useState } from "react";

import { ApiError, register } from "@/lib/api";
import { normalizeNextPath } from "@/lib/auth";
import { useMe } from "@/lib/hooks";

function SignupPageContent() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const queryClient = useQueryClient();
  const { data: currentSession, isLoading: sessionLoading } = useMe();
  const nextPath = normalizeNextPath(searchParams.get("next"));
  const [companyName, setCompanyName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    if (currentSession) {
      startTransition(() => {
        router.replace(nextPath);
      });
    }
  }, [currentSession, nextPath, router]);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSubmitting(true);
    setErrorMessage(null);
    try {
      const session = await register({
        company_name: companyName.trim(),
        email: email.trim(),
        password,
      });
      queryClient.setQueryData(["me"], session);
      startTransition(() => {
        router.replace(nextPath);
      });
    } catch (error) {
      if (error instanceof ApiError) {
        setErrorMessage(error.detail);
      } else if (error instanceof Error) {
        setErrorMessage(error.message);
      } else {
        setErrorMessage("สมัครใช้งานไม่สำเร็จ");
      }
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="flex min-h-screen">
      <div className="hidden w-3/5 flex-col justify-between bg-gradient-to-br from-[oklch(0.55_0.18_275)] to-[oklch(0.45_0.18_275)] p-12 lg:flex">
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

        <div className="space-y-3">
          <div className="flex items-center gap-2 rounded-xl bg-white/10 px-4 py-3">
            <span className="text-sm font-semibold text-white">ทดลองใช้ฟรี 7 วัน</span>
            <span className="ml-auto text-xs text-white/60">ไม่ต้องใช้บัตรเครดิต</span>
          </div>
          <p className="text-sm text-white/40">
            © 2569 e-GP Intelligence Platform สงวนลิขสิทธิ์
          </p>
        </div>
      </div>

      <div className="flex w-full items-center justify-center bg-[var(--bg-surface)] px-8 lg:w-2/5">
        <div className="w-full max-w-[420px] space-y-6">
          <div>
            <h1 className="text-2xl font-bold text-[var(--text-primary)]">
              ทดลองใช้งานฟรี 7 วัน
            </h1>
            <p className="mt-1 text-sm text-[var(--text-muted)]">
              สร้างบัญชีใหม่และเริ่มใช้งานได้ทันทีโดยไม่ต้องรอแอดมินสร้างผู้ใช้
            </p>
          </div>

          {errorMessage ? (
            <div className="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
              {errorMessage}
            </div>
          ) : null}

          <form className="space-y-4" onSubmit={handleSubmit}>
            <div className="space-y-2">
              <label htmlFor="companyName" className="text-sm font-medium text-[var(--text-primary)]">
                ชื่อบริษัท / องค์กร
              </label>
              <input
                id="companyName"
                value={companyName}
                onChange={(event) => setCompanyName(event.target.value)}
                autoComplete="organization"
                placeholder="บริษัท ตัวอย่าง จำกัด"
                required
                className="h-12 w-full rounded-xl border border-[var(--border-default)] bg-[var(--bg-surface)] px-4 text-sm focus:border-primary focus:outline-none focus:ring-2 focus:ring-primary/20"
              />
            </div>

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

            <div className="space-y-2">
              <label htmlFor="password" className="text-sm font-medium text-[var(--text-primary)]">
                รหัสผ่าน
              </label>
              <input
                id="password"
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                type="password"
                autoComplete="new-password"
                placeholder="อย่างน้อย 12 ตัวอักษร"
                minLength={12}
                required
                className="h-12 w-full rounded-xl border border-[var(--border-default)] bg-[var(--bg-surface)] px-4 text-sm focus:border-primary focus:outline-none focus:ring-2 focus:ring-primary/20"
              />
            </div>

            <button
              type="submit"
              disabled={submitting || sessionLoading}
              className="h-12 w-full rounded-xl bg-primary text-sm font-bold text-white hover:bg-primary-hover disabled:cursor-not-allowed disabled:opacity-60"
            >
              {submitting ? "กำลังสร้างบัญชี..." : "เริ่มทดลองใช้งานฟรี"}
            </button>
          </form>

          <p className="text-center text-xs text-[var(--text-muted)]">
            การสมัครใช้งานถือว่าคุณยอมรับ{" "}
            <span className="font-medium text-[var(--text-primary)]">ข้อกำหนดการใช้งาน</span>
            {" "}และ{" "}
            <span className="font-medium text-[var(--text-primary)]">นโยบายความเป็นส่วนตัว</span>
          </p>

          <p className="text-center text-sm text-[var(--text-muted)]">
            มีบัญชีอยู่แล้ว?{" "}
            <Link href="/login" className="font-semibold text-primary">
              เข้าสู่ระบบ
            </Link>
          </p>
        </div>
      </div>
    </div>
  );
}

export default function SignupPage() {
  return (
    <Suspense fallback={<div className="min-h-screen bg-[var(--bg-surface)]" />}>
      <SignupPageContent />
    </Suspense>
  );
}
