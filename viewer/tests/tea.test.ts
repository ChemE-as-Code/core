import { describe, expect, it } from "vitest";
import type { TeaReport } from "@/api";
import {
  basisRows,
  breakEvenRows,
  capexBuildUp,
  cashflowCell,
  cashflowChart,
  cashflowColumns,
  cashflowScale,
  classCheck,
  compactNumber,
  costOfProduction,
  decisionMetric,
  domainOf,
  eventScheduleText,
  extraTables,
  flowRows,
  inputLabel,
  lineLabel,
  lineRows,
  metricText,
  moneyText,
  operationRows,
  percentText,
  probabilityText,
  rangeGeometry,
  rhoWorsens,
  scenarioBars,
  scenarioMetrics,
  scenarioRows,
  statisticOf,
  toIntervalStats,
  tornadoBars,
  tornadoRows,
  unpricedFlows,
  verdict,
} from "@/lib/tea";
import asuJson from "./fixtures/api/tea-asu.json";
import blocksJson from "./fixtures/api/tea-blocks.json";

// Real /api/tea answers (scripts/regen-fixtures.py): the ASU (an LCOP decision, its main product
// unpriced) and core's process-blocks (a cash cost decision, a chemical, an event, an emission).
const asu = asuJson as unknown as TeaReport;
const blocks = blocksJson as unknown as TeaReport;
const both = [
  ["ASU", asu],
  ["blocks", blocks],
] as const;

describe("numbers", () => {
  it("formats money compactly, percentages and probabilities", () => {
    expect(compactNumber(36.5e6)).toBe("36.5 M");
    expect(compactNumber(-106615174.6)).toBe("-106.6 M");
    expect(compactNumber(730000)).toBe("730 k");
    expect(compactNumber(61.5588)).toBe("61.56");
    expect(moneyText(36.5e6, "USD")).toBe("36.5 M USD");
    expect(moneyText(36.5e6, "USD", false)).toBe("36,500,000 USD");
    expect(moneyText(null, "USD")).toBe("");
    expect(percentText(0.12814)).toBe("12.8 %");
    // one decimal: 89.75 % must not read as the 90 % a decision asks for
    expect(probabilityText(0.8975)).toBe("89.8 %");
  });

  it("writes each metric in its unit, a missing one as none", () => {
    expect(metricText(asu, "lcop", 61.5588)).toBe("61.56 USD/t");
    expect(metricText(asu, "cash_cost", 41.087)).toBe("41.09 USD/t");
    expect(metricText(asu, "npv", -1.066e8)).toBe("-106.6 M USD");
    expect(metricText(blocks, "irr", 0.1227)).toBe("12.3 %");
    expect(metricText(asu, "irr", null)).toBe("none");
    // a Monte Carlo statistic's unit: a fraction is a percentage
    expect(metricText(blocks, "irr", 0.1, "fraction")).toBe("10 %");
  });
});

describe("decision", () => {
  it("states the verdict, its comparator and the confidence", () => {
    const v = verdict(asu);
    expect(v.metric).toBe("lcop");
    expect(v.comparator).toBe("≤");
    expect(v.meets).toBe(true);
    expect(v.level).toBe("pass");
    expect(v.threshold).toBe(100);
    expect(v.value).toBeCloseTo(asu.results!.lcop!, 9);
    expect(v.confidence).toBe(0.8);
    expect(v.confident).toBe(v.probability! >= 0.8);
  });

  it("a cash cost decision is a cost: at most the threshold, in the LCOP's unit", () => {
    expect(decisionMetric(blocks)).toBe("cash_cost");
    const v = verdict(blocks);
    expect(v.comparator).toBe("≤");
    expect(v.value).toBeCloseTo(blocks.results!.cash_cost!, 9);
    expect(metricText(blocks, v.metric, v.value)).toMatch(/EUR\/t$/);
  });

  it("an NPV decision is at least the threshold; no results means no verdict", () => {
    expect(verdict({ ...asu, metric: "npv", decision: { ...asu.decision, metric: "npv" } }).comparator).toBe("≥");
    const empty = verdict({ ...asu, results: {}, uncertainty: null });
    expect(empty.meets).toBeNull();
    expect(empty.level).toBe("na");
    expect(empty.text).toBe("no verdict");
    expect(empty.confident).toBeNull();
  });

  it("checks the AACE class against the stage, either way", () => {
    expect(classCheck(asu)).toMatchObject({ claimed: 5, expected: 4, matches: false });
    expect(classCheck(asu).text).toContain("coarser");
    expect(classCheck(blocks).text).toContain("finer");
    expect(classCheck({ ...asu, expected_class: null }).matches).toBeNull();
  });

  it("lists the basis with rates as percentages, and the operation", () => {
    const rows = basisRows(asu);
    expect(rows.find((r) => r.key === "discount_rate")!.value).toBe("8 %");
    expect(rows.find((r) => r.key === "product")!.value).toBe("GOXP");
    expect(operationRows(blocks).find((r) => r.key === "ramp_up")!.value).toBe("50 %, 80 %");
    expect(operationRows({ ...asu, operation: null })).toEqual([]);
  });
});

