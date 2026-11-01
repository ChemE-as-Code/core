import { readFileSync } from "node:fs";
import { expect, test, type Page } from "@playwright/test";
import { interlocksAsu, mockApi } from "./fixtures";

/**
 * The cause & effect page: the ASU's real `/api/interlocks` (I-01 LIA-4107 LALL trips P-4101A/B
 * and closes XV-4136; I-02 the same for the LIN tank). The mocked plant draws P-01 only, so the
 * interlocks are moved onto it for the P&ID links.
 */
const onP01 = { ...interlocksAsu, rows: interlocksAsu.rows.map((r) => ({ ...r, sheet: "P-01" })) };

/** The ASU matrix as a branch might have it: XV-4136 opens, and I-02 has a SIL. */
const changed = {
  ...onP01,
  rows: [
    { ...onP01.rows[0]!, cells: ["trip", "trip", "open", "", "", ""] },
    { ...onP01.rows[1]!, sil: 1 },
  ],
};

async function openMatrix(page: Page, options: Parameters<typeof mockApi>[1] = {}) {
  await mockApi(page, { interlocks: onP01, ...options });
  await page.goto("/");
  await page.getByRole("navigation", { name: "Pages" }).getByRole("link", { name: "Cause & effect" }).click();
  await expect(page).toHaveURL(/\/cause-effect/);
  return page.getByRole("table", { name: "Cause and effect matrix" });
}

