import { expect, test, type Page } from "@playwright/test";
import { asuFiles } from "./asuFiles";
import { mepLayout, mockApi, mtoMep, reactionsBedCooled, reactionsUnbalanced, simulationStale, streamsSimulation } from "./fixtures";

/**
 * Screenshots for checking by eye, only with `LAYOUT_SHOTS=<dir>`: a pump close up, the tank's
 * spiral stair, the cold box's stairs and proposals, the realistic look, trays and a cable route,
 * ducts, a wall penetration, the take-off page, the LCA page, the simulation tab and the reactions
 * page (light and dark).
 */
const SHOTS = process.env.LAYOUT_SHOTS ?? "";
const TWO_FRAMES = "new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve)))";
const ALL = "site,areas,roads,structures,platforms,equipment,nozzles,pipes,insulation,inline,trays,ducts,zones";
const NO_ZONES = "site,areas,roads,structures,platforms,equipment,nozzles,pipes,insulation,inline,trays,ducts";

test.use({ launchOptions: { args: ["--ignore-gpu-blocklist", "--enable-gpu", ...(process.platform === "darwin" ? ["--use-angle=metal"] : [])] } });

async function shot(page: Page, url: string, name: string): Promise<void> {
  await page.goto(url);
  await expect(page.locator("canvas.layout-canvas")).toBeVisible();
  await page.waitForFunction(() => !!(globalThis as unknown as { __layoutRenderer?: unknown }).__layoutRenderer);
  await page.evaluate(TWO_FRAMES);
  await page.waitForTimeout(400);
  await page.locator(".layout .stage").screenshot({ path: `${SHOTS}/${name}.png` });
}

