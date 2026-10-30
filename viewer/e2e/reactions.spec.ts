import { expect, test } from "@playwright/test";
import { mockApi, reactionsAmmonia, reactionsBedCooled, reactionsBedFailed, reactionsBedSim, reactionsShift, reactionsUnbalanced, simulationBedStale, streamsAmmonia } from "./fixtures";

/** The ammonia loop's stream table with its reactor R1 linked to R-101 on P-01 (the example has no P&ID). */
const streamsLinked = {
  ...streamsAmmonia,
  nodes: streamsAmmonia.nodes.map((n) =>
    n.id === "R1" ? { ...n, links: [{ target: "equipment", ref: "R-101", sheet: "P-01", role: "", resolved: true, problem: null }] } : n,
  ),
};

/** The reactions page: core's real `/api/reactions` of its examples/process-ammonia. */
test.describe("reactions", () => {
  test("the nav and home link it; reactions, reactors, balances", async ({ page }) => {
    await mockApi(page, { reactions: reactionsAmmonia, streams: streamsLinked });
    await page.goto("/");
    await expect(page.getByTestId("home-pages").getByRole("link", { name: "Reactions" })).toBeVisible();
    await page.getByRole("navigation", { name: "Pages" }).getByRole("link", { name: "Reactions" }).click();
    await expect(page).toHaveURL(/\/reactions/);
    await expect(page.getByRole("heading", { level: 1 })).toContainText("Reactions");
    await expect(page.getByRole("heading", { level: 1 })).toContainText("process/reactions.yaml in the working tree");
    await expect(page.getByLabel("Case")).toHaveValue("design");

    const reactions = page.getByRole("table", { name: "Reactions" });
    const syn = reactions.locator('tr[data-reaction="NH3_SYN"]');
    await expect(syn).toContainText("Ammonia synthesis");
    await expect(syn.locator("[data-equation]")).toHaveText("N2 + 3 H2 <=> 2 NH3");
    await expect(syn.locator("[data-type]")).toHaveText("equilibrium");
    await expect(syn).toContainText("vapor reversible");
    await expect(syn.locator("[data-extent]")).toHaveText("K from the components' ideal-gas data");
    await expect(syn.locator("[data-heat]")).toContainText("-91116 kJ/kmol at 298.15 K");
    await expect(syn.locator("[data-heat] .prov")).toHaveText("G");
    await expect(syn.locator("[data-heat] .prov")).toHaveAttribute("title", /given: 2 x dHf\(NH3, g\)/);
    await expect(syn.locator('[data-catalyst] [data-link="catalyst"]')).toHaveText("FE_NH3");
    await expect(syn.locator('[data-place="R1"]')).toContainText("R1 equilibrium, ΔT 20 K");
    await expect(syn.locator("[data-elements]")).toHaveText("balanced");
    await expect(syn.locator("[data-elements]")).toHaveClass(/pass/);
    await syn.locator(".sources summary").click();
    await expect(syn.locator(".sources li")).toContainText("Ullmann");

    const reactors = page.getByRole("table", { name: "Reactors" });
    const r1 = reactors.locator('tr[data-reactor="R1"]');
    await expect(r1.locator("[data-t-out]")).toHaveText("743.15 K");
    await expect(r1).toContainText("20000 kPa");
    await expect(r1.locator("[data-extent]")).toHaveText("222.942 kmol/h");
    await expect(r1.locator("[data-approach]")).toContainText("-5.62e-6");
    await expect(r1.locator("[data-approach] .badge")).toHaveText("at equilibrium");
    await expect(r1.locator("[data-duty]")).toHaveText("-4798.1 kW");
    await expect(r1.locator('[data-link="pid"]')).toHaveAttribute("href", /\/pid\/pid\/P-01\.xml\?select=R-101/);
    const loop = reactors.locator('tr[data-reactor="LOOP"]');
    await expect(loop.locator('[data-link="pid"]')).toHaveCount(0);
    await expect(loop.locator("[data-missing]")).toContainText("one outlet with a temperature");
    await expect(loop.locator("[data-duty]")).toHaveText("");

    const balances = page.getByRole("table", { name: "Reactive balances" });
    await expect(balances.locator("tr[data-balance]")).toHaveCount(2);
    await expect(balances.locator('tr[data-balance="R1"]')).toContainText("NH3_SYN 222.942 kmol/h");
    await expect(page.locator("[data-no-findings]")).toBeVisible();
    // no rate law, no bed; the catalyst of the converter
    await expect(page.locator("[data-rate-law]")).toHaveCount(0);
    await expect(page.locator("[data-bed]")).toHaveCount(0);
    const cat = page.getByRole("article", { name: "Catalyst FE_NH3" });
    await expect(cat).toContainText("Promoted iron ammonia synthesis catalyst");
    await expect(cat.locator("[data-catalyses]")).toHaveText("NH3_SYN");
    await expect(cat.locator("[data-held-by]")).toContainText("R1");
    await expect(cat.locator("[data-window]")).toContainText("643.15–803.15 K, 10000–35000 kPa(a)");
    await expect(cat.locator("[data-window] .prov")).toHaveText("A");

    await r1.locator('[data-link="pid"]').click();
    await expect(page).toHaveURL(/\/pid\/pid\/P-01\.xml\?select=R-101/);
  });

  test("an unbalanced reaction: its badge, the atoms, the findings", async ({ page }) => {
    await mockApi(page, { reactions: reactionsUnbalanced, streams: streamsAmmonia });
    await page.goto("/reactions");
    await expect(page.getByRole("heading", { level: 1 }).locator(".badge")).toHaveText("1 unbalanced");
    const syn = page.locator('tr[data-reaction="NH3_SYN"]');
    await expect(syn.locator("[data-elements]")).toHaveText("unbalanced");
    await expect(syn.locator("[data-elements]")).toHaveClass(/error/);
    await expect(syn).toContainText("N +1, H +3");
    const findings = page.getByRole("region", { name: "Reaction findings" });
    await expect(findings.locator("li")).toHaveCount(4);
    await expect(findings.locator('li[data-rule="cheme.reaction-element-balance"]')).toContainText("reaction NH3_SYN does not balance");
    await expect(findings.locator('li[data-rule="cheme.reaction-element-balance"] a')).toHaveAttribute("href", /\/file\/process\/reactions\.yaml\?line=11/);
    await expect(page.locator('tr[data-balance="R1"]')).toHaveClass(/error/);
  });

  test("the case select asks for the case; a core without kinetics: no catalysts", async ({ page }) => {
    const requests: string[] = [];
    page.on("request", (r) => {
      if (r.url().includes("/api/reactions")) requests.push(r.url());
    });
    await mockApi(page, { reactions: { ...reactionsAmmonia, cases: ["design", "turndown"], kinetics: null }, streams: streamsAmmonia });
    await page.goto("/reactions");
    await expect(page.locator("[data-no-catalysts]")).toContainText("No process/catalysts.yaml");
    await page.getByLabel("Case").selectOption("turndown");
    await expect(page).toHaveURL(/case=turndown/);
    await expect(page.getByLabel("Case")).toHaveValue("turndown");
    expect(requests.some((u) => u.includes("case=turndown"))).toBe(true);
  });

  test("kinetics: the rate law with its parameters and k(T), the bed, the catalyst linked both ways", async ({ page }) => {
    await mockApi(page, { reactions: reactionsShift });
    await page.goto("/reactions");
    const wgs = page.locator('tr[data-reaction="WGS"]');
    await expect(wgs.locator('[data-link="rate-law"]')).toHaveText("power law");

    const law = page.getByRole("article", { name: "Rate law of WGS" });
    await expect(law.locator("[data-expression]")).toHaveText("r = k(T) · p_CO · p_CO2^-0.36 · p_H2^-0.09 · (1 - Q/K)");
    await expect(law.locator("[data-form]")).toHaveText("power law, per kg of catalyst, on partial pressures (bar), to equilibrium (1 − Q/K)");
    await expect(law.locator("[data-k]")).toHaveText("A 1000 kmol/(kg s) / bar^0.55, Ea 111000 kJ/kmol");
    await expect(law.locator("[data-orders]")).toHaveText("CO 1, CO2 -0.36, H2 -0.09");
    await expect(law.locator("[data-range]")).toHaveText("573.15–773.15 K");
    await expect(law.locator("[data-prov]")).toHaveText("A");
    await expect(law.locator("[data-prov]")).toHaveAttribute("title", /^assumed: form and Ea of Hla/);
    await expect(law.locator("[data-source]")).toContainText("doi:10.1016/j.cej.2008.09.023");
    const chart = law.getByRole("img", { name: "k(T) of WGS over its temperature_range" });
    await expect(chart.locator("path.line")).toHaveAttribute("d", /^M0\.0,110\.0 /);
    await expect(chart.locator("[data-x-min]")).toHaveText("573.1");
    await expect(chart.locator("[data-x-max]")).toHaveText("773.1");
    await expect(chart.locator("[data-y-min]")).toHaveText("7.66e-8");
    await expect(law.locator("figcaption")).toHaveText("k in kmol/(kg s) / bar^0.55, over the rate law's temperature range");

    const bed = page.getByRole("article", { name: "Fixed bed R1" });
    await expect(bed.locator("[data-bed-catalyst]")).toHaveText("40000 kg, 35.4 m³ of bed (FE_CR)");
    await expect(bed.locator("[data-hot-spot] strong")).toHaveText("704.415 K");
    await expect(bed.locator("[data-peak-place]")).toHaveText("the sampled value at the outlet (40000 kg): an endpoint maximum, no interior hot spot");
    await expect(bed.locator("[data-pressure-drop]")).toHaveText("0.7491 kPa");
    await expect(bed.getByRole("img", { name: /^Temperature along the catalyst of R1/ })).toBeVisible();
    await expect(bed.getByRole("img", { name: /^Pressure along the catalyst of R1/ })).toBeVisible();
    await expect(page.locator('tr[data-reactor="R1"] [data-rate]')).toContainText("kmol/(kg s)");

    const cat = page.getByRole("article", { name: "Catalyst FE_CR" });
    await expect(cat.locator("[data-active-phase]")).toHaveText("Fe3O4 (from Fe2O3)");
    await expect(cat.locator("[data-physical]")).toContainText("pellet, d 6 mm, sphericity 0.86, particle 1950 kg/m³, bulk 1130 kg/m³, voidage 0.42, BET 80 m²/g");
    await expect(cat.locator("[data-held-by]")).toContainText("R1 pfr, catalyst mass 40000 kg, diameter 3 m, adiabatic, viscosity 0.000026 Pa s");
    await expect(cat.locator("[data-price]")).toContainText("12 USD/kg (2024)");
    await expect(cat.locator("[data-deactivation]")).toContainText("5 years; sintering, poisoning");
    const findings = page.getByRole("region", { name: "Catalyst findings" });
    await expect(findings.locator('li[data-rule="cheme.catalyst-poison"]')).toHaveCount(2);

    // reaction -> catalyst -> reaction
    await wgs.locator('[data-link="catalyst"]').click();
    await expect(cat).toHaveClass(/focused/);
    await expect(cat).toBeInViewport();
    await cat.locator('[data-catalyses] [data-link="reaction"]').click();
    await expect(wgs).toHaveClass(/focused/);
    await wgs.locator('[data-link="rate-law"]').click();
    await expect(law).toHaveClass(/focused/);
    await expect(page).toHaveURL(/\/reactions$/);
  });

  test("without process/reactions.yaml: no nav link, a hint", async ({ page }) => {
    await mockApi(page);
    await page.goto("/");
    await expect(page.getByRole("navigation", { name: "Pages" }).getByRole("link", { name: "Reactions" })).toHaveCount(0);
    await expect(page.getByRole("link", { name: "Reactions and reactors" })).toHaveCount(0);
    await page.goto("/reactions");
    await expect(page.locator("[data-reactions-missing]")).toContainText("No reactions");
  });

  test("phone width: the tables scroll inside, the page does not", async ({ page }) => {
    await mockApi(page, { reactions: reactionsShift });
    await page.setViewportSize({ width: 375, height: 740 });
    await page.goto("/reactions");
    await expect(page.getByRole("table", { name: "Reactors" })).toBeVisible();
    const overflow = await page.locator("main").evaluate((el) => el.scrollWidth - el.clientWidth);
    expect(overflow).toBeLessThanOrEqual(1);
    const [scroll, width] = await page.locator("html").evaluate((el) => [el.scrollWidth, el.clientWidth]);
    expect(scroll).toBeLessThanOrEqual(width! + 1);
  });

  test("fixed beds: an interior hot spot with its references, the profile table, a bed core could not solve", async ({ page }) => {
    await mockApi(page, { reactions: reactionsBedCooled });
    await page.goto("/reactions");
    const bed = page.getByRole("article", { name: "Fixed bed R1" });
    await expect(bed.locator("[data-bed-mode-text]")).toHaveText("cooled: coolant 620 K, U 30 W/(m² K), 800 tubes of 0.1 m");
    await expect(bed.locator("[data-peak-place]")).toHaveText("the sampled value at 12800 kg (inside the bed): an interior hot spot");
    const chart = bed.getByRole("img", { name: /^Temperature along the catalyst of R1/ });
    await expect(chart.locator("[data-peak-marker]")).toHaveCount(1);
    await expect(chart.locator("[data-reference]")).toHaveCount(2);
    await chart.focus();
    await page.keyboard.press("End");
    await expect(bed.locator("[data-readout]").first()).toHaveText(/^Catalyst mass 40000 kg \(outlet\): T 627\.45 K/);
    await bed.locator(".profile-table summary").click();
    await expect(bed.getByRole("table", { name: "Profile of R1" }).locator("tbody tr")).toHaveCount(51);
    const download = page.waitForEvent("download");
    await bed.locator('[data-action="bed-csv"]').click();
    expect((await download).suggestedFilename()).toBe("bed-R1-design.csv");

    await mockApi(page, { reactions: reactionsBedFailed });
    await page.goto("/reactions");
    const failed = page.getByRole("article", { name: "Fixed bed R1" });
    await expect(failed.locator("[data-bed-failure]")).toContainText("a cooled bed needs coolant_temperature, heat_transfer_coefficient and diameter");
    await expect(failed.locator("[data-bed-chart]")).toHaveCount(0);
  });

  test("fixed beds: the bed's row of a stale simulation run", async ({ page }) => {
    await mockApi(page, { reactions: reactionsBedSim, simulation: simulationBedStale });
    await page.goto("/reactions");
    const bed = page.getByRole("article", { name: "Fixed bed R1" });
    await expect(bed.locator("[data-run-state]")).toHaveText("stale");
    await expect(bed.locator("[data-run-stale]")).toContainText("process/flowsheet.yaml");
    await expect(bed.locator('[data-flat="pressure"]')).toContainText("core calculated no pressure drop");
  });
});
