// Keyboard access and navigation and what a page shows while another revision loads.
import { expect, test } from "@playwright/test";
import { SHEET, mockApi, streams } from "./fixtures";

test.describe("keyboard", () => {
  test("an object on a P&ID is stepped to with N/P and opened with Enter", async ({ page }) => {
    await mockApi(page);
    await page.goto(`/pid/${SHEET}`);
    const pane = page.locator(".pid .pane");
    await expect(pane.locator('[id="Pump1"]')).toBeAttached();
    const said = pane.getByTestId("pane-announcement");

    await pane.focus();
    // Enter with nothing marked says what to do instead of picking nothing.
    await page.keyboard.press("Enter");
    await expect(said).toHaveText(/Press N or P/);
    // P from the start is the last object (Tank1), once more the pump before it.
    await page.keyboard.press("p");
    await expect(said).toHaveText(/^Tank1 \(T-101\), 4 of 4\./);
    await page.keyboard.press("p");
    await expect(said).toHaveText(/^Pump1 \(P-101\), 3 of 4\./);
    await expect(page.locator("aside.info")).toHaveCount(0);

    await page.keyboard.press("Enter");
    const info = page.locator("aside.info");
    await expect(info.locator("dd code")).toHaveText("Pump1");
    await expect(info).toContainText("P-101");
    await expect(said).toHaveText("Pump1 selected.");
    await expect(pane).toBeFocused();

    // N wraps around: after the last object comes the first (the sheet's border group).
    await page.keyboard.press("n");
    await page.keyboard.press("n");
    await expect(said).toHaveText(/1 of 4\./);
    await page.keyboard.press("Escape");
    await expect(info).toHaveCount(0);
  });

  test("Enter on a zoom button presses the button, not the marked object", async ({ page }) => {
    await mockApi(page);
    await page.goto(`/pid/${SHEET}`);
    const pane = page.locator(".pid .pane");
    await expect(pane.locator('[id="Pump1"]')).toBeAttached();
    const stage = pane.locator(".stage");
    await pane.focus();
    await page.keyboard.press("p");
    const before = await stage.getAttribute("style");
    await pane.getByRole("button", { name: "Zoom in" }).focus();
    await page.keyboard.press("Enter");
    await expect.poll(() => stage.getAttribute("style")).not.toBe(before);
    await expect(page.locator("aside.info")).toHaveCount(0);
  });

  test("stream table rows are selected with Enter and Space", async ({ page }) => {
    await mockApi(page);
    await page.goto("/streams");
    const row = page.locator('tr[data-stream="S2"]');
    await row.focus();
    await expect(row).toBeFocused();
    await page.keyboard.press("Enter");
    await expect(row).toHaveClass(/selected/);
    await expect(row).toHaveAttribute("aria-current", "true");
    await page.keyboard.press("Space");
    await expect(row).not.toHaveClass(/selected/);
    await expect(row).not.toHaveAttribute("aria-current");
  });
});

test.describe("navigation", () => {
  test("every page sets the document title, and the focus moves to its heading", async ({ page }) => {
    await mockApi(page);
    await page.goto("/streams");
    await expect(page).toHaveTitle("Stream table – Test plant – cheme-as-code viewer");
    await page.getByRole("navigation", { name: "Pages" }).getByRole("link", { name: "Validation" }).click();
    await expect(page).toHaveTitle("Validation – Test plant – cheme-as-code viewer");
    await expect(page.locator("main h1")).toBeFocused();
    await page.goto(`/pid/${SHEET}`);
    await expect(page).toHaveTitle(`P&ID ${SHEET} – Test plant – cheme-as-code viewer`);
    await page.goBack();
    await expect(page).toHaveTitle("Validation – Test plant – cheme-as-code viewer");
  });

  test("a skip link jumps past the header and the file tree", async ({ page }) => {
    await mockApi(page);
    await page.goto("/streams");
    await expect(page.locator('tr[data-stream="S2"]')).toBeVisible();
    await page.keyboard.press("Tab");
    const skip = page.getByRole("link", { name: "Skip to content" });
    await expect(skip).toBeFocused();
    await expect(skip).toBeInViewport();
    await page.keyboard.press("Enter");
    await expect(page.locator("main")).toBeFocused();
  });
});

