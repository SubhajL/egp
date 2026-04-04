"use client";

import { FormEvent, useEffect, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { ArrowRightLeft, Landmark, ReceiptText } from "lucide-react";

import { PageHeader } from "@/components/layout/page-header";
import { QueryState } from "@/components/ui/query-state";
import { StatusBadge } from "@/components/ui/status-badge";
import {
  createBillingRecord,
  recordBillingPayment,
  reconcileBillingPayment,
  transitionBillingRecord,
  type BillingPlan,
  type BillingRecordDetail,
} from "@/lib/api";
import { useBillingPlans, useBillingRecords } from "@/lib/hooks";
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

export default function BillingPage() {
  const queryClient = useQueryClient();
  const { data, isLoading, isError, error } = useBillingRecords();
  const { data: plansData } = useBillingPlans();
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
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [paymentError, setPaymentError] = useState<string | null>(null);
  const [actionBusy, setActionBusy] = useState(false);

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

  async function refreshBilling() {
    await queryClient.invalidateQueries({ queryKey: ["billing-records"] });
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
        mutationError instanceof Error ? mutationError.message : "ไม่สามารถสร้างรายการเรียกเก็บได้",
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
        mutationError instanceof Error ? mutationError.message : "ไม่สามารถบันทึกรายการโอนได้",
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
        mutationError instanceof Error ? mutationError.message : "ไม่สามารถกระทบยอดได้",
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
        mutationError instanceof Error ? mutationError.message : "ไม่สามารถเปลี่ยนสถานะบิลได้",
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

  return (
    <>
      <PageHeader
        title="บิลและชำระเงิน"
        subtitle="สร้างใบแจ้งหนี้ตามแพ็กเกจจริง ออกบิล ติดตามยอดชำระ และดูสถานะการเปิดสิทธิ์ใช้งาน"
      />

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
            <StatusBadge state="draft" variant="billing" />
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
                <span className="mt-1 block text-xs text-[var(--text-muted)]">
                  {selectedPlan.description}
                </span>
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
