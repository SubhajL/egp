import { describe, expect, it } from "vitest";

import { buildLinePaymentMessage, buildLinePaymentUrl } from "../../src/lib/line";

describe("buildLinePaymentMessage", () => {
  it("includes reference, plan, and amount", () => {
    const message = buildLinePaymentMessage({
      referenceCode: "INV-2026-0001",
      planLabel: "สมาชิกรายเดือน",
      amount: "1500.00",
    });
    expect(message).toContain("Reference: INV-2026-0001");
    expect(message).toContain("สมาชิกรายเดือน");
    expect(message).toContain("1500.00");
  });

  it("omits plan and amount when not provided", () => {
    const message = buildLinePaymentMessage({ referenceCode: "INV-2026-0002" });
    expect(message).toContain("Reference: INV-2026-0002");
    expect(message).not.toContain("แพ็กเกจ:");
    expect(message).not.toContain("จำนวนเงิน:");
  });
});

describe("buildLinePaymentUrl", () => {
  it("returns a /ti/p/ add-friend link UNCHANGED (it ignores ?text=, so we don't fake a prefill)", () => {
    const url = buildLinePaymentUrl("https://line.me/R/ti/p/@egptracker", "Reference: INV-1");
    expect(url).toBe("https://line.me/R/ti/p/@egptracker");
  });

  it("prefills an oaMessage-style url where ?text actually works", () => {
    const url = buildLinePaymentUrl("https://line.me/R/oaMessage/@egptracker/", "hi");
    expect(url).toBe("https://line.me/R/oaMessage/@egptracker/?" + encodeURIComponent("hi"));
  });

  it("returns null when no base url is configured", () => {
    expect(buildLinePaymentUrl("", "hi")).toBeNull();
    expect(buildLinePaymentUrl(null, "hi")).toBeNull();
    expect(buildLinePaymentUrl(undefined, "hi")).toBeNull();
  });
});
