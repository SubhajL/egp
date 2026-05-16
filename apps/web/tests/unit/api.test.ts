import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiError, fetchMe } from "../../src/lib/api";

describe("fetchMe", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("parses structured validation errors", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify({
            detail: [
              { loc: ["body", "password"], msg: "String should have at least 12 characters" },
            ],
          }),
          { status: 422, statusText: "Unprocessable Entity" },
        ),
      ),
    );

    await expect(fetchMe()).rejects.toEqual(
      new ApiError(422, "password: String should have at least 12 characters"),
    );
  });

  it("falls back when the response body is unreadable", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response("not-json", {
          status: 500,
          statusText: "Internal Server Error",
        }),
      ),
    );

    await expect(fetchMe()).rejects.toEqual(
      new ApiError(500, "API request failed: 500 Internal Server Error"),
    );
  });
});
