"use client";

import type { Metadata } from "next";
import Link from "next/link";
import { useState, useRef } from "react";

/* ─────────────────────────────────────────────
   Types
───────────────────────────────────────────── */
type ServiceType = "proposal" | "poc" | "both";
type PackageType = "small" | "medium";
type RefType = "number" | "files";

interface FormState {
  services: ServiceType | "";
  refType: RefType;
  projectRef: string;
  companyName: string;
  contactName: string;
  email: string;
  phone: string;
  packageSize: PackageType | "";
  notes: string;
}

const INITIAL: FormState = {
  services: "",
  refType: "number",
  projectRef: "",
  companyName: "",
  contactName: "",
  email: "",
  phone: "",
  packageSize: "",
  notes: "",
};

/* ─────────────────────────────────────────────
   Small UI helpers
───────────────────────────────────────────── */
function FieldLabel({ children, required }: { children: React.ReactNode; required?: boolean }) {
  return (
    <label className="mb-1.5 block text-sm font-semibold text-[#0f172a]">
      {children}
      {required && <span className="ml-1 text-red-500">*</span>}
    </label>
  );
}

function Input({
  type = "text",
  value,
  onChange,
  placeholder,
  required,
}: {
  type?: string;
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
  required?: boolean;
}) {
  return (
    <input
      type={type}
      value={value}
      onChange={(e) => onChange(e.target.value)}
      placeholder={placeholder}
      required={required}
      className="w-full rounded-xl border border-[#e2e8f0] bg-white px-4 py-2.5 text-sm text-[#0f172a] placeholder-[#94a3b8] outline-none transition focus:border-[oklch(.55_.18_275)] focus:ring-2 focus:ring-[oklch(.55_.18_275)]/20"
    />
  );
}

function Textarea({
  value,
  onChange,
  placeholder,
  rows = 3,
}: {
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
  rows?: number;
}) {
  return (
    <textarea
      value={value}
      onChange={(e) => onChange(e.target.value)}
      placeholder={placeholder}
      rows={rows}
      className="w-full resize-none rounded-xl border border-[#e2e8f0] bg-white px-4 py-2.5 text-sm text-[#0f172a] placeholder-[#94a3b8] outline-none transition focus:border-[oklch(.55_.18_275)] focus:ring-2 focus:ring-[oklch(.55_.18_275)]/20"
    />
  );
}

function RadioCard<T extends string>({
  name,
  value,
  checked,
  onChange,
  title,
  description,
}: {
  name: string;
  value: T;
  checked: boolean;
  onChange: (v: T) => void;
  title: string;
  description?: string;
}) {
  return (
    <label
      className={`flex cursor-pointer gap-3 rounded-xl border p-4 transition ${
        checked
          ? "border-[oklch(.55_.18_275)] bg-[rgba(79,70,229,0.05)]"
          : "border-[#e2e8f0] hover:border-[#c7d2fe]"
      }`}
    >
      <input
        type="radio"
        name={name}
        value={value}
        checked={checked}
        onChange={() => onChange(value)}
        className="mt-0.5 accent-[oklch(.55_.18_275)]"
      />
      <div>
        <p className="text-sm font-semibold text-[#0f172a]">{title}</p>
        {description && <p className="mt-0.5 text-xs text-[#64748b]">{description}</p>}
      </div>
    </label>
  );
}

/* ─────────────────────────────────────────────
   Success state
───────────────────────────────────────────── */
function SuccessScreen() {
  return (
    <div className="flex min-h-screen items-center justify-center bg-[#FAFBFC] px-6">
      <div className="max-w-md text-center">
        <div className="mx-auto mb-6 flex h-20 w-20 items-center justify-center rounded-full bg-green-100 text-4xl">
          ✅
        </div>
        <h1 className="mb-3 text-2xl font-bold text-[#0f172a]">ส่งข้อมูลสำเร็จ!</h1>
        <p className="mb-8 text-[#475569]">
          ทีมงานได้รับข้อมูลของคุณแล้ว และจะติดต่อกลับภายใน 1 วันทำการ
          พร้อมใบเสนอราคาและรายละเอียดการดำเนินงาน
        </p>
        <Link
          href="/"
          className="inline-flex rounded-full bg-[oklch(.55_.18_275)] px-6 py-2.5 text-sm font-bold text-white transition-colors hover:bg-[oklch(.48_.2_275)]"
        >
          กลับหน้าหลัก
        </Link>
      </div>
    </div>
  );
}

