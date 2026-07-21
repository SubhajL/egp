import { describe, expect, it } from "vitest";

import {
  suggestKeywordGroupName,
  validateKeywordGroupName,
  keywordGroupStatusPresentation,
} from "../../src/app/(app)/rules/page-helpers";

describe("keyword group status presentation", () => {
  it("maps every effective state to stable Thai copy", () => {
    expect(keywordGroupStatusPresentation("running", null).label).toBe("กำลังติดตาม");
    expect(keywordGroupStatusPresentation("paused_by_user", null).label).toBe("หยุดโดยคุณ");
    expect(
      keywordGroupStatusPresentation("paused_by_plan", "subscription_inactive").label,
    ).toBe("พักไว้ตามแพ็กเกจ");
    expect(
      keywordGroupStatusPresentation("blocked_quota", "keyword_limit_exceeded").label,
    ).toBe("ต้องจัดการโควต้า");
  });
});

describe("keyword group name helpers", () => {
  it("requires a nonblank unique normalized name", () => {
    expect(validateKeywordGroupName("   ", [])).toBe("กรุณาตั้งชื่อกลุ่มคำค้น");
    expect(validateKeywordGroupName("  INFRASTRUCTURE ", ["Infrastructure"])).toBe(
      "ชื่อกลุ่มคำค้นนี้ถูกใช้แล้ว",
    );
    expect(validateKeywordGroupName("Analytics", ["Infrastructure"])).toBeNull();
  });

  it("suggests the first unused numbered group name", () => {
    expect(suggestKeywordGroupName(["กลุ่มคำค้น 1", "กลุ่มคำค้น 3"])).toBe(
      "กลุ่มคำค้น 2",
    );
  });
});
