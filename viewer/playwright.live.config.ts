import { defineConfig, devices } from "@playwright/test";

// The integration smoke test: the built app (dist/) served by a real `cheme serve --ui dist` on a
// plant repository, started by scripts/integration_smoke.py at the repository root. Nothing is
// mocked here, unlike playwright.config.ts.
const base = process.env.CHEME_LIVE_URL ?? "http://127.0.0.1:8795";

export default defineConfig({
  testDir: "e2e-live",
  forbidOnly: !!process.env.CI,
  reporter: "list",
  use: { baseURL: base, trace: "retain-on-failure" },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"], viewport: { width: 1280, height: 800 } } }],
});
