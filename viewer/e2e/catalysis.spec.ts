import { expect, test } from "@playwright/test";
import { kineticsShift, libraryShift, mockApi, reactionsAmmonia, reactionsCoox, reactionsShift } from "./fixtures";

/** The catalysis results on core's real answers: microkinetics, the gas model, kinetic data, the library. */
test.describe("catalysis", () => {
  test("a mechanism at its reactor's outlet: conditions, TOF, coverages, rate control", async ({ page }) => {
    await mockApi(page, { reactions: reactionsCoox });
    await page.goto("/reactions");
    const card = page.locator('[data-mechanism="COOX"]');
    await expect(card.locator("[data-mk-conditions]")).toContainText("At the outlet S2 of R: 500 K, CO 0.01005 bar, CO2 0.01005 bar, O2 0.09548 bar");
    await expect(card.locator('[data-step-equation="S3"]')).toHaveText("S3 CO* + O* -> CO2 + 2 *");
    await expect(card.locator("[data-tof]")).toHaveText("7.718e-7 1/s (CO2 per site)");
    await expect(card.locator("[data-mk-orders]")).toHaveText("CO -2, O2 1");
    await expect(card.locator("[data-mk-reading]")).toHaveText("S2 controls the rate; CO* covers most sites");
    await expect(card.locator('[data-coverage="CO*"]')).toContainText("100 %");
    await expect(card.locator("[data-rate-control] .bar-row").first()).toHaveAttribute("data-step", "S2");
    await expect(page.locator('[data-mechanism="UNUSED"] [data-mk-missing]')).toHaveText("Not analysed: the reaction takes place in no block or step");
    await expect(page.locator("[data-kinetic-data]")).toHaveCount(0);
  });

  test("the reactor's gas model; no microkinetics without a mechanism", async ({ page }) => {
    await mockApi(page, { reactions: reactionsAmmonia });
    await page.goto("/reactions");
    await expect(page.locator('tr[data-reactor="R1"] [data-fugacity]')).toHaveText("Peng–Robinson");
    await expect(page.locator('tr[data-reactor="LOOP"] [data-fugacity]')).toHaveCount(0);
    await expect(page.locator("[data-microkinetics]")).toHaveCount(0);
  });

  test("kinetic data with their fit; a file that does not validate", async ({ page }) => {
    await mockApi(page, { reactions: reactionsShift, kinetics: kineticsShift });
    await page.goto("/reactions");
    const wgs = page.locator('[data-kinetic-file="experiments/kinetics/wgs.yaml"]');
    await expect(wgs.locator("header")).toContainText("wgs.yaml WGS on FE_CR, 12 points");
    await expect(wgs.locator("[data-fit-law]")).toContainText("· (1 − Q/K)");
    await expect(wgs.locator("[data-r2]")).toContainText("1, worst point");
    await expect(wgs.locator('[data-parameter="Ea"]')).toContainText("111000 kJ/kmol");
    await wgs.locator(".sources summary").click();
    await expect(wgs.locator("tr[data-point]")).toHaveCount(12);
    await expect(page.locator('[data-kinetic-file="experiments/kinetics/broken.yaml"] [data-kinetic-problem]')).toHaveText("experiments/kinetics/broken.yaml: kind: Input should be 'kinetic-data' (and 3 more)");
  });

  test("the library: marks, filter, and the link from the reactions page", async ({ page }) => {
    await mockApi(page, { reactions: reactionsShift, library: libraryShift });
    await page.goto("/reactions");
    await page.getByRole("link", { name: "Reaction library" }).click();
    await expect(page).toHaveURL(/\/library/);
    await expect(page.locator("[data-library-entry]")).toHaveCount(23);
    const shift = page.locator('[data-library-entry="ht_shift"]');
    await expect(shift.locator("[data-match]")).toHaveText("in the plant");
    await expect(shift.locator('[data-component="CO"]')).toHaveClass(/have/);
    await expect(shift.locator('[data-library-catalyst="FE_CR"] .mark')).toHaveText("≠");
    await expect(shift.locator("[data-add]")).toHaveText("cheme chemistry library ht_shift --add");
    await page.locator("[data-library-filter]").fill("ammox");
    await expect(page.locator("[data-library-entry]")).toHaveCount(1);
    await expect(page.locator('[data-library-entry="acrylonitrile"] [data-match]')).toHaveText("1 of 7 in the plant");
    await page.locator("[data-library-filter]").fill("");
    await page.locator("[data-library-only-plant]").check();
    await expect(page.locator('[data-library-entry="ht_shift"]')).toBeVisible();
    await expect(page.locator('[data-library-entry="sulfuric_acid"]')).toHaveCount(0);
  });

  test("an older server: the library page says so", async ({ page }) => {
    await mockApi(page, {});
    await page.goto("/library");
    await expect(page.locator("[data-library-missing]")).toContainText("No reaction library here.");
  });
});