test.describe("another revision", () => {
  test("while it loads, the stream table of the previous one is not shown under its label", async ({ page }) => {
    await mockApi(page);
    let release: () => void = () => {};
    const held = new Promise<void>((resolve) => (release = resolve));
    await page.route("**/api/streams**", async (route) => {
      const url = new URL(route.request().url());
      if (url.searchParams.get("rev") !== "v2") return route.fallback();
      await held;
      const renamed = streams.streams.map((s) => ({ ...s, id: `${s.id}-v2` }));
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ ...streams, rev: "v2", streams: renamed }) });
    });
    await page.goto("/streams");
    await expect(page.locator('tr[data-stream="S2"]')).toBeVisible();

    await page.locator('button[title^="Show another revision"]').click();
    await page.locator("#rev-select").fill("v2");
    await page.keyboard.press("Enter");
    await expect(page.locator("main h1")).toContainText("v2");
    await expect(page.locator("main").getByText("Loading…")).toBeVisible();
    await expect(page.locator('tr[data-stream="S2"]')).toHaveCount(0);
    // Nor its cases: v2 may have others.
    await expect(page.getByLabel("Case", { exact: true })).toHaveCount(0);

    release();
    await expect(page.locator('tr[data-stream="S2-v2"]')).toBeVisible();
    await expect(page.getByLabel("Case", { exact: true })).toBeVisible();
    await expect(page.locator("main").getByText("Loading…")).toHaveCount(0);
  });

  test("a revision whose stream table fails shows the error and none of the previous cases", async ({ page }) => {
    await mockApi(page);
    await page.route("**/api/streams**", (route) => {
      if (new URL(route.request().url()).searchParams.get("rev") !== "v2") return route.fallback();
      return route.fulfill({ status: 404, contentType: "application/json", body: '{"error":"no process/flowsheet.yaml at v2"}' });
    });
    await page.goto("/streams");
    const select = page.getByLabel("Case", { exact: true });
    await expect(select).toBeVisible();
    await page.locator('button[title^="Show another revision"]').click();
    await page.locator("#rev-select").fill("v2");
    await page.keyboard.press("Enter");
    await expect(page.locator("main [role=alert]")).toContainText("no process/flowsheet.yaml at v2");
    await expect(select).toHaveCount(0);
    await expect(page.locator('tr[data-stream="S2"]')).toHaveCount(0);
  });

  test("picking another case keeps the focus on the case select", async ({ page }) => {
    await mockApi(page);
    await page.goto("/streams");
    const select = page.getByLabel("Case", { exact: true });
    await select.focus();
    await select.selectOption("turndown");
    await expect(page).toHaveURL(/case=turndown/);
    await expect(select).toHaveValue("turndown");
    await expect(select).toBeFocused();
  });

  test("the object picked in the previous revision's drawing is let go", async ({ page }) => {
    await mockApi(page);
    await page.goto(`/pid/${SHEET}`);
    const pane = page.locator(".pid .pane");
    await pane.locator('[id="Pump1"] circle').click();
    await expect(page.locator("aside.info dd code")).toHaveText("Pump1");
    await page.locator('button[title^="Show another revision"]').click();
    await page.locator("#rev-select").fill("v2");
    await page.keyboard.press("Enter");
    await expect(page).toHaveURL(/rev=v2/);
    await expect(page.locator("aside.info")).toHaveCount(0);
  });

  test("History's Load more keeps the list while the longer one loads", async ({ page }) => {
    await mockApi(page);
    const commit = (i: number) => ({ sha: `${i}`.padStart(40, "0"), short: `${i}`.padStart(7, "0"), subject: `Commit ${i}`, author: "A", date: "2026-10-01T00:00:00Z" });
    let release: () => void = () => {};
    const held = new Promise<void>((resolve) => (release = resolve));
    await page.route((url) => url.pathname === "/api/log", async (route) => {
      const limit = Number(new URL(route.request().url()).searchParams.get("limit"));
      if (limit > 50) await held;
      return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(Array.from({ length: limit }, (_, i) => commit(i + 1))) });
    });
    await page.goto("/history");
    await expect(page.getByText("Commit 50", { exact: true })).toBeVisible();
    await page.getByRole("button", { name: "Load more" }).click();
    await expect(page.getByText("Commit 1", { exact: true })).toBeVisible();
    await expect(page.locator("main").getByText("Loading…")).toHaveCount(0);
    release();
    await expect(page.getByText("Commit 100", { exact: true })).toBeVisible();
  });
});
