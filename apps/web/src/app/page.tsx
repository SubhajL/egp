import type { Metadata } from "next";
import Link from "next/link";

/* ─────────────────────────────────────────────
   Site base URL — set NEXT_PUBLIC_SITE_URL in
   your environment; falls back to placeholder.
───────────────────────────────────────────── */
const BASE_URL = process.env.NEXT_PUBLIC_SITE_URL ?? "https://egp.example.com";

const OG_DESCRIPTION =
  "ติดตามการประกวดราคาภาครัฐ อัตโนมัติ — รับแจ้งเตือน TOR และโครงการใหม่ก่อนใคร";

/* ─────────────────────────────────────────────
   SEO / AEO metadata
───────────────────────────────────────────── */
export const metadata: Metadata = {
  metadataBase: new URL(BASE_URL),
  title: "e-GP Intelligence Platform — ติดตามการประกวดราคาภาครัฐ อัตโนมัติ",
  description:
    "แพลตฟอร์ม SaaS สำหรับติดตามโครงการจัดซื้อจัดจ้างภาครัฐจากระบบ e-GP ของกรมบัญชีกลาง รับแจ้งเตือนทันที ดูเอกสาร TOR และวิเคราะห์ข้อมูลอย่างครบถ้วน",
  keywords: [
    "e-GP",
    "ประกวดราคา",
    "จัดซื้อจัดจ้างภาครัฐ",
    "TOR",
    "gprocurement",
    "กรมบัญชีกลาง",
    "แจ้งเตือนราคากลาง",
  ],
  alternates: {
    canonical: `${BASE_URL}/`,
    languages: { "th-TH": `${BASE_URL}/` },
  },
  openGraph: {
    type: "website",
    url: `${BASE_URL}/`,
    title: "e-GP Intelligence Platform",
    description: OG_DESCRIPTION,
    siteName: "e-GP Intelligence",
    locale: "th_TH",
    images: [
      {
        url: `${BASE_URL}/opengraph-image`,
        width: 1200,
        height: 630,
        alt: "e-GP Intelligence Platform — ติดตามการประกวดราคาภาครัฐ อัตโนมัติ",
      },
    ],
  },
  twitter: {
    card: "summary_large_image",
    title: "e-GP Intelligence Platform — ติดตามการประกวดราคาภาครัฐ อัตโนมัติ",
    description: OG_DESCRIPTION,
    images: [`${BASE_URL}/opengraph-image`],
  },
  robots: { index: true, follow: true },
};

/* ─────────────────────────────────────────────
   JSON-LD structured data
───────────────────────────────────────────── */
const jsonLd = {
  "@context": "https://schema.org",
  "@graph": [
    /* ── Organization ── */
    {
      "@type": "Organization",
      "@id": `${BASE_URL}/#organization`,
      name: "e-GP Intelligence Platform",
      url: BASE_URL,
      logo: {
        "@type": "ImageObject",
        url: `${BASE_URL}/opengraph-image`,
        width: 1200,
        height: 630,
      },
      description:
        "แพลตฟอร์ม SaaS สำหรับติดตามโครงการจัดซื้อจัดจ้างภาครัฐจากระบบ e-GP ของกรมบัญชีกลาง",
      inLanguage: "th-TH",
    },

    /* ── WebSite ── */
    {
      "@type": "WebSite",
      "@id": `${BASE_URL}/#website`,
      url: BASE_URL,
      name: "e-GP Intelligence Platform",
      description:
        "แพลตฟอร์มติดตามโครงการจัดซื้อจัดจ้างภาครัฐจากระบบ e-GP",
      publisher: { "@id": `${BASE_URL}/#organization` },
      inLanguage: "th-TH",
      potentialAction: {
        "@type": "SearchAction",
        target: {
          "@type": "EntryPoint",
          urlTemplate: `${BASE_URL}/projects?q={search_term_string}`,
        },
        "query-input": "required name=search_term_string",
      },
    },

    /* ── WebPage (root) ── */
    {
      "@type": "WebPage",
      "@id": `${BASE_URL}/#webpage`,
      url: `${BASE_URL}/`,
      name: "e-GP Intelligence Platform — ติดตามการประกวดราคาภาครัฐ อัตโนมัติ",
      isPartOf: { "@id": `${BASE_URL}/#website` },
      about: { "@id": `${BASE_URL}/#organization` },
      inLanguage: "th-TH",
      description:
        "แพลตฟอร์ม SaaS สำหรับติดตามโครงการจัดซื้อจัดจ้างภาครัฐจากระบบ e-GP ของกรมบัญชีกลาง รับแจ้งเตือนทันที ดูเอกสาร TOR และวิเคราะห์ข้อมูลอย่างครบถ้วน",
    },

    /* ── BreadcrumbList ── */
    {
      "@type": "BreadcrumbList",
      "@id": `${BASE_URL}/#breadcrumb`,
      itemListElement: [
        {
          "@type": "ListItem",
          position: 1,
          name: "หน้าแรก",
          item: `${BASE_URL}/`,
        },
      ],
    },

    /* ── SoftwareApplication ── */
    {
      "@type": "SoftwareApplication",
      "@id": `${BASE_URL}/#app`,
      name: "e-GP Intelligence Platform",
      applicationCategory: "BusinessApplication",
      operatingSystem: "Web",
      url: `${BASE_URL}/`,
      isPartOf: { "@id": `${BASE_URL}/#website` },
      description:
        "แพลตฟอร์มติดตามโครงการจัดซื้อจัดจ้างภาครัฐจากระบบ e-GP ของกรมบัญชีกลาง พร้อมแจ้งเตือน TOR และการวิเคราะห์ข้อมูล",
      offers: [
        {
          "@type": "Offer",
          name: "Free Trial",
          price: "0",
          priceCurrency: "THB",
          description: "ทดลองใช้ฟรี 7 วัน — 1 คำค้น",
          availability: "https://schema.org/InStock",
        },
        {
          "@type": "Offer",
          name: "One-Time Search Pack",
          price: "300",
          priceCurrency: "THB",
          description: "แพ็กเกจค้นหาครั้งเดียว 3 วัน — 1 คำค้น",
          availability: "https://schema.org/InStock",
        },
        {
          "@type": "Offer",
          name: "Monthly Membership",
          price: "1500",
          priceCurrency: "THB",
          description: "สมาชิกรายเดือน 1 เดือน — 5 คำค้น",
          availability: "https://schema.org/InStock",
        },
      ],
    },

    /* ── FAQPage ── */
    {
      "@type": "FAQPage",
      "@id": `${BASE_URL}/#faq`,
      mainEntity: [
        {
          "@type": "Question",
          name: "e-GP Intelligence Platform คืออะไร?",
          acceptedAnswer: {
            "@type": "Answer",
            text: "แพลตฟอร์มที่ดึงข้อมูลโครงการจัดซื้อจัดจ้างจากระบบ e-GP ของกรมบัญชีกลาง (gprocurement.go.th) โดยอัตโนมัติ พร้อมแจ้งเตือนเมื่อมีโครงการใหม่ตรงกับคำค้นของคุณ",
          },
        },
        {
          "@type": "Question",
          name: "ข้อมูลมาจากแหล่งไหน?",
          acceptedAnswer: {
            "@type": "Answer",
            text: "ข้อมูลทั้งหมดดึงตรงจากเว็บไซต์ gprocurement.go.th ซึ่งเป็นระบบ e-GP ที่ดำเนินการโดยกรมบัญชีกลาง กระทรวงการคลัง",
          },
        },
        {
          "@type": "Question",
          name: "การแจ้งเตือนทำงานอย่างไร?",
          acceptedAnswer: {
            "@type": "Answer",
            text: "สำหรับแพ็กเกจ One-Time Search Pack และ Monthly Membership ระบบจะส่งอีเมลทันทีเมื่อพบโครงการใหม่ที่ตรงกับคำค้นที่คุณตั้งไว้ ความล่าช้าโดยเฉลี่ยน้อยกว่า 1 นาทีหลังข้อมูลปรากฏบน e-GP",
          },
        },
        {
          "@type": "Question",
          name: "ทดลองใช้ฟรีได้นานแค่ไหน?",
          acceptedAnswer: {
            "@type": "Answer",
            text: "แพ็กเกจ Free Trial ใช้งานได้ฟรี 7 วัน รองรับ 1 คำค้น ต้องยืนยันอีเมลเท่านั้น ไม่ต้องชำระเงินใดๆ",
          },
        },
        {
          "@type": "Question",
          name: "ความแตกต่างระหว่าง One-Time Pack กับ Monthly Membership?",
          acceptedAnswer: {
            "@type": "Answer",
            text: "One-Time Search Pack (฿300) เหมาะสำหรับการค้นหาชั่วคราว 3 วัน 1 คำค้น Monthly Membership (฿1,500/เดือน) เหมาะสำหรับองค์กรที่ต้องการติดตามต่อเนื่อง รองรับ 5 คำค้นพร้อมฟีเจอร์ครบครัน",
          },
        },
        {
          "@type": "Question",
          name: "ชำระเงินด้วยวิธีใดได้บ้าง?",
          acceptedAnswer: {
            "@type": "Answer",
            text: "รองรับการชำระเงิน 2 วิธี: พร้อมเพย์ QR (สแกนจ่ายได้ทันที) และการโอนเงินผ่านธนาคาร ไม่รองรับบัตรเครดิต ระบบจะยืนยันและเปิดใช้งานแพ็กเกจภายใน 1 ชั่วโมงหลังได้รับการยืนยันการชำระเงิน",
          },
        },
        {
          "@type": "Question",
          name: "สามารถดูเอกสาร TOR ได้หรือไม่?",
          acceptedAnswer: {
            "@type": "Answer",
            text: "ได้ สำหรับแพ็กเกจ One-Time และ Monthly ระบบจะดาวน์โหลดและจัดเก็บเอกสาร TOR ทุกเวอร์ชัน พร้อม diff view เพื่อเปรียบเทียบการเปลี่ยนแปลงระหว่างเวอร์ชัน แพ็กเกจ Free Trial จะเห็นข้อมูลเมตาโครงการแต่ไม่รองรับการดาวน์โหลดเอกสาร",
          },
        },
      ],
    },
  ],
};