describe("capital cost", () => {
  it.each(both)("%s: the lines add up to the fixed capital", (_, report) => {
    const b = capexBuildUp(report);
    expect(b.sums).toBe(true);
    expect(b.steps.at(-1)!.cumulative).toBeCloseTo(report.results!.fixed_capital!, 3);
    expect(b.steps.reduce((s, x) => s + (x.share ?? 0), 0)).toBeCloseTo(1, 9);
  });

  it("uses the contribution in the TEA's currency, and says what the estimate was in", () => {
    const line = { ...asu.capex![0]!, value: 33e6, currency: "EUR", tea_value: 36.5e6 };
    const b = capexBuildUp({ ...asu, capex: [line, ...asu.capex!.slice(1)] });
    expect(b.steps[0]!.value).toBe(36.5e6);
    expect(b.steps[0]!.original).toEqual({ value: 33e6, currency: "EUR" });
    expect(capexBuildUp(asu).steps[0]!.original).toBeNull();
    // an older core: no tea_value, the value itself
    const old = capexBuildUp({ ...asu, capex: asu.capex!.map(({ tea_value: _t, currency: _c, ...rest }) => rest) });
    expect(old.sums).toBe(true);
  });

  it("places the AACE range on an axis from 0", () => {
    const g = rangeGeometry(asu)!;
    expect(g.min).toBe(0);
    expect(g.outer[0]).toBeLessThan(g.inner[0]);
    expect(g.inner[0]).toBeLessThan(g.point);
    expect(g.point).toBeLessThan(g.inner[1]);
    expect(g.inner[1]).toBeLessThan(g.outer[1]);
    expect(g.outer[1]).toBeLessThanOrEqual(1);
    expect(g.lowPercent[0]).toBeCloseTo(-50, 6);
    expect(g.highPercent[1]).toBeCloseTo(100, 6);
    expect(rangeGeometry({ ...asu, capex_range: null })).toBeNull();
  });
});

describe("flows and lines", () => {
  it("marks each flow priced, free, the main product or unpriced", () => {
    const roles = Object.fromEntries(flowRows(asu).map((f) => [f.key, f.role]));
    expect(roles["feed:POWER"]).toBe("priced");
    expect(roles["feed:AIR"]).toBe("free");
    expect(roles["product:GOXP"]).toBe("main");
    expect(roles["product:LOX"]).toBe("unpriced");
    expect(unpricedFlows(asu).map((f) => f.key)).toEqual(["product:GANP", "product:LOX", "product:LIN", "product:CW"]);
    expect(flowRows(asu)[0]!.direction).toBe("feed");
    expect(flowRows(blocks).find((f) => f.key === "product:PROD")!.role).toBe("priced");
  });

  it("labels priced lines of every kind", () => {
    expect(lineLabel(blocks, "feed:FEED")).toBe("Aqueous feed");
    expect(lineLabel(blocks, "variable:naoh")).toBe("Caustic soda for neutralisation");
    expect(lineLabel(blocks, "emission:wastewater")).toBe("Emission: wastewater");
    expect(lineLabel(asu, "product:GANP@N2")).toBe("GAN to battery limit (N2)");
    expect(lineLabel(asu, "feed:POWER~summer")).toBe("Electric power (6.6 kV grid supply), summer");
    expect(lineLabel(asu, "allowance:carbon")).toBe("Free allowances: carbon");
    const rows = lineRows(blocks);
    expect(rows.at(-1)!.revenue).toBe(true);
    expect(rows.find((r) => r.key === "variable:naoh")!.category).toBe("chemical");
  });

  it("labels the sensitivity inputs", () => {
    expect(inputLabel(asu, "price:feed:POWER")).toBe("Price: Electric power (6.6 kV grid supply)");
    expect(inputLabel(asu, "capex:isbl")).toBe("Capital: ISBL (given)");
    expect(inputLabel(asu, "opex:maintenance")).toBe("Fixed opex: Maintenance");
    expect(inputLabel(asu, "operation:hours_per_year")).toBe("Operation: hours per year");
    expect(inputLabel(blocks, "event:catalyst")).toBe("Event: Catalyst replacement");
    expect(inputLabel(blocks, "finance:wc:receivables")).toBe("Working capital: receivables (days)");
    expect(inputLabel(blocks, "nonsense")).toBe("nonsense");
  });

  it("says when an event recurs", () => {
    expect(eventScheduleText(blocks.events![0]!)).toBe("every 3 a from operating year 3");
    expect(eventScheduleText({ every_hours: 40000 })).toBe("every 40,000 operating h");
    expect(eventScheduleText({ first_year: 2 })).toBe("once, operating year 2");
  });
});

