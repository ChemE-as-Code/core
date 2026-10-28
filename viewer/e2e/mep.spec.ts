import { readFileSync } from "node:fs";
import { expect, test } from "@playwright/test";
import { asuWithPenetration, mepLayout, mockApi, mtoMep } from "./fixtures";

/**
 * The material take-off page (the ASU's `/api/mto` with example rates), cable trays, cable routes
 * and ducts (core's small cabling and HVAC plant), the access proposals and the engineering rules'
 * findings of the ASU.
 */
const csv = (name: string) => readFileSync(new URL(`../tests/fixtures/api/${name}`, import.meta.url), "utf-8");

test.describe("material take-off", () => {
  test("tables per category, totals, the example estimate and the CSV files cheme-as-code writes", async ({ page }) => {
    await mockApi(page);
    await page.goto("/");
    await page.getByRole("navigation", { name: "Pages" }).getByRole("link", { name: "MTO" }).click();
    await expect(page).toHaveURL(/\/mto/);
    await expect(page.getByRole("heading", { level: 1 })).toContainText("Material take-off");

    const totals = page.getByRole("region", { name: "Totals" });
    await expect(totals.locator('[data-category="pipe"]')).toContainText("4,768.422 m");
    await expect(totals.locator('[data-category="steel"]')).toContainText("578.762 t");
    // One table per category, in core's order.
    const categories = await page.locator("section.category").evaluateAll((els) => els.map((e) => e.getAttribute("data-category")));
    expect(categories.slice(0, 3)).toEqual(["pipe", "elbow", "tee"]);
    expect(categories).toContain("concrete");

    const estimate = page.getByRole("region", { name: "Estimate" });
    await expect(estimate.getByRole("note")).toContainText("example");
    await expect(estimate.locator("[data-total]")).toHaveText("43,547.50");
    await expect(page.getByRole("region", { name: "Findings" })).toContainText("estimate-example-rates");

    // The filter narrows the rows.
    await page.getByLabel("Filter the rows").fill("HEB");
    await expect(page.locator("section.category")).toHaveCount(1);
    await expect(page.locator('section.category[data-category="steel"] tbody tr').first()).toContainText("HEB");
    await page.getByLabel("Filter the rows").fill("");

    // The downloads are the files `cheme assess mto|estimate --csv` write.
    const [mto] = await Promise.all([page.waitForEvent("download"), page.locator('[data-action="mto-csv"]').click()]);
    expect(mto.suggestedFilename()).toBe("mto.csv");
    expect(readFileSync(await mto.path(), "utf-8")).toBe(csv("mto-asu.csv"));
    const [est] = await Promise.all([page.waitForEvent("download"), page.locator('[data-action="estimate-csv"]').click()]);
    expect(readFileSync(await est.path(), "utf-8")).toBe(csv("estimate-asu.csv"));
  });

  test("says how to get a model when there is none", async ({ page }) => {
    await mockApi(page, { mto: null });
    await page.goto("/mto");
    await expect(page.getByText("No 3D model")).toBeVisible();
    await expect(page.getByText("cheme layout build")).toBeVisible();
  });

  test("opens from the layout view", async ({ page }) => {
    await mockApi(page, { layout: mepLayout, mto: mtoMep });
    await page.goto("/layout");
    await page.locator('[data-action="open-mto"]').click();
    await expect(page).toHaveURL(/\/mto/);
    await expect(page.getByRole("region", { name: "Totals" }).locator('[data-category="valve"]')).toContainText("1 ea");
  });
});

