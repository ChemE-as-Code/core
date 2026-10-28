import { expect, test } from "@playwright/test";
import { asuFiles } from "./asuFiles";
import { equipmentAsu, mockApi } from "./fixtures";

/**
 * The equipment estimate on the take-off page (the ASU's `cheme assess equipment --json` as
 * `/api/estimate/equipment` answers it) and the committed cable schedule beside the layout.
 */
test.describe("equipment estimate", () => {
  test("totals with the AACE range, items with their status and size source, findings", async ({ page }) => {
    await mockApi(page, { equipment: equipmentAsu, files: asuFiles });
    await page.goto("/mto");
    // The take-off is the default; the Equipment tab sits beside it.
    await expect(page.getByRole("heading", { level: 1 })).toContainText("Material take-off");
    await page.getByRole("tab", { name: "Equipment" }).click();
    await expect(page).toHaveURL(/tab=equipment/);
    await expect(page.getByRole("heading", { level: 1 })).toContainText("Equipment estimate");

    const totals = page.getByRole("region", { name: "Equipment totals" });
    await expect(totals.locator('[data-total="bare_module"]')).toContainText("2,099,909 USD");
    await expect(totals.locator('[data-total="bare_module"]')).toContainText("3 of 39 items");
    await expect(totals.locator('[data-total="purchased"]')).toContainText("4,002,556 USD");
    await expect(totals.locator('[data-total="purchased"]')).toContainText("25 of 39 items");
    await expect(totals.locator('[data-total="class"]')).toContainText("AACE class 5");
    await expect(totals.locator('[data-total="class"]')).toContainText("-20 % to -50 % / +30 % to +100 %");
    await expect(page.locator("[data-band]")).toContainText("the low end lies between 1,049,955 and 1,679,927");
    await expect(page.locator("[data-band]")).toContainText("for the 3 items it covers");
    await expect(page.getByText("escalated to CEPCI 797.9 (2023)")).toBeVisible();

    const items = page.getByRole("table", { name: "Equipment items" });
    await expect(items.locator("tbody tr")).toHaveCount(39);
    const c1102 = items.locator('tr[data-tag="C-1102"]');
    await expect(c1102.locator(".status .badge")).toHaveText("bare module");
    await expect(c1102.locator(".status .badge")).toHaveClass(/pass/);
    await expect(items.locator('tr[data-tag="E-1101"] .status .badge')).toHaveClass(/warning/);
    await expect(items.locator('tr[data-tag="F-1101"] .status .badge')).toHaveClass(/error/);
    // The size's provenance opens on click.
    const source = c1102.locator("td.source details");
    await expect(source.locator("summary")).toContainText("datasheet type_specific.volume_m3");
    await expect(source.locator("summary .badge")).toHaveText("ASSUMED");
    await expect(source.locator(".provenance")).toBeHidden();
    await source.locator("summary").click();
    await expect(source.locator(".provenance")).toBeVisible();
    // A tag links its datasheet and the item in 3D.
    await expect(c1102.locator('[data-link="datasheet"]')).toHaveAttribute("href", /\/datasheets\/C-1102(\?|$)/);
    await expect(c1102.locator('[data-link="layout"]')).toHaveAttribute("href", /\/layout\?select=C-1102/);

    // The status chips filter; so does the text filter.
    await page.locator('.chip[data-status="uncovered"]').click();
    await expect(items.locator("tbody tr")).toHaveCount(14);
    await page.locator('.chip[data-status="uncovered"]').click();
    await page.getByLabel("Filter the items").fill("pump");
    await expect(items.locator("tbody tr")).toHaveCount(8);

    const findings = page.getByRole("region", { name: "Equipment findings" });
    await expect(findings.locator("li")).toHaveCount(37);
    await expect(findings.locator('li[data-rule="cheme.estimate-equipment-range"]').first()).toContainText("not extrapolated");
  });

  test("without a 3D model: the MTO link and the page show the equipment estimate", async ({ page }) => {
    await mockApi(page, { equipment: equipmentAsu, mto: null, hasLayout: false });
    await page.goto("/");
    const nav = page.getByRole("navigation", { name: "Pages" });
    await expect(nav.getByRole("link", { name: "Layout 3D" })).toHaveCount(0);
    await nav.getByRole("link", { name: "MTO" }).click();
    await expect(page.getByRole("heading", { level: 1 })).toContainText("Equipment estimate");
    await expect(page.getByRole("tab", { name: "Equipment" })).toHaveAttribute("aria-selected", "true");
    // No layout: no 3D link on the items.
    await expect(page.locator('[data-link="layout"]')).toHaveCount(0);
    await page.getByRole("tab", { name: "Take-off" }).click();
    await expect(page.getByText("No 3D model")).toBeVisible();
    await page.getByRole("button", { name: "Equipment" }).click();
    await expect(page.getByRole("region", { name: "Equipment totals" })).toBeVisible();
  });

  test("an older server or a snapshot without the endpoint: no tab, a hint", async ({ page }) => {
    await mockApi(page);
    await page.goto("/mto");
    await expect(page.getByRole("region", { name: "Totals" })).toBeVisible();
    await expect(page.getByRole("tab")).toHaveCount(0);
    await page.goto("/mto?tab=equipment");
    await expect(page.locator("[data-equipment-missing]")).toContainText("cheme assess equipment");
    await mockApi(page, { mto: null, hasLayout: false });
    await page.goto("/");
    await expect(page.getByRole("navigation", { name: "Pages" }).getByRole("link", { name: "MTO" })).toHaveCount(0);
    await page.goto("/mto");
    await expect(page.getByText("No 3D model")).toBeVisible();
    await expect(page.getByText("cheme assess equipment")).toBeVisible();
  });
});

