import { describe, expect, it } from "vitest";

import {
  isPaymentRequestExpired,
  isUsablePendingPaymentRequest,
  type PaymentRequestLifecycleInput,
} from "../../src/lib/billing-payment-requests";

const NOW = new Date("2026-06-12T07:00:00.000Z");

function request(
  overrides: Partial<PaymentRequestLifecycleInput> = {},
): PaymentRequestLifecycleInput {
  return {
    status: "pending",
    expires_at: "2026-06-12T07:30:00.000Z",
    ...overrides,
  };
}

describe("isPaymentRequestExpired", () => {
  it("detects pending requests that expired before now", () => {
    expect(
      isPaymentRequestExpired(
        request({ expires_at: "2026-06-12T06:59:59.999Z" }),
        NOW,
      ),
    ).toBe(true);
  });

  it("detects pending requests that expire exactly at now", () => {
    expect(
      isPaymentRequestExpired(request({ expires_at: "2026-06-12T07:00:00.000Z" }), NOW),
    ).toBe(true);
  });

  it("keeps future pending requests usable", () => {
    expect(isPaymentRequestExpired(request(), NOW)).toBe(false);
    expect(isUsablePendingPaymentRequest(request(), NOW)).toBe(true);
  });

  it("does not expire non-pending requests", () => {
    expect(
      isPaymentRequestExpired(
        request({ status: "settled", expires_at: "2026-06-12T06:00:00.000Z" }),
        NOW,
      ),
    ).toBe(false);
  });

  it("treats missing or invalid expiry as not expired", () => {
    expect(isPaymentRequestExpired(request({ expires_at: null }), NOW)).toBe(false);
    expect(isPaymentRequestExpired(request({ expires_at: "not-a-date" }), NOW)).toBe(false);
  });

  it("does not treat expired pending requests as usable", () => {
    expect(
      isUsablePendingPaymentRequest(
        request({ expires_at: "2026-06-12T06:00:00.000Z" }),
        NOW,
      ),
    ).toBe(false);
  });
});
