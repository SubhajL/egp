import { describe, expect, it } from "vitest";

import { getSiteBaseUrl } from "../../src/lib/site-url";

describe("getSiteBaseUrl", () => {
  it("falls back when the configured site URL is empty", () => {
    expect(getSiteBaseUrl("")).toBe("https://egp.example.com");
  });

  it("falls back when the configured site URL is whitespace", () => {
    expect(getSiteBaseUrl("   ")).toBe("https://egp.example.com");
  });

  it("trims and preserves a valid absolute site URL", () => {
    expect(getSiteBaseUrl(" https://app.egptracker.com ")).toBe("https://app.egptracker.com");
  });

  it("falls back when the configured site URL is not absolute", () => {
    expect(getSiteBaseUrl("not-a-url")).toBe("https://egp.example.com");
  });
});