/* ─────────────────────────────────────────────
   Main page
───────────────────────────────────────────── */
export default function InquiryPage() {
  const [form, setForm] = useState<FormState>(INITIAL);
  const [files, setFiles] = useState<File[]>([]);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [submitted, setSubmitted] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);

  const set = <K extends keyof FormState>(key: K, value: FormState[K]) =>
    setForm((f) => ({ ...f, [key]: value }));

  const handleFiles = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files) setFiles(Array.from(e.target.files));
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      const fd = new FormData();
      (Object.entries(form) as [string, string][]).forEach(([k, v]) => fd.append(k, v));
      files.forEach((f) => fd.append("files", f));
      const res = await fetch("/api/inquiry", { method: "POST", body: fd });
      if (!res.ok) throw new Error("server error");
      setSubmitted(true);
    } catch {
      setError("เกิดข้อผิดพลาด กรุณาลองใหม่อีกครั้ง หรือติดต่อทีมงานโดยตรง");
    } finally {
      setSubmitting(false);
    }
  };

  if (submitted) return <SuccessScreen />;

  return (
    <div className="min-h-screen bg-[#FAFBFC]">

      {/* ── Navbar ── */}
      <header className="border-b border-[#e2e8f0] bg-white/80 backdrop-blur-md">
        <div className="mx-auto flex max-w-4xl items-center justify-between px-6 py-3">
          <Link href="/" className="flex items-center gap-2.5">
            <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-[oklch(.55_.18_275)]">
              <svg className="h-4 w-4 text-white" viewBox="0 0 24 24" fill="none" aria-hidden="true">
                <path
                  d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z"
                  stroke="currentColor"
                  strokeWidth="2"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                />
              </svg>
            </span>
            <span className="text-sm font-bold tracking-tight text-[#0f172a]">e-GP Intelligence</span>
          </Link>
          <Link
            href="/#services"
            className="text-sm font-medium text-[#475569] transition-colors hover:text-[oklch(.55_.18_275)]"
          >
            ← ข้อมูลบริการ
          </Link>
        </div>
      </header>

      {/* ── Page content ── */}
      <main className="mx-auto max-w-2xl px-6 py-12">

        {/* Page header */}
        <div className="mb-10 text-center">
          <h1 className="text-3xl font-extrabold text-[#0f172a]">ยื่นข้อมูลโครงการ</h1>
          <p className="mt-2 text-[#475569]">
            กรอกข้อมูลด้านล่าง ทีมงานจะติดต่อกลับพร้อมใบเสนอราคาภายใน 1 วันทำการ
          </p>
        </div>

        <form onSubmit={handleSubmit} className="space-y-8">

          {/* ── Section 1: บริการที่ต้องการ ── */}
          <div className="rounded-2xl border border-[#e2e8f0] bg-white p-6 shadow-[0_4px_20px_-2px_rgba(0,0,0,0.05)]">
            <h2 className="mb-4 text-base font-bold text-[#0f172a]">
              1. บริการที่ต้องการ <span className="text-red-500">*</span>
            </h2>
            <div className="grid gap-3 sm:grid-cols-3">
              {([
                { value: "proposal", title: "จัดทำข้อเสนอ", description: "เอกสารข้อเสนอ + แผนภาพ" },
                { value: "poc", title: "พัฒนา POC", description: "ระบบต้นแบบสำหรับสาธิต" },
                { value: "both", title: "ทั้งสองบริการ", description: "ข้อเสนอ + POC คู่กัน" },
              ] as const).map((opt) => (
                <RadioCard
                  key={opt.value}
                  name="services"
                  value={opt.value}
                  checked={form.services === opt.value}
                  onChange={(v) => set("services", v)}
                  title={opt.title}
                  description={opt.description}
                />
              ))}
            </div>
          </div>

          {/* ── Section 2: ข้อมูลโครงการ ── */}
          <div className="rounded-2xl border border-[#e2e8f0] bg-white p-6 shadow-[0_4px_20px_-2px_rgba(0,0,0,0.05)]">
            <h2 className="mb-4 text-base font-bold text-[#0f172a]">
              2. ข้อมูลโครงการ <span className="text-red-500">*</span>
            </h2>

            {/* Ref type toggle */}
            <div className="mb-4 flex gap-3">
              {([
                { value: "number", label: "หมายเลขอ้างอิง e-GP" },
                { value: "files", label: "แนบไฟล์เอกสาร" },
              ] as const).map((opt) => (
                <button
                  key={opt.value}
                  type="button"
                  onClick={() => set("refType", opt.value)}
                  className={`rounded-full px-4 py-1.5 text-xs font-semibold transition ${
                    form.refType === opt.value
                      ? "bg-[oklch(.55_.18_275)] text-white"
                      : "border border-[#e2e8f0] text-[#475569] hover:border-[#c7d2fe]"
                  }`}
                >
                  {opt.label}
                </button>
              ))}
            </div>

            {form.refType === "number" ? (
              <div>
                <FieldLabel>หมายเลขอ้างอิงโครงการในระบบ e-GP</FieldLabel>
                <Input
                  value={form.projectRef}
                  onChange={(v) => set("projectRef", v)}
                  placeholder="เช่น 66047000000"
                />
                <p className="mt-1.5 text-xs text-[#94a3b8]">
                  พบได้ใน URL ของโครงการที่ gprocurement.go.th
                </p>
              </div>
            ) : (
              <div>
                <FieldLabel>อัปโหลด TOR, ประกาศจัดซื้อจัดจ้าง หรือเอกสารที่เกี่ยวข้อง</FieldLabel>
                <div
                  onClick={() => fileRef.current?.click()}
                  className="flex cursor-pointer flex-col items-center justify-center gap-2 rounded-xl border-2 border-dashed border-[#c7d2fe] bg-[rgba(79,70,229,0.03)] px-6 py-8 text-center transition hover:border-[oklch(.55_.18_275)] hover:bg-[rgba(79,70,229,0.06)]"
                >
                  <span className="text-2xl">📎</span>
                  <p className="text-sm font-semibold text-[#4338CA]">คลิกเพื่อเลือกไฟล์</p>
                  <p className="text-xs text-[#94a3b8]">PDF, Word, Excel ขนาดไม่เกิน 20 MB ต่อไฟล์</p>
                  <input
                    ref={fileRef}
                    type="file"
                    multiple
                    accept=".pdf,.doc,.docx,.xls,.xlsx"
                    onChange={handleFiles}
                    className="hidden"
                  />
                </div>
                {files.length > 0 && (
                  <ul className="mt-3 space-y-1">
                    {files.map((f) => (
                      <li key={f.name} className="flex items-center gap-2 text-xs text-[#475569]">
                        <span className="text-green-500">✓</span>
                        {f.name}
                        <span className="text-[#94a3b8]">
                          ({(f.size / 1024 / 1024).toFixed(1)} MB)
                        </span>
                      </li>
                    ))}
                  </ul>
                )}
                <div className="mt-4">
                  <FieldLabel>ชื่อโครงการ / รายละเอียดเพิ่มเติม</FieldLabel>
                  <Textarea
                    value={form.projectRef}
                    onChange={(v) => set("projectRef", v)}
                    placeholder="ชื่อโครงการ วงเงินโดยประมาณ และข้อมูลอื่นที่เป็นประโยชน์"
                  />
                </div>
              </div>
            )}
          </div>

          {/* ── Section 3: แพ็กเกจ ── */}
          <div className="rounded-2xl border border-[#e2e8f0] bg-white p-6 shadow-[0_4px_20px_-2px_rgba(0,0,0,0.05)]">
            <h2 className="mb-1 text-base font-bold text-[#0f172a]">
              3. ขนาดแพ็กเกจ <span className="text-red-500">*</span>
            </h2>
            <p className="mb-4 text-xs text-[#64748b]">เลือกตามวงเงินของโครงการที่จะยื่นประกวดราคา</p>
            <div className="grid gap-3 sm:grid-cols-2">
              {([
                {
                  value: "small",
                  title: "S — Small  (วงเงิน < 5 ล้านบาท)",
                  description: "ข้อเสนอ ฿50,000 · POC ฿50,000 · ส่งมอบ 7 วันทำการ",
                },
                {
                  value: "medium",
                  title: "M — Medium  (วงเงิน < 10 ล้านบาท)",
                  description: "ข้อเสนอ ฿100,000 · POC ฿100,000 · ส่งมอบ 10 วันทำการ",
                },
              ] as const).map((opt) => (
                <RadioCard
                  key={opt.value}
                  name="packageSize"
                  value={opt.value}
                  checked={form.packageSize === opt.value}
                  onChange={(v) => set("packageSize", v)}
                  title={opt.title}
                  description={opt.description}
                />
              ))}
            </div>
          </div>

          {/* ── Section 4: ข้อมูลผู้ติดต่อ ── */}
          <div className="rounded-2xl border border-[#e2e8f0] bg-white p-6 shadow-[0_4px_20px_-2px_rgba(0,0,0,0.05)]">
            <h2 className="mb-4 text-base font-bold text-[#0f172a]">
              4. ข้อมูลบริษัทและผู้ติดต่อ
            </h2>
            <div className="grid gap-4 sm:grid-cols-2">
              <div className="sm:col-span-2">
                <FieldLabel required>ชื่อบริษัท / หน่วยงาน</FieldLabel>
                <Input
                  value={form.companyName}
                  onChange={(v) => set("companyName", v)}
                  placeholder="บริษัท ตัวอย่าง จำกัด"
                  required
                />
              </div>
              <div>
                <FieldLabel required>ชื่อผู้ติดต่อ</FieldLabel>
                <Input
                  value={form.contactName}
                  onChange={(v) => set("contactName", v)}
                  placeholder="ชื่อ นามสกุล"
                  required
                />
              </div>
              <div>
                <FieldLabel>เบอร์โทรศัพท์</FieldLabel>
                <Input
                  type="tel"
                  value={form.phone}
                  onChange={(v) => set("phone", v)}
                  placeholder="0812345678"
                />
              </div>
              <div className="sm:col-span-2">
                <FieldLabel required>อีเมล (รับใบเสนอราคาและอัปเดต)</FieldLabel>
                <Input
                  type="email"
                  value={form.email}
                  onChange={(v) => set("email", v)}
                  placeholder="you@company.com"
                  required
                />
              </div>
            </div>
          </div>

          {/* ── Section 5: หมายเหตุ ── */}
          <div className="rounded-2xl border border-[#e2e8f0] bg-white p-6 shadow-[0_4px_20px_-2px_rgba(0,0,0,0.05)]">
            <h2 className="mb-4 text-base font-bold text-[#0f172a]">5. ข้อมูลเพิ่มเติม (ถ้ามี)</h2>
            <Textarea
              value={form.notes}
              onChange={(v) => set("notes", v)}
              placeholder="กำหนดส่งข้อเสนอ, ข้อกำหนดพิเศษ, หรือข้อมูลอื่น ๆ ที่เป็นประโยชน์"
              rows={4}
            />
          </div>

          {/* ── Terms notice ── */}
          <div className="rounded-xl border border-amber-200 bg-amber-50 px-5 py-4 text-xs text-amber-800">
            การส่งข้อมูลนี้ไม่ถือเป็นการผูกมัดทางกฎหมาย ทีมงานจะส่งใบเสนอราคาอย่างเป็นทางการก่อนเริ่มงานทุกครั้ง
            งานจะเริ่มต้นเมื่อได้รับมัดจำ 50% เท่านั้น
          </div>

          {/* ── Error ── */}
          {error && (
            <p className="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
              {error}
            </p>
          )}

          {/* ── Submit ── */}
          <button
            type="submit"
            disabled={submitting || !form.services || !form.packageSize || !form.email || !form.companyName || !form.contactName}
            className="w-full rounded-full bg-[oklch(.55_.18_275)] py-3 text-sm font-bold text-white shadow-lg transition-all hover:bg-[oklch(.48_.2_275)] hover:scale-[1.01] disabled:cursor-not-allowed disabled:opacity-50"
          >
            {submitting ? "กำลังส่ง…" : "ส่งข้อมูลและรับใบเสนอราคา →"}
          </button>

        </form>
      </main>
    </div>
  );
}
