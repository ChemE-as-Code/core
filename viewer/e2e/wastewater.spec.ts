import { expect, test } from "@playwright/test";
import { mockApi } from "./fixtures";
import streams from "../tests/fixtures/api/streams-qsdsan.json" with { type: "json" };
import stale from "../tests/fixtures/api/streams-qsdsan-stale.json" with { type: "json" };
import simulation from "../tests/fixtures/api/simulation-qsdsan.json" with { type: "json" };

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
