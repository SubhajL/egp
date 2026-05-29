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

// Append a prefilled ?text= message to a LINE add-friend / OA deep link.
// Returns null when no base URL is configured so callers can hide the button.
export function buildLinePaymentUrl(
  lineAddUrl: string | null | undefined,
  message: string,
): string | null {
  const base = (lineAddUrl ?? "").trim();
  if (!base) {
    return null;
  }
  const separator = base.includes("?") ? "&" : "?";
  return `${base}${separator}text=${encodeURIComponent(message)}`;
}
