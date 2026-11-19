import { expect, test } from "@playwright/test";
import { mockApi } from "./fixtures";
import streams from "../tests/fixtures/api/streams-qsdsan.json" with { type: "json" };
import stale from "../tests/fixtures/api/streams-qsdsan-stale.json" with { type: "json" };
import simulation from "../tests/fixtures/api/simulation-qsdsan.json" with { type: "json" };
import partial from "../tests/fixtures/api/simulation-worker-partial.json" with { type: "json" };

test("native table retains pressure and measured-unit calculated values", async ({ page }) => {
  await mockApi(page, { streams, simulation });
  await page.goto("/streams");
  const feed = page.locator('tr[data-stream="FEED"]');
  await expect(feed.locator('[data-field="pressure"]')).toContainText("101.325");
  await expect(feed.locator('[data-calculated="flow"]')).toContainText("100 m3/day");
  await expect(feed.locator('[data-calculated="TN"]')).toContainText("20 mg N/L");
  await expect(feed.locator('[data-calculated="NH4"]')).toHaveText("—");
  await expect(page.locator('tr[data-stream="WATER"] [data-calculated="NH4"]')).toContainText("0 mg N/L");
});

test("a changed input marks the previously calculated quantity stale", async ({ page }) => {
  await mockApi(page, { streams: stale });
  await page.goto("/streams");
  await expect(page.locator('tr[data-stream="FEED"] [data-calculated="TN"] .badge')).toHaveText("stale");
});

test("dynamic outcome separates completion from steady state", async ({ page }) => {
  await mockApi(page, { streams, simulation });
  await page.goto("/streams?tab=simulation");
  await page.getByRole("tab", { name: "Simulation", exact: true }).click();
  await expect(page.locator("[data-run-state]")).toHaveText("integration completed");
  const outcome = page.getByLabel("Calculation outcome");
  await expect(outcome).toContainText("not-applicable");
  await expect(outcome).toContainText("not-evaluated");
  await expect(page.getByRole("link", { name: "Saved run evidence" })).toBeVisible();
  await expect(page.locator("[data-conv]")).toHaveCount(0);
  await expect(page.locator(".spec-line")).not.toContainText("Tolerance:");
});

test("a partial dynamic record is not presented as convergence", async ({ page }) => {
  await mockApi(page, { streams, simulation: partial });
  await page.goto("/streams");
  await page.getByRole("tab", { name: "Simulation", exact: true }).click();
  await expect(page.locator("[data-run-state]")).toHaveText("integration incomplete");
  await expect(page.locator("[data-failed]")).toContainText("dynamic run did not complete");
  await expect(page.locator("[data-filled-count]")).toHaveCount(0);
});
