import { expect, test } from "@playwright/test";
import { mockApi, teaAsu, teaBlocks } from "./fixtures";

/**
 * The TEA page: the ASU's `/api/tea` (an LCOP decision, its main product unpriced) and core's
 * process-blocks (a cash cost decision, example premises, a chemical, an event, an emission).
 */
test.describe("techno-economic analysis", () => {
  test("the ASU: decision, results, capital, operating cost, cash flow, scenarios, tornado, break-even, Monte Carlo", async ({ page }) => {
    await mockApi(page, { tea: teaAsu });
    await page.goto("/");
    await page.getByRole("navigation", { name: "Pages" }).getByRole("link", { name: "TEA" }).click();
    await expect(page).toHaveURL(/\/tea/);
    await expect(page.getByRole("heading", { level: 1 })).toContainText("USD 2023");
    // real premises: no example note
    await expect(page.getByRole("note")).toHaveCount(0);

    const decision = page.getByRole("region", { name: "Decision" });
    await expect(decision).toContainText("Take ASU-1 from basic engineering into FEED");
    await expect(decision.locator('[data-verdict="threshold"]')).toContainText("meets");
    await expect(decision.locator('[data-verdict="threshold"]')).toContainText("≤ 100 USD/t");
    await expect(decision.locator('[data-verdict="confidence"]')).toContainText("confident");
    await expect(decision.locator('[data-verdict="class"]')).toContainText("AACE class 5");
    await expect(decision.locator('[data-verdict="class"]')).toContainText("coarser than the basic stage expects (class 4)");

    const cards = page.getByRole("region", { name: "Results" });
    await expect(cards.locator('[data-card="lcop"]')).toContainText("73.94 USD/t");
    await expect(cards.locator('[data-card="lcop"]')).toContainText("decision");
    await expect(cards.locator('[data-card="npv"]')).toContainText("-128.1 M USD");
    await expect(cards.locator('[data-card="npv"]')).toContainText("without the main product's revenue");
    await expect(cards.locator('[data-card="irr"]')).toContainText("none");
    await expect(cards.locator('[data-card="payback_years"]')).toContainText("never");
    await expect(cards.locator('[data-card="fixed_capital"]')).toContainText("36.5 M USD");
    await expect(cards.locator('[data-card="cash_cost"]')).toContainText("53.47 USD/t");

    const cost = page.getByRole("region", { name: "Cost of production" });
    await expect(cost.locator('[data-cost="utility"]')).toContainText("40.34 USD/t");
    await expect(cost.locator('[data-cost="total"]')).toContainText("73.94 USD/t");
    await expect(cost.getByRole("img", { name: /Cost of production/ })).toBeVisible();

    const capital = page.getByRole("region", { name: "Capital cost" });
    await expect(capital.locator('[data-capex="fixed_capital"]')).toContainText("36,500,000 USD");
    await expect(capital.getByRole("img", { name: /AACE range/ })).toBeVisible();
    await expect(capital).toContainText("-50 % to -20 %");

    const opex = page.getByRole("region", { name: "Operating cost" });
    await expect(opex.locator('[data-flow="feed:POWER"]')).toContainText("80.4 USD/MWh");
    await expect(opex.locator('[data-flow="feed:AIR"]')).toContainText("free");
    await expect(opex.locator('[data-flow="product:GOXP"]')).toContainText("main product");
    await expect(opex.locator('[data-flow="product:LOX"]')).toContainText("no price");
    await expect(opex.locator("[data-unpriced]")).toContainText("LOX to storage, LIN to storage");
    await expect(opex.locator('[data-opex="maintenance"]')).toContainText("1.095 M USD");
    await expect(opex.getByRole("table", { name: "Priced lines" }).locator('[data-line="product:GOXP"]')).toContainText("main product");

    // core's boundary check: gaps, what the operating cost leaves out, the boundary findings here
    const boundary = page.getByTestId("tea-boundary");
    await expect(boundary).toContainText("gaps found");
    await expect(boundary.locator('[data-boundary="excluded"]')).toContainText("GANP, LOX, LIN, CW");
    await expect(boundary.locator('[data-boundary="duties"]')).toContainText("C1101U");
    await expect(boundary.getByRole("region", { name: "Boundary gaps" })).toContainText("boundary-unclassified");

    const cashflow = page.getByRole("region", { name: "Cash flow" });
    await expect(cashflow.getByRole("img", { name: /Cash flow per year: 27 years/ })).toBeVisible();
    await expect(cashflow.locator("[data-year]").first()).toBeVisible();
    await cashflow.locator('[data-action="cashflow-table"]').click();
    const table = cashflow.getByRole("table", { name: "Cash flow table" });
    await expect(table.locator('tr[data-year="0"]')).toContainText("-14.60");
    await expect(table.locator("thead")).toContainText("periodic");

    const scenarios = page.getByRole("region", { name: "Scenarios" });
    await expect(scenarios.locator("[data-scenario]")).toHaveCount(4);
    await expect(scenarios.locator('[data-scenario="power-california"]')).toContainText("does not meet");
    await expect(scenarios.locator('[data-bar="power-california"] [data-value]')).toContainText("127.1 USD/t");

    const tornado = page.getByRole("region", { name: "Tornado" });
    await expect(tornado.locator("[data-bar]").first()).toHaveAttribute("data-bar", "capex:isbl");
    await expect(tornado.locator('[data-tornado="capex:isbl"]')).toContainText("Capital: ISBL (given)");

    const breakEven = page.getByRole("region", { name: "Break-even" });
    await expect(breakEven.locator('[data-turn="price:feed:POWER"]')).toContainText("132.3 USD/MWh");

    const uncertainty = page.getByRole("region", { name: "Uncertainty" });
    await expect(uncertainty.getByRole("img", { name: /P10 to P90/ })).toBeVisible();
    await expect(uncertainty.locator("[data-interval]")).toContainText("USD/t");
    await expect(uncertainty.locator('[data-input="capex:isbl"]')).toContainText("Capital: ISBL (given)");
    await uncertainty.locator('[data-action="statistic"]').selectOption("fixed_capital");
    await expect(uncertainty.locator("[data-interval]")).toContainText("M USD");

    await expect(page.getByRole("region", { name: "Inputs" }).locator('[data-input-row="finance:discount_rate"]')).toContainText("8 %");
    await expect(page.getByRole("region", { name: "Findings" })).toContainText("tea-price-missing");
  });

  test("process-blocks: example premises, a cash cost decision, a chemical, an event, an emission", async ({ page }) => {
    await mockApi(page, { tea: teaBlocks });
    await page.goto("/tea");
    await expect(page.getByRole("heading", { level: 1 })).toContainText("EUR 2025");
    await expect(page.getByRole("note")).toContainText("example");
    const decision = page.getByRole("region", { name: "Decision" });
    await expect(decision.locator('[data-verdict="threshold"]')).toContainText("Cash cost 361.8 EUR/t");
    await expect(decision.locator('[data-verdict="threshold"]')).toContainText("≤ 600 EUR/t");
    const cards = page.getByRole("region", { name: "Results" });
    await expect(cards.locator('[data-card="cash_cost"]')).toContainText("decision");
    await expect(cards.locator('[data-card="irr"]')).toContainText("12.3 %");
    await expect(cards.locator('[data-card="npv"]')).not.toContainText("main product");
    await expect(page.getByRole("region", { name: "Cost of production" }).locator('[data-cost="events"]')).toContainText("13.78 EUR/t");
    const opex = page.getByRole("region", { name: "Operating cost" });
    await expect(opex.getByRole("table", { name: "Variable items" }).locator('[data-variable="naoh"]')).toContainText("Aqueous feed");
    await expect(opex.getByRole("table", { name: "Events" }).locator('[data-event="catalyst"]')).toContainText("every 3 a from operating year 3");
    await expect(opex.locator("[data-emissions]")).toContainText("240 t CO2-eq/a");
    await expect(page.locator('[data-operation="ramp_up"]')).toHaveText("50 %, 80 %");
    await expect(page.getByRole("region", { name: "Scenarios" }).locator("thead")).toContainText("Cash cost");
    await expect(page.getByRole("region", { name: "Findings" })).toContainText("tea-example");
  });

  test("says how to start one when there is none, and hides the nav link", async ({ page }) => {
    await mockApi(page);
    await page.goto("/tea");
    await expect(page.getByText("No TEA")).toBeVisible();
    await expect(page.getByText("estimate/tea.yaml").first()).toBeVisible();
    await expect(page.getByRole("navigation", { name: "Pages" }).getByRole("link", { name: "TEA" })).toHaveCount(0);
  });

  test("a TEA that does not compute shows why", async ({ page }) => {
    await mockApi(page, { teaError: "estimate/tea.yaml:12: capex.isbl: give a value" });
    await page.goto("/tea");
    await expect(page.getByRole("alert")).toContainText("capex.isbl: give a value");
    await expect(page.getByRole("navigation", { name: "Pages" }).getByRole("link", { name: "TEA" })).toBeVisible();
  });

  test("fits a phone: no horizontal page scroll", async ({ page }) => {
    await mockApi(page, { tea: teaBlocks });
    await page.setViewportSize({ width: 390, height: 900 });
    await page.goto("/tea");
    await expect(page.getByRole("region", { name: "Results" })).toBeVisible();
    const overflow = await page.locator("main").evaluate((el) => el.scrollWidth - el.clientWidth);
    expect(overflow).toBeLessThanOrEqual(1);
    const pageOverflow = await page.evaluate(() => {
      const root = (globalThis as unknown as { document: { documentElement: { scrollWidth: number; clientWidth: number } } }).document.documentElement;
      return root.scrollWidth - root.clientWidth;
    });
    expect(pageOverflow).toBeLessThanOrEqual(1);
  });
});