describe("cost of production", () => {
  it.each(both)("%s: the categories sum to the LCOP", (_, report) => {
    const c = costOfProduction(report)!;
    expect(c.total).toBeCloseTo(report.results!.lcop!, 6);
    expect(c.unit).toBe(report.results!.lcop_unit);
    expect(c.rows.map((r) => r.category)).toContain("capital_and_tax");
  });

  it("stacks costs right of 0 and credits left of it, filling the bar", () => {
    // a by-product credit (the ASU's GAN was one before its price was dropped)
    const withCredit = { ...blocks, cost_of_production: [...blocks.cost_of_production!, { category: "byproduct", per_unit: -50, per_year: -1.2e5 }] };
    const c = costOfProduction(withCredit)!;
    const credit = c.segments.find((s) => s.category === "byproduct")!;
    expect(credit.credit).toBe(true);
    expect(credit.to).toBeCloseTo(c.zero, 9);
    expect(Math.min(...c.segments.map((s) => s.from))).toBeCloseTo(0, 9);
    expect(Math.max(...c.segments.map((s) => s.to))).toBeCloseTo(1, 9);
    expect(costOfProduction(blocks)!.zero).toBe(0);
    const { cost_of_production: _, ...without } = asu;
    expect(costOfProduction(without)).toBeNull();
  });
});

describe("cash flow", () => {
  it.each(both)("%s: one bar per year, the line ends at the NPV", (_, report) => {
    const chart = cashflowChart(report)!;
    expect(chart.bars).toHaveLength(report.cashflow!.length);
    expect(chart.bars.at(-1)!.cumulative).toBeCloseTo(report.results!.npv!, 2);
    expect(chart.zero).toBeGreaterThanOrEqual(0);
    expect(chart.zero).toBeLessThanOrEqual(100);
    for (const b of chart.bars) expect(b.top + b.height).toBeLessThanOrEqual(100.0001);
  });

  it("finds the year the cumulative turns positive (none when it never does)", () => {
    expect(cashflowChart(asu)!.breakEvenYear).toBeNull();
    const year = cashflowChart(blocks)!.breakEvenYear!;
    const row = blocks.cashflow!.find((r) => r.year === year)!;
    expect(row.cumulative).toBeGreaterThanOrEqual(0);
  });

  it("shows every column core sends, money in one scale", () => {
    const columns = cashflowColumns(blocks);
    expect(columns).toContain("periodic");
    expect(columns[0]).toBe("year");
    const scale = cashflowScale(asu);
    expect(scale.label).toBe("M USD");
    expect(cashflowCell(asu.cashflow![0]!, "capital", scale.factor)).toBe("14.60");
    expect(cashflowCell(asu.cashflow![5]!, "capacity", scale.factor)).toBe("100 %");
    expect(cashflowCell(asu.cashflow![0]!, "phase", scale.factor)).toBe("construction");
    expect(cashflowChart({ ...asu, cashflow: [] })).toBeNull();
  });
});