test.describe("screenshots", () => {
  test.skip(!SHOTS, "screenshots only on request");

  test("the ASU close up", async ({ page }) => {
    await mockApi(page);
    await shot(page, `/layout?cam=62.6,53.6,2.4,66,57,0.6&layers=${NO_ZONES}&look=realistic`, "asu-pump-closeup-realistic");
    await shot(page, `/layout?cam=62.6,53.6,2.4,66,57,0.6&layers=${NO_ZONES}`, "asu-pump-closeup");
    await shot(page, `/layout?cam=104,92,14,118,106,5&layers=${NO_ZONES}&look=realistic`, "asu-tank-stair-realistic");
    await shot(page, `/layout?cam=190,-15,60,133,44,22&layers=${NO_ZONES}&mode=provenance`, "asu-coldbox-stairs-provenance");
    await shot(page, `/layout?cam=190,-15,60,133,44,22&layers=${NO_ZONES}&look=realistic`, "asu-coldbox-stairs-realistic");
    await shot(page, `/layout?cam=150,30,14,140,41,10&layers=${NO_ZONES}&look=realistic&select=platform:CB-1/stair-to-E20`, "asu-coldbox-stair-proposal");
    await shot(page, `/layout?cam=40,-15,75,110,60,5&layers=${NO_ZONES},buildings,labels&look=realistic`, "asu-iso-realistic");
  });

  test("a wall penetration and an engineering finding", async ({ page }) => {
    await mockApi(page);
    await shot(page, `/layout?cam=27,22,8,36.1,29,3.7&select=penetration:B1/AIR-1001&layers=${NO_ZONES},buildings`, "asu-penetration");
    await shot(page, `/layout?cam=27,22,8,36.1,29,3.7&layers=${NO_ZONES},buildings&look=realistic`, "asu-penetration-realistic");
  });

  test("operators, the hatch H1 and the lifting study (pre-release issue 61)", async ({ page }) => {
    await mockApi(page, { files: asuFiles });
    await shot(page, `/layout?cam=143,57,26,138.3,47,20.9&layers=${NO_ZONES}&select=hatch:CB-1/H1`, "asu-hatch-h1");
    await shot(page, `/layout?cam=143,57,26,138.3,47,20.9&layers=${NO_ZONES}&look=realistic`, "asu-hatch-h1-realistic");
    await shot(page, `/layout?cam=67.5,54.5,5,63.8,58.5,2.6&layers=${NO_ZONES}&select=inline:P-01/BV_P1101A_S`, "asu-chainwheel-valve");
    await shot(page, `/layout?cam=67.5,54.5,5,63.8,58.5,2.6&layers=${NO_ZONES}&look=realistic`, "asu-chainwheel-valve-realistic");
    await shot(page, `/layout?cam=20,19,7,25.6,27.7,3&layers=${NO_ZONES}&select=nozzle:F-1101/I1`, "asu-remote-transmitter-capillary");
    await shot(page, `/layout?cam=80,46,14,74.6,52,10&layers=${NO_ZONES}&select=nozzle:C-1101/I1`, "asu-remote-transmitter-platform");
    await page.goto("/layout?select=K-4101");
    const study = page.getByRole("region", { name: "Lifting study" });
    await expect(study.locator("tr[data-lift]")).toHaveCount(14);
    await study.scrollIntoViewIfNeeded();
    await study.screenshot({ path: `${SHOTS}/asu-lifting-panel.png` });
    await page.getByRole("region", { name: "Selection" }).screenshot({ path: `${SHOTS}/asu-lifting-selection.png` });
  });

  test("trays, a cable route and ducts", async ({ page }) => {
    await mockApi(page, { layout: mepLayout, mto: mtoMep });
    const noBuildings = "site,areas,roads,structures,platforms,equipment,nozzles,pipes,insulation,inline,trays,ducts";
    await shot(page, `/layout?cam=2,-8,16,22,14,4&layers=${ALL}`, "mep-trays");
    await shot(page, `/layout?cam=2,-8,16,22,14,4&layers=${noBuildings}&select=equipment:P-101`, "mep-cable-route-pump");
    await shot(page, `/layout?cam=2,-8,16,22,14,4&layers=${noBuildings}&select=PT-101`, "mep-cable-route-instrument");
    await shot(page, `/layout?cam=16,-6,14,26,7,3&layers=${noBuildings}`, "mep-ducts");
    await shot(page, `/layout?cam=16,-6,14,26,7,3&layers=${noBuildings}&look=realistic&detail=full`, "mep-ducts-realistic");
    await shot(page, `/layout?cam=16,-6,14,26,7,3&layers=${noBuildings}&select=hvac_room:HALL`, "mep-room-ducts");
  });

  test("the take-off page", async ({ page }) => {
    await mockApi(page);
    await page.goto("/mto");
    await expect(page.getByRole("region", { name: "Estimate" })).toBeVisible();
    await page.screenshot({ path: `${SHOTS}/mto-page.png`, fullPage: false });
    await page.locator('section.category[data-category="steel"]').scrollIntoViewIfNeeded();
    await page.screenshot({ path: `${SHOTS}/mto-steel.png` });
  });

  test("the LCA page", async ({ page }) => {
    await mockApi(page);
    for (const scheme of ["light", "dark"] as const) {
      await page.emulateMedia({ colorScheme: scheme });
      await page.setViewportSize({ width: 1280, height: 1000 });
      await page.goto("/lca");
      await expect(page.getByRole("img", { name: /Contributions/ })).toBeVisible();
      await page.screenshot({ path: `${SHOTS}/lca-page-${scheme}.png`, fullPage: true });
      await page.getByRole("region", { name: "Scenarios" }).screenshot({ path: `${SHOTS}/lca-scenarios-${scheme}.png` });
      await page.getByRole("region", { name: "Contribution table" }).screenshot({ path: `${SHOTS}/lca-table-${scheme}.png` });
      await page.getByRole("region", { name: "Allocation" }).screenshot({ path: `${SHOTS}/lca-allocation-${scheme}.png` });
      await page.getByRole("region", { name: "Uncertainty" }).screenshot({ path: `${SHOTS}/lca-uncertainty-${scheme}.png` });
    }
    await page.setViewportSize({ width: 390, height: 900 });
    await page.goto("/lca");
    await expect(page.getByRole("img", { name: /Contributions/ })).toBeVisible();
    await page.screenshot({ path: `${SHOTS}/lca-page-phone.png`, fullPage: false });
  });

  test("the simulation tab and the reactions page", async ({ page }) => {
    await mockApi(page, { simulation: simulationStale, streams: streamsSimulation, reactions: reactionsUnbalanced });
    for (const scheme of ["light", "dark"] as const) {
      await page.emulateMedia({ colorScheme: scheme });
      for (const [width, size] of [[1280, "desktop"], [390, "phone"]] as const) {
        await page.setViewportSize({ width, height: 900 });
        await page.goto("/streams?tab=simulation");
        await expect(page.getByRole("table", { name: "Simulation units" })).toBeVisible();
        await page.screenshot({ path: `${SHOTS}/simulation-${size}-${scheme}.png`, fullPage: true });
        await page.goto("/streams");
        await expect(page.locator("tr[data-stream]").first()).toBeVisible();
        await page.screenshot({ path: `${SHOTS}/simulation-streams-${size}-${scheme}.png` });
        await page.goto("/reactions");
        await expect(page.getByRole("table", { name: "Reactors" })).toBeVisible();
        await page.screenshot({ path: `${SHOTS}/reactions-${size}-${scheme}.png`, fullPage: true });
      }
    }
  });

  test("a fixed bed with an interior hot spot", async ({ page }) => {
    await mockApi(page, { reactions: reactionsBedCooled });
    for (const scheme of ["light", "dark"] as const) {
      await page.emulateMedia({ colorScheme: scheme });
      for (const [width, size] of [[1280, "desktop"], [390, "phone"]] as const) {
        await page.setViewportSize({ width, height: 900 });
        await page.goto("/reactions");
        const bed = page.getByRole("article", { name: "Fixed bed R1" });
        await bed.getByRole("img", { name: /^Temperature/ }).hover({ position: { x: 150, y: 60 } });
        await bed.screenshot({ path: `${SHOTS}/bed-${size}-${scheme}.png` });
      }
    }
  });
});
