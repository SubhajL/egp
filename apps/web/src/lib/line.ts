// Helpers for forwarding a customer into LINE OA with a prefilled payment
// message so they can send their PromptPay slip image to the operator.

export function buildLinePaymentMessage(params: {
  referenceCode: string;
  planLabel?: string | null;
  amount?: string | null;
}): string {
  const lines = ["ขอแจ้งชำระเงิน / ส่งสลิปการโอน"];
  if (params.planLabel) {
    lines.push(`แพ็กเกจ: ${params.planLabel}`);
  }
  if (params.amount) {
    lines.push(`จำนวนเงิน: ${params.amount} บาท`);
  }
  lines.push(`Reference: ${params.referenceCode}`);
  return lines.join("\n");
}

// Build the LINE deep link, prefilling the payment message only where LINE
// actually honors it. Returns null when no base URL is configured so callers
// can hide the button.
//
// IMPORTANT: the /ti/p/ add-friend & profile scheme silently ignores a text
// param, so we must NOT fake a prefill there (it gives false confidence that
// the reference was sent). For those links the UI conveys the reference via a
// copy button instead. Only the oaMessage scheme reliably prefills text.
export function buildLinePaymentUrl(
  lineAddUrl: string | null | undefined,
  message: string,
): string | null {
  const base = (lineAddUrl ?? "").trim();
  if (!base) {
    return null;
  }
  if (base.includes("/ti/p/")) {
    return base;
  }
  if (base.includes("/oaMessage/")) {
    const separator = base.includes("?") ? "&" : "?";
    return `${base}${separator}${encodeURIComponent(message)}`;
  }
  const separator = base.includes("?") ? "&" : "?";
  return `${base}${separator}text=${encodeURIComponent(message)}`;
}
