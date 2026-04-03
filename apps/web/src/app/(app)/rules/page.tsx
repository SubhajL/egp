"use client";

import { useState } from "react";
import { Plus, X } from "lucide-react";
import { PageHeader } from "@/components/layout/page-header";

/* ------------------------------------------------------------------ */
/*  Mock Data                                                          */
/* ------------------------------------------------------------------ */

type Profile = {
  name: string;
  description: string;
  active: boolean;
  maxPages: number;
  consultingDays: number;
  staleDays: number;
  keywords: string[];
};

const MOCK_PROFILES: Profile[] = [
  {
    name: "TOR",
    description: "ค้นหาเอกสาร TOR และประกวดราคา",
    active: true,
    maxPages: 15,
    consultingDays: 30,
    staleDays: 45,
    keywords: [
      "วิเคราะห์ข้อมูล", "ระบบสารสนเทศ", "เทคโนโลยีสารสนเทศ",
      "ระบบคลังข้อมูล", "ระบบฐานข้อมูลใหญ่", "แผนแม่บท",
      "ที่ปรึกษา", "ระบบบริหาร", "จ้างพัฒนา",
      "Digital", "ระบบดิจิทัล", "แพลตฟอร์ม",
    ],
  },
  {
    name: "TOE",
    description: "ค้นหาเอกสารข้อกำหนดทางเทคนิค",
    active: true,
    maxPages: 10,
    consultingDays: 30,
    staleDays: 45,
    keywords: [
      "คอมพิวเตอร์", "ซอฟต์แวร์", "ระบบเครือข่าย",
      "เครื่องแม่ข่าย", "อุปกรณ์จัดเก็บ", "ระบบรักษาความปลอดภัย",
    ],
  },
  {
    name: "LUE",
    description: "ค้นหาเอกสารเงื่อนไขการใช้งาน",
    active: false,
    maxPages: 10,
    consultingDays: 30,
    staleDays: 45,
    keywords: [
      "สัญญา", "เงื่อนไข", "ข้อกำหนด", "การรับประกัน",
    ],
  },
];

const TABS = [
  { key: "profiles", label: "โปรไฟล์คำค้น" },
  { key: "closure", label: "กฎการปิด" },
  { key: "notifications", label: "การแจ้งเตือน" },
  { key: "schedule", label: "กำหนดเวลา" },
];

/* ------------------------------------------------------------------ */
/*  Component                                                          */
/* ------------------------------------------------------------------ */