test.describe("cause and effect matrix", () => {
  test("causes as rows, effect tags as columns, the action in each cell", async ({ page }) => {
    const table = await openMatrix(page);
    await expect(page.getByRole("heading", { level: 1 })).toContainText("control/cause-effect.yaml");
    await expect(table.locator("thead th[data-column]")).toHaveText(["P-4101A", "P-4101B", "XV-4136", "P-4102A", "P-4102B", "XV-4137"]);
    const i01 = table.locator('tr[data-row="I-01"]');
    await expect(i01).toContainText("LOX tank low-low level");
    await expect(i01).toContainText("LIA-4107");
    await expect(i01).toContainText("LALL");
    await expect(table.locator('[data-cell="I-01|P-4101A"]')).toHaveText("trip");
    await expect(table.locator('[data-cell="I-01|XV-4136"]')).toHaveText("close");
    await expect(table.locator('[data-cell="I-01|P-4102A"]')).toHaveText("");
    await expect(table.locator('[data-cell="I-02|XV-4137"]')).toHaveText("close");
    await expect(page.getByRole("region", { name: "Notes" })).toContainText("NPSHr of P-4101A/B");

    const [download] = await Promise.all([page.waitForEvent("download"), page.locator('[data-action="ce-csv"]').click()]);
    expect(download.suggestedFilename()).toBe("cause-effect.csv");
    expect(readFileSync(await download.path(), "utf-8")).toContain("I-01,LIA-4107,LALL,P-01,,trip,trip,close,,,\n");
  });

  test("cause and effect tags open the P&ID with the tag selected", async ({ page }) => {
    const table = await openMatrix(page);
    await expect(table.getByRole("link", { name: "LIA-4107" })).toHaveAttribute("href", "/pid/pid/P-01.xml?select=LIA-4107");
    await table.locator("thead").getByRole("link", { name: "XV-4136" }).click();
    await expect(page).toHaveURL(/\/pid\/pid\/P-01\.xml\?select=XV-4136/);
  });

  test("a P&ID link by tag selects the object drawn for it", async ({ page }) => {
    await mockApi(page);
    await page.goto("/pid/pid/P-01.xml?select=P-101");
    const info = page.locator("aside.info");
    await expect(info.locator("dd code")).toHaveText("Pump1");
    await expect(info).toContainText("P-101");
  });

  test("compared with another revision, changed cells are marked", async ({ page }) => {
    const table = await openMatrix(page, { interlocks: changed, interlocksAt: { main: onP01 } });
    await page.locator('[data-action="compare"]').selectOption("main");
    await expect(page.locator("[data-compare-summary]")).toContainText("1 cell changed");
    const cell = table.locator('[data-cell="I-01|XV-4136"]');
    await expect(cell).toHaveClass(/changed/);
    await expect(cell).toContainText("open");
    await expect(cell.locator("del")).toHaveText("close");
    await expect(table.locator('[data-cell="I-01|P-4101A"]')).not.toHaveClass(/changed/);
    await expect(table.locator('tr[data-row="I-02"] .c-sil')).toHaveClass(/changed/);
  });

  test("a cell with several actions shows each in its own tone, the cell in the most severe", async ({ page }) => {
    // I-01 also alarms on XV-4136, so core joins the two actions in one cell.
    const multi = { ...onP01, rows: [{ ...onP01.rows[0]!, cells: ["trip", "trip", "close + alarm", "", "", ""] }, onP01.rows[1]!] };
    const table = await openMatrix(page, { interlocks: multi, interlocksAt: { main: onP01 } });
    const cell = table.locator('[data-cell="I-01|XV-4136"]');
    await expect(cell).toHaveClass(/tone-stop/);
    const chips = cell.locator("[data-action-chip]");
    await expect(chips).toHaveText(["close", "alarm"]);
    await expect(chips.nth(0)).toHaveClass(/tone-stop/);
    await expect(chips.nth(1)).toHaveClass(/tone-alarm/);
    // a single action keeps its plain cell
    await expect(table.locator('[data-cell="I-01|P-4101A"] [data-action-chip]')).toHaveCount(0);
    await expect(table.locator('[data-cell="I-01|P-4101A"]')).toHaveClass(/tone-stop/);

    const [download] = await Promise.all([page.waitForEvent("download"), page.locator('[data-action="ce-csv"]').click()]);
    expect(readFileSync(await download.path(), "utf-8")).toContain("I-01,LIA-4107,LALL,P-01,,trip,trip,close + alarm,,,\n");

    await page.locator('[data-action="compare"]').selectOption("main");
    await expect(page.locator("[data-compare-summary]")).toContainText("1 cell changed");
    await expect(cell).toHaveClass(/changed/);
    await expect(cell.locator("del")).toHaveText("close");
  });

  test("fits a phone: the matrix scrolls sideways, the cause column stays", async ({ page }) => {
    await page.setViewportSize({ width: 375, height: 740 });
    await mockApi(page, { interlocks: onP01 });
    await page.goto("/cause-effect");
    const wrap = page.locator(".matrix-wrap");
    await expect(wrap).toBeVisible();
    // no page-wide horizontal scroll: only the matrix scrolls sideways
    const [scroll, width] = await page.locator("html").evaluate((el) => [el.scrollWidth, el.clientWidth]);
    expect(scroll).toBeLessThanOrEqual(width!);
    const cause = page.locator('tr[data-row="I-01"] td.c-cause');
    const before = (await cause.boundingBox())!.x;
    await wrap.evaluate((el) => (el.scrollLeft = 400));
    expect(await wrap.evaluate((el) => el.scrollLeft)).toBeGreaterThan(0);
    expect((await cause.boundingBox())!.x).toBeCloseTo(before, 0);
  });

  test("without control/cause-effect.yaml: no nav link, and the page says so", async ({ page }) => {
    await mockApi(page);
    await page.goto("/");
    await expect(page.getByTestId("home-pages").getByRole("link", { name: "Checks" })).toBeVisible();
    await expect(page.getByRole("navigation", { name: "Pages" }).getByRole("link", { name: "Cause & effect" })).toHaveCount(0);
    await expect(page.getByTestId("home-pages").getByRole("link", { name: "Cause & effect" })).toHaveCount(0);
    await page.goto("/cause-effect");
    await expect(page.locator("[data-ce-missing]")).toContainText("No interlocks");
  });

  test("the home page links the matrix", async ({ page }) => {
    await mockApi(page, { interlocks: onP01 });
    await page.goto("/");
    await page.getByTestId("home-pages").getByRole("link", { name: "Cause & effect" }).click();
    await expect(page.locator('[data-cell="I-02|P-4102A"]')).toHaveText("trip");
  });
});
