import { expect, test } from "@playwright/test";
import { asuFiles } from "./asuFiles";
import { mepLayout, mockApi, mtoMep } from "./fixtures";

/**
 * Core#61 on the ASU: declared operators (a chain wheel valve, a remote-mounted transmitter), the
 * cold box hatch H1, the committed lifting study and the datasheet links beside the model.
 */
test.describe("operators, hatches, lifting study and datasheets", () => {
  test.beforeEach(async ({ page }) => {
    await mockApi(page, { files: asuFiles });
  });

  test("a chain wheel valve and a remote-mounted transmitter say how they are operated", async ({ page }) => {
    await page.goto("/layout?select=P-01/BV_P1101A_S");
    const panel = page.getByRole("region", { name: "Selection" });
    await expect(panel.locator(".tag")).toHaveText("P-01/BV_P1101A_S");
    await expect(panel).toContainText("chain wheel (infrequent use)");
    await expect(panel).toContainText("spare-pump changeover and maintenance only (D-040)");
    await expect(panel).toContainText("chain to 1 m (1 m above grade at 0 m); schematic, by the viewer");

    await page.goto("/layout?select=nozzle:F-1101/I1");
    await expect(panel.locator(".tag")).toHaveText("F-1101/I1");
    await expect(panel).toContainText("remote mount (capillary, regular use)");
    await expect(panel).toContainText(/capillary, [\d.]+ m to a stand 1\.2 m above grade/);
  });

  test("the cold box hatch H1 is an item of its own", async ({ page }) => {
    await page.goto("/layout?select=H1");
    const panel = page.getByRole("region", { name: "Selection" });
    await expect(panel.locator(".tag")).toHaveText("CB-1/H1");
    await expect(panel).toContainText("Hatch H1 in the north wall of CB-1");
    await expect(panel).toContainText("1.2 x 1.2 m");
    await panel.getByRole("button", { name: "CB-1" }).click();
    await expect(panel.locator(".tag")).toHaveText("CB-1");
  });

  test("lists the lifting study per item and selects the item and its pad", async ({ page }) => {
    await page.goto("/layout");
    const study = page.getByRole("region", { name: "Lifting study" });
    await expect(study).toContainText("15 lifts, 0 lanes blocked");
    await expect(study.locator("tr[data-lift]")).toHaveCount(15);
    // the MAC motor (K-1101's heaviest maintenance lift) under the B1 crane
    await expect(study.locator('tr[data-lift="K-1101"]')).toContainText("building B1");
    const k4101 = study.locator('tr[data-lift="K-4101"]');
    await expect(k4101).toContainText("Z-PAD-A4");
    await expect(k4101.locator("td.num")).toHaveText(["12.5", "650", "69.3"]);
    await expect(k4101).toContainText("clear");
    await expect(study.locator('tr[data-lift="E-1101"]')).toContainText("building B1");
    await expect(study.getByRole("link", { name: "layout/lifting-study.md" })).toHaveAttribute("href", /\/file\/layout\/lifting-study\.md/);

    await k4101.getByRole("button", { name: "K-4101" }).click();
    const panel = page.getByRole("region", { name: "Selection" });
    await expect(panel.locator(".tag")).toHaveText("K-4101");
    await expect(panel.locator("[data-lift]")).toContainText("mobile from Z-PAD-A4, 12.5 m radius, 650 t m, 69.3 t chart capacity needed; lane clear");
    await expect(k4101).toHaveClass(/active/);
    await panel.locator("[data-lift]").getByRole("button", { name: "Z-PAD-A4" }).click();
    await expect(panel.locator(".tag")).toHaveText("Z-PAD-A4");
  });

  test("links an item's datasheet", async ({ page }) => {
    await page.goto("/layout?select=K-4101");
    const panel = page.getByRole("region", { name: "Selection" });
    await expect(panel.locator("[data-datasheet] a")).toHaveAttribute("href", /\/datasheets\/K-4101$/);
    await expect(panel.locator("[data-datasheet] a")).toHaveText("equipment/datasheets/K-4101.yaml");
    // A silencer is a piping item: no datasheet.
    await page.goto("/layout?select=S-1101");
    await expect(panel.locator("[data-datasheet]")).toContainText("none in equipment/datasheets/");
  });

  test("shows no lifting study where the repo has none", async ({ page }) => {
    await mockApi(page, { layout: mepLayout, mto: mtoMep });
    await page.goto("/layout");
    await expect(page.locator("canvas.layout-canvas")).toBeVisible();
    await expect(page.getByRole("region", { name: "Equipment" })).toBeVisible();
    await expect(page.getByRole("region", { name: "Lifting study" })).toHaveCount(0);
  });
});
