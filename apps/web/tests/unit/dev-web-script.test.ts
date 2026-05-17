import { readFileSync } from "node:fs";

import { describe, expect, it } from "vitest";

describe("dev web script", () => {
  it("preserves the shared dev dist directory between concurrent servers", () => {
    const source = readFileSync("scripts/dev-web.sh", "utf8");

    expect(source).not.toContain('rm -rf "$NEXT_DIST_DIR"');
    expect(source).toContain('NEXT_DIST_DIR="${NEXT_DIST_DIR:-.next-dev}"');
  });

  it("isolates the Playwright dev server from the primary local server", () => {
    const source = readFileSync("playwright.config.ts", "utf8");

    expect(source).toContain('NEXT_DIST_DIR: ".next-playwright"');
  });
});
