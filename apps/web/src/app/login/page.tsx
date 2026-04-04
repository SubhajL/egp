import { Search, FileText, Bell } from "lucide-react";

export default function LoginPage() {
  return (
    <div className="flex min-h-screen">
      {/* Left Panel — Indigo Branding */}
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
                ติดตามประกาศจัดซื้อจัดจ้างจาก e-GP แบบ Real-time ไม่พลาดทุกโครงการ
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

      {/* Right Panel — Login Form */}
      <div className="flex w-full items-center justify-center bg-[var(--bg-surface)] px-8 lg:w-2/5">
        <div className="w-full max-w-[400px] space-y-6">
          <div>
            <h1 className="text-2xl font-bold text-[var(--text-primary)]">เข้าสู่ระบบ</h1>
            <p className="mt-1 text-sm text-[var(--text-muted)]">
              เข้าสู่ระบบเพื่อเริ่มติดตามโครงการ
            </p>
          </div>

          <div className="space-y-4">
            <div className="space-y-2">
              <label htmlFor="email" className="text-sm font-medium text-[var(--text-primary)]">
                อีเมล
              </label>
              <input
                id="email"
                type="email"
                placeholder="name@company.com"
                className="h-12 w-full rounded-xl border border-[var(--border-default)] bg-[var(--bg-surface)] px-4 text-sm focus:border-primary focus:outline-none focus:ring-2 focus:ring-primary/20"
              />
            </div>
            <div className="space-y-2">
              <label htmlFor="password" className="text-sm font-medium text-[var(--text-primary)]">
                รหัสผ่าน
              </label>
              <input
                id="password"
                type="password"
                placeholder="••••••••"
                className="h-12 w-full rounded-xl border border-[var(--border-default)] bg-[var(--bg-surface)] px-4 text-sm focus:border-primary focus:outline-none focus:ring-2 focus:ring-primary/20"
              />
            </div>

            <div className="flex items-center justify-between">
              <label className="flex items-center gap-2 text-sm text-[var(--text-secondary)]">
                <input type="checkbox" className="size-4 rounded border-[var(--border-default)]" />
                จดจำอุปกรณ์นี้
              </label>
              <a href="#" className="text-sm font-medium text-primary hover:text-primary-hover">
                ลืมรหัสผ่าน?
              </a>
            </div>

            <button
              type="button"
              className="h-12 w-full rounded-xl bg-primary text-sm font-bold text-white hover:bg-primary-hover"
            >
              เข้าสู่ระบบ →
            </button>
          </div>

          <div className="relative">
            <div className="absolute inset-0 flex items-center">
              <div className="w-full border-t border-[var(--border-default)]" />
            </div>
            <div className="relative flex justify-center text-xs">
              <span className="bg-[var(--bg-surface)] px-4 text-[var(--text-muted)]">หรือ</span>
            </div>
          </div>

          <div className="grid grid-cols-2 gap-3">
            <button
              type="button"
              className="flex h-11 items-center justify-center gap-2 rounded-xl border border-[var(--border-default)] text-sm font-medium text-[var(--text-secondary)] hover:bg-[var(--bg-surface-hover)]"
            >
              Google
            </button>
            <button
              type="button"
              className="flex h-11 items-center justify-center gap-2 rounded-xl border border-[var(--border-default)] text-sm font-medium text-[var(--text-secondary)] hover:bg-[var(--bg-surface-hover)]"
            >
              Microsoft
            </button>
          </div>

          <p className="text-center text-sm text-[var(--text-muted)]">
            ยังไม่มีบัญชี?{" "}
            <a href="#" className="font-medium text-primary hover:text-primary-hover">
              ติดต่อผู้ดูแลระบบ
            </a>
          </p>
        </div>
      </div>
    </div>
  );
}
