import { defineConfig, devices } from "@playwright/test";

const PORT = 3100;
const API_BASE_URL = "http://127.0.0.1:3300";

export default defineConfig({
  testDir: "./tests/e2e",
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  reporter: process.env.CI ? "dot" : "list",
  use: {
    baseURL: `http://127.0.0.1:${PORT}`,
    trace: "on-first-retry",
    ...devices["Desktop Chrome"],
  },
  webServer: {
    command: `npm run dev:web -- --hostname 127.0.0.1 --port ${PORT}`,
    port: PORT,
    reuseExistingServer: !process.env.CI,
    env: {
      NEXT_PUBLIC_EGP_API_BASE_URL: API_BASE_URL,
    },
  },
});
