import { readFileSync } from "node:fs";
import { expect, test } from "@playwright/test";
import { lcaAsu, lcaReadiness, mockApi } from "./fixtures";
import { LOW_GRID, NO_GRID, withLowGrid, withMissingGrid } from "../tests/helpers/lcaScenario";

/**
 * The LCA page: the ASU's `/api/lca` (operation, construction, open background data DESNZ 2026: a
 * partial screening carbon footprint with declared gaps, publishable). The ASU has no scenario;
 * the scenario views are tested with a synthetic one (tests/helpers/lcaScenario.ts).
 */
const csv = (name: string) => readFileSync(new URL(`../tests/fixtures/api/${name}`, import.meta.url), "utf-8");

test.describe("life cycle assessment", () => {
  test("totals, the contribution Sankey, coverage, sources, tables and the CSV cheme-as-code writes", async ({ page }) => {
    await mockApi(page);
    await page.goto("/");
    await page.getByRole("navigation", { name: "Pages" }).getByRole("link", { name: "Life cycle assessment" }).click();
    await expect(page).toHaveURL(/\/lca/);
    await expect(page.getByRole("heading", { level: 1 })).toContainText("per 1 t GOXP");
    // what the result is, before the numbers
    await expect(page.locator("[data-result]")).toContainText("partial screening carbon footprint");
    await expect(page.locator("[data-result]")).toContainText("geography or reference year not checked");
    await expect(page.locator("[data-publication]")).toHaveCount(0);

    const totals = page.getByRole("region", { name: "Totals" });
    await expect(totals.locator('[data-card="total"]')).toContainText("66.7");
    await expect(totals.locator("[data-with-gaps]")).toContainText("not counted as 0");
    await expect(totals.locator('[data-card="construction"]')).toBeVisible();

    // The Sankey: the flows, the two phases and the functional unit.
    const sankey = page.getByRole("img", { name: /Contributions to Climate change/ });
    await expect(sankey).toBeVisible();
    await expect(sankey.locator('[data-node="total"]')).toContainText("1 t GOXP");
    await expect(sankey.locator('[data-node="phase:operation"]')).toBeVisible();
    await expect(sankey.locator('[data-node="phase:construction"]')).toBeVisible();
    await expect(sankey.locator('[data-node="flow:feed:POWER"]')).toContainText("Electric power");
    await expect(sankey.locator('[data-link="feed:POWER"]')).toHaveCount(1);

    // the gaps beside the total, with their quantities and why; the sources with attribution
    const gaps = page.getByRole("region", { name: "Gaps" });
    await expect(gaps.locator("[data-gap]")).toHaveCount(18);
    await expect(gaps).toContainText("construction:pipe");
    await expect(gaps).toContainText("no open factor per m of pipe");
    await expect(gaps).toContainText("no coverage percentage");
    const sources = page.getByRole("region", { name: "Sources" });
    await expect(sources.locator("[data-source]")).toContainText("OGL-3.0");
    await expect(sources.locator("[data-attribution]")).toContainText("Open Government Licence v3.0");
    await expect(page.getByRole("region", { name: "Scenarios" })).toHaveCount(0);
    const power = page.getByRole("region", { name: "Contribution table" }).locator('[data-key="feed:POWER"]');
    await expect(power).toBeVisible();
    // each contribution's status, location and source registry id
    await expect(power.locator("[data-status]")).toHaveText("PROXY");
    await expect(power.locator("[data-location]")).toHaveText("GB");
    await expect(power.locator("[data-source-id]")).toHaveText("desnz-ghg-2026");

    const inventory = page.getByRole("region", { name: "Inventory" });
    await expect(inventory.locator('[data-inventory="construction:steel"]')).toContainText("construction");
    await expect(page.getByRole("region", { name: "Findings" })).toContainText("lca-equipment-weight");

    const [download] = await Promise.all([page.waitForEvent("download"), page.locator('[data-action="lca-csv"]').click()]);
    expect(download.suggestedFilename()).toBe("lca-results.csv");
    expect(readFileSync(await download.path(), "utf-8")).toBe(csv("lca-asu.csv"));
  });

  test("scenario bars and the scenario selector", async ({ page }) => {
    await mockApi(page, { lca: withLowGrid(lcaAsu) });
    await page.goto("/lca");
    const bars = page.getByRole("region", { name: "Scenarios" });
    await expect(bars.locator("[data-scenario]")).toHaveCount(2);
    // the synthetic low-grid scenario: power at a quarter, so the bar is shorter
    // as the page formats an impact (src/lib/lca.ts impactText): 4 significant digits, grouped
    const impactText = (v: number) => Number(v.toPrecision(4)).toLocaleString("en-US", { maximumFractionDigits: 6 });
    const low = impactText(lcaAsu.totals["climate-change"] - lcaAsu.impacts.filter((i) => i.scenario === "baseline" && i.key === "feed:POWER").reduce((s, i) => s + i.value, 0) * 0.75);
    await expect(bars.locator(`[data-scenario="${LOW_GRID}"] [data-total]`)).toContainText(low);
    await page.locator('[data-action="scenario"]').selectOption(LOW_GRID);
    const totals = page.getByRole("region", { name: "Totals" });
    await expect(totals.locator('[data-card="total"]')).toContainText(low);
    // the scenario's gaps stay with it
    await expect(totals.locator("[data-with-gaps]")).toBeVisible();
    await expect(page.getByRole("region", { name: "Gaps" }).locator("[data-gap]")).toHaveCount(18);
  });

  test("a scenario missing the baseline's electricity gets no bar and no comparison", async ({ page }) => {
    await mockApi(page, { lca: withMissingGrid(lcaAsu) });
    await page.goto("/lca");
    const bars = page.getByRole("region", { name: "Scenarios" });
    const row = bars.locator(`[data-scenario="${NO_GRID}"]`);
    await expect(row.locator("[data-not-comparable]")).toContainText("Electric power");
    await expect(row.locator(".segment")).toHaveCount(0);
    await expect(row.locator("[data-total]")).toHaveText("–");
    await expect(bars.locator("[data-scenario-details]")).toContainText("background DE 2026 (not a plant location)");
    await expect(bars.locator("[data-scenario-details]")).toContainText("same plant, background only");
    await page.locator('[data-action="scenario"]').selectOption(NO_GRID);
    await expect(page.getByRole("region", { name: "Totals" }).locator("[data-not-comparable]")).toContainText("not comparable");
    // no number to read as a lower footprint: no total, no phase cards
    await expect(page.getByRole("region", { name: "Totals" }).locator("[data-no-total]")).toHaveText("no total");
    await expect(page.getByRole("region", { name: "Totals" }).locator('[data-card="construction"]')).toHaveCount(0);
  });

  test("the comparison verdict stands beside a scenario's number", async ({ page }) => {
    const verdicts = { baseline: { verdict: "baseline", reasons: [] }, [LOW_GRID]: { verdict: "not comparable", reasons: ["basis differs (direct+upstream / direct)"] } };
    await mockApi(page, { lca: { ...withLowGrid(lcaAsu), comparability: verdicts, scenario_details: [{ id: LOW_GRID, title: "low grid", location: "NL", year: 2026, electricity: null, case: null, source: "synthetic" }] } });
    await page.goto("/lca");
    const totals = page.getByRole("region", { name: "Totals" });
    // the baseline is the reference: no verdict beside it
    await expect(totals.locator("[data-verdict]")).toHaveCount(0);
    await page.locator('[data-action="scenario"]').selectOption(LOW_GRID);
    await expect(totals.locator('[data-verdict="not-comparable"]')).toContainText("nor as a country footprint");
    const details = page.getByRole("region", { name: "Scenarios" }).locator("[data-scenario-details]");
    await expect(details.locator("[data-scenario-verdict]")).toHaveText("not comparable");
    await expect(details).toContainText("basis differs");
  });

  test("a server without a verdict never shows a scenario as comparable", async ({ page }) => {
    await mockApi(page, { lca: withLowGrid(lcaAsu) });
    await page.goto("/lca");
    await page.locator('[data-action="scenario"]').selectOption(LOW_GRID);
    await expect(page.getByRole("region", { name: "Totals" }).locator('[data-verdict="not-assessed"]')).toBeVisible();
  });

  test("results not for publication say so", async ({ page }) => {
    const restricted = { ...lcaAsu, publication: { policy: "restricted", publishable: false, restricted_by: ["brightway:asu-1"] } };
    await mockApi(page, { lca: restricted });
    await page.goto("/lca");
    await expect(page.locator("[data-publication]")).toContainText("Not for publication");
    await expect(page.locator("[data-publication]")).toContainText("brightway:asu-1");
  });

  test("restricted results published under a reviewed decision say so", async ({ page }) => {
    const decided = { ...lcaAsu, publication: { policy: "restricted", publishable: true, restricted_by: ["vendor"] } };
    await mockApi(page, { lca: decided });
    await page.goto("/lca");
    await expect(page.locator("[data-publication]")).toHaveCount(0);
    await expect(page.locator("[data-publication-decision]")).toContainText("reviewed decision");
  });

  test("a source URL that is not http(s) is shown as plain text, not a link", async ({ page }) => {
    const [source] = lcaAsu.sources;
    if (!source) throw new Error("the ASU's LCA has no sources");
    await mockApi(page, { lca: { ...lcaAsu, sources: [{ ...source, url: "javascript:alert(document.domain)" }] } });
    await page.goto("/lca");
    const row = page.getByRole("region", { name: "Sources" }).locator("[data-source]");
    await expect(row).toContainText(source.title);
    await expect(row.locator("a")).toHaveCount(0);
  });

  test("an older server without coverage fields still shows the LCA", async ({ page }) => {
    const { classification, label, reasons, gaps, sources, publication, limitations, climate_only, ...older } = lcaAsu;
    void [classification, label, reasons, gaps, sources, publication, limitations, climate_only];
    await mockApi(page, { lca: older });
    await page.goto("/lca");
    await expect(page.getByRole("img", { name: /Contributions/ })).toBeVisible();
    await expect(page.locator("[data-result]")).toHaveCount(0);
    await expect(page.getByRole("region", { name: "Gaps" })).toHaveCount(0);
  });

  test("says how to start one when there is none, and hides the nav link", async ({ page }) => {
    await mockApi(page, { lca: null });
    await page.goto("/lca");
    await expect(page.getByText("No LCA")).toBeVisible();
    await expect(page.getByText("lca/lca.yaml").first()).toBeVisible();
    await expect(page.getByRole("navigation", { name: "Pages" }).getByRole("link", { name: "LCA" })).toHaveCount(0);
  });

  test("a single scenario shows no scenario bars", async ({ page }) => {
    const single = {
      ...lcaAsu,
      scenario_ids: ["baseline"],
      scenarios: { baseline: lcaAsu.scenarios.baseline },
      impacts: lcaAsu.impacts.filter((i) => i.scenario === "baseline"),
    };
    await mockApi(page, { lca: single });
    await page.goto("/lca");
    await expect(page.getByRole("img", { name: /Contributions/ })).toBeVisible();
    await expect(page.getByRole("region", { name: "Scenarios" })).toHaveCount(0);
    await expect(page.locator('[data-action="scenario"]')).toHaveCount(0);
  });
});

