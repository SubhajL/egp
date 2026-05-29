import { describe, expect, it } from "vitest";

import { supportsCardPayment } from "../../src/lib/payment";

describe("supportsCardPayment", () => {
  it("is true only for acquirer-backed providers", () => {
    expect(supportsCardPayment("opn")).toBe(true);
    expect(supportsCardPayment("stripe")).toBe(true);
  });

  it("is false for manual / mock PromptPay (no card rails)", () => {
    expect(supportsCardPayment("promptpay_manual")).toBe(false);
    expect(supportsCardPayment("mock_promptpay")).toBe(false);
  });

  it("is false for unknown / missing provider", () => {
    expect(supportsCardPayment(undefined)).toBe(false);
    expect(supportsCardPayment(null)).toBe(false);
    expect(supportsCardPayment("")).toBe(false);
  });
});