/* ─────────────────────────────────────────────
   Small reusable primitives (inline to keep the
   file self-contained; no extra component files)
───────────────────────────────────────────── */

function Badge({ children, color = "indigo" }: { children: React.ReactNode; color?: string }) {
  const colors: Record<string, string> = {
    indigo: "bg-[var(--badge-indigo-bg)] text-[var(--badge-indigo-text)]",
    /* light variant — use when the badge sits on a dark background */
    "indigo-light": "bg-indigo-400/20 text-indigo-200",
    teal: "bg-[var(--badge-teal-bg)] text-[var(--badge-teal-text)]",
    green: "bg-[var(--badge-green-bg)] text-[var(--badge-green-text)]",
    purple: "bg-[var(--badge-purple-bg)] text-[var(--badge-purple-text)]",
    amber: "bg-[var(--badge-amber-bg)] text-[var(--badge-amber-text)]",
  };
  return (
    <span
      className={`inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-xs font-semibold ${colors[color] ?? colors.indigo}`}
    >
      {children}
    </span>
  );
}

function CheckIcon() {
  return (
    <svg
      className="mt-0.5 h-4 w-4 shrink-0 text-[var(--color-success)]"
      viewBox="0 0 16 16"
      fill="none"
      aria-hidden="true"
    >
      <path
        d="M3 8l3.5 3.5L13 4.5"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

function ChevronDown() {
  return (
    <svg
      className="faq-chevron h-5 w-5 shrink-0 text-[var(--text-muted)] transition-transform duration-200"
      viewBox="0 0 20 20"
      fill="none"
      aria-hidden="true"
    >
      <path
        d="M5 7.5l5 5 5-5"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

/* ─────────────────────────────────────────────
   Landing page (Server Component)
───────────────────────────────────────────── */
export default function LandingPage() {
  return (
    <>
      {/* JSON-LD */}
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{ __html: JSON.stringify(jsonLd) }}
      />

      <div className="min-h-screen bg-[var(--bg-page)] font-[var(--font-sans)]">
        {/* ── NAVBAR ─────────────────────────────── */}
        <header className="sticky top-0 z-50 border-b border-[var(--border-default)] bg-white/80 backdrop-blur-md">
          <div className="mx-auto flex max-w-7xl items-center justify-between px-6 py-3">
            {/* Logo */}
            <Link href="/" className="flex items-center gap-2.5">
              <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-[var(--color-primary)]">
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
              <span className="text-sm font-bold tracking-tight text-[var(--text-primary)]">
                e-GP Intelligence
              </span>
            </Link>

            {/* Nav links */}
            <nav className="hidden items-center gap-6 md:flex" aria-label="Main navigation">
              {[
                { href: "#features", label: "ฟีเจอร์" },
                { href: "#services", label: "บริการ" },
                { href: "#pricing", label: "ราคา" },
                { href: "#faq", label: "คำถาม" },
              ].map((l) => (
                <a
                  key={l.href}
                  href={l.href}
                  className="text-sm font-medium text-[var(--text-secondary)] transition-colors hover:text-[var(--color-primary)]"
                >
                  {l.label}
                </a>
              ))}
            </nav>

            {/* CTAs */}
            <div className="flex items-center gap-2">
              <Link
                href="/login"
                className="hidden rounded-full px-4 py-1.5 text-sm font-medium text-[var(--text-secondary)] transition-colors hover:text-[var(--color-primary)] sm:inline-flex"
              >
                เข้าสู่ระบบ
              </Link>
              <Link
                href="/signup"
                className="rounded-full bg-[var(--color-primary)] px-4 py-1.5 text-sm font-semibold text-white transition-colors hover:bg-[var(--color-primary-hover)]"
              >
                ทดลองใช้ฟรี
              </Link>
            </div>
          </div>
        </header>

        {/* ── HERO ───────────────────────────────── */}
        <section
          aria-label="Hero"
          style={{ background: "linear-gradient(135deg, #0f0c29 0%, #302b63 55%, #24243e 100%)" }}
          className="relative overflow-hidden pb-24 pt-20"
        >
          {/* Grid overlay */}
          <div
            aria-hidden="true"
            className="pointer-events-none absolute inset-0 opacity-[0.04]"
            style={{
              backgroundImage:
                "linear-gradient(rgba(255,255,255,0.5) 1px, transparent 1px), linear-gradient(90deg, rgba(255,255,255,0.5) 1px, transparent 1px)",
              backgroundSize: "40px 40px",
            }}
          />
          {/* Glow orbs */}
          <div
            aria-hidden="true"
            className="pointer-events-none absolute -left-32 top-0 h-96 w-96 rounded-full"
            style={{ background: "radial-gradient(circle, rgba(99,102,241,0.35) 0%, transparent 70%)" }}
          />
          <div
            aria-hidden="true"
            className="pointer-events-none absolute -right-32 bottom-0 h-96 w-96 rounded-full"
            style={{ background: "radial-gradient(circle, rgba(139,92,246,0.3) 0%, transparent 70%)" }}
          />

          <div className="relative mx-auto max-w-7xl px-6">
            <div className="flex flex-col items-center gap-16 lg:flex-row lg:items-start lg:gap-12">
              {/* Left: copy */}
              <div className="flex-1 text-center lg:text-left">
                {/* Animated badge */}
                <div className="mb-6 inline-flex items-center gap-2 rounded-full border border-indigo-400/30 bg-indigo-500/10 px-4 py-1.5 text-xs font-semibold text-indigo-200">
                  <span className="relative flex h-2 w-2">
                    <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-indigo-400 opacity-75" />
                    <span className="relative inline-flex h-2 w-2 rounded-full bg-indigo-300" />
                  </span>
                  ข้อมูล e-GP อัปเดตแบบเรียลไทม์
                </div>

                <h1 className="mb-5 text-4xl font-extrabold leading-tight tracking-tight text-white sm:text-5xl lg:text-[3.5rem]">
                  ติดตามการประกวดราคา
                  <br />
                  <span
                    style={{
                      background: "linear-gradient(90deg, #a5b4fc 0%, #c4b5fd 100%)",
                      WebkitBackgroundClip: "text",
                      WebkitTextFillColor: "transparent",
                    }}
                  >
                    ภาครัฐ อัตโนมัติ
                  </span>
                </h1>

                <p className="mb-8 max-w-lg text-base leading-relaxed text-indigo-200/80">
                  รับแจ้งเตือนทันทีเมื่อมีโครงการจัดซื้อจัดจ้างใหม่จากระบบ e-GP ของกรมบัญชีกลาง
                  พร้อมเอกสาร TOR, วิเคราะห์ข้อมูล และ Dashboard ครบครัน
                </p>

                <div className="mb-12 flex flex-wrap justify-center gap-3 lg:justify-start">
                  <Link
                    href="/signup"
                    className="rounded-full bg-white px-6 py-2.5 text-sm font-bold text-indigo-700 shadow-lg transition-transform hover:scale-105 hover:bg-indigo-50"
                  >
                    เริ่มทดลองใช้ฟรี 7 วัน
                  </Link>
                  <a
                    href="#features"
                    className="rounded-full border border-indigo-400/40 px-6 py-2.5 text-sm font-semibold text-indigo-200 transition-colors hover:border-indigo-300/60 hover:text-white"
                  >
                    ดูฟีเจอร์ทั้งหมด →
                  </a>
                </div>

                {/* Stats strip */}
                <div className="flex flex-wrap justify-center gap-8 lg:justify-start">
                  {[
                    { value: "10,000+", label: "โครงการที่ติดตาม" },
                    { value: "24/7", label: "ทำงานตลอดเวลา" },
                    { value: "<1 นาที", label: "ความเร็วแจ้งเตือน" },
                  ].map((s) => (
                    <div key={s.value} className="text-center lg:text-left">
                      <div className="text-2xl font-extrabold text-white">{s.value}</div>
                      <div className="text-xs text-indigo-300/70">{s.label}</div>
                    </div>
                  ))}
                </div>
              </div>

              {/* Right: mock dashboard card */}
              <div className="w-full max-w-lg flex-shrink-0 lg:max-w-md xl:max-w-lg">
                <div className="overflow-hidden rounded-2xl border border-white/10 bg-white/5 shadow-2xl backdrop-blur-sm">
                  {/* Window chrome */}
                  <div className="flex items-center gap-1.5 border-b border-white/10 bg-white/5 px-4 py-3">
                    {["bg-red-400", "bg-yellow-400", "bg-green-400"].map((c) => (
                      <span key={c} className={`h-2.5 w-2.5 rounded-full ${c}`} />
                    ))}
                    <span className="ml-auto text-xs text-white/30">e-GP Intelligence — Dashboard</span>
                  </div>
                  {/* Mock content */}
                  <div className="space-y-3 p-4">
                    {/* Header row */}
                    <div className="flex items-center justify-between">
                      <span className="text-xs font-semibold text-white/70">โครงการล่าสุด</span>
                      <span className="rounded-full bg-green-500/20 px-2 py-0.5 text-[10px] font-semibold text-green-300">
                        อัปเดตแล้ว
                      </span>
                    </div>
                    {/* Mock project rows */}
                    {[
                      {
                        dept: "กรมทางหลวง",
                        title: "จ้างก่อสร้างถนน สาย ก.1 ตอน 3",
                        budget: "฿12,500,000",
                        status: "ประกาศ",
                        statusColor: "text-indigo-300",
                      },
                      {
                        dept: "มหาวิทยาลัยเชียงใหม่",
                        title: "จัดซื้ออุปกรณ์ห้องปฏิบัติการ",
                        budget: "฿3,200,000",
                        status: "TOR ใหม่",
                        statusColor: "text-amber-300",
                      },
                      {
                        dept: "กระทรวงสาธารณสุข",
                        title: "จัดซื้อครุภัณฑ์การแพทย์",
                        budget: "฿8,750,000",
                        status: "ประกาศ",
                        statusColor: "text-indigo-300",
                      },
                    ].map((p) => (
                      <div
                        key={p.title}
                        className="rounded-lg border border-white/8 bg-white/5 px-3 py-2.5"
                      >
                        <div className="flex items-start justify-between gap-2">
                          <div className="min-w-0">
                            <p className="truncate text-[11px] font-semibold text-white/90">{p.title}</p>
                            <p className="text-[10px] text-white/40">{p.dept}</p>
                          </div>
                          <div className="shrink-0 text-right">
                            <p className="text-[11px] font-semibold text-white/80">{p.budget}</p>
                            <p className={`text-[10px] font-medium ${p.statusColor}`}>{p.status}</p>
                          </div>
                        </div>
                      </div>
                    ))}
                    {/* Mini bar chart stub */}
                    <div className="mt-2 flex items-end gap-1 pt-1">
                      {[30, 55, 40, 70, 60, 85, 50, 90, 65, 75].map((h, i) => (
                        <div
                          key={i}
                          className="flex-1 rounded-sm bg-indigo-400/50"
                          style={{ height: `${h * 0.5}px` }}
                        />
                      ))}
                    </div>
                    <p className="text-center text-[10px] text-white/30">โครงการที่พบรายสัปดาห์</p>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </section>

        {/* ── TRUST BAR ──────────────────────────── */}
        <section aria-label="Data sources" className="border-b border-[var(--border-default)] bg-white py-6">
          <div className="mx-auto max-w-7xl px-6">
            <p className="mb-4 text-center text-xs font-semibold uppercase tracking-widest text-[var(--text-muted)]">
              ข้อมูลดึงตรงจาก
            </p>
            <div className="flex flex-wrap items-center justify-center gap-4 md:gap-8">
              {[
                "gprocurement.go.th",
                "กรมบัญชีกลาง",
                "ระบบ e-GP",
                "เอกสาร TOR",
                "กระทรวงการคลัง",
              ].map((src) => (
                <span
                  key={src}
                  className="rounded-full border border-[var(--border-default)] bg-[var(--bg-surface-secondary)] px-4 py-1.5 text-xs font-semibold text-[var(--text-secondary)]"
                >
                  {src}
                </span>
              ))}
            </div>
          </div>
        </section>

        {/* ── FEATURES BENTO GRID ────────────────── */}
        <section id="features" className="py-24">
          <div className="mx-auto max-w-7xl px-6">
            <div className="mb-14 text-center">
              <Badge color="indigo">ฟีเจอร์</Badge>
              <h2 className="mt-3 text-3xl font-bold text-[var(--text-primary)] sm:text-4xl">
                ทุกสิ่งที่คุณต้องการในที่เดียว
              </h2>
              <p className="mx-auto mt-3 max-w-xl text-base text-[var(--text-secondary)]">
                ระบบอัตโนมัติครบวงจรสำหรับติดตามการประกวดราคาภาครัฐ ตั้งแต่การค้นหาจนถึงการแจ้งเตือน
              </p>
            </div>

            <div className="grid auto-rows-fr grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
              {/* Card 1 — Keyword Crawl (spans 2 cols) */}
              <div className="flex flex-col rounded-2xl border border-[var(--border-default)] bg-white p-6 shadow-[var(--shadow-soft)] sm:col-span-2 lg:col-span-2">
                <Badge color="indigo">คีย์เวิร์ด</Badge>
                <h3 className="mt-3 text-lg font-bold text-[var(--text-primary)]">
                  ค้นหาและติดตามด้วยคำค้นของคุณ
                </h3>
                <p className="mt-2 text-sm leading-relaxed text-[var(--text-secondary)]">
                  กำหนดคำค้นที่สนใจ ระบบจะสแกนโครงการใหม่ทุกครั้งที่ e-GP อัปเดต และแจ้งเตือนคุณทันที
                </p>
                <div className="mt-5 flex flex-wrap gap-2">
                  {[
                    "ก่อสร้างถนน",
                    "ครุภัณฑ์การแพทย์",
                    "ระบบ IT",
                    "จัดซื้อยานพาหนะ",
                    "งานออกแบบ",
                  ].map((kw) => (
                    <span
                      key={kw}
                      className="rounded-full bg-[var(--badge-indigo-bg)] px-3 py-1 text-xs font-semibold text-[var(--badge-indigo-text)]"
                    >
                      {kw}
                    </span>
                  ))}
                </div>
              </div>

              {/* Card 2 — Real-time notifications */}
              <div className="flex flex-col rounded-2xl border border-[var(--border-default)] bg-white p-6 shadow-[var(--shadow-soft)]">
                <Badge color="green">แจ้งเตือน</Badge>
                <h3 className="mt-3 text-lg font-bold text-[var(--text-primary)]">
                  แจ้งเตือนเรียลไทม์
                </h3>
                <p className="mt-2 text-sm leading-relaxed text-[var(--text-secondary)]">
                  รับอีเมลทันทีเมื่อมีโครงการใหม่หรือ TOR ที่เปลี่ยนแปลง
                </p>
                <div className="mt-4 space-y-2">
                  {[
                    { text: "โครงการใหม่ตรงคำค้น", time: "เมื่อสักครู่" },
                    { text: "TOR เวอร์ชันใหม่พร้อมแล้ว", time: "2 นาทีที่แล้ว" },
                  ].map((n) => (
                    <div
                      key={n.text}
                      className="flex items-start gap-2 rounded-lg border border-[var(--border-default)] px-3 py-2"
                    >
                      <span className="mt-1 flex h-2 w-2 shrink-0 rounded-full bg-green-400" />
                      <div>
                        <p className="text-xs font-semibold text-[var(--text-primary)]">{n.text}</p>
                        <p className="text-[10px] text-[var(--text-muted)]">{n.time}</p>
                      </div>
                    </div>
                  ))}
                </div>
              </div>

              {/* Card 3 — TOR Diff View */}
              <div className="flex flex-col rounded-2xl border border-[var(--border-default)] bg-white p-6 shadow-[var(--shadow-soft)]">
                <Badge color="purple">TOR Diff</Badge>
                <h3 className="mt-3 text-lg font-bold text-[var(--text-primary)]">
                  เปรียบเทียบ TOR ทุกเวอร์ชัน
                </h3>
                <p className="mt-2 text-sm leading-relaxed text-[var(--text-secondary)]">
                  ดูการเปลี่ยนแปลงระหว่างเวอร์ชันของเอกสาร TOR ได้ทันที
                </p>
                <div className="mt-4 space-y-1 rounded-lg border border-[var(--border-default)] bg-[var(--bg-surface-secondary)] p-3 font-mono text-xs">
                  <p className="text-red-500">− งบประมาณ: 10,000,000 บาท</p>
                  <p className="text-green-600">+ งบประมาณ: 12,500,000 บาท</p>
                  <p className="text-[var(--text-muted)]">  ระยะเวลา: 180 วัน</p>
                  <p className="text-red-500">− เอกสารยื่น: 5 ชุด</p>
                  <p className="text-green-600">+ เอกสารยื่น: 3 ชุด</p>
                </div>
              </div>

              {/* Card 4 — Analytics (spans 2 cols) */}
              <div className="flex flex-col rounded-2xl border border-[var(--border-default)] bg-white p-6 shadow-[var(--shadow-soft)] sm:col-span-2">
                <Badge color="teal">Analytics</Badge>
                <h3 className="mt-3 text-lg font-bold text-[var(--text-primary)]">
                  Dashboard วิเคราะห์ข้อมูล
                </h3>
                <p className="mt-2 text-sm leading-relaxed text-[var(--text-secondary)]">
                  กราฟและสถิติเชิงลึกของโครงการทั้งหมด แยกตามหน่วยงาน งบประมาณ และสถานะ
                </p>
                <div className="mt-5 flex items-end gap-2">
                  {[45, 60, 38, 75, 55, 80, 48, 92, 67, 84, 71, 95].map((h, i) => (
                    <div key={i} className="flex-1 rounded-t-sm bg-[var(--color-primary)]/20" style={{ height: `${h * 0.7}px` }}>
                      <div
                        className="w-full rounded-t-sm bg-[var(--color-primary)]"
                        style={{ height: `${h * 0.4}px` }}
                      />
                    </div>
                  ))}
                </div>
                <div className="mt-2 flex justify-between text-[10px] text-[var(--text-muted)]">
                  <span>ม.ค.</span><span>ก.พ.</span><span>มี.ค.</span><span>เม.ย.</span>
                  <span>พ.ค.</span><span>มิ.ย.</span><span>ก.ค.</span><span>ส.ค.</span>
                  <span>ก.ย.</span><span>ต.ค.</span><span>พ.ย.</span><span>ธ.ค.</span>
                </div>
              </div>

              {/* Card 5 — Project Lifecycle */}
              <div className="flex flex-col rounded-2xl border border-[var(--border-default)] bg-white p-6 shadow-[var(--shadow-soft)] sm:col-span-2 lg:col-span-2">
                <Badge color="amber">Project Lifecycle</Badge>
                <h3 className="mt-3 text-lg font-bold text-[var(--text-primary)]">
                  ติดตามวงจรชีวิตโครงการ
                </h3>
                <p className="mt-2 text-sm leading-relaxed text-[var(--text-secondary)]">
                  เห็นภาพรวมสถานะโครงการตั้งแต่ประกาศจนถึงสัญญา ไม่พลาดทุกขั้นตอน
                </p>
                <div className="mt-5 flex items-center gap-0">
                  {[
                    { label: "ประกาศ", done: true },
                    { label: "TOR", done: true },
                    { label: "เปิดซอง", done: true },
                    { label: "ประกาศผล", done: false },
                    { label: "สัญญา", done: false },
                  ].map((step, i, arr) => (
                    <div key={step.label} className="flex flex-1 items-center">
                      <div className="flex flex-col items-center gap-1">
                        <div
                          className={`flex h-7 w-7 items-center justify-center rounded-full text-xs font-bold ${
                            step.done
                              ? "bg-[var(--color-primary)] text-white"
                              : "border-2 border-[var(--border-default)] bg-white text-[var(--text-muted)]"
                          }`}
                        >
                          {step.done ? "✓" : i + 1}
                        </div>
                        <span className="text-[10px] text-[var(--text-muted)]">{step.label}</span>
                      </div>
                      {i < arr.length - 1 && (
                        <div
                          className={`mx-1 h-0.5 flex-1 ${step.done ? "bg-[var(--color-primary)]" : "bg-[var(--border-default)]"}`}
                        />
                      )}
                    </div>
                  ))}
                </div>
              </div>

              {/* Card 6 — Export */}
              <div className="flex flex-col rounded-2xl border border-[var(--border-default)] bg-white p-6 shadow-[var(--shadow-soft)]">
                <Badge color="teal">Export</Badge>
                <h3 className="mt-3 text-lg font-bold text-[var(--text-primary)]">
                  ส่งออกข้อมูล
                </h3>
                <p className="mt-2 text-sm leading-relaxed text-[var(--text-secondary)]">
                  Export ข้อมูลในรูปแบบที่ต้องการ เพื่อนำไปใช้ต่อได้ทันที
                </p>
                <div className="mt-4 flex flex-wrap gap-2">
                  {[
                    { fmt: "Excel", color: "green" },
                    { fmt: "CSV", color: "teal" },
                    { fmt: "PDF", color: "purple" },
                  ].map((f) => (
                    <Badge key={f.fmt} color={f.color as "green" | "teal" | "purple"}>
                      {f.fmt}
                    </Badge>
                  ))}
                </div>
              </div>
            </div>
          </div>
        </section>

        {/* ── HOW IT WORKS ───────────────────────── */}
        <section
          className="py-24"
          style={{ background: "var(--bg-surface-secondary)" }}
        >
          <div className="mx-auto max-w-7xl px-6">
            <div className="mb-14 text-center">
              <Badge color="purple">วิธีการทำงาน</Badge>
              <h2 className="mt-3 text-3xl font-bold text-[var(--text-primary)] sm:text-4xl">
                ใช้งานง่าย 3 ขั้นตอน
              </h2>
            </div>
            <div className="grid gap-8 md:grid-cols-3">
              {[
                {
                  step: "01",
                  title: "ตั้งค่าคำค้น",
                  desc: "กำหนดคีย์เวิร์ดที่คุณสนใจ เช่น 'ก่อสร้าง', 'IT', 'ครุภัณฑ์' ระบบจะจดจำและเริ่มติดตามทันที",
                  icon: "🔍",
                },
                {
                  step: "02",
                  title: "ระบบทำงานอัตโนมัติ",
                  desc: "AI Crawler สแกนระบบ e-GP ตลอด 24/7 ดึงข้อมูลโครงการและเอกสาร TOR ทุกชิ้น",
                  icon: "⚙️",
                },
                {
                  step: "03",
                  title: "รับการแจ้งเตือน",
                  desc: "รับอีเมลแจ้งเตือนทันทีพร้อมรายละเอียดโครงการ งบประมาณ และลิงก์ดาวน์โหลด TOR",
                  icon: "🔔",
                },
              ].map((s) => (
                <div key={s.step} className="relative rounded-2xl border border-[var(--border-default)] bg-white p-8 shadow-[var(--shadow-soft)]">
                  <div className="mb-4 flex items-center gap-3">
                    <span
                      className="flex h-10 w-10 items-center justify-center rounded-xl text-xl"
                      style={{ background: "var(--badge-indigo-bg)" }}
                    >
                      {s.icon}
                    </span>
                    <span className="text-xs font-bold tracking-widest text-[var(--color-primary)]">
                      {s.step}
                    </span>
                  </div>
                  <h3 className="mb-2 text-lg font-bold text-[var(--text-primary)]">{s.title}</h3>
                  <p className="text-sm leading-relaxed text-[var(--text-secondary)]">{s.desc}</p>
                </div>
              ))}
            </div>
          </div>
        </section>

        {/* ── CONSULTING SERVICES ────────────────── */}
        <section id="services" className="py-24 bg-white">
          <div className="mx-auto max-w-7xl px-6">

            {/* Header */}
            <div className="mb-14 text-center">
              <Badge color="purple">บริการเสริม</Badge>
              <h2 className="mt-3 text-3xl font-bold text-[var(--text-primary)] sm:text-4xl">
                บริการที่ปรึกษาและพัฒนาระบบ
              </h2>
              <p className="mx-auto mt-3 max-w-2xl text-base text-[var(--text-secondary)]">
                ทีมผู้เชี่ยวชาญพร้อมช่วยคุณตั้งแต่การจัดทำข้อเสนอจนถึงการพัฒนาระบบต้นแบบ
                เพิ่มโอกาสชนะการประกวดราคาด้วยข้อเสนอที่โดดเด่นและระบบสาธิตที่น่าเชื่อถือ
              </p>
            </div>

            {/* Two service process cards */}
            <div className="mb-12 grid gap-8 lg:grid-cols-2">

              {/* Service 1 — TOR Proposal */}
              <div className="flex flex-col rounded-2xl border border-[var(--border-default)] bg-[var(--bg-surface-secondary)] p-8">
                <div className="mb-5 flex items-center gap-3">
                  <span
                    className="flex h-12 w-12 items-center justify-center rounded-xl text-2xl"
                    style={{ background: "var(--badge-indigo-bg)" }}
                  >
                    📋
                  </span>
                  <Badge color="indigo">บริการที่ 1</Badge>
                </div>
                <h3 className="mb-2 text-xl font-bold text-[var(--text-primary)]">
                  จัดทำข้อเสนอโครงการ
                </h3>
                <p className="mb-6 text-sm leading-relaxed text-[var(--text-secondary)]">
                  วิเคราะห์ TOR และประกาศจัดซื้อจัดจ้างด้วยระบบ AI เพื่อจัดทำข้อเสนอที่ครบถ้วน
                  ตรงตามเกณฑ์การให้คะแนน พร้อมแผนภาพ แผนผัง และกราฟิกที่ออกแบบอย่างมืออาชีพ
                  ทำให้ข้อเสนอของคุณโดดเด่นและสร้างความได้เปรียบในการแข่งขัน
                </p>
                <ol className="flex-1 space-y-3">
                  {[
                    "รับเอกสาร TOR และประกาศจัดซื้อจัดจ้าง หรือหมายเลขอ้างอิงระบบ e-GP",
                    "วิเคราะห์คะแนน TOR รายข้อ จัดลำดับความสำคัญของข้อกำหนดทางเทคนิค",
                    "จัดทำโครงสร้างข้อเสนอ พร้อมออกแบบแผนภาพ ตาราง และกราฟิกประกอบ",
                    "ส่งมอบไฟล์ Word + PDF พร้อมสำหรับการแก้ไขและนำเสนอ",
                  ].map((step, i) => (
                    <li key={i} className="flex gap-3 text-sm text-[var(--text-secondary)]">
                      <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-[var(--color-primary)] text-[10px] font-bold text-white">
                        {i + 1}
                      </span>
                      {step}
                    </li>
                  ))}
                </ol>
              </div>

              {/* Service 2 — POC/Pilot */}
              <div className="flex flex-col rounded-2xl border border-[var(--border-default)] bg-[var(--bg-surface-secondary)] p-8">
                <div className="mb-5 flex items-center gap-3">
                  <span
                    className="flex h-12 w-12 items-center justify-center rounded-xl text-2xl"
                    style={{ background: "var(--badge-purple-bg)" }}
                  >
                    💻
                  </span>
                  <Badge color="purple">บริการที่ 2</Badge>
                </div>
                <h3 className="mb-2 text-xl font-bold text-[var(--text-primary)]">
                  พัฒนาระบบต้นแบบ (POC / Pilot)
                </h3>
                <p className="mb-6 text-sm leading-relaxed text-[var(--text-secondary)]">
                  พัฒนาระบบต้นแบบที่ใช้งานได้จริงสำหรับการสาธิตในการประกวดราคา
                  แสดงขีดความสามารถทางเทคนิคตามข้อกำหนด TOR สร้างความน่าเชื่อถือ
                  และแสดงให้คณะกรรมการเห็นว่าคุณเข้าใจโจทย์ของโครงการอย่างลึกซึ้ง
                </p>
                <ol className="flex-1 space-y-3">
                  {[
                    "วิเคราะห์ข้อกำหนดเชิงเทคนิคจาก TOR และกำหนดขอบเขตระบบต้นแบบ",
                    "ออกแบบสถาปัตยกรรมระบบ UI/UX และ Flow การทำงานหลัก",
                    "พัฒนา POC ที่ใช้งานได้จริง ครอบคลุมฟีเจอร์สำคัญตามข้อกำหนด",
                    "ส่งมอบระบบต้นแบบพร้อมสคริปต์การสาธิตและเอกสารประกอบ",
                  ].map((step, i) => (
                    <li key={i} className="flex gap-3 text-sm text-[var(--text-secondary)]">
                      <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-[var(--color-purple)] text-[10px] font-bold text-white">
                        {i + 1}
                      </span>
                      {step}
                    </li>
                  ))}
                </ol>
              </div>
            </div>

            {/* Pricing table */}
            <div className="mb-10 overflow-hidden rounded-2xl border border-[var(--border-default)] shadow-[var(--shadow-soft)]">
              <div className="bg-[var(--color-primary)] px-6 py-4">
                <h3 className="text-base font-bold text-white">ตารางราคาบริการ</h3>
                <p className="mt-0.5 text-xs text-indigo-200">ราคาไม่รวม VAT 7%</p>
              </div>
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-[var(--border-default)] bg-[var(--bg-surface-secondary)]">
                      <th className="px-6 py-3 text-left font-semibold text-[var(--text-primary)]">แพ็กเกจ</th>
                      <th className="px-6 py-3 text-left font-semibold text-[var(--text-primary)]">วงเงินโครงการ</th>
                      <th className="px-6 py-3 text-right font-semibold text-[var(--text-primary)]">จัดทำข้อเสนอ</th>
                      <th className="px-6 py-3 text-right font-semibold text-[var(--text-primary)]">พัฒนา POC</th>
                      <th className="px-6 py-3 text-right font-semibold text-[var(--text-primary)]">เวลาส่งมอบ</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-[var(--border-default)] bg-white">
                    <tr>
                      <td className="px-6 py-4"><Badge color="amber">S — Small</Badge></td>
                      <td className="px-6 py-4 text-[var(--text-secondary)]">&lt; 5 ล้านบาท</td>
                      <td className="px-6 py-4 text-right font-semibold text-[var(--text-primary)]">฿50,000</td>
                      <td className="px-6 py-4 text-right font-semibold text-[var(--text-primary)]">฿50,000</td>
                      <td className="px-6 py-4 text-right text-[var(--text-secondary)]">7 วันทำการ</td>
                    </tr>
                    <tr>
                      <td className="px-6 py-4"><Badge color="purple">M — Medium</Badge></td>
                      <td className="px-6 py-4 text-[var(--text-secondary)]">&lt; 10 ล้านบาท</td>
                      <td className="px-6 py-4 text-right font-semibold text-[var(--text-primary)]">฿100,000</td>
                      <td className="px-6 py-4 text-right font-semibold text-[var(--text-primary)]">฿100,000</td>
                      <td className="px-6 py-4 text-right text-[var(--text-secondary)]">10 วันทำการ</td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </div>

            {/* Payment terms + Notes */}
            <div className="mb-12 grid gap-6 md:grid-cols-2">

              {/* Payment terms */}
              <div className="rounded-2xl border border-[var(--border-default)] bg-[var(--bg-surface-secondary)] p-6">
                <h4 className="mb-4 text-sm font-bold text-[var(--text-primary)]">
                  💳 เงื่อนไขการชำระเงิน
                </h4>
                <ul className="space-y-3">
                  {[
                    "มัดจำ 50% เพื่อเริ่มงาน — ชำระส่วนที่เหลือ 50% ก่อนส่งมอบ",
                    "ต้องได้รับมัดจำอย่างน้อย 7 วันทำการก่อนวันยื่นข้อเสนอ",
                    "ชำระผ่านพร้อมเพย์ QR หรือโอนเงินธนาคาร",
                  ].map((t, i) => (
                    <li key={i} className="flex items-start gap-2 text-sm text-[var(--text-secondary)]">
                      <CheckIcon />
                      {t}
                    </li>
                  ))}
                </ul>
              </div>

              {/* Disclaimer */}
              <div className="rounded-2xl border border-amber-200 bg-amber-50 p-6">
                <h4 className="mb-4 text-sm font-bold text-amber-900">
                  ⚠️ หมายเหตุสำคัญ
                </h4>
                <ul className="space-y-3">
                  {[
                    "ส่งมอบในรูปแบบไฟล์ Word และ PDF เท่านั้น",
                    "ลูกค้ารับผิดชอบการจัดรูปแบบ การพิมพ์ และการยื่นเอกสารด้วยตนเอง",
                    "บริษัทไม่รับผิดชอบต่อผลการตัดสินหรือผลการประกวดราคา",
                  ].map((n, i) => (
                    <li key={i} className="flex items-start gap-2 text-sm text-amber-800">
                      <span className="mt-1 h-1.5 w-1.5 shrink-0 rounded-full bg-amber-500" />
                      {n}
                    </li>
                  ))}
                </ul>
              </div>
            </div>

            {/* CTA */}
            <div className="text-center">
              <Link
                href="/inquiry"
                className="inline-flex rounded-full bg-[var(--color-primary)] px-8 py-3 text-sm font-bold text-white shadow-lg transition-transform hover:scale-105 hover:bg-[var(--color-primary-hover)]"
              >
                ยื่นข้อมูลโครงการเพื่อรับใบเสนอราคา →
              </Link>
              <p className="mt-3 text-xs text-[var(--text-muted)]">
                ไม่มีค่าใช้จ่ายในการยื่นข้อมูล • ทีมงานจะติดต่อกลับภายใน 1 วันทำการ
              </p>
            </div>

          </div>
        </section>

        {/* ── PRICING ────────────────────────────── */}
        <section id="pricing" className="py-24">
          <div className="mx-auto max-w-7xl px-6">
            <div className="mb-14 text-center">
              <Badge color="green">ราคา</Badge>
              <h2 className="mt-3 text-3xl font-bold text-[var(--text-primary)] sm:text-4xl">
                เลือกแพ็กเกจที่เหมาะกับคุณ
              </h2>
              <p className="mx-auto mt-3 max-w-md text-base text-[var(--text-secondary)]">
                ราคาโปร่งใส ไม่มีค่าธรรมเนียมซ่อนเร้น
              </p>
            </div>

            <div className="grid gap-6 md:grid-cols-3">
              {/* Free Trial */}
              <div className="flex flex-col rounded-2xl border border-[var(--border-default)] bg-white p-8 shadow-[var(--shadow-soft)]">
                <Badge color="gray">Free Trial</Badge>
                <p className="mt-4 text-4xl font-extrabold text-[var(--text-primary)]">฿0</p>
                <p className="mt-1 text-sm text-[var(--text-muted)]">ทดลองใช้ 7 วัน • ยืนยันอีเมลเท่านั้น</p>
                <ul className="my-6 flex-1 space-y-2.5">
                  {[
                    "1 คำค้น",
                    "ข้อมูล e-GP แบบเรียลไทม์",
                    "ดูรายการโครงการ",
                  ].map((f) => (
                    <li key={f} className="flex items-start gap-2 text-sm text-[var(--text-secondary)]">
                      <CheckIcon />
                      {f}
                    </li>
                  ))}
                </ul>
                <Link
                  href="/signup"
                  className="w-full rounded-full border border-[var(--color-primary)] py-2.5 text-center text-sm font-semibold text-[var(--color-primary)] transition-colors hover:bg-[var(--badge-indigo-bg)]"
                >
                  เริ่มทดลองใช้ฟรี
                </Link>
              </div>

              {/* One-Time Pack */}
              <div className="flex flex-col rounded-2xl border border-[var(--border-default)] bg-white p-8 shadow-[var(--shadow-soft)]">
                <Badge color="amber">One-Time Pack</Badge>
                <p className="mt-4 text-4xl font-extrabold text-[var(--text-primary)]">฿300</p>
                <p className="mt-1 text-sm text-[var(--text-muted)]">จ่ายครั้งเดียว • 3 วัน</p>
                <ul className="my-6 flex-1 space-y-2.5">
                  {[
                    "1 คำค้น",
                    "ข้อมูล e-GP แบบเรียลไทม์",
                    "แจ้งเตือนทางอีเมล",
                    "ดาวน์โหลดเอกสาร TOR",
                    "Export Excel",
                  ].map((f) => (
                    <li key={f} className="flex items-start gap-2 text-sm text-[var(--text-secondary)]">
                      <CheckIcon />
                      {f}
                    </li>
                  ))}
                </ul>
                <Link
                  href="/login"
                  className="w-full rounded-full border border-[var(--color-primary)] py-2.5 text-center text-sm font-semibold text-[var(--color-primary)] transition-colors hover:bg-[var(--badge-indigo-bg)]"
                >
                  ซื้อแพ็กเกจครั้งเดียว
                </Link>
                <p className="mt-3 text-center text-xs text-[var(--text-muted)]">
                  ชำระผ่าน พร้อมเพย์ QR · โอนเงิน
                </p>
              </div>

              {/* Monthly — highlighted */}
              <div
                className="relative flex flex-col rounded-2xl p-8 text-white shadow-2xl"
                style={{ background: "linear-gradient(135deg, #4F46E5 0%, #6D28D9 100%)" }}
              >
                <div className="absolute -top-3 left-1/2 -translate-x-1/2">
                  <span className="rounded-full bg-gradient-to-r from-amber-400 to-orange-400 px-4 py-1 text-xs font-bold text-white shadow">
                    แนะนำ
                  </span>
                </div>
                <Badge color="indigo-light">Monthly Membership</Badge>
                <p className="mt-4 text-4xl font-extrabold">฿1,500</p>
                <p className="mt-1 text-sm text-indigo-200">ต่อเดือน • 1 เดือน</p>
                <ul className="my-6 flex-1 space-y-2.5">
                  {[
                    "5 คำค้น",
                    "ข้อมูล e-GP แบบเรียลไทม์",
                    "แจ้งเตือนทางอีเมล",
                    "ดาวน์โหลดเอกสาร TOR ทุกเวอร์ชัน",
                    "TOR Diff View",
                    "Analytics Dashboard",
                    "Export Excel",
                    "Project Lifecycle Tracking",
                  ].map((f) => (
                    <li key={f} className="flex items-start gap-2 text-sm text-indigo-100">
                      <svg
                        className="mt-0.5 h-4 w-4 shrink-0 text-indigo-200"
                        viewBox="0 0 16 16"
                        fill="none"
                        aria-hidden="true"
                      >
                        <path
                          d="M3 8l3.5 3.5L13 4.5"
                          stroke="currentColor"
                          strokeWidth="2"
                          strokeLinecap="round"
                          strokeLinejoin="round"
                        />
                      </svg>
                      {f}
                    </li>
                  ))}
                </ul>
                <Link
                  href="/login"
                  className="w-full rounded-full bg-white py-2.5 text-center text-sm font-bold text-indigo-700 transition-colors hover:bg-indigo-50"
                >
                  สมัครสมาชิกรายเดือน
                </Link>
                <p className="mt-3 text-center text-xs text-indigo-300">
                  ชำระผ่าน พร้อมเพย์ QR · โอนเงิน
                </p>
              </div>
            </div>
          </div>
        </section>

        {/* ── FAQ ────────────────────────────────── */}
        <section
          id="faq"
          className="py-24"
          style={{ background: "var(--bg-surface-secondary)" }}
        >
          <div className="mx-auto max-w-3xl px-6">
            <div className="mb-14 text-center">
              <Badge color="purple">FAQ</Badge>
              <h2 className="mt-3 text-3xl font-bold text-[var(--text-primary)] sm:text-4xl">
                คำถามที่พบบ่อย
              </h2>
            </div>

            <div className="space-y-3">
              {[
                {
                  q: "e-GP Intelligence Platform คืออะไร?",
                  a: "แพลตฟอร์มที่ดึงข้อมูลโครงการจัดซื้อจัดจ้างจากระบบ e-GP ของกรมบัญชีกลาง (gprocurement.go.th) โดยอัตโนมัติ พร้อมแจ้งเตือนเมื่อมีโครงการใหม่ตรงกับคำค้นของคุณ",
                },
                {
                  q: "ข้อมูลมาจากแหล่งไหน?",
                  a: "ข้อมูลทั้งหมดดึงตรงจากเว็บไซต์ gprocurement.go.th ซึ่งเป็นระบบ e-GP ที่ดำเนินการโดยกรมบัญชีกลาง กระทรวงการคลัง",
                },
                {
                  q: "การแจ้งเตือนทำงานอย่างไร?",
                  a: "สำหรับแพ็กเกจ One-Time Search Pack และ Monthly Membership ระบบจะส่งอีเมลทันทีเมื่อพบโครงการใหม่ที่ตรงกับคำค้นที่คุณตั้งไว้ ความล่าช้าโดยเฉลี่ยน้อยกว่า 1 นาทีหลังข้อมูลปรากฏบน e-GP",
                },
                {
                  q: "ทดลองใช้ฟรีได้นานแค่ไหน?",
                  a: "แพ็กเกจ Free Trial ใช้งานได้ฟรี 7 วัน รองรับ 1 คำค้น ต้องยืนยันอีเมลเท่านั้น ไม่ต้องชำระเงินใดๆ",
                },
                {
                  q: "ความแตกต่างระหว่าง One-Time Pack กับ Monthly Membership?",
                  a: "One-Time Search Pack (฿300) เหมาะสำหรับการค้นหาชั่วคราว 3 วัน 1 คำค้น Monthly Membership (฿1,500/เดือน) เหมาะสำหรับองค์กรที่ต้องการติดตามต่อเนื่อง รองรับ 5 คำค้นพร้อมฟีเจอร์ครบครัน",
                },
                {
                  q: "ชำระเงินด้วยวิธีใดได้บ้าง?",
                  a: "รองรับการชำระเงิน 2 วิธี: พร้อมเพย์ QR (สแกนจ่ายได้ทันที) และการโอนเงินผ่านธนาคาร ไม่รองรับบัตรเครดิต ระบบจะยืนยันและเปิดใช้งานแพ็กเกจภายใน 1 ชั่วโมงหลังได้รับการยืนยันการชำระเงิน",
                },
                {
                   q: "สามารถดูเอกสาร TOR ได้หรือไม่?",
                   a: "ได้ สำหรับแพ็กเกจ One-Time และ Monthly ระบบจะดาวน์โหลดและจัดเก็บเอกสาร TOR ทุกเวอร์ชัน พร้อม Diff View เพื่อเปรียบเทียบการเปลี่ยนแปลงระหว่างเวอร์ชัน แพ็กเกจ Free Trial จะเห็นข้อมูลเมตาโครงการแต่ไม่รองรับการดาวน์โหลดเอกสาร",
                 },
              ].map((item) => (
                <details
                  key={item.q}
                  className="group rounded-xl border border-[var(--border-default)] bg-white"
                >
                  <summary className="flex cursor-pointer list-none items-center justify-between gap-4 px-6 py-4 text-sm font-semibold text-[var(--text-primary)] hover:text-[var(--color-primary)]">
                    {item.q}
                    <ChevronDown />
                  </summary>
                  <p className="px-6 pb-5 text-sm leading-relaxed text-[var(--text-secondary)]">
                    {item.a}
                  </p>
                </details>
              ))}
            </div>
          </div>
        </section>

        {/* ── CTA BANNER ─────────────────────────── */}
        <section
          className="py-24"
          style={{ background: "linear-gradient(135deg, #4F46E5 0%, #6D28D9 100%)" }}
          aria-label="Call to action"
        >
          <div className="mx-auto max-w-3xl px-6 text-center">
            <h2 className="mb-4 text-3xl font-extrabold text-white sm:text-4xl">
              พร้อมเริ่มติดตามการประกวดราคาได้เลย
            </h2>
            <p className="mb-8 text-base text-indigo-200">
              ทดลองใช้ฟรี 7 วัน ไม่ต้องใช้บัตรเครดิต ยกเลิกได้ทุกเมื่อ
            </p>
            <div className="flex flex-wrap justify-center gap-4">
              <Link
                href="/signup"
                className="rounded-full bg-white px-8 py-3 text-sm font-bold text-indigo-700 shadow-lg transition-transform hover:scale-105 hover:bg-indigo-50"
              >
                เริ่มทดลองใช้ฟรี 7 วัน
              </Link>
              <Link
                href="/login"
                className="rounded-full border border-white/40 px-8 py-3 text-sm font-semibold text-white transition-colors hover:border-white/70 hover:bg-white/10"
              >
                เข้าสู่ระบบ
              </Link>
            </div>
          </div>
        </section>

        {/* ── FOOTER ─────────────────────────────── */}
        <footer className="border-t border-[var(--border-default)] bg-white py-10">
          <div className="mx-auto max-w-7xl px-6">
            <div className="flex flex-col items-center justify-between gap-6 md:flex-row">
              {/* Logo */}
              <Link href="/" className="flex items-center gap-2.5">
                <span className="flex h-7 w-7 items-center justify-center rounded-lg bg-[var(--color-primary)]">
                  <svg className="h-3.5 w-3.5 text-white" viewBox="0 0 24 24" fill="none" aria-hidden="true">
                    <path
                      d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z"
                      stroke="currentColor"
                      strokeWidth="2"
                      strokeLinecap="round"
                      strokeLinejoin="round"
                    />
                  </svg>
                </span>
                <span className="text-sm font-bold text-[var(--text-primary)]">e-GP Intelligence</span>
              </Link>

              {/* Nav */}
              <nav className="flex flex-wrap justify-center gap-6" aria-label="Footer navigation">
                {[
                  { href: "#features", label: "ฟีเจอร์" },
                  { href: "#pricing", label: "ราคา" },
                  { href: "#faq", label: "คำถาม" },
                  { href: "/login", label: "เข้าสู่ระบบ" },
                ].map((l) => (
                  <a
                    key={l.href}
                    href={l.href}
                    className="text-xs text-[var(--text-muted)] transition-colors hover:text-[var(--color-primary)]"
                  >
                    {l.label}
                  </a>
                ))}
              </nav>

              {/* Copyright */}
              <p className="text-xs text-[var(--text-muted)]">
                © {new Date().getFullYear()} e-GP Intelligence Platform
              </p>
            </div>
          </div>
        </footer>
      </div>
    </>
  );
}
