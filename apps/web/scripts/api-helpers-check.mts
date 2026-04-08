import assert from "node:assert/strict";

import {
  ApiError,
  getApiBaseUrl,
  localizeApiError,
  normalizeSignupApiError,
  shouldShowSignupLoginLink,
} from "../src/lib/api.ts";

function withWindow(location: Location, run: () => void) {
  const descriptor = Object.getOwnPropertyDescriptor(globalThis, "window");
  Object.defineProperty(globalThis, "window", {
    configurable: true,
    value: { location },
  });
  try {
    run();
  } finally {
    if (descriptor) {
      Object.defineProperty(globalThis, "window", descriptor);
      return;
    }
    delete (globalThis as { window?: unknown }).window;
  }
}

assert.equal(
  localizeApiError(new ApiError(409, "workspace slug required", "workspace_slug_required"), "fallback"),
  "อีเมลนี้ถูกใช้ในหลาย workspace กรุณาระบุ Workspace slug เพื่อเข้าสู่ระบบ",
);

assert.equal(
  normalizeSignupApiError(
    new ApiError(
      409,
      "account already exists for this email; please sign in",
      "account_already_exists",
    ),
  ),
  "อีเมลนี้มีบัญชีอยู่แล้ว กรุณาเข้าสู่ระบบแทนการสมัครใหม่",
);
assert.equal(
  shouldShowSignupLoginLink(
    new ApiError(
      409,
      "account already exists for this email; please sign in",
      "account_already_exists",
    ),
  ),
  true,
);
assert.equal(
  normalizeSignupApiError(
    new ApiError(
      422,
      "password: String should have at least 12 characters",
      "validation_password_too_short",
    ),
  ),
  "รหัสผ่านต้องมีอย่างน้อย 12 ตัวอักษร",
);
assert.equal(
  shouldShowSignupLoginLink(
    new ApiError(
      422,
      "password: String should have at least 12 characters",
      "validation_password_too_short",
    ),
  ),
  false,
);

withWindow(
  {
    protocol: "http:",
    hostname: "localhost",
    origin: "http://localhost:3000",
  } as Location,
  () => {
    process.env.NEXT_PUBLIC_EGP_API_BASE_URL = "http://127.0.0.1:8000/";
    assert.equal(getApiBaseUrl(), "http://localhost:8000");
    delete process.env.NEXT_PUBLIC_EGP_API_BASE_URL;
  },
);

console.log("api helpers ok");
