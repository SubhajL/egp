import { describe, expect, it } from "vitest";

import { resolveTabKey } from "../../src/lib/tabs";

const KEYS = ["users", "slips", "billing"] as const;

describe("resolveTabKey", () => {
  it("returns the query tab when it is a valid key", () => {
    expect(resolveTabKey("slips", KEYS, "users")).toBe("slips");
  });

  it("falls back for unknown / missing values", () => {
    expect(resolveTabKey("nope", KEYS, "users")).toBe("users");
    expect(resolveTabKey(null, KEYS, "users")).toBe("users");
    expect(resolveTabKey(undefined, KEYS, "users")).toBe("users");
    expect(resolveTabKey("", KEYS, "users")).toBe("users");
  });
});
