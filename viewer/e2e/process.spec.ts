import { expect, test } from "@playwright/test";
import { mockApi, streams } from "./fixtures";

test.describe("process sheets", () => {
  test("the page navigation groups Process (BFD, PFD) before the P&IDs, with kind badges", async ({ page }) => {
    await mockApi(page);
    await page.goto("/pid/process/BFD.xml");
    const groups = page.getByRole("navigation", { name: "Pages" }).locator("section[data-group]");
    await expect(groups.nth(0)).toHaveAttribute("data-group", "process");
    await expect(groups.nth(0).locator("h2")).toHaveText("Process");
    await expect(groups.nth(0).locator(".kind")).toHaveText(["BFD", "PFD"]);
    await expect(groups.nth(0)).toContainText("Stream table");
    await expect(groups.nth(0).locator("[aria-current=page]")).toHaveText(/^BFD/);
    await expect(groups.nth(1).locator("h2")).toHaveText("P&IDs");
    await expect(groups.nth(1).locator(".kind")).toHaveText(["P&ID"]);
  });

  test("clicking a BFD connection lists the streams it represents", async ({ page }) => {
    await mockApi(page);
    await page.goto("/pid/process/BFD.xml");
    await expect(page.locator(".pid h1 .badge")).toHaveText("BFD");
    const pane = page.locator(".pid .pane");
    await pane.locator('[id="S2"] text').click();
    const panel = page.locator("aside.process-panel");
    await expect(panel).toContainText("BFD connection S2");
    await expect(panel).toContainText("Represents 1 stream");
    await expect(panel.locator('[data-stream="S2"]')).toContainText("1500 kg/h");
    await expect(panel.locator('[data-stream="S2"]')).toContainText("stale");
  });

  test("an aggregated BFD connection lists every stream it represents", async ({ page }) => {
    await mockApi(page);
    const s3 = { ...streams.streams[0]!, id: "S3", title: "Side draw", from: "M1.side", to: "C1.feed2" };
    const table = { ...streams, streams: [...streams.streams, s3], bfd_connections: { S2: ["S2", "S3"], S5: ["S5"] } };
    await page.route(/\/api\/streams(\?|$)/, (route) => route.fulfill({ json: table }));
    await page.goto("/pid/process/BFD.xml");
    await page.locator('.pid .pane [id="S2"] text').click();
    const panel = page.locator("aside.process-panel");
    await expect(panel).toContainText("BFD connection S2 (aggregated)");
    await expect(panel).toContainText("Represents 2 streams");
    await expect(panel.locator('[data-stream="S3"]')).toContainText("Side draw");
    await page.goto("/streams");
    await expect(page.locator('tr[data-stream="S3"] td.bfd')).toHaveText("in S2");
    await expect(page.locator('tr[data-stream="S2"] td.bfd')).toHaveText("yes");
  });

  test("clicking a block shows its balance", async ({ page }) => {
    await mockApi(page);
    await page.goto("/pid/process/PFD.xml");
    await page.locator('.pid .pane [id="SEP"] text').click();
    const panel = page.locator("aside.process-panel");
    await expect(panel).toContainText("block SEP");
    await expect(panel.locator(".badge.fail").first()).toContainText("imbalance");
  });
});

test.describe("stream table", () => {
  test("shows values with provenance, highlights errors and stale values, and filters", async ({ page }) => {
    await mockApi(page);
    await page.goto("/streams");
    const rows = page.locator(".stream-table tbody tr[data-stream]");
    await expect(rows).toHaveCount(2);
    const s2 = page.locator('tr[data-stream="S2"]');
    await expect(s2).toHaveClass(/stale/);
    await expect(s2.locator(".prov.assumed")).toHaveCount(1);
    await expect(s2).toContainText("350 K");
    await expect(page.locator('tr[data-stream="S5"]')).toHaveClass(/error/);
    await expect(page.locator('tr[data-balance="SEP"] .badge')).toHaveText("imbalance");

    await page.getByPlaceholder("Filter streams").fill("bottoms");
    await expect(rows).toHaveCount(1);
    await page.getByPlaceholder("Filter streams").fill("");
    await page.getByRole("button", { name: "Problems" }).click();
    await expect(rows).toHaveCount(2); // S2 is stale, S5 fails a balance
  });

  test("the case selector reloads the table for that case", async ({ page }) => {
    await mockApi(page);
    await page.goto("/streams");
    await page.getByLabel("Case").selectOption("turndown");
    await expect(page).toHaveURL(/case=turndown/);
    await expect(page.getByLabel("Case")).toHaveValue("turndown");
  });

  test("a ?stream= link selects that row and scrolls it into view", async ({ page }) => {
    await mockApi(page);
    await page.goto("/streams?stream=S2");
    const s2 = page.locator('tr[data-stream="S2"]');
    await expect(s2).toHaveClass(/selected/);
    await expect(s2).toBeInViewport();
  });
});

test("the flowsheet YAML shows a table per section", async ({ page }) => {
  await mockApi(page);
  await page.goto("/yaml/process/flowsheet.yaml");
  const tabs = page.getByRole("tab");
  await expect(tabs).toHaveCount(2);
  await expect(page.locator("table.data tbody tr")).toHaveCount(1);
  await tabs.filter({ hasText: "blocks" }).click();
  await expect(page.locator("table.data tbody tr")).toHaveCount(2);
});