describe("scenarios and tornado", () => {
  it("puts the baseline first with each scenario's change in the decision metric", () => {
    const rows = scenarioRows(asu);
    expect(rows[0]!.baseline).toBe(true);
    expect(rows).toHaveLength(asu.scenarios!.length + 1);
    const cal = rows.find((r) => r.id === "power-california")!;
    expect(cal.delta).toBeCloseTo(cal.lcop! - asu.results!.lcop!, 9);
    expect(scenarioMetrics(blocks)).toEqual(["npv", "irr", "lcop", "cash_cost"]);
    const bars = scenarioBars(asu)!;
    expect(bars.marks.map((m) => m.key)).toEqual(["zero", "threshold"]);
    expect(bars.rows.find((r) => r.key === "power-california")!.segments[0]!.tone).toBe("bad");
    expect(scenarioBars({ ...asu, scenarios: [] })).toBeNull();
  });

  it("sorts the tornado widest first, centred on the baseline", () => {
    const rows = tornadoRows(asu);
    for (let i = 1; i < rows.length; i++) expect(rows[i - 1]!.width!).toBeGreaterThanOrEqual(rows[i]!.width!);
    const chart = tornadoBars(asu)!;
    const base = chart.marks.find((m) => m.key === "baseline")!.at;
    for (const row of chart.rows) for (const s of row.segments) expect(s.from <= base + 1e-9 || s.to >= base - 1e-9).toBe(true);
  });

  it("keeps an end where the metric does not exist out of the bar", () => {
    const report = { ...asu, tornado: [{ input: "capex:isbl", low: 0.8, high: 1.2, basis: "swing", at_low: 50, at_high: null, width: null }] };
    const rows = tornadoRows(report);
    expect(rows[0]!.atHigh).toBeNull();
    expect(rows[0]!.width).toBeNull();
    const chart = tornadoBars(report)!;
    expect(chart.rows[0]!.segments.map((s) => s.tone)).toEqual(["low"]);
    expect(chart.rows[0]!.text).toBe("50 USD/t .. none");
  });

  it("an axis holds 0 and every value, padded", () => {
    const d = domainOf([10, 20]);
    expect(d.min).toBe(0);
    expect(d.pos(20)).toBeLessThan(1);
    const flat = domainOf([5, 5], false);
    expect(flat.max).toBeGreaterThan(flat.min);
  });
});

describe("break-even and uncertainty", () => {
  it("says never when the metric does not reach the threshold through an input", () => {
    const never = breakEvenRows(blocks).find((r) => r.input === "event:catalyst")!;
    expect(never.never).toBe(true);
    expect(never.text).toBe("never");
    expect(never.multiplierText).toBe("");
    const rows = breakEvenRows(asu);
    const power = rows.find((r) => r.input === "price:feed:POWER")!;
    expect(power.text).toMatch(/USD\/MWh$/);
    expect(power.multiplierText).toMatch(/^× \d/);
    expect(rows.find((r) => r.input === "finance:discount_rate")!.text).toMatch(/ %$/);
  });

  it("maps P10, P50 and P90 to the range the page draws", () => {
    const stat = statisticOf(asu, "lcop")!;
    expect(toIntervalStats(stat)).toEqual({ low: stat.p10, high: stat.p90, median: stat.p50, deterministic: stat.deterministic });
    expect(toIntervalStats({ ...stat, p90: null })).toBeNull();
    expect(toIntervalStats(null)).toBeNull();
    // the ASU's main product has no price: no NPV or IRR in its Monte Carlo
    expect(statisticOf(asu, "npv")).toBeNull();
    expect(statisticOf(blocks, "cash_cost")).not.toBeNull();
  });

  it("tones a driver by whether it worsens the metric", () => {
    expect(rhoWorsens("lcop", 0.7)).toBe(true);
    expect(rhoWorsens("cash_cost", -0.3)).toBe(false);
    expect(rhoWorsens("npv", 0.7)).toBe(false);
    expect(rhoWorsens("npv", -0.7)).toBe(true);
  });
});

describe("what a newer core adds", () => {
  it("shows unknown arrays of records as tables, and nothing for the known keys", () => {
    expect(extraTables(asu)).toEqual([]);
    const newer = { ...asu, water_balance: [{ stream: "CW", m3_per_h: 880.5 }, { stream: "make-up", note: "x" }] } as TeaReport;
    const [t] = extraTables(newer);
    expect(t!.key).toBe("water_balance");
    expect(t!.title).toBe("Water balance");
    expect(t!.columns).toEqual(["stream", "m3_per_h", "note"]);
  });
});
