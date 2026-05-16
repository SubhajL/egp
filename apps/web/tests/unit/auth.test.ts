import { describe, expect, it } from "vitest";

import { getUserDisplayName, getUserInitials } from "../../src/lib/auth";
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