test.describe("cable schedule", () => {
  test("a sortable, filterable table; a row selects its cable and marks its way", async ({ page }) => {
    // One cable flagged for review (the ASU has none).
    const csv = asuFiles["electrical/cable-schedule.csv"]!.replace(/^(C-M-P-4101A,.*),$/m, "$1,yes");
    await mockApi(page, { files: { ...asuFiles, "electrical/cable-schedule.csv": csv } });
    await page.goto("/layout");
    const schedule = page.getByRole("region", { name: "Cable schedule" });
    await expect(schedule).toContainText("130 cables");
    await expect(schedule).toContainText("1 to review");
    await expect(schedule.getByRole("link", { name: "electrical/cable-schedule.md" })).toHaveAttribute("href", /\/file\/electrical\/cable-schedule\.md/);
    const rows = schedule.locator("tr[data-cable]");
    await expect(rows).toHaveCount(130);
    await expect(schedule.locator('tr[data-cable="C-M-P-4101A"]')).toHaveClass(/review/);

    // Sort by length, longest first, then filter.
    await schedule.locator('[data-sort="length_m"]').click();
    await expect(schedule.locator('th[aria-sort="descending"]')).toContainText("m");
    const first = await rows.first().getAttribute("data-cable");
    const second = await rows.nth(1).getAttribute("data-cable");
    expect(first).toBeTruthy();
    await schedule.locator('[data-sort="length_m"]').click();
    await expect(schedule.locator('th[aria-sort="ascending"]')).toContainText("m");
    expect(await rows.first().getAttribute("data-cable")).not.toBe(first);
    expect(second).toBeTruthy();
    await page.getByLabel("Filter the cables").fill("power");
    await expect(rows).toHaveCount(11);
    await page.getByLabel("Filter the cables").fill("review");
    await expect(rows).toHaveCount(1);
    await page.getByLabel("Filter the cables").fill("");

    // A row selects the cable: its details and its way over the trays.
    await schedule.locator('tr[data-cable="C-E-2101"] td.ends').click();
    const panel = page.getByRole("region", { name: "Selection" });
    await expect(panel.locator(".tag")).toHaveText("C-E-2101");
    await expect(panel).toContainText("PT-MCC-1 > PT-PR1-1 > PT-PR1-2 > PT-PR1-3 > PT-E-2101");
    await expect(panel.locator("[data-route]")).toContainText("1 cable over 5 trays");
    await expect(page).toHaveURL(/select=cable/);
    await expect(schedule.locator('tr[data-cable="C-E-2101"]')).toHaveClass(/active/);
    await schedule.getByRole("button", { name: "C-M-P-4101A" }).click();
    await expect(panel.locator(".tag")).toHaveText("C-M-P-4101A");
    await expect(schedule.locator('tr[data-cable="C-M-P-4101A"]')).toHaveClass(/active/);
  });

  test("no panel where the repo has no schedule", async ({ page }) => {
    await mockApi(page);
    await page.goto("/layout");
    await expect(page.getByRole("region", { name: "Equipment" })).toBeVisible();
    await expect(page.getByRole("region", { name: "Cable schedule" })).toHaveCount(0);
  });
});