test.describe("cable trays, cables and ducts", () => {
  test.beforeEach(async ({ page }) => {
    await mockApi(page, { layout: mepLayout, mto: mtoMep });
  });

  test("layers for trays and ducts, a motor's cable route and a cable's details", async ({ page }) => {
    await page.goto("/layout");
    await expect(page.locator("canvas.layout-canvas")).toBeVisible();
    await page.locator("summary", { hasText: "Layers" }).click();
    for (const layer of ["trays", "ducts"]) {
      const box = page.locator(`input[data-layer="${layer}"]`);
      await expect(box).toBeChecked();
      await expect(box.locator("xpath=..").locator(".count")).not.toHaveText("0");
    }
    await page.locator("summary", { hasText: "Layers" }).click();
    await expect(page.getByRole("region", { name: "Cabling" })).toContainText("6 cables");
    await expect(page.getByRole("region", { name: "HVAC" })).toContainText("5,760");

    // The pump: its motor cable's way from the MCC over the rack.
    await page.locator('.chip[data-item="equipment:P-101"]').click();
    const panel = page.getByRole("region", { name: "Selection" });
    await expect(panel.locator("[data-route]")).toContainText("1 cable over 3 trays");
    await panel.getByRole("button", { name: "C-M-P-101" }).click();
    await expect(panel.locator(".tag")).toHaveText("C-M-P-101");
    await expect(panel).toContainText("4C x 4 mm2");
    await expect(panel).toContainText("PT-MCC-1 > PT-PR-1-1 > PT-M-P-101");
    // ... and on to a tray it runs in.
    await panel.getByRole("button", { name: "PT-PR-1-1" }).click();
    await expect(panel.locator(".tag")).toHaveText("PT-PR-1-1");
    await expect(panel).toContainText("power trunk");
  });

  test("an instrument's way to its junction box and on to the control room; a unit's ducts", async ({ page }) => {
    await page.goto("/layout?select=PT-101");
    const panel = page.getByRole("region", { name: "Selection" });
    await expect(panel.locator(".tag")).toHaveText("PT-101");
    await expect(panel.locator("[data-route]")).toContainText("2 cables over 3 trays");
    await page.goto("/layout?select=AHU-1");
    await expect(panel.locator(".tag")).toHaveText("AHU-1");
    await expect(panel.locator("[data-route]")).toContainText("10 ducts marked");
    await panel.getByRole("button", { name: "HALL" }).click();
    await expect(panel).toContainText("6 per hour");
    const legend = page.getByRole("region", { name: "Legend" });
    await legend.getByRole("button", { name: "Legend" }).click();
    await expect(legend.getByRole("region", { name: "Trays, ducts and walls" })).toContainText("supply air duct");
  });
});

test.describe("access proposals and the engineering rules", () => {
  test.beforeEach(async ({ page }) => {
    await mockApi(page);
  });

  test("lists the proposals to review; each says why and how to keep it", async ({ page }) => {
    await page.goto("/layout");
    const review = page.getByRole("region", { name: "To review" });
    // The ASU has pinned its cold box stairs (process-library#2); the rack ladders are proposed.
    await expect(review.locator('[data-proposal="stair"]')).toHaveCount(0);
    await review.locator('[data-proposal="ladder"] summary').click();
    await review.locator('.chip[data-item="platform:PR1/ladder-start"]').click();
    const panel = page.getByRole("region", { name: "Selection" });
    await expect(panel.locator(".tag")).toHaveText("PR1/ladder-start");
    await expect(panel).toContainText("review needed");
    await expect(panel).toContainText("access to the tiers");
    await expect(panel).toContainText("cheme layout pin PR1/ladder-start");
    // AIR-2002 enters the cold box through its declared opening (asu-1 D-046): no sleeve.
    await expect(review.locator('[data-proposal="penetration"]')).toHaveCount(0);
    // The valve access platforms and the support steel the build still proposes (VP-1 .. VP-9
    // are declared since asu-1 D-047; a proposal is named by its first valve, VP-<valve tag>).
    await review.locator('[data-proposal="valve platform"] summary').click();
    await expect(review.locator('.chip[data-item="structure:VP-1"]')).toHaveCount(0);
    await review.locator('.chip[data-item="structure:VP-XV-2101A"]').click();
    await expect(panel.locator(".tag")).toHaveText("VP-XV-2101A");
    await expect(panel).toContainText("valve access platform");
    await expect(panel).toContainText("cheme layout pin VP-XV-2101A");
    await expect(review.locator('[data-proposal="support steel"]')).toHaveCount(1);
  });

  test("a wall penetration finding selects its sleeve", async ({ page }) => {
    await mockApi(page, { layout: asuWithPenetration });
    await page.goto("/layout");
    const review = page.getByRole("region", { name: "To review" });
    await review.locator('[data-proposal="penetration"] summary').click();
    await expect(review.locator('[data-proposal="penetration"] .chip')).toHaveCount(1);
    const group = page.locator('.finding-group[data-rule$="layout-wall-penetration"]');
    await group.locator("summary").click();
    await group.locator(".finding", { hasText: "AIR-2002" }).first().click();
    const panel = page.getByRole("region", { name: "Selection" });
    await expect(panel.locator(".tag")).toHaveText("CB-1/AIR-2002");
    await expect(panel).toContainText("opening needed");
  });
});