export default function RulesPage() {
  const [activeTab, setActiveTab] = useState("profiles");
  const [consultingDays, setConsultingDays] = useState("30");
  const [staleDays, setStaleDays] = useState("45");
  const [closeOnWinner, setCloseOnWinner] = useState(true);
  const [closeOnContract, setCloseOnContract] = useState(true);

  return (
    <>
      <PageHeader
        title="กฎและโปรไฟล์"
        subtitle="จัดการคำค้น, กฎการปิดโครงการ, และการแจ้งเตือน"
      />

      {/* Tab Bar */}
      <div className="mb-6 flex gap-1 rounded-xl bg-[var(--bg-surface-secondary)] p-1">
        {TABS.map((tab) => (
          <button
            key={tab.key}
            type="button"
            onClick={() => setActiveTab(tab.key)}
            className={`rounded-lg px-4 py-2 text-sm font-medium transition-colors ${
              activeTab === tab.key
                ? "bg-[var(--bg-surface)] text-primary shadow-sm"
                : "text-[var(--text-muted)] hover:text-[var(--text-secondary)]"
            }`}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {/* Profiles Tab Content */}
      {activeTab === "profiles" && (
        <div className="space-y-6">
          {/* Profile Cards */}
          <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
            {MOCK_PROFILES.map((profile) => (
              <div
                key={profile.name}
                className={`rounded-2xl bg-[var(--bg-surface)] p-6 shadow-[var(--shadow-soft)] ${
                  !profile.active ? "opacity-60" : ""
                }`}
              >
                {/* Header */}
                <div className="mb-3 flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <h3 className="text-lg font-bold text-[var(--text-primary)]">{profile.name}</h3>
                    <span className={`rounded-full px-2 py-0.5 text-[10px] font-semibold ${
                      profile.active
                        ? "bg-[var(--badge-green-bg)] text-[var(--badge-green-text)]"
                        : "bg-[var(--badge-gray-bg)] text-[var(--badge-gray-text)]"
                    }`}>
                      {profile.active ? "ใช้งาน" : "ปิดใช้งาน"}
                    </span>
                  </div>
                  <button
                    type="button"
                    className={`relative h-6 w-11 rounded-full transition-colors ${
                      profile.active ? "bg-primary" : "bg-[var(--text-disabled)]"
                    }`}
                  >
                    <span className={`absolute top-0.5 size-5 rounded-full bg-white shadow transition-transform ${
                      profile.active ? "left-[22px]" : "left-0.5"
                    }`} />
                  </button>
                </div>

                <p className="mb-3 text-sm text-[var(--text-muted)]">{profile.description}</p>

                {/* Settings */}
                <div className="mb-4 flex gap-4 text-xs text-[var(--text-muted)]">
                  <span>หน้า: {profile.maxPages}</span>
                  <span>ที่ปรึกษา: {profile.consultingDays} วัน</span>
                  <span>Stale: {profile.staleDays} วัน</span>
                </div>

                {/* Keywords */}
                <div className="mb-4 flex flex-wrap gap-1.5">
                  {profile.keywords.map((kw) => (
                    <span
                      key={kw}
                      className="inline-flex items-center gap-1 rounded-full border border-primary/30 bg-primary/5 px-2.5 py-1 text-xs font-medium text-primary"
                    >
                      {kw}
                      <X className="size-3 cursor-pointer opacity-50 hover:opacity-100" />
                    </span>
                  ))}
                </div>

                {/* Footer */}
                <div className="flex gap-3">
                  <button type="button" className="text-sm font-medium text-primary hover:text-primary-hover">
                    + เพิ่มคำค้น
                  </button>
                  <button type="button" className="text-sm font-medium text-[var(--text-muted)] hover:text-[var(--text-secondary)]">
                    แก้ไขโปรไฟล์
                  </button>
                </div>
              </div>
            ))}
          </div>

          {/* Add New Profile */}
          <button
            type="button"
            className="flex w-full items-center justify-center gap-2 rounded-2xl border-2 border-dashed border-[var(--border-default)] py-6 text-sm font-medium text-[var(--text-muted)] transition-colors hover:border-primary hover:text-primary"
          >
            <Plus className="size-5" />
            สร้างโปรไฟล์ใหม่
          </button>

          {/* Global Settings */}
          <div className="rounded-2xl bg-[var(--bg-surface)] p-6 shadow-[var(--shadow-soft)]">
            <h2 className="mb-4 text-lg font-bold text-[var(--text-primary)]">ตั้งค่าทั่วไป</h2>
            <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
              {/* Left: Timeouts */}
              <div className="space-y-4">
                <div>
                  <label className="mb-1 block text-sm font-medium text-[var(--text-primary)]">
                    ระยะเวลาปิดโครงการที่ปรึกษา
                  </label>
                  <div className="flex items-center gap-2">
                    <input
                      type="number"
                      value={consultingDays}
                      onChange={(e) => setConsultingDays(e.target.value)}
                      className="h-10 w-20 rounded-lg border border-[var(--border-default)] px-3 text-center font-mono text-sm focus:border-primary focus:outline-none focus:ring-2 focus:ring-primary/20"
                    />
                    <span className="text-sm text-[var(--text-muted)]">วัน</span>
                  </div>
                </div>
                <div>
                  <label className="mb-1 block text-sm font-medium text-[var(--text-primary)]">
                    ระยะเวลาปิดโครงการ Stale
                  </label>
                  <div className="flex items-center gap-2">
                    <input
                      type="number"
                      value={staleDays}
                      onChange={(e) => setStaleDays(e.target.value)}
                      className="h-10 w-20 rounded-lg border border-[var(--border-default)] px-3 text-center font-mono text-sm focus:border-primary focus:outline-none focus:ring-2 focus:ring-primary/20"
                    />
                    <span className="text-sm text-[var(--text-muted)]">วัน</span>
                  </div>
                </div>
              </div>

              {/* Right: Toggles */}
              <div className="space-y-4">
                <div className="flex items-center justify-between">
                  <div>
                    <p className="text-sm font-medium text-[var(--text-primary)]">ปิดเมื่อประกาศผู้ชนะ</p>
                    <p className="text-xs text-[var(--text-muted)]">ปิดอัตโนมัติเมื่อพบประกาศผู้ชนะ</p>
                  </div>
                  <button
                    type="button"
                    onClick={() => setCloseOnWinner(!closeOnWinner)}
                    className={`relative h-6 w-11 rounded-full transition-colors ${
                      closeOnWinner ? "bg-primary" : "bg-[var(--text-disabled)]"
                    }`}
                  >
                    <span className={`absolute top-0.5 size-5 rounded-full bg-white shadow transition-transform ${
                      closeOnWinner ? "left-[22px]" : "left-0.5"
                    }`} />
                  </button>
                </div>
                <div className="flex items-center justify-between">
                  <div>
                    <p className="text-sm font-medium text-[var(--text-primary)]">ปิดเมื่อลงนามสัญญา</p>
                    <p className="text-xs text-[var(--text-muted)]">ปิดอัตโนมัติเมื่อพบการลงนามสัญญา</p>
                  </div>
                  <button
                    type="button"
                    onClick={() => setCloseOnContract(!closeOnContract)}
                    className={`relative h-6 w-11 rounded-full transition-colors ${
                      closeOnContract ? "bg-primary" : "bg-[var(--text-disabled)]"
                    }`}
                  >
                    <span className={`absolute top-0.5 size-5 rounded-full bg-white shadow transition-transform ${
                      closeOnContract ? "left-[22px]" : "left-0.5"
                    }`} />
                  </button>
                </div>
              </div>
            </div>

            <div className="mt-6 flex justify-end">
              <button type="button" className="rounded-xl bg-primary px-6 py-2.5 text-sm font-medium text-white hover:bg-primary-hover">
                บันทึกการตั้งค่า
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Other tabs — placeholder content */}
      {activeTab !== "profiles" && (
        <div className="rounded-2xl bg-[var(--bg-surface)] p-12 text-center shadow-[var(--shadow-soft)]">
          <p className="text-[var(--text-muted)]">
            {TABS.find((t) => t.key === activeTab)?.label} — กำลังพัฒนา
          </p>
        </div>
      )}
    </>
  );
}
