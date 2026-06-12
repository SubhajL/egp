export interface PaymentRequestLifecycleInput {
  status: string;
  expires_at: string | null;
}

export function isPaymentRequestExpired(
  request: PaymentRequestLifecycleInput | null | undefined,
  now: Date = new Date(),
): boolean {
  if (request?.status !== "pending" || !request.expires_at) {
    return false;
  }
  const expiresAtMs = Date.parse(request.expires_at);
  if (Number.isNaN(expiresAtMs)) {
    return false;
  }
  return expiresAtMs <= now.getTime();
}

export function isUsablePendingPaymentRequest(
  request: PaymentRequestLifecycleInput | null | undefined,
  now: Date = new Date(),
): boolean {
  return request?.status === "pending" && !isPaymentRequestExpired(request, now);
}
