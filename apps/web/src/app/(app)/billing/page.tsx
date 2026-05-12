"use client";

import { FormEvent, useEffect, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { ArrowRightLeft, Landmark, ReceiptText } from "lucide-react";
import { useSearchParams } from "next/navigation";
import QRCode from "qrcode";

import { PageHeader } from "@/components/layout/page-header";
import { QueryState } from "@/components/ui/query-state";
import { StatusBadge } from "@/components/ui/status-badge";
import {
  createBillingUpgrade,
  createBillingRecord,
  createBillingPaymentRequest,
  localizeApiError,
  recordBillingPayment,
  reconcileBillingPayment,
  startFreeTrial,
  transitionBillingRecord,
  type BillingPlan,
  type BillingRecordDetail,
  type EntitlementSummary,
} from "@/lib/api";
import { useBillingPlans, useBillingRecords, useRules } from "@/lib/hooks";
import { formatBudget, formatThaiDate } from "@/lib/utils";

const EMPTY_RECORDS: BillingRecordDetail[] = [];

function toIsoOrUndefined(value: string): string | undefined {
  if (!value.trim()) return undefined;
  return new Date(value).toISOString();
}

function SummaryCard({
  label,
  value,
  hint,
  icon: Icon,
}: {
  label: string;
  value: string | number;
  hint: string;
  icon: React.ComponentType<{ className?: string }>;
}) {
  return (
    <div className="rounded-2xl bg-[var(--bg-surface)] p-5 shadow-[var(--shadow-soft)]">
      <div className="flex items-start justify-between gap-4">
        <div>
          <p className="text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">
            {label}
          </p>
          <p className="mt-2 font-mono text-3xl font-bold text-[var(--text-primary)]">{value}</p>
          <p className="mt-1 text-sm text-[var(--text-muted)]">{hint}</p>
        </div>
        <div className="rounded-xl bg-primary/10 p-3 text-primary">
          <Icon className="size-5" />
        </div>
      </div>
    </div>
  );
}

function EventLabel({ eventType }: { eventType: string }) {
  const labels: Record<string, string> = {
    billing_record_created: "สร้างรายการเรียกเก็บ",
    billing_record_status_changed: "เปลี่ยนสถานะใบแจ้งหนี้",
    payment_request_created: "สร้างคำขอชำระเงิน",
    payment_request_settled: "ยืนยันการชำระเงิน",
    payment_recorded: "บันทึกยอดโอน",
    payment_reconciled: "กระทบยอดสำเร็จ",
    payment_rejected: "ปฏิเสธรายการโอน",
    subscription_activated: "เปิดใช้งานแพ็กเกจ",
  };
  return <span>{labels[eventType] ?? eventType}</span>;
}

function deriveBillingPeriodEnd(start: string, plan: BillingPlan | null): string {
  if (!start || !plan) return "";

  const [yearText, monthText, dayText] = start.split("-");
  const startYear = Number(yearText);
  const startMonth = Number(monthText);
  const startDay = Number(dayText);
  if (
    !Number.isInteger(startYear) ||
    !Number.isInteger(startMonth) ||
    !Number.isInteger(startDay)
  ) {
    return "";
  }

  const startDate = new Date(Date.UTC(startYear, startMonth - 1, startDay));
  if (Number.isNaN(startDate.getTime())) return "";

  if (plan.duration_days) {
    const endDate = new Date(startDate);
    endDate.setUTCDate(endDate.getUTCDate() + plan.duration_days - 1);
    return endDate.toISOString().slice(0, 10);
  }

  if (plan.duration_months) {
    const monthIndex = startMonth - 1 + plan.duration_months;
    const nextYear = startYear + Math.floor(monthIndex / 12);
    const nextMonthIndex = monthIndex % 12;
    const nextMonthLastDay = new Date(Date.UTC(nextYear, nextMonthIndex + 1, 0)).getUTCDate();
    const candidateDay = Math.min(startDay, nextMonthLastDay);
    const nextPeriodStart = new Date(Date.UTC(nextYear, nextMonthIndex, candidateDay));
    const endDate = new Date(nextPeriodStart);
    endDate.setUTCDate(endDate.getUTCDate() - 1);
    return endDate.toISOString().slice(0, 10);
  }

  return "";
}

function planCapabilityHint(plan: BillingPlan | null): string | null {
  if (!plan) return null;
  if (plan.code === "free_trial") {
    return "ทดลองใช้งาน 7 วัน สำหรับ 1 คำค้น โดยยังไม่รวม export, ดาวน์โหลดเอกสาร, และการแจ้งเตือน";
  }
  return null;
}

type UpgradeOption = {
  targetPlanCode: string;
  title: string;
  description: string;
  immediateChangeCopy: string;
  beforePaymentCopy: string;
  waitInsteadCopy: string;
};

function todayIsoDate(): string {
  return new Date().toISOString().slice(0, 10);
}

function getUpgradeOptions(
  entitlements: EntitlementSummary | undefined,
  billingPlans: BillingPlan[],
): UpgradeOption[] {
  const planMap = new Map(billingPlans.map((plan) => [plan.code, plan]));
  const currentPlanCode = entitlements?.plan_code;
  if (currentPlanCode === "free_trial") {
    return ["one_time_search_pack", "monthly_membership"]
      .map((targetPlanCode) => {
        const plan = planMap.get(targetPlanCode);
        if (!plan) {
          return null;
        }
        return {
          targetPlanCode,
          title: `อัปเกรดเป็น ${plan.label}`,
          description:
            targetPlanCode === "one_time_search_pack"
              ? "ชำระครั้งเดียวเพื่อปลดล็อก export ดาวน์โหลดเอกสาร และการแจ้งเตือนสำหรับรอบแพ็กเกจนี้"
              : "เปลี่ยนเป็นแพ็กเกจรายเดือนเพื่อเพิ่มโควต้าเป็น 5 คำค้นและปลดล็อกทุกช่องทางการใช้งานทันทีหลังชำระสำเร็จ",
          immediateChangeCopy:
            targetPlanCode === "one_time_search_pack"
              ? "ปลดล็อกส่งออก Excel ดาวน์โหลดเอกสาร และการแจ้งเตือนทันที"
              : "ปลดล็อกส่งออก Excel ดาวน์โหลดเอกสาร และการแจ้งเตือนทันที",
          beforePaymentCopy:
            targetPlanCode === "one_time_search_pack"
              ? "เมื่อชำระสำเร็จ ระบบจะปลดล็อก export ดาวน์โหลดเอกสาร และการแจ้งเตือนทันทีในรอบแพ็กเกจนี้"
              : "เมื่อชำระสำเร็จ ระบบจะเพิ่มสิทธิ์เป็นแพ็กเกจรายเดือนและปลดล็อกทุกช่องทางทันที",
          waitInsteadCopy:
            targetPlanCode === "one_time_search_pack"
              ? "หากต้องการใช้ Free Trial ต่อก่อน กรุณารอจนกว่าจะสิ้นสุดแล้วค่อยอัปเกรด"
              : "หากต้องการใช้ Free Trial ต่อก่อน กรุณารอจนกว่าจะสิ้นสุดแล้วค่อยอัปเกรด",
        };
      })
      .filter((option): option is UpgradeOption => option !== null);
  }
  if (currentPlanCode === "one_time_search_pack") {
    const monthlyPlan = planMap.get("monthly_membership");
    if (!monthlyPlan) {
      return [];
    }
    return [
      {
        targetPlanCode: monthlyPlan.code,
        title: `อัปเกรดเป็น ${monthlyPlan.label}`,
        description:
          "เพิ่มโควต้าเป็น 5 คำค้น และเปลี่ยนเป็นรอบสมาชิกรายเดือนหลังการชำระสำเร็จ",
        immediateChangeCopy: "โควต้าคำค้นจะเพิ่มเป็น 5 และเปิดสิทธิ์รายเดือนทันที",
        beforePaymentCopy:
          "เมื่อชำระสำเร็จ ระบบจะเปลี่ยนจากแพ็กเกจ one-shot เป็นสมาชิกรายเดือนทันที และโควต้าคำค้นจะเพิ่มเป็น 5",
        waitInsteadCopy:
          "หากต้องการใช้แพ็กเกจ one-shot ปัจจุบันต่อก่อน กรุณารอจนกว่าจะสิ้นสุดแล้วค่อยอัปเกรด",
      },
    ];
  }
  return [];
}

function describeUpgradeSettlement(record: BillingRecordDetail["record"]): {
  title: string;
  primary: string;
  secondary: string;
} {
  if (record.upgrade_mode === "replace_on_activation") {
    return {
      title: "รอเริ่มใช้งานตามรอบใหม่",
      primary: "ชำระเงินสำเร็จแล้ว ระบบจะเปิดแพ็กเกจใหม่ตามวันเริ่มรอบที่กำหนดไว้",
      secondary: "แพ็กเกจปัจจุบันยังใช้งานได้ต่อจนกว่าจะถึงวันเริ่มของแพ็กเกจใหม่",
    };
  }
  return {
    title: "สิ่งที่จะเปลี่ยนทันทีหลังชำระสำเร็จ",
    primary:
      record.plan_code === "monthly_membership"
        ? "ปลดล็อกส่งออก Excel ดาวน์โหลดเอกสาร และการแจ้งเตือนทันที"
        : "ปลดล็อก export ดาวน์โหลดเอกสาร และการแจ้งเตือนทันทีหลังชำระสำเร็จ",
    secondary: "แพ็กเกจเดิมจะถูกแทนที่เมื่อการชำระเงินสำเร็จ",
  };
}

function UpgradeCallout({
  entitlements,
  billingPlans,
  busy,
  busyPlanCode,
  errorMessage,
  statusMessage,
  onUpgrade,
}: {
  entitlements: EntitlementSummary | undefined;
  billingPlans: BillingPlan[];
  busy: boolean;
  busyPlanCode: string | null;
  errorMessage: string | null;
  statusMessage: string | null;
  onUpgrade: (targetPlanCode: string, optionTitle: string) => Promise<void>;
}) {
  const options = getUpgradeOptions(entitlements, billingPlans);
  if (options.length === 0) {
    return null;
  }
  const title =
    entitlements?.plan_code === "free_trial"
      ? "อัปเกรดจาก Free Trial"
      : "อัปเกรดจาก One-Time Search Pack";
  return (
    <div className="rounded-2xl border border-primary/15 bg-[linear-gradient(135deg,rgba(22,163,74,0.08),rgba(14,116,144,0.08))] p-5 shadow-[var(--shadow-soft)]">
      <div className="flex flex-col gap-2">
        <p className="text-xs font-semibold uppercase tracking-wider text-primary">
          Upgrade Channel
        </p>
        <h2 className="text-lg font-bold text-[var(--text-primary)]">{title}</h2>
        <p className="text-sm text-[var(--text-muted)]">
          ระบบจะสร้างใบเรียกเก็บสำหรับการอัปเกรดและเปิด PromptPay QR ให้ทันที เพื่อให้ลูกค้าชำระและเปลี่ยนสิทธิ์ได้ใน flow เดียว
        </p>
      </div>

      {statusMessage ? (
        <div className="mt-4 rounded-xl border border-emerald-200 bg-emerald-50 px-3 py-2 text-sm text-emerald-700">
          {statusMessage}
        </div>
      ) : null}

      {errorMessage ? (
        <div className="mt-4 rounded-xl border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
          {errorMessage}
        </div>
      ) : null}

      <div className="mt-4 grid gap-3">
        {options.map((option) => (
          <div
            key={option.targetPlanCode}
            className="rounded-2xl border border-primary/15 bg-white/70 p-4"
          >
            <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
              <div>
                <p className="font-semibold text-[var(--text-primary)]">{option.title}</p>
                <p className="mt-1 text-sm text-[var(--text-muted)]">{option.description}</p>
                <p className="mt-2 text-sm font-medium text-primary">{option.beforePaymentCopy}</p>
                <p className="mt-1 text-sm text-[var(--text-secondary)]">{option.waitInsteadCopy}</p>
              </div>
              <button
                type="button"
                disabled={busy}
                onClick={() => void onUpgrade(option.targetPlanCode, option.title)}
                className="rounded-xl bg-primary px-4 py-2.5 text-sm font-semibold text-white transition-colors hover:bg-primary-hover disabled:cursor-not-allowed disabled:opacity-60"
              >
                {busyPlanCode === option.targetPlanCode ? "กำลังสร้างคำขอ..." : option.title}
              </button>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

export default function BillingPage() {
  const searchParams = useSearchParams();
  const queryClient = useQueryClient();
  const { data, isLoading, isError, error } = useBillingRecords();
  const { data: plansData } = useBillingPlans();
  const { data: rulesData } = useRules();
  const notice = searchParams.get("notice");
  const [selectedRecordId, setSelectedRecordId] = useState("");
  const [recordNumber, setRecordNumber] = useState("");
  const [planCode, setPlanCode] = useState("monthly_membership");
  const [periodStart, setPeriodStart] = useState("2026-04-01");
  const [periodEnd, setPeriodEnd] = useState("2026-04-30");
  const [dueAt, setDueAt] = useState("2026-04-15T16:00");
  const [amountDue, setAmountDue] = useState("1500.00");
  const [recordNotes, setRecordNotes] = useState("");
  const [paymentAmount, setPaymentAmount] = useState("");
  const [paymentReference, setPaymentReference] = useState("");
  const [paymentReceivedAt, setPaymentReceivedAt] = useState("2026-04-16T10:30");
  const [paymentNote, setPaymentNote] = useState("");
  const [paymentRequestMethod, setPaymentRequestMethod] = useState<"promptpay_qr" | "card">(
    "promptpay_qr",
  );
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [paymentError, setPaymentError] = useState<string | null>(null);
  const [upgradeError, setUpgradeError] = useState<string | null>(null);
  const [upgradeStatusMessage, setUpgradeStatusMessage] = useState<string | null>(null);
  const [renderedQrSvg, setRenderedQrSvg] = useState("");
  const [actionBusy, setActionBusy] = useState(false);
  const [upgradeInFlightPlanCode, setUpgradeInFlightPlanCode] = useState<string | null>(null);
  const [upgradeCopy, setUpgradeCopy] = useState<string | null>(null);

  const records = data?.records ?? EMPTY_RECORDS;
  const billingPlans = plansData?.plans ?? [];
  const selectedPlan = billingPlans.find((plan) => plan.code === planCode) ?? null;
  const planLabels = new Map(billingPlans.map((plan) => [plan.code, plan.label]));
  const summary = data?.summary ?? {
    open_records: 0,
    awaiting_reconciliation: 0,
    outstanding_amount: "0.00",
    collected_amount: "0.00",
  };

  useEffect(() => {
    if (!selectedPlan) return;
    setAmountDue(selectedPlan.amount_due);
    const derivedEnd = deriveBillingPeriodEnd(periodStart, selectedPlan);
    if (derivedEnd) {
      setPeriodEnd(derivedEnd);
    }
  }, [selectedPlan, periodStart]);

  useEffect(() => {
    if (records.length === 0) {
      setSelectedRecordId("");
      return;
    }
    if (!selectedRecordId || !records.some((item) => item.record.id === selectedRecordId)) {
      setSelectedRecordId(records[0].record.id);
      setPaymentAmount(records[0].record.outstanding_balance);
    }
  }, [records, selectedRecordId]);

  const selectedRecord =
    records.find((item) => item.record.id === selectedRecordId) ?? records[0] ?? null;
  const latestPaymentRequest = selectedRecord?.payment_requests[0] ?? null;
  const latestRequestIsPromptPay = latestPaymentRequest?.payment_method === "promptpay_qr";
  const latestRequestIsCard = latestPaymentRequest?.payment_method === "card";

  useEffect(() => {
    let cancelled = false;
    const payload = latestRequestIsPromptPay ? latestPaymentRequest?.qr_payload : "";
    if (!payload) {
      setRenderedQrSvg("");
      return () => {
        cancelled = true;
      };
    }
    void QRCode.toString(payload, {
      errorCorrectionLevel: "M",
      margin: 1,
      type: "svg",
      color: {
        dark: "#111827",
        light: "#ffffff",
      },
    })
      .then((svg: string) => {
        if (!cancelled) {
          setRenderedQrSvg(svg);
        }
      })
      .catch(() => {
        if (!cancelled) {
          setRenderedQrSvg(latestPaymentRequest?.qr_svg ?? "");
        }
      });
    return () => {
      cancelled = true;
    };
  }, [latestPaymentRequest, latestRequestIsPromptPay]);

  async function refreshBilling() {
    await queryClient.invalidateQueries({ queryKey: ["billing-records"] });
    await queryClient.invalidateQueries({ queryKey: ["rules"] });
  }

  async function createPromptPayRequestForRecord(recordId: string) {
    return createBillingPaymentRequest(recordId, {
      provider: "opn",
      payment_method: "promptpay_qr",
      expires_in_minutes: 30,
    });
  }

  async function handleCreateRecord(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSubmitError(null);
    setActionBusy(true);
    try {
      const created = await createBillingRecord({
        record_number: recordNumber.trim(),
        plan_code: planCode.trim(),
        status: "draft",
        billing_period_start: periodStart,
        billing_period_end: periodEnd || undefined,
        due_at: toIsoOrUndefined(dueAt),
        amount_due: amountDue.trim() || undefined,
        notes: recordNotes.trim() || undefined,
      });
      setRecordNumber("");
      setRecordNotes("");
      await refreshBilling();
      setSelectedRecordId(created.record.id);
      setPaymentAmount(created.record.outstanding_balance);
    } catch (mutationError) {
      setSubmitError(
        localizeApiError(mutationError, "ไม่สามารถสร้างรายการเรียกเก็บได้"),
      );
    } finally {
      setActionBusy(false);
    }
  }

  async function handleRecordPayment(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selectedRecord) return;
    setPaymentError(null);
    setActionBusy(true);
    try {
      await recordBillingPayment(selectedRecord.record.id, {
        amount: paymentAmount.trim(),
        reference_code: paymentReference.trim() || undefined,
        received_at: toIsoOrUndefined(paymentReceivedAt) ?? new Date().toISOString(),
        note: paymentNote.trim() || undefined,
      });
      setPaymentReference("");
      setPaymentNote("");
      await refreshBilling();
    } catch (mutationError) {
      setPaymentError(
        localizeApiError(mutationError, "ไม่สามารถบันทึกรายการโอนได้"),
      );
    } finally {
      setActionBusy(false);
    }
  }

  async function handleReconcile(paymentId: string, status: "reconciled" | "rejected") {
    setPaymentError(null);
    setActionBusy(true);
    try {
      const detail = await reconcileBillingPayment(paymentId, { status });
      await refreshBilling();
      setSelectedRecordId(detail.record.id);
      setPaymentAmount(detail.record.outstanding_balance);
    } catch (mutationError) {
      setPaymentError(
        localizeApiError(mutationError, "ไม่สามารถกระทบยอดได้"),
      );
    } finally {
      setActionBusy(false);
    }
  }

  async function handleTransition(status: string, note: string) {
    if (!selectedRecord) return;
    setPaymentError(null);
    setActionBusy(true);
    try {
      const detail = await transitionBillingRecord(selectedRecord.record.id, { status, note });
      await refreshBilling();
      setSelectedRecordId(detail.record.id);
    } catch (mutationError) {
      setPaymentError(
        localizeApiError(mutationError, "ไม่สามารถเปลี่ยนสถานะบิลได้"),
      );
    } finally {
      setActionBusy(false);
    }
  }

  async function handleCreatePaymentRequest() {
    if (!selectedRecord) return;
    setPaymentError(null);
    setActionBusy(true);
    try {
      const detail = await createBillingPaymentRequest(selectedRecord.record.id, {
        provider: "opn",
        payment_method: paymentRequestMethod,
      });
      await refreshBilling();
      setSelectedRecordId(detail.record.id);
    } catch (mutationError) {
      setPaymentError(
        localizeApiError(
          mutationError,
          paymentRequestMethod === "card"
            ? "ไม่สามารถสร้างลิงก์ชำระด้วยบัตรได้"
            : "ไม่สามารถสร้าง PromptPay QR ได้",
        ),
      );
    } finally {
      setActionBusy(false);
    }
  }

  async function handleCreateUpgrade(targetPlanCode: string, optionTitle: string) {
    setSubmitError(null);
    setPaymentError(null);
    setUpgradeError(null);
    setUpgradeStatusMessage(null);
    setUpgradeCopy(null);
    setUpgradeInFlightPlanCode(targetPlanCode);
    setActionBusy(true);
    try {
      const upgrade = await createBillingUpgrade({
        target_plan_code: targetPlanCode,
        billing_period_start: todayIsoDate(),
      });
      const detail = await createPromptPayRequestForRecord(upgrade.record.id);
      await refreshBilling();
      setSelectedRecordId(detail.record.id);
      setPaymentAmount(detail.record.outstanding_balance);
      setUpgradeStatusMessage(
        `สร้างคำขอ ${optionTitle} แล้ว กรุณาสแกน PromptPay QR เพื่อชำระเงิน`,
      );
      setUpgradeCopy(
        targetPlanCode === "monthly_membership"
          ? "ปลดล็อกส่งออก Excel ดาวน์โหลดเอกสาร และการแจ้งเตือนทันที"
          : "ปลดล็อก export ดาวน์โหลดเอกสาร และการแจ้งเตือนทันทีหลังชำระสำเร็จ",
      );
    } catch (mutationError) {
      setUpgradeError(localizeApiError(mutationError, "ไม่สามารถเริ่มคำขออัปเกรดได้"));
    } finally {
      setActionBusy(false);
      setUpgradeInFlightPlanCode(null);
    }
  }

  async function handleStartFreeTrial() {
    setSubmitError(null);
    setActionBusy(true);
    try {
      await startFreeTrial();
      await refreshBilling();
    } catch (mutationError) {
      setSubmitError(
        localizeApiError(mutationError, "ไม่สามารถเริ่ม Free Trial ได้"),
      );
    } finally {
      setActionBusy(false);
    }
  }

  const canRecordPayment = selectedRecord
    ? ["issued", "awaiting_payment", "overdue", "payment_detected"].includes(
        selectedRecord.record.status,
      )
    : false;
  const canGeneratePaymentRequest = selectedRecord
    ? ["draft", "issued", "awaiting_payment", "overdue", "payment_detected"].includes(
        selectedRecord.record.status,
      ) && selectedRecord.record.outstanding_balance !== "0.00"
    : false;

  return (
    <>
      <PageHeader
        title="บิลและชำระเงิน"
        subtitle="สร้างใบแจ้งหนี้ตามแพ็กเกจจริง ออกบิล ติดตามยอดชำระ และดูสถานะการเปิดสิทธิ์ใช้งาน"
      />

      {notice === "payment_overdue" ? (
        <div className="mt-6 rounded-2xl border border-amber-200 bg-amber-50 px-5 py-4 text-sm text-amber-900 shadow-[var(--shadow-soft)]">
          <p className="font-semibold">กรุณาอัปเดตการชำระเงินก่อนดำเนินการต่อ</p>
          <p className="mt-1">
            ระบบพาคุณมายังหน้าชำระเงินแล้ว กรุณาตรวจสอบบิลที่เกินกำหนดและดำเนินการชำระก่อนกลับไปใช้งานส่วนอื่น
          </p>
        </div>
      ) : null}

      <div className="grid grid-cols-1 gap-6 md:grid-cols-4">
        <SummaryCard
          label="บิลที่ยังเปิดอยู่"
          value={summary.open_records}
          hint="ยังไม่ปิดสถานะทางการเงิน"
          icon={ReceiptText}
        />
        <SummaryCard
          label="รอตรวจสอบยอดโอน"
          value={summary.awaiting_reconciliation}
          hint="รายการโอนที่ยังไม่กระทบยอด"
          icon={ArrowRightLeft}
        />
        <SummaryCard
          label="ยอดคงค้าง"
          value={formatBudget(summary.outstanding_amount)}
          hint="ยอดที่ยังเก็บไม่ครบ"
          icon={Landmark}
        />
        <SummaryCard
          label="ยอดเก็บแล้ว"
          value={formatBudget(summary.collected_amount)}
          hint="เฉพาะยอดที่กระทบยอดแล้ว"
          icon={Landmark}
        />
      </div>

      <div className="mt-6 grid grid-cols-1 gap-6 xl:grid-cols-[420px_minmax(0,1fr)]">
        <div className="space-y-6">
          <UpgradeCallout
            entitlements={rulesData?.entitlements}
            billingPlans={billingPlans}
            busy={actionBusy}
            busyPlanCode={upgradeInFlightPlanCode}
            errorMessage={upgradeError}
            statusMessage={upgradeStatusMessage}
            onUpgrade={handleCreateUpgrade}
          />

          <form
            onSubmit={(event) => void handleCreateRecord(event)}
            className="rounded-2xl bg-[var(--bg-surface)] p-6 shadow-[var(--shadow-soft)]"
          >
            <div className="flex items-center justify-between gap-4">
              <div>
                <h2 className="text-lg font-bold text-[var(--text-primary)]">สร้างรายการเรียกเก็บ</h2>
                <p className="mt-1 text-sm text-[var(--text-muted)]">
                  เริ่มจากร่างใบแจ้งหนี้ แล้วค่อยออกบิลและรอชำระตาม lifecycle จริง
                </p>
              </div>
              <div className="flex items-center gap-3">
                <StatusBadge state="draft" variant="billing" />
                <button
                  type="button"
                  disabled={actionBusy}
                  onClick={() => void handleStartFreeTrial()}
                  className="rounded-xl border border-primary/30 bg-primary/5 px-3 py-2 text-sm font-semibold text-primary transition-colors hover:border-primary disabled:cursor-not-allowed disabled:opacity-60"
                >
                  เริ่ม Free Trial
                </button>
              </div>
            </div>

            <div className="mt-5 grid grid-cols-1 gap-4">
              <label className="text-sm text-[var(--text-secondary)]">
                เลขที่บิล
                <input
                  value={recordNumber}
                  onChange={(event) => setRecordNumber(event.target.value)}
                  placeholder="INV-2026-0002"
                  className="mt-1 w-full rounded-xl border border-[var(--border-default)] bg-[var(--bg-surface-secondary)] px-3 py-2.5 text-sm text-[var(--text-primary)] outline-none"
                  required
                />
              </label>

              <label className="text-sm text-[var(--text-secondary)]">
                แผนราคา
                <select
                  value={planCode}
                  onChange={(event) => setPlanCode(event.target.value)}
                  className="mt-1 w-full rounded-xl border border-[var(--border-default)] bg-[var(--bg-surface-secondary)] px-3 py-2.5 text-sm text-[var(--text-primary)] outline-none"
                  required
                >
                  {billingPlans.map((plan) => (
                    <option key={plan.code} value={plan.code}>
                      {plan.label}
                    </option>
                  ))}
                </select>
                {selectedPlan ? (
                  <>
                    <span className="mt-1 block text-xs text-[var(--text-muted)]">
                      {selectedPlan.description}
                    </span>
                    {planCapabilityHint(selectedPlan) ? (
                      <span className="mt-1 block text-xs text-primary">
                        {planCapabilityHint(selectedPlan)}
                      </span>
                    ) : null}
                  </>
                ) : null}
              </label>

              <div className="grid grid-cols-2 gap-4">
                <label className="text-sm text-[var(--text-secondary)]">
                  รอบบิลเริ่ม
                  <input
                    type="date"
                    value={periodStart}
                    onChange={(event) => setPeriodStart(event.target.value)}
                    className="mt-1 w-full rounded-xl border border-[var(--border-default)] bg-[var(--bg-surface-secondary)] px-3 py-2.5 text-sm text-[var(--text-primary)] outline-none"
                    required
                  />
                </label>
                <label className="text-sm text-[var(--text-secondary)]">
                  รอบบิลสิ้นสุด
                  <input
                    type="date"
                    value={periodEnd}
                    onChange={(event) => setPeriodEnd(event.target.value)}
                    className="mt-1 w-full rounded-xl border border-[var(--border-default)] bg-[var(--bg-surface-secondary)] px-3 py-2.5 text-sm text-[var(--text-primary)] outline-none"
                    required
                    readOnly={!!selectedPlan}
                  />
                </label>
              </div>

              <div className="grid grid-cols-2 gap-4">
                <label className="text-sm text-[var(--text-secondary)]">
                  กำหนดชำระ
                  <input
                    type="datetime-local"
                    value={dueAt}
                    onChange={(event) => setDueAt(event.target.value)}
                    className="mt-1 w-full rounded-xl border border-[var(--border-default)] bg-[var(--bg-surface-secondary)] px-3 py-2.5 text-sm text-[var(--text-primary)] outline-none"
                  />
                </label>
                <label className="text-sm text-[var(--text-secondary)]">
                  ยอดเรียกเก็บ
                  <input
                    value={amountDue}
                    onChange={(event) => setAmountDue(event.target.value)}
                    className="mt-1 w-full rounded-xl border border-[var(--border-default)] bg-[var(--bg-surface-secondary)] px-3 py-2.5 text-sm text-[var(--text-primary)] outline-none"
                    required
                    readOnly={!!selectedPlan}
                  />
                </label>
              </div>

              <label className="text-sm text-[var(--text-secondary)]">
                หมายเหตุ
                <textarea
                  value={recordNotes}
                  onChange={(event) => setRecordNotes(event.target.value)}
                  rows={3}
                  className="mt-1 w-full rounded-xl border border-[var(--border-default)] bg-[var(--bg-surface-secondary)] px-3 py-2.5 text-sm text-[var(--text-primary)] outline-none"
                  placeholder="เช่น รอบใช้งานเดือนเมษายน / internal beta"
                />
              </label>
            </div>

            {submitError ? (
              <div className="mt-4 rounded-xl border border-[var(--badge-red-bg)] bg-red-50 px-3 py-2 text-sm text-[var(--badge-red-text)]">
                {submitError}
              </div>
            ) : null}

            <button
              type="submit"
              disabled={actionBusy}
              className="mt-5 w-full rounded-xl bg-primary px-4 py-3 text-sm font-semibold text-white transition-colors hover:bg-primary-hover disabled:cursor-not-allowed disabled:opacity-60"
            >
              {actionBusy ? "กำลังบันทึก..." : "สร้างร่างใบแจ้งหนี้"}
            </button>
          </form>
        </div>

        <QueryState
          isLoading={isLoading}
          isError={isError}
          error={error instanceof Error ? error : undefined}
          isEmpty={!isLoading && records.length === 0}
          emptyMessage="ยังไม่มีรายการเรียกเก็บใน tenant นี้"
        >
          <div className="grid grid-cols-1 gap-6 2xl:grid-cols-[minmax(0,1.1fr)_minmax(420px,0.9fr)]">
            <div className="rounded-2xl bg-[var(--bg-surface)] p-6 shadow-[var(--shadow-soft)]">
              <div className="mb-4 flex items-center justify-between gap-4">
                <div>
                  <h2 className="text-lg font-bold text-[var(--text-primary)]">รายการเรียกเก็บ</h2>
                  <p className="mt-1 text-sm text-[var(--text-muted)]">
                    เลือกรายการเพื่อดูประวัติการชำระและการกระทบยอด
                  </p>
                </div>
                <span className="rounded-full bg-[var(--bg-surface-secondary)] px-3 py-1 text-xs font-semibold text-[var(--text-secondary)]">
                  {data?.total ?? 0} รายการ
                </span>
              </div>

              <div className="space-y-3">
                {records.map((detail) => {
                  const isSelected = detail.record.id === selectedRecord?.record.id;
                  return (
                    <button
                      key={detail.record.id}
                      type="button"
                      onClick={() => {
                        setSelectedRecordId(detail.record.id);
                        setPaymentAmount(detail.record.outstanding_balance);
                      }}
                      className={`w-full rounded-2xl border p-4 text-left transition-colors ${
                        isSelected
                          ? "border-primary bg-primary/5"
                          : "border-[var(--border-default)] bg-[var(--bg-surface-secondary)] hover:border-primary/40"
                      }`}
                    >
                      <div className="flex flex-wrap items-start justify-between gap-3">
                        <div>
                          <div className="flex items-center gap-2">
                            <p className="font-mono text-sm font-semibold text-[var(--text-primary)]">
                              {detail.record.record_number}
                            </p>
                            <StatusBadge state={detail.record.status} variant="billing" />
                          </div>
                          <p className="mt-1 text-sm text-[var(--text-secondary)]">
                            แผน {planLabels.get(detail.record.plan_code) ?? detail.record.plan_code} • รอบ{" "}
                            {detail.record.billing_period_start} ถึง {detail.record.billing_period_end}
                          </p>
                        </div>
                        <div className="text-right">
                          <p className="font-mono text-lg font-bold text-[var(--text-primary)]">
                            {formatBudget(detail.record.amount_due)}
                          </p>
                          <p className="text-xs text-[var(--text-muted)]">
                            คงค้าง {formatBudget(detail.record.outstanding_balance)}
                          </p>
                        </div>
                      </div>
                    </button>
                  );
                })}
              </div>
            </div>

            {selectedRecord ? (
              <div className="space-y-6">
                <div className="rounded-2xl bg-[var(--bg-surface)] p-6 shadow-[var(--shadow-soft)]">
                  <div className="flex flex-wrap items-start justify-between gap-4">
                    <div>
                      <p className="text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">
                        รายการที่เลือก
                      </p>
                      <h2 className="mt-1 font-mono text-2xl font-bold text-[var(--text-primary)]">
                        {selectedRecord.record.record_number}
                      </h2>
                      <p className="mt-1 text-sm text-[var(--text-secondary)]">
                        กำหนดชำระ {formatThaiDate(selectedRecord.record.due_at)}
                      </p>
                      <p className="mt-1 text-sm text-[var(--text-muted)]">
                        {planLabels.get(selectedRecord.record.plan_code) ??
                          selectedRecord.record.plan_code}
                      </p>
                    </div>
                    <StatusBadge state={selectedRecord.record.status} variant="billing" />
                  </div>

                  <div className="mt-4 flex flex-wrap gap-2">
                    {selectedRecord.record.status === "draft" ? (
                      <button
                        type="button"
                        disabled={actionBusy}
                        onClick={() => void handleTransition("issued", "Invoice issued to customer")}
                        className="rounded-xl border border-[var(--border-default)] px-3 py-2 text-sm font-semibold text-[var(--text-primary)] transition-colors hover:border-primary disabled:cursor-not-allowed disabled:opacity-60"
                      >
                        ออกบิล
                      </button>
                    ) : null}
                    {selectedRecord.record.status === "issued" ? (
                      <button
                        type="button"
                        disabled={actionBusy}
                        onClick={() =>
                          void handleTransition("awaiting_payment", "Customer payment requested")
                        }
                        className="rounded-xl border border-[var(--border-default)] px-3 py-2 text-sm font-semibold text-[var(--text-primary)] transition-colors hover:border-primary disabled:cursor-not-allowed disabled:opacity-60"
                      >
                        ตั้งเป็นรอชำระ
                      </button>
                    ) : null}
                    {selectedRecord.record.status === "awaiting_payment" ? (
                      <button
                        type="button"
                        disabled={actionBusy}
                        onClick={() => void handleTransition("overdue", "Invoice is past due")}
                        className="rounded-xl border border-[var(--border-default)] px-3 py-2 text-sm font-semibold text-[var(--text-primary)] transition-colors hover:border-primary disabled:cursor-not-allowed disabled:opacity-60"
                      >
                        ทำเครื่องหมายเกินกำหนด
                      </button>
                    ) : null}
                    {selectedRecord.record.status === "overdue" ? (
                      <button
                        type="button"
                        disabled={actionBusy}
                        onClick={() =>
                          void handleTransition("awaiting_payment", "Payment follow-up resumed")
                        }
                        className="rounded-xl border border-[var(--border-default)] px-3 py-2 text-sm font-semibold text-[var(--text-primary)] transition-colors hover:border-primary disabled:cursor-not-allowed disabled:opacity-60"
                      >
                        กลับไปรอชำระ
                      </button>
                    ) : null}
                    {canGeneratePaymentRequest ? (
                      <div className="flex items-center gap-2">
                        <select
                          value={paymentRequestMethod}
                          onChange={(event) =>
                            setPaymentRequestMethod(
                              event.target.value === "card" ? "card" : "promptpay_qr",
                            )
                          }
                          disabled={actionBusy}
                          className="rounded-xl border border-[var(--border-default)] bg-[var(--bg-surface-secondary)] px-3 py-2 text-sm text-[var(--text-primary)] outline-none disabled:cursor-not-allowed disabled:opacity-60"
                        >
                          <option value="promptpay_qr">PromptPay QR</option>
                          <option value="card">บัตรเครดิต/เดบิต</option>
                        </select>
                        <button
                          type="button"
                          disabled={actionBusy}
                          onClick={() => void handleCreatePaymentRequest()}
                          className="rounded-xl border border-primary/30 bg-primary/5 px-3 py-2 text-sm font-semibold text-primary transition-colors hover:border-primary disabled:cursor-not-allowed disabled:opacity-60"
                        >
                          {paymentRequestMethod === "card"
                            ? "สร้างลิงก์ชำระด้วยบัตร"
                            : "สร้าง PromptPay QR"}
                        </button>
                      </div>
                    ) : null}
                    {["draft", "issued", "awaiting_payment", "overdue", "failed", "payment_detected"].includes(
                      selectedRecord.record.status,
                    ) ? (
                      <button
                        type="button"
                        disabled={actionBusy}
                        onClick={() => void handleTransition("cancelled", "Invoice cancelled")}
                        className="rounded-xl border border-[var(--badge-red-bg)] px-3 py-2 text-sm font-semibold text-[var(--badge-red-text)] transition-colors hover:bg-red-50 disabled:cursor-not-allowed disabled:opacity-60"
                      >
                        ยกเลิกบิล
                      </button>
                    ) : null}
                  </div>

                  <div className="mt-5 grid grid-cols-2 gap-4">
                    <div className="rounded-xl bg-[var(--bg-surface-secondary)] px-4 py-3">
                      <p className="text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">
                        ยอดเรียกเก็บ
                      </p>
                      <p className="mt-1 font-mono text-xl font-bold text-[var(--text-primary)]">
                        {formatBudget(selectedRecord.record.amount_due)}
                      </p>
                    </div>
                    <div className="rounded-xl bg-[var(--bg-surface-secondary)] px-4 py-3">
                      <p className="text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">
                        ยอดกระทบแล้ว
                      </p>
                      <p className="mt-1 font-mono text-xl font-bold text-[var(--text-primary)]">
                        {formatBudget(selectedRecord.record.reconciled_total)}
                      </p>
                    </div>
                  </div>

                  {selectedRecord.subscription ? (
                    <div className="mt-5 rounded-2xl border border-[var(--border-default)] bg-[var(--bg-surface-secondary)] p-4">
                      <div className="flex flex-wrap items-start justify-between gap-3">
                        <div>
                          <p className="text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">
                            สถานะแพ็กเกจ
                          </p>
                          <p className="mt-1 text-sm text-[var(--text-secondary)]">
                            ใช้งานตั้งแต่ {selectedRecord.subscription.billing_period_start} ถึง{" "}
                            {selectedRecord.subscription.billing_period_end}
                          </p>
                        </div>
                        <StatusBadge
                          state={selectedRecord.subscription.subscription_status}
                          variant="subscription"
                        />
                      </div>
                      <p className="mt-3 text-sm text-[var(--text-secondary)]">
                        สิทธิ์คีย์เวิร์ดสูงสุด{" "}
                        {selectedRecord.subscription.keyword_limit ?? "ไม่กำหนด"} รายการ
                      </p>
                    </div>
                  ) : null}

                  {selectedRecord.record.upgrade_from_subscription_id ? (
                    <div className="mt-5 rounded-2xl border border-amber-200 bg-amber-50 p-4">
                      <p className="text-xs font-semibold uppercase tracking-wider text-amber-900">
                        {describeUpgradeSettlement(selectedRecord.record).title}
                      </p>
                      <p className="mt-2 text-sm text-amber-800">
                        {upgradeCopy ?? describeUpgradeSettlement(selectedRecord.record).primary}
                      </p>
                      <p className="mt-2 text-sm text-amber-700">
                        {describeUpgradeSettlement(selectedRecord.record).secondary}
                      </p>
                    </div>
                  ) : null}

                  {latestPaymentRequest ? (
                    <div className="mt-5 rounded-2xl border border-primary/15 bg-primary/5 p-4">
                      <div className="flex flex-wrap items-start justify-between gap-3">
                        <div>
                          <p className="text-xs font-semibold uppercase tracking-wider text-primary">
                            {latestRequestIsCard ? "Card Checkout" : "PromptPay Request"}
                          </p>
                          <p className="mt-1 font-mono text-sm text-[var(--text-primary)]">
                            {latestPaymentRequest.provider_reference}
                          </p>
                          <p className="mt-1 text-sm text-[var(--text-muted)]">
                            หมดอายุ {formatThaiDate(latestPaymentRequest.expires_at)}
                          </p>
                        </div>
                        <StatusBadge state={latestPaymentRequest.status} variant="billing" />
                      </div>

                      {latestRequestIsPromptPay ? (
                        <div className="mt-4 grid grid-cols-1 gap-4 md:grid-cols-[200px_minmax(0,1fr)]">
                          <div
                            className="mx-auto w-[180px] rounded-2xl bg-white p-3 shadow-[var(--shadow-soft)]"
                            dangerouslySetInnerHTML={{
                              __html: renderedQrSvg || latestPaymentRequest.qr_svg,
                            }}
                          />
                          <div className="space-y-3">
                            <div>
                              <p className="text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">
                                Link ชำระเงิน
                              </p>
                              <a
                                href={latestPaymentRequest.payment_url}
                                target="_blank"
                                rel="noreferrer"
                                className="mt-1 block break-all text-sm font-medium text-primary underline decoration-primary/40 underline-offset-4"
                              >
                                {latestPaymentRequest.payment_url}
                              </a>
                            </div>
                            <div>
                              <p className="text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">
                                PromptPay Payload
                              </p>
                              <p className="mt-1 break-all rounded-xl bg-[var(--bg-surface)] px-3 py-2 font-mono text-xs text-[var(--text-secondary)]">
                                {latestPaymentRequest.qr_payload}
                              </p>
                            </div>
                          </div>
                        </div>
                      ) : null}

                      {latestRequestIsCard ? (
                        <div className="mt-4 rounded-2xl bg-[var(--bg-surface)] p-4">
                          <p className="text-sm text-[var(--text-secondary)]">
                            ส่งลูกค้าไปยังหน้าชำระเงินของ Opn เพื่อกรอกข้อมูลบัตรและยืนยัน 3DS ตามที่ธนาคารร้องขอ
                          </p>
                          <a
                            href={latestPaymentRequest.payment_url}
                            target="_blank"
                            rel="noreferrer"
                            className="mt-3 inline-flex items-center rounded-xl bg-primary px-4 py-2.5 text-sm font-semibold text-white transition-colors hover:bg-primary-hover"
                          >
                            เปิดหน้าชำระเงินด้วยบัตร
                          </a>
                          <p className="mt-3 break-all text-xs text-[var(--text-muted)]">
                            {latestPaymentRequest.payment_url}
                          </p>
                        </div>
                      ) : null}
                    </div>
                  ) : null}

                  <form
                    onSubmit={(event) => void handleRecordPayment(event)}
                    className="mt-5 rounded-2xl border border-dashed border-[var(--border-default)] p-4"
                  >
                    <div className="flex items-center justify-between gap-4">
                      <div>
                        <h3 className="font-semibold text-[var(--text-primary)]">บันทึกยอดโอนเข้า</h3>
                        <p className="mt-1 text-sm text-[var(--text-muted)]">
                          ใช้ reconciliation hook เดิมเพื่อขยับ invoice ไปสู่การเปิดสิทธิ์ใช้งาน
                        </p>
                      </div>
                      <StatusBadge state="pending_reconciliation" variant="payment" />
                    </div>

                    <div className="mt-4 grid grid-cols-1 gap-4 md:grid-cols-2">
                      <label className="text-sm text-[var(--text-secondary)]">
                        จำนวนเงิน
                        <input
                          value={paymentAmount}
                          onChange={(event) => setPaymentAmount(event.target.value)}
                          className="mt-1 w-full rounded-xl border border-[var(--border-default)] bg-[var(--bg-surface-secondary)] px-3 py-2.5 text-sm text-[var(--text-primary)] outline-none"
                          required
                        />
                      </label>
                      <label className="text-sm text-[var(--text-secondary)]">
                        เลขอ้างอิง
                        <input
                          value={paymentReference}
                          onChange={(event) => setPaymentReference(event.target.value)}
                          placeholder="KBANK-0004"
                          className="mt-1 w-full rounded-xl border border-[var(--border-default)] bg-[var(--bg-surface-secondary)] px-3 py-2.5 text-sm text-[var(--text-primary)] outline-none"
                        />
                      </label>
                      <label className="text-sm text-[var(--text-secondary)]">
                        เวลาได้รับยอด
                        <input
                          type="datetime-local"
                          value={paymentReceivedAt}
                          onChange={(event) => setPaymentReceivedAt(event.target.value)}
                          className="mt-1 w-full rounded-xl border border-[var(--border-default)] bg-[var(--bg-surface-secondary)] px-3 py-2.5 text-sm text-[var(--text-primary)] outline-none"
                          required
                        />
                      </label>
                      <label className="text-sm text-[var(--text-secondary)]">
                        หมายเหตุ
                        <input
                          value={paymentNote}
                          onChange={(event) => setPaymentNote(event.target.value)}
                          placeholder="ยืนยันจาก statement ธนาคาร"
                          className="mt-1 w-full rounded-xl border border-[var(--border-default)] bg-[var(--bg-surface-secondary)] px-3 py-2.5 text-sm text-[var(--text-primary)] outline-none"
                        />
                      </label>
                    </div>

                    {paymentError ? (
                      <div className="mt-4 rounded-xl border border-[var(--badge-red-bg)] bg-red-50 px-3 py-2 text-sm text-[var(--badge-red-text)]">
                        {paymentError}
                      </div>
                    ) : null}

                    <button
                      type="submit"
                      disabled={actionBusy || !canRecordPayment}
                      className="mt-4 rounded-xl bg-primary px-4 py-2.5 text-sm font-semibold text-white transition-colors hover:bg-primary-hover disabled:cursor-not-allowed disabled:opacity-60"
                    >
                      {actionBusy ? "กำลังบันทึก..." : "บันทึกรายการโอน"}
                    </button>
                    {!canRecordPayment ? (
                      <p className="mt-3 text-sm text-[var(--text-muted)]">
                        ต้องออกบิลหรือเปิดสถานะรอชำระก่อน จึงจะบันทึกยอดโอนได้
                      </p>
                    ) : null}
                  </form>
                </div>

                <div className="rounded-2xl bg-[var(--bg-surface)] p-6 shadow-[var(--shadow-soft)]">
                  <h3 className="text-lg font-bold text-[var(--text-primary)]">รายการโอนและการกระทบยอด</h3>
                  <div className="mt-4 space-y-3">
                    {selectedRecord.payments.length === 0 ? (
                      <p className="text-sm text-[var(--text-muted)]">ยังไม่มีรายการโอนสำหรับบิลนี้</p>
                    ) : (
                      selectedRecord.payments.map((payment) => (
                        <div
                          key={payment.id}
                          className="rounded-2xl border border-[var(--border-default)] bg-[var(--bg-surface-secondary)] p-4"
                        >
                          <div className="flex flex-wrap items-start justify-between gap-3">
                            <div>
                              <div className="flex items-center gap-2">
                                <StatusBadge state={payment.payment_status} variant="payment" />
                                <span className="font-mono text-sm text-[var(--text-secondary)]">
                                  {payment.reference_code ?? "ไม่มีเลขอ้างอิง"}
                                </span>
                              </div>
                              <p className="mt-2 font-mono text-lg font-bold text-[var(--text-primary)]">
                                {formatBudget(payment.amount)}
                              </p>
                              <p className="text-sm text-[var(--text-muted)]">
                                รับยอด {formatThaiDate(payment.received_at)}
                              </p>
                            </div>
                            {payment.payment_status === "pending_reconciliation" ? (
                              <div className="flex gap-2">
                                <button
                                  type="button"
                                  onClick={() => void handleReconcile(payment.id, "reconciled")}
                                  disabled={actionBusy}
                                  className="rounded-xl bg-primary px-3 py-2 text-sm font-semibold text-white transition-colors hover:bg-primary-hover disabled:cursor-not-allowed disabled:opacity-60"
                                >
                                  กระทบยอด
                                </button>
                                <button
                                  type="button"
                                  onClick={() => void handleReconcile(payment.id, "rejected")}
                                  disabled={actionBusy}
                                  className="rounded-xl border border-[var(--border-default)] px-3 py-2 text-sm font-semibold text-[var(--text-primary)] transition-colors hover:bg-[var(--bg-surface)] disabled:cursor-not-allowed disabled:opacity-60"
                                >
                                  ปฏิเสธ
                                </button>
                              </div>
                            ) : null}
                          </div>
                          {payment.note ? (
                            <p className="mt-3 text-sm text-[var(--text-muted)]">{payment.note}</p>
                          ) : null}
                        </div>
                      ))
                    )}
                  </div>
                </div>

                <div className="rounded-2xl bg-[var(--bg-surface)] p-6 shadow-[var(--shadow-soft)]">
                  <h3 className="text-lg font-bold text-[var(--text-primary)]">ประวัติการเปลี่ยนแปลง</h3>
                  <div className="mt-4 space-y-3">
                    {selectedRecord.events.map((eventItem) => (
                      <div
                        key={eventItem.id}
                        className="rounded-2xl border border-[var(--border-default)] bg-[var(--bg-surface-secondary)] p-4"
                      >
                        <div className="flex flex-wrap items-center justify-between gap-3">
                          <p className="font-medium text-[var(--text-primary)]">
                            <EventLabel eventType={eventItem.event_type} />
                          </p>
                          <p className="text-xs text-[var(--text-muted)]">
                            {formatThaiDate(eventItem.created_at)}
                          </p>
                        </div>
                        <p className="mt-2 text-sm text-[var(--text-muted)]">
                          {eventItem.from_status ? `${eventItem.from_status} -> ` : ""}
                          {eventItem.to_status ?? "ไม่เปลี่ยนสถานะ"}
                        </p>
                        {eventItem.note ? (
                          <p className="mt-1 text-sm text-[var(--text-secondary)]">{eventItem.note}</p>
                        ) : null}
                      </div>
                    ))}
                  </div>
                </div>
              </div>
            ) : null}
          </div>
        </QueryState>
      </div>
    </>
  );
}
