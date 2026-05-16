import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "../../src/lib/api";
import type { CurrentSessionResponse } from "../../src/lib/api";

const { fetchMe, clearStoredCurrentSession, writeStoredCurrentSession } = vi.hoisted(() => ({
  fetchMe: vi.fn<() => Promise<CurrentSessionResponse>>(),
  clearStoredCurrentSession: vi.fn(),
  writeStoredCurrentSession: vi.fn(),
}));

vi.mock("../../src/lib/api", async () => {
  const actual = await vi.importActual<typeof import("../../src/lib/api")>("../../src/lib/api");
  return {
    ...actual,
    fetchMe,
  };
});

vi.mock("../../src/lib/auth", async () => {
  const actual = await vi.importActual<typeof import("../../src/lib/auth")>("../../src/lib/auth");
  return {
    ...actual,
    clearStoredCurrentSession,
    writeStoredCurrentSession,
  };
});

import { fetchCurrentSession } from "../../src/lib/hooks";

const SESSION: CurrentSessionResponse = {
  user: {
    id: "user-1",
    subject: "subject-1",
    email: "operator@example.com",
    full_name: "Operator One",
    role: "owner",
    status: "active",
    email_verified: true,
    email_verified_at: "2026-05-16T00:00:00Z",
    mfa_enabled: false,
  },
  tenant: {
    id: "tenant-1",
    name: "Tenant One",
    slug: "tenant-one",
    plan_code: "monthly_membership",
    is_active: true,
    created_at: "2026-05-16T00:00:00Z",
    updated_at: "2026-05-16T00:00:00Z",
  },
  requires_billing_update: false,
};

describe("fetchCurrentSession", () => {
  beforeEach(() => {
    fetchMe.mockReset();
    clearStoredCurrentSession.mockReset();
    writeStoredCurrentSession.mockReset();
  });

  it("stores successful refreshes", async () => {
    fetchMe.mockResolvedValue(SESSION);

    await expect(fetchCurrentSession()).resolves.toEqual(SESSION);
    expect(writeStoredCurrentSession).toHaveBeenCalledWith(SESSION);
    expect(clearStoredCurrentSession).not.toHaveBeenCalled();
  });

  it("clears only unauthorized sessions", async () => {
    fetchMe.mockRejectedValue(new ApiError(401, "unauthorized"));

    await expect(fetchCurrentSession()).rejects.toEqual(new ApiError(401, "unauthorized"));
    expect(clearStoredCurrentSession).toHaveBeenCalledTimes(1);
    expect(writeStoredCurrentSession).not.toHaveBeenCalled();
  });

  it("preserves stored sessions on transient failures", async () => {
    fetchMe.mockRejectedValue(new ApiError(500, "server error"));

    await expect(fetchCurrentSession()).rejects.toEqual(new ApiError(500, "server error"));
    expect(clearStoredCurrentSession).not.toHaveBeenCalled();
    expect(writeStoredCurrentSession).not.toHaveBeenCalled();
  });
});