test.describe("LCA allocation, uncertainty and revisions", () => {
  test("every allocation method, the 95 % interval with what drives it, and another revision", async ({ page }) => {
    await mockApi(page);
    // the other revision: power halved
    await page.route(/\/api\/lca\?.*rev=/, (route) => {
      const halved = {
        ...lcaAsu,
        impacts: lcaAsu.impacts.map((i) => (i.key === "feed:POWER" ? { ...i, value: i.value / 2 } : i)),
        scenarios: Object.fromEntries(
          Object.entries(lcaAsu.scenarios).map(([s, totals]) => [
            s,
            Object.fromEntries(
              Object.entries(totals).map(([c, v]) => [
                c,
                v - lcaAsu.impacts.filter((i) => i.scenario === s && i.category === c && i.key === "feed:POWER").reduce((sum, i) => sum + i.value / 2, 0),
              ]),
            ),
          ]),
        ),
      };
      return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(halved) });
    });
    await page.goto("/lca");
    const allocation = page.getByRole("region", { name: "Allocation" });
    await expect(allocation.locator('[data-method="exergy"]')).toContainText("used");
    await expect(allocation.locator('[data-method="mass"]')).toContainText("60.8 %");
    await expect(allocation.locator('[data-method="shares"]')).toContainText("not applicable");
    // the substitutes are declared missing: substitution does not apply (no credit of 0)
    await expect(allocation.locator('[data-method="substitution"]')).toContainText("not applicable");

    const uncertainty = page.getByRole("region", { name: "Uncertainty" });
    await expect(uncertainty.locator("[data-interval]")).toContainText("..");
    await expect(uncertainty.getByRole("img", { name: /95 % interval/ })).toBeVisible();
    await expect(uncertainty.locator('[data-input="factor:desnz-ghg-2026:electricity-gb"]')).toContainText("desnz-ghg-2026:electricity-gb");
    await expect(page.getByRole("region", { name: "Totals" }).locator("[data-interval]")).toContainText("95 %");

    const compare = page.getByRole("region", { name: "Compare" });
    await compare.locator('[data-action="compare"]').selectOption("main");
    await expect(compare.locator('[data-compare="climate-change"]')).toContainText("%");
    await expect(compare.locator('[data-change="feed:POWER"]')).toContainText("+");
  });
});


