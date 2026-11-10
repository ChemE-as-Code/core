import { expect, test } from "@playwright/test";
import { mockApi, streamsSimulation } from "./fixtures";

function wastewater(stale = false) {
  const table = structuredClone(streamsSimulation);
  const columns = [
    ["flow", "Flow", "m3/day"], ["COD", "COD", "mg COD/L"],
    ["TN", "TN", "mg N/L"], ["TP", "TP", "mg P/L"],
    ["TSS", "TSS", "mg TSS/L"], ["NH4", "NH4-N", "mg N/L"], ["PO4", "PO4-P", "mg P/L"],
  ].map(([key, label, unit]) => ({ key, label, unit, basis: label }));
  return {
    ...table,
    wastewater: {
      status: "available", case: table.case, run_file: "process/simulation-run.json",
      run_at: "2026-11-04T16:49:23+01:00", evidence: "runs/recorded-example",
      stale, changed_files: stale ? ["inputs/baseline.json"] : [], columns,
      findings: [] as { file: string; rule: string; message: string; hint: string }[],
    },
    streams: table.streams.map(s => ({
      ...s, stale: stale ? ["wastewater"] : [],
      wastewater: Object.fromEntries(columns.map((c, i) => [c.key, {
        value: i === 0 ? 18061 : i === 1 ? 44.91762822 : i === 2 ? 15.67771051 : i === 3 ? 7.39093409 : 0,
        unit: c.unit, provenance: "calculated", source: "process/simulation-run.json", stale,
      }])),
    })),
  };
}

test("native stream table shows wastewater units, values, filtering and separate balances", async ({ page }) => {
  await mockApi(page, { streams: wastewater() });
  await page.goto("/streams");
  await expect(page.locator("[data-wastewater]")).toContainText("runs/recorded-example");
  await expect(page.locator('[data-wastewater-column="flow"]')).toHaveText("Flowm3/day");
  await expect(page.locator('[data-wastewater-column="COD"]')).toContainText("mg COD/L");
  await expect(page.locator('[data-wastewater-column="TN"]')).toContainText("mg N/L");
  await expect(page.locator('[data-wastewater-column="TP"]')).toContainText("mg P/L");
  const row = page.locator('tr[data-stream="S1"]');
  await expect(row.locator('[data-field="flow"]')).toHaveText("18061 C");
  await expect(row.locator('[data-field="COD"]')).toHaveText("44.9176 C");
  await expect(row.locator('[data-field="TN"]')).toHaveText("15.6777 C");
  await expect(row.locator('[data-field="TP"]')).toHaveText("7.39093 C");
  await expect(row.locator('[data-field="NH4"]')).toHaveText("0 C");
  await expect(page.locator('th', { hasText: /^Pressure$/ })).toHaveCount(0);
  await expect(page.locator(".balance-table")).not.toBeVisible();
  await page.getByText("Molecular mass-balance checks (separate from wastewater results)").click();
  await expect(page.locator(".balance-table")).toBeVisible();
  await page.getByRole("searchbox", { name: "Filter streams" }).fill("S1");
  await expect(page.locator("tr[data-stream]")).toHaveCount(1);
});

test("stale run shows changed inputs and marks its values", async ({ page }) => {
  await mockApi(page, { streams: wastewater(true) });
  await page.goto("/streams");
  await expect(page.locator("[data-wastewater-stale]")).toBeVisible();
  await expect(page.locator("[data-wastewater]")).toContainText("inputs/baseline.json");
  await expect(page.locator('tr[data-stream="S1"]')).toHaveClass(/stale/);
  await expect(page.locator('tr[data-stream="S1"] [data-field="TN"] .badge')).toHaveText("stale");
});

test("missing results stay blank with an explanation, never zero", async ({ page }) => {
  const table = wastewater();
  table.wastewater.status = "missing";
  table.wastewater.findings = [{ file: "process/simulation-run.json", rule: "cheme.process-wastewater-record", message: "No saved wastewater run.", hint: "Record a new run." }];
  table.streams.forEach(s => { s.wastewater = {}; });
  await mockApi(page, { streams: table });
  await page.goto("/streams");
  await expect(page.locator('tr[data-stream="S1"] [data-field="TN"]')).toHaveText("—");
  await page.locator("[data-wastewater-findings] summary").click();
  await expect(page.locator("[data-wastewater-findings]")).toContainText("No saved wastewater run.");
});
