import { describe, expect, it } from "vitest";

import { getUserDisplayName, getUserInitials, normalizeNextPath } from "../../src/lib/auth";
import type { AuthenticatedUser } from "../../src/lib/api";

function buildUser(overrides: Partial<AuthenticatedUser> = {}): AuthenticatedUser {
  return {
    id: "user-1",
    subject: "subject-1",
    email: "operator@example.com",
    full_name: "Ada Lovelace",
    role: "owner",
    status: "active",
    email_verified: true,
    email_verified_at: "2026-05-16T00:00:00Z",
    mfa_enabled: false,
    ...overrides,
  };
}

describe("auth view-model helpers", () => {
  it("prefers full name, then email, then subject", () => {
    expect(getUserDisplayName(buildUser())).toBe("Ada Lovelace");
    expect(getUserDisplayName(buildUser({ full_name: " ", email: "owner@example.com" }))).toBe(
      "owner@example.com",
    );
    expect(getUserDisplayName(buildUser({ full_name: null, email: " " }))).toBe("subject-1");
  });

  it("derives stable initials from display names", () => {
    expect(getUserInitials(buildUser())).toBe("AL");
    expect(getUserInitials(buildUser({ full_name: "Cher" }))).toBe("C");
    expect(getUserInitials(buildUser({ full_name: " ", email: " " }))).toBe("S");
  });
});

describe("normalizeNextPath", () => {
  const trustedBase = "https://app.example/";

  function expectSafeDestination(actual: string, expected: string) {
    expect(actual).toBe(expected);
    const parsed = new URL(actual, trustedBase);
    expect(parsed.origin).toBe(new URL(trustedBase).origin);
    expect(parsed.username).toBe("");
    expect(parsed.password).toBe("");
  }

  it.each([
    "/dashboard",
    "/security",
    "/security?tab=mfa#setup",
    "/projects/project-1?return=%2Fsecurity&value=%5Cname#section/%2F",
  ])("normalizes next paths by preserving safe app destination %s", (candidate) => {
    expectSafeDestination(normalizeNextPath(candidate), candidate);
  });

  it.each([
    [null, "/dashboard"],
    [undefined, "/dashboard"],
    ["", "/dashboard"],
    ["security", "/dashboard"],
    ["./security", "/dashboard"],
    ["https://attacker.invalid/path", "/dashboard"],
    ["http://attacker.invalid/path", "/dashboard"],
    ["javascript:alert(1)", "/dashboard"],
    ["data:text/html,attack", "/dashboard"],
    ["//attacker.invalid/path", "/dashboard"],
    ["//app.example/path", "/dashboard"],
    ["///attacker.invalid/path", "/dashboard"],
    ["\\attacker.invalid/path", "/dashboard"],
    ["/\\attacker.invalid/path", "/dashboard"],
    ["/\\/attacker.invalid/path", "/dashboard"],
    ["\\/attacker.invalid/path", "/dashboard"],
    ["/safe\\segment", "/dashboard"],
    ["/\t/attacker.invalid/path", "/dashboard"],
    ["/\n/attacker.invalid/path", "/dashboard"],
    ["/\r/attacker.invalid/path", "/dashboard"],
    ["/%2fattacker.invalid", "/dashboard"],
    ["/%2Fattacker.invalid", "/dashboard"],
    ["/%5cattacker.invalid", "/dashboard"],
    ["/%5Cattacker.invalid", "/dashboard"],
    ["/safe/%2Fsegment", "/dashboard"],
    ["/safe/%5csegment", "/dashboard"],
  ])("normalizes next paths by rejecting unsafe destination %j", (candidate, expected) => {
    expectSafeDestination(normalizeNextPath(candidate), expected);
  });

  it("normalizes next paths after the query parser decoding layer", () => {
    const decodedBackslash = new URLSearchParams("next=%2F%5Cattacker.invalid%2Fpath").get("next");
    const exposedEncodedSlash = new URLSearchParams("next=%2F%252Fattacker.invalid").get("next");
    const exposedEncodedBackslash = new URLSearchParams("next=%2F%255Cattacker.invalid").get(
      "next",
    );

    expectSafeDestination(normalizeNextPath(decodedBackslash), "/dashboard");
    expectSafeDestination(normalizeNextPath(exposedEncodedSlash), "/dashboard");
    expectSafeDestination(normalizeNextPath(exposedEncodedBackslash), "/dashboard");
  });

  it("normalizes next paths with a validated custom fallback", () => {
    expectSafeDestination(normalizeNextPath("/\\attacker.invalid", "/security?tab=mfa#setup"),
      "/security?tab=mfa#setup");
    expectSafeDestination(normalizeNextPath("/security", "/\\attacker.invalid"), "/security");
    expectSafeDestination(normalizeNextPath("/\\attacker.invalid", "//fallback.invalid"),
      "/dashboard");
  });
});