test("a revision whose LCA fails says so, not that there is none", async ({ page }) => {
  await mockApi(page);
  await page.route(/\/api\/lca\?.*rev=/, (route) =>
    route.fulfill({ status: 500, contentType: "application/json", body: '{"error":"internal error"}' }),
  );
  await page.goto("/lca");
  const compare = page.getByRole("region", { name: "Compare" });
  await compare.locator('[data-action="compare"]').selectOption("main");
  await expect(compare.locator("[data-compare-error]")).toContainText("does not compute");
  await expect(compare.getByText("No LCA at")).toHaveCount(0);
});

test("a gap of unknown amount says so", async ({ page }) => {
  await mockApi(page);
  await page.goto("/lca");
  const row = page.getByRole("region", { name: "Gaps" }).locator("[data-gap]", { hasText: "no-weight:equipment-al/E-3103" });
  await expect(row).toContainText("unknown");
  await expect(row).toContainText("E-3103 has no dimensions.weight");
});

test("the LCI readiness of the dataset: closure, DQR, missing metadata, each linked to its source", async ({ page }) => {
  await mockApi(page, { lca: lcaReadiness, files: { "lca/dataset.yaml": csv("dataset-asu.yaml") } });
  await page.goto("/lca");
  const section = page.getByRole("region", { name: "LCI readiness" });
  await expect(section.locator('[data-balance-state="lci-mass-balance"]')).toHaveText("mass: closed");
  await expect(section.locator('[data-readiness-card="dqr"]')).toContainText("2.67");
  await expect(section.locator('[data-missing="location"]')).toBeVisible();
  await expect(section.locator('[data-topic="emissions"]')).toContainText("V-3101");
  await expect(section.locator('[data-source="balance"]')).toHaveAttribute("href", /\/file\/lca\/dataset\.yaml$/);
  await expect(section.locator('[data-source="dqr"]')).toHaveAttribute("href", /\/file\/lca\/dataset\.yaml$/);
  await section.locator("[data-excluded] summary").click();
  await expect(section.locator("[data-excluded] li", { hasText: "construction:concrete" }).getByRole("link")).toHaveAttribute("href", /\/file\/lca\/dataset\.yaml\?line=\d+/);
  await section.locator("summary", { hasText: "Pedigree per exchange" }).click();
  await section.locator('[data-pedigree-row="feed:AIR"] a').click();
  await expect(page).toHaveURL(/\/file\/lca\/dataset\.yaml\?line=\d+/);
});

test("an older core reports no readiness: the section is hidden", async ({ page }) => {
  await mockApi(page);
  await page.goto("/lca");
  await expect(page.getByRole("region", { name: "Totals" })).toBeVisible();
  await expect(page.getByRole("region", { name: "LCI readiness" })).toHaveCount(0);
});
