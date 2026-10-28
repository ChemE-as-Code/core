import { defineConfig, devices } from "@playwright/test";

// End-to-end tests of the built app (dist/) in Chromium. `vite preview` serves dist/; every
// /api request is answered in the browser from e2e/fixtures.ts, so no cheme-as-code server is
// needed. Ports 8790-8799 are kept for test servers (8765 is cheme serve's default).
const port = Number(process.env.E2E_PORT ?? 8790);

export default defineConfig({
  testDir: "e2e",
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [["list"], ["html", { open: "never" }]] : "list",
  use: {
    baseURL: `http://127.0.0.1:${port}`,
    trace: "retain-on-failure",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"], viewport: { width: 1280, height: 800 } } }],
  webServer: {
    command: `npx vite preview --host 127.0.0.1 --port ${port} --strictPort`,
    url: `http://127.0.0.1:${port}/`,
    reuseExistingServer: false,
    timeout: 60_000,
  },
});
