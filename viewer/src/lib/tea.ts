/**
 * The techno-economic analysis (`GET /api/tea`, `cheme assess tea`): pure helpers that state what
 * core computed. Nothing here recomputes the economics; it orders, labels, formats and places the
 * numbers on axes. Everything is generic over the process: no product keys or units are assumed,
 * they come from the payload (`flows[].key`, `price_unit`, `rate_unit`, `results.lcop_unit`,
 * `basis.product`). Every field of the payload may be missing or null (core grows it).
 */
import type {
  TeaCapexLine,
  TeaCashflowRow,
  TeaFlowLine,
  TeaOpexLine,
  TeaReport,
  TeaResults,
  TeaScenario,
  TeaStatistic,
  TeaTornadoBar,
  TeaTurn,
} from "@/api";

// -- numbers -----------------------------------------------------------------------------------

/** A finite number, or null (core turns NaN and inf into null; older payloads may omit it). */
export function finite(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

/** A number for the page: 4 significant digits, digits grouped (`36,500,000` keeps 4: `36,500,000`). */
export function numberText(value: number | null | undefined, digits = 4): string {
  const v = finite(value);
  if (v === null) return "";
  if (v === 0) return "0";
  const magnitude = Math.abs(v);
  if (magnitude >= 1e-3 && magnitude < 1e15) return Number(v.toPrecision(digits)).toLocaleString("en-US", { maximumFractionDigits: 6 });
  return v.toExponential(digits - 1);
}

const SCALES: [number, string][] = [
  [1e9, "bn"],
  [1e6, "M"],
  [1e3, "k"],
];

/** A compact number: `-106.6 M`, `730 k`, `61.56`. */
export function compactNumber(value: number | null | undefined): string {
  const v = finite(value);
  if (v === null) return "";
  const magnitude = Math.abs(v);
  for (const [factor, suffix] of SCALES) {
    if (magnitude >= factor) return `${numberText(v / factor)} ${suffix}`;
  }
  return numberText(v);
}

/** Money in the report's currency, compact (`36.5 M USD`) or whole (`36,500,000 USD`). */
export function moneyText(value: number | null | undefined, currency = "", compact = true): string {
  const v = finite(value);
  if (v === null) return "";
  const text = compact ? compactNumber(v) : Math.round(v).toLocaleString("en-US");
  return currency ? `${text} ${currency}` : text;
}

/** A fraction as a percentage: `0.128` -> `12.8 %`. */
export function percentText(fraction: number | null | undefined, digits = 1): string {
  const v = finite(fraction);
  if (v === null) return "";
  return `${Number((v * 100).toFixed(digits)).toLocaleString("en-US", { maximumFractionDigits: digits })} %`;
}

/** A probability for the verdict, one decimal so 89.8 % never reads as 90 %. */
export function probabilityText(p: number | null | undefined): string {
  const v = finite(p);
  if (v === null) return "";
  return `${(v * 100).toFixed(1)} %`;
}

/** One scale for a table of money: the largest magnitude decides (`M USD`, `k EUR`, `USD`). */
export function moneyScale(values: Iterable<number | null | undefined>, currency = ""): { factor: number; label: string } {
  let largest = 0;
  for (const value of values) {
    const v = finite(value);
    if (v !== null) largest = Math.max(largest, Math.abs(v));
  }
  for (const [factor, suffix] of SCALES) {
    if (largest >= factor * 10) return { factor, label: currency ? `${suffix} ${currency}` : suffix };
  }
  return { factor: 1, label: currency };
}

/** A value in a scaled money table: two decimals, digits grouped. */
export function scaledText(value: number | null | undefined, factor: number): string {
  const v = finite(value);
  if (v === null) return "";
  const scaled = v / factor;
  const text = scaled.toLocaleString("en-US", factor === 1 ? { maximumFractionDigits: 0 } : { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  return text === "-0.00" || text === "-0" ? text.slice(1) : text;
}

/** `owners_cost` -> `owners cost`, `cash_flow` -> `cash flow`. */
export function keyLabel(key: string): string {
  return key.replace(/_/g, " ");
}

// -- metrics and the decision ------------------------------------------------------------------

const METRIC_LABELS: Record<string, string> = {
  npv: "NPV",
  irr: "IRR",
  lcop: "LCOP",
  cash_cost: "Cash cost",
  fixed_capital: "Fixed capital",
  payback_years: "Payback",
};

/** The metric's short name: `NPV`, `IRR`, `LCOP`, else the key in words. */
export function metricLabel(metric: string): string {
  return METRIC_LABELS[metric] ?? keyLabel(metric);
}

/** What a metric means, for titles. */
export function metricTitle(metric: string): string {
  if (metric === "npv") return "Net present value";
  if (metric === "irr") return "Internal rate of return";
  if (metric === "lcop") return "Levelised cost of the product";
  if (metric === "cash_cost") return "Cash cost of the product (no capital charge)";
  return metricLabel(metric);
}

/** The results, `{}` when there is no baseline. */
export function resultsOf(report: TeaReport): TeaResults {
  return report.results ?? {};
}

/** The decision metric (`npv`, `irr`, `lcop`): the report's, else the decision's, else NPV. */
export function decisionMetric(report: TeaReport): string {
  return report.metric || report.decision?.metric || "npv";
}

/** The threshold of the decision (the report's, else the decision's). */
export function thresholdOf(report: TeaReport): number | null {
  return finite(report.threshold) ?? finite(report.decision?.threshold);
}

/** Metrics that are a cost per unit of the main product (in `results.lcop_unit`). */
export const PER_UNIT_METRICS = new Set(["lcop", "cash_cost", "lcop_unsubsidised"]);

/** Lower is better for a cost (LCOP, cash cost, capital), higher for NPV and IRR. */
export function lowerIsBetter(metric: string): boolean {
  return PER_UNIT_METRICS.has(metric) || metric === "fixed_capital";
}

/** Whether raising an input with Spearman correlation *rho* makes *metric* worse. */
export function rhoWorsens(metric: string, rho: number): boolean {
  return lowerIsBetter(metric) ? rho > 0 : rho < 0;
}

/** The unit of a metric: the currency for money, `%` for the IRR, `lcop_unit` for the LCOP. */
export function metricUnit(report: TeaReport, metric: string): string {
  if (metric === "irr") return "%";
  if (PER_UNIT_METRICS.has(metric)) return resultsOf(report).lcop_unit ?? "";
  if (metric === "payback_years") return "a";
  return report.currency ?? "";
}

/**
 * A metric's value for the page: money compact in the currency, the IRR (a fraction) as a
 * percentage, the LCOP in its unit; *unit* overrides (a Monte Carlo statistic's: `fraction` is a
 * percentage). Null (no IRR, no payback) reads `none`.
 */
export function metricText(report: TeaReport, metric: string, value: number | null | undefined, unit?: string): string {
  const v = finite(value);
  if (v === null) return "none";
  const u = unit ?? metricUnit(report, metric);
  if (metric === "irr" || u === "fraction" || u === "%") return percentText(v);
  if (u && u === report.currency) return moneyText(v, u);
  return u ? `${numberText(v)} ${u}` : numberText(v);
}

export type VerdictLevel = "pass" | "error" | "na";

export interface Verdict {
  metric: string;
  threshold: number | null;
  value: number | null;
  meets: boolean | null;
  level: VerdictLevel;
  /** `meets`, `does not meet`, `no verdict`. */
  text: string;
  /** `≤` for a cost, `≥` otherwise. */
  comparator: string;
  /** P(the metric meets the threshold) from the Monte Carlo, and the confidence asked for. */
  probability: number | null;
  confidence: number | null;
  /** probability >= confidence (null: either is missing). */
  confident: boolean | null;
}

/** The decision's verdict: the baseline against the threshold, and the probability against the confidence. */
export function verdict(report: TeaReport): Verdict {
  const metric = decisionMetric(report);
  const results = resultsOf(report);
  const meets = typeof results.meets === "boolean" ? results.meets : null;
  const probability = finite(report.uncertainty?.probability);
  const confidence = finite(report.decision?.confidence);
  return {
    metric,
    threshold: thresholdOf(report),
    value: finite((results as Record<string, unknown>)[metric]),
    meets,
    level: meets === true ? "pass" : meets === false ? "error" : "na",
    text: meets === true ? "meets" : meets === false ? "does not meet" : "no verdict",
    comparator: lowerIsBetter(metric) ? "≤" : "≥",
    probability,
    confidence,
    confident: probability !== null && confidence !== null ? probability >= confidence : null,
  };
}

export interface ClassCheck {
  claimed: number | null;
  expected: number | null;
  /** The class claimed is the one the stage expects (null: either is unknown). */
  matches: boolean | null;
  text: string;
}

/** The AACE class claimed against the one the stage expects (1 finest, 5 coarsest). */
export function classCheck(report: TeaReport): ClassCheck {
  const claimed = finite(report.estimate_class);
  const expected = finite(report.expected_class);
  const matches = claimed !== null && expected !== null ? claimed === expected : null;
  let text = "";
  if (claimed !== null && expected !== null && claimed > expected) text = `coarser than the ${report.stage || "stage"} stage expects (class ${expected})`;
  else if (claimed !== null && expected !== null && claimed < expected) text = `finer than the ${report.stage || "stage"} stage supports (class ${expected})`;
  else if (matches) text = `as the ${report.stage || "stage"} stage expects`;
  return { claimed, expected, matches, text };
}

// -- basis ---------------------------------------------------------------------------------------

export interface BasisRow {
  key: string;
  label: string;
  value: string;
}

/** The basis as rows, in core's order, empty values left out; `*_rate` fractions also as a percentage. */
export function basisRows(report: TeaReport): BasisRow[] {
  const out: BasisRow[] = [];
  for (const [key, raw] of Object.entries(report.basis ?? {})) {
    if (raw === null || raw === undefined || raw === "") continue;
    let value = String(raw);
    const number = Number(raw);
    if (key.endsWith("_rate") && value.trim() !== "" && Number.isFinite(number) && Math.abs(number) <= 1) value = percentText(number);
    out.push({ key, label: keyLabel(key), value });
  }
  return out;
}

// -- capital cost ------------------------------------------------------------------------------

export interface CapexStep extends TeaCapexLine {
  /** In the TEA's currency and cost year (`tea_value`, else `value`). */
  value: number | null;
  /** The line's own value and currency when they differ from the TEA's (another currency or year). */
  original: { value: number; currency: string } | null;
  /** The running sum up to and with this line. */
  cumulative: number | null;
  /** Its share of the fixed capital. */
  share: number | null;
}

export interface CapexBuildUp {
  steps: CapexStep[];
  fixedCapital: number | null;
  workingCapital: number | null;
  /** The lines add up to the fixed capital (within a cent per million). */
  sums: boolean;
}

/** The capital build-up: each `capex[]` line with the running sum and its share of the fixed capital. */
export function capexBuildUp(report: TeaReport): CapexBuildUp {
  const results = resultsOf(report);
  const fixedCapital = finite(results.fixed_capital);
  let running = 0;
  let known = true;
  const steps = (report.capex ?? []).map((line) => {
    // its contribution in the TEA's currency and cost year (older cores: the value itself)
    const value = finite(line.tea_value) ?? finite(line.value);
    const own = finite(line.value);
    const original = own !== null && (own !== value || Boolean(line.currency && line.currency !== report.currency)) ? { value: own, currency: line.currency || report.currency || "" } : null;
    if (value === null) known = false;
    else running += value;
    return { ...line, value, original, cumulative: known ? running : null, share: value !== null && fixedCapital ? value / fixedCapital : null };
  });
  const sums = known && fixedCapital !== null && Math.abs(running - fixedCapital) <= Math.max(1e-6 * Math.abs(fixedCapital), 0.01);
  return { steps, fixedCapital, workingCapital: finite(results.working_capital), sums };
}

export interface RangeGeometry {
  /** Fractions 0..1 of the axis: the outer band (worst low to worst high), the inner (best low to best high), the point estimate. */
  outer: [number, number];
  inner: [number, number];
  point: number;
  /** In currency: the axis bounds and the bands. */
  min: number;
  max: number;
  low: [number, number];
  high: [number, number];
  value: number;
  /** The range relative to the point estimate, e.g. `-50 % to -20 %`. */
  lowPercent: [number, number];
  highPercent: [number, number];
}

/** The AACE accuracy range of the fixed capital on an axis from 0. Null without both bands. */
export function rangeGeometry(report: TeaReport): RangeGeometry | null {
  const range = report.capex_range;
  const value = finite(resultsOf(report).fixed_capital);
  const pair = (p: unknown): [number, number] | null => {
    if (!Array.isArray(p) || p.length < 2) return null;
    const a = finite(p[0]);
    const b = finite(p[1]);
    return a === null || b === null ? null : [Math.min(a, b), Math.max(a, b)];
  };
  const low = pair(range?.low);
  const high = pair(range?.high);
  if (!range || !low || !high || value === null) return null;
  const min = Math.min(0, low[0], value);
  const max = Math.max(high[1], value) * 1.04 || 1;
  const span = max - min || 1;
  const pos = (v: number) => (v - min) / span;
  const rel = (v: number) => (value ? (v / value - 1) * 100 : 0);
  return {
    outer: [pos(low[0]), pos(high[1])],
    inner: [pos(low[1]), pos(high[0])],
    point: pos(value),
    min,
    max,
    low,
    high,
    value,
    lowPercent: [rel(low[0]), rel(low[1])],
    highPercent: [rel(high[0]), rel(high[1])],
  };
}

// -- flows and operating cost ------------------------------------------------------------------

/** How a flow is valued: priced, free (listed under `free:` with why), the main product the LCOP prices, or unpriced (counted as 0). */
export type FlowRole = "priced" | "free" | "main" | "unpriced";

export interface FlowRow extends TeaFlowLine {
  /** `feed`, `product` or whatever precedes the first colon of the key. */
  direction: string;
  role: FlowRole;
}

/** The main product's flow key (`product:<basis.product>`), or null. */
export function mainProductKey(report: TeaReport): string | null {
  const product = report.basis?.product;
  return product ? `product:${String(product)}` : null;
}

/** The flows with their direction and how each is valued, feeds first, in core's order within. */
export function flowRows(report: TeaReport): FlowRow[] {
  const main = mainProductKey(report);
  const rows = (report.flows ?? []).map((flow): FlowRow => {
    const direction = flow.key.includes(":") ? flow.key.split(":")[0]! : "";
    let role: FlowRole = "unpriced";
    if (finite(flow.price) !== null) role = "priced";
    else if (flow.free) role = "free";
    else if (flow.key === main) role = "main";
    return { ...flow, direction, role };
  });
  const order = (d: string) => (d === "feed" ? 0 : d === "product" ? 1 : 2);
  return rows.map((r, i) => [r, i] as const).sort((a, b) => order(a[0].direction) - order(b[0].direction) || a[1] - b[1]).map(([r]) => r);
}

/** The flows counted as free without a reason (no price, not under `free:`, not the main product). */
export function unpricedFlows(report: TeaReport): FlowRow[] {
  return flowRows(report).filter((f) => f.role === "unpriced");
}

/** A rate with its unit: `9,488 kWh/h`. */
export function rateText(flow: Pick<TeaFlowLine, "rate" | "rate_unit">): string {
  const v = finite(flow.rate);
  if (v === null) return "";
  return `${numberText(v)}${flow.rate_unit ? ` ${flow.rate_unit}` : ""}`;
}

/** A price in the report's currency per its unit: `80.4 USD/MWh`. */
export function priceText(flow: Pick<TeaFlowLine, "price" | "price_unit">, currency = ""): string {
  const v = finite(flow.price);
  if (v === null) return "";
  const unit = [currency, flow.price_unit].filter(Boolean).join("/");
  return unit ? `${numberText(v)} ${unit}` : numberText(v);
}

export interface OpexRow extends TeaOpexLine {
  /** Its share of the fixed operating cost per year. */
  share: number | null;
}

/** The fixed operating costs with their share of `fixed_cost_per_year`. */
export function opexRows(report: TeaReport): OpexRow[] {
  const total = finite(resultsOf(report).fixed_cost_per_year) ?? (report.opex ?? []).reduce((s, o) => s + (finite(o.per_year) ?? 0), 0);
  return (report.opex ?? []).map((o) => {
    const v = finite(o.per_year);
    return { ...o, share: v !== null && total ? v / total : null };
  });
}

// -- cash flow ---------------------------------------------------------------------------------

export interface CashflowBar {
  year: number;
  phase: string;
  value: number;
  cumulative: number | null;
  /** Percent of the plot height from its top: the bar's top and height, the cumulative point. */
  top: number;
  height: number;
  point: number | null;
}

export interface CashflowChart {
  column: string;
  line: string;
  bars: CashflowBar[];
  min: number;
  max: number;
  /** Percent from the top where 0 is. */
  zero: number;
  /** The first year the cumulative line is at or above 0, or null. */
  breakEvenYear: number | null;
}

/** The cash flow per year as bars (`column`) with the running total (`line`) on one axis that holds 0. */
export function cashflowChart(report: TeaReport, column = "cash_flow", line = "cumulative"): CashflowChart | null {
  const rows = (report.cashflow ?? []).filter((r) => finite(r.year) !== null);
  if (!rows.length) return null;
  const values = rows.map((r) => finite(r[column]) ?? 0);
  const points = rows.map((r) => finite(r[line]));
  const all = [0, ...values, ...points.filter((p): p is number => p !== null)];
  const min = Math.min(...all);
  const max = Math.max(...all);
  const span = max - min || 1;
  const pos = (v: number) => ((max - v) / span) * 100;
  const bars = rows.map((r, i) => {
    const value = values[i]!;
    return {
      year: r.year,
      phase: String(r.phase ?? ""),
      value,
      cumulative: points[i] ?? null,
      top: pos(Math.max(value, 0)),
      height: (Math.abs(value) / span) * 100,
      point: points[i] !== null && points[i] !== undefined ? pos(points[i]!) : null,
    };
  });
  const turn = bars.find((b, i) => i > 0 && b.cumulative !== null && b.cumulative >= 0 && (bars[i - 1]!.cumulative ?? -1) < 0);
  return { column, line, bars, min, max, zero: pos(0), breakEvenYear: turn ? turn.year : null };
}

/** The columns of the cash flow table: every key the rows have, in the first row's order (new columns show up). */
export function cashflowColumns(report: TeaReport): string[] {
  const out: string[] = [];
  for (const row of report.cashflow ?? []) for (const key of Object.keys(row)) if (!out.includes(key)) out.push(key);
  return out;
}

/** Cash flow columns that are not money: shown as they are (capacity as a percentage). */
export const CASHFLOW_TEXT_COLUMNS = new Set(["year", "phase"]);
export const CASHFLOW_FRACTION_COLUMNS = new Set(["capacity"]);

/** The money columns' scale of the cash flow table. */
export function cashflowScale(report: TeaReport): { factor: number; label: string } {
  const columns = cashflowColumns(report).filter((c) => !CASHFLOW_TEXT_COLUMNS.has(c) && !CASHFLOW_FRACTION_COLUMNS.has(c));
  const values: number[] = [];
  for (const row of report.cashflow ?? []) for (const c of columns) values.push(finite(row[c]) ?? 0);
  return moneyScale(values, report.currency ?? "");
}

/** One cell of the cash flow table. */
export function cashflowCell(row: TeaCashflowRow, column: string, factor: number): string {
  const raw = row[column];
  if (CASHFLOW_TEXT_COLUMNS.has(column) || typeof raw === "string" || typeof raw === "boolean") return raw === null || raw === undefined ? "" : String(raw);
  if (CASHFLOW_FRACTION_COLUMNS.has(column)) return percentText(raw as number, 0);
  return scaledText(raw as number, factor);
}

// -- horizontal bars (scenarios, tornado) ------------------------------------------------------

export interface Domain {
  min: number;
  max: number;
  /** A value's position, a fraction 0..1. */
  pos: (value: number) => number;
}

/** An axis over the finite *values* (and 0 when *withZero*), padded by 4 % either side. */
export function domainOf(values: Iterable<number | null | undefined>, withZero = true): Domain {
  const finiteValues = [...values].map(finite).filter((v): v is number => v !== null);
  if (withZero) finiteValues.push(0);
  let min = finiteValues.length ? Math.min(...finiteValues) : 0;
  let max = finiteValues.length ? Math.max(...finiteValues) : 1;
  if (min === max) {
    min -= Math.abs(min) * 0.1 || 1;
    max += Math.abs(max) * 0.1 || 1;
  }
  const pad = (max - min) * 0.04;
  if (!(withZero && min === 0)) min -= pad;
  if (!(withZero && max === 0)) max += pad;
  const span = max - min;
  return { min, max, pos: (v: number) => (v - min) / span };
}

/** One segment of a bar, fractions of the axis. */
export interface BarSegment {
  from: number;
  to: number;
  /** `low`/`high` (tornado ends), `good`/`bad` (against the threshold), `neutral`. */
  tone: string;
  title: string;
}

export interface BarRow {
  key: string;
  label: string;
  title?: string | undefined;
  segments: BarSegment[];
  /** The text at the end of the bar. */
  text: string;
  /** Marked (the baseline among the scenarios). */
  emphasis?: boolean;
}

export interface BarChart {
  rows: BarRow[];
  domain: Domain;
  /** Vertical lines across the rows: 0, the threshold, the baseline. */
  marks: { key: string; at: number; label: string }[];
}

export interface ScenarioRow extends TeaScenario {
  /** The decision metric and its change from the baseline. */
  value: number | null;
  delta: number | null;
  baseline: boolean;
}

/** The baseline and each scenario with the decision metric and its change from the baseline. */
export function scenarioRows(report: TeaReport): ScenarioRow[] {
  const metric = decisionMetric(report);
  const r = resultsOf(report);
  const base = finite((r as Record<string, unknown>)[metric]);
  const baseline: ScenarioRow = {
    id: "baseline",
    title: "Baseline",
    fixed_capital: r.fixed_capital ?? null,
    npv: r.npv ?? null,
    irr: r.irr ?? null,
    lcop: r.lcop ?? null,
    cash_cost: r.cash_cost ?? null,
    meets: r.meets ?? null,
    value: base,
    delta: null,
    baseline: true,
  };
  const rows = (report.scenarios ?? []).map((s): ScenarioRow => {
    const value = finite((s as unknown as Record<string, unknown>)[metric]);
    return { ...s, value, delta: value !== null && base !== null ? value - base : null, baseline: false };
  });
  return [baseline, ...rows];
}

/** The metrics the scenario table shows: those core gives for the baseline or a scenario. */
export function scenarioMetrics(report: TeaReport): string[] {
  const r = resultsOf(report);
  return ["npv", "irr", "lcop", "cash_cost"].filter((m) => m in r || (report.scenarios ?? []).some((s) => m in s));
}

/** The decision metric of the baseline and each scenario as bars from 0, toned by the threshold. */
export function scenarioBars(report: TeaReport): BarChart | null {
  const rows = scenarioRows(report);
  if (rows.length < 2) return null;
  const metric = decisionMetric(report);
  const threshold = thresholdOf(report);
  const domain = domainOf([...rows.map((r) => r.value), threshold]);
  const zero = domain.pos(0);
  const out: BarRow[] = rows.map((row) => {
    const text = metricText(report, metric, row.value);
    const segments: BarSegment[] = [];
    if (row.value !== null) {
      const at = domain.pos(row.value);
      const tone = row.meets === true ? "good" : row.meets === false ? "bad" : "neutral";
      segments.push({ from: Math.min(zero, at), to: Math.max(zero, at), tone, title: `${row.title || row.id}: ${text}` });
    }
    return { key: row.id, label: row.title || row.id, title: row.source || undefined, segments, text, emphasis: row.baseline };
  });
  const marks = [{ key: "zero", at: zero, label: "0" }];
  if (threshold !== null) marks.push({ key: "threshold", at: domain.pos(threshold), label: `threshold ${metricText(report, metric, threshold)}` });
  return { rows: out, domain, marks };
}

export interface TornadoRow {
  input: string;
  label: string;
  basis: string;
  /** Multipliers of the input at either end. */
  low: number | null;
  high: number | null;
  /** The decision metric at either end (null: it does not exist there). */
  atLow: number | null;
  atHigh: number | null;
  width: number | null;
}

/** The tornado's inputs, widest first; an end where the metric does not exist stays null. */
export function tornadoRows(report: TeaReport): TornadoRow[] {
  const width = (bar: TeaTornadoBar): number | null => {
    const given = finite(bar.width);
    if (given !== null) return given;
    const a = finite(bar.at_low);
    const b = finite(bar.at_high);
    return a !== null && b !== null ? Math.abs(b - a) : null;
  };
  return (report.tornado ?? [])
    .map((bar) => ({
      input: bar.input,
      label: inputLabel(report, bar.input),
      basis: bar.basis ?? "",
      low: finite(bar.low),
      high: finite(bar.high),
      atLow: finite(bar.at_low),
      atHigh: finite(bar.at_high),
      width: width(bar),
    }))
    .sort((a, b) => (b.width ?? -Infinity) - (a.width ?? -Infinity));
}

/** A multiplier as text: `x 0.80`. */
export function multiplierText(m: number | null | undefined): string {
  const v = finite(m);
  return v === null ? "" : `× ${v.toFixed(2)}`;
}

/** The tornado as bars around the baseline value: the input's low end one tone, its high end the other. */
export function tornadoBars(report: TeaReport): BarChart | null {
  const rows = tornadoRows(report);
  if (!rows.length) return null;
  const metric = decisionMetric(report);
  const base = finite((resultsOf(report) as Record<string, unknown>)[metric]);
  const threshold = thresholdOf(report);
  const domain = domainOf([...rows.flatMap((r) => [r.atLow, r.atHigh]), base, threshold], false);
  const centre = base !== null ? domain.pos(base) : null;
  const out = rows.map((row): BarRow => {
    const segments: BarSegment[] = [];
    const end = (value: number | null, tone: "low" | "high", m: number | null) => {
      if (value === null || centre === null) return;
      const at = domain.pos(value);
      segments.push({ from: Math.min(centre, at), to: Math.max(centre, at), tone, title: `${row.label} ${multiplierText(m)}: ${metricText(report, metric, value)}` });
    };
    end(row.atLow, "low", row.low);
    end(row.atHigh, "high", row.high);
    const text = `${metricText(report, metric, row.atLow)} .. ${metricText(report, metric, row.atHigh)}`;
    return { key: row.input, label: row.label, title: row.input, segments, text };
  });
  const marks: BarChart["marks"] = [];
  if (centre !== null && base !== null) marks.push({ key: "baseline", at: centre, label: `baseline ${metricText(report, metric, base)}` });
  if (threshold !== null) marks.push({ key: "threshold", at: domain.pos(threshold), label: `threshold ${metricText(report, metric, threshold)}` });
  return { rows: out, domain, marks };
}

// -- inputs, break-even ------------------------------------------------------------------------

/** A readable input: `price:feed:POWER` -> `Price: Electric power`, `capex:isbl` -> `ISBL (given)`. */
export function inputLabel(report: TeaReport, id: string): string {
  const [kind, ...rest] = id.split(":");
  const key = rest.join(":");
  if (!key) return id;
  if (kind === "price" || kind === "rate") return `${kind === "price" ? "Price" : "Rate"}: ${lineLabel(report, key)}`;
  if (kind === "event") {
    const event = (report.events ?? []).find((e) => e.id === key);
    return `Event: ${event?.title || keyLabel(key)}`;
  }
  if (kind === "finance" && key.startsWith("wc:")) return `Working capital: ${keyLabel(key.slice(3))} (days)`;
  if (kind === "capex") {
    const line = (report.capex ?? []).find((c) => c.id === key);
    return `Capital: ${line?.title || keyLabel(key)}`;
  }
  if (kind === "opex") {
    const line = (report.opex ?? []).find((o) => o.id === key);
    return `Fixed opex: ${line?.title || keyLabel(key)}`;
  }
  return `${keyLabel(kind!)[0]!.toUpperCase()}${keyLabel(kind!).slice(1)}: ${keyLabel(key)}`;
}

/** An input's value in its unit: a fraction as a percentage, currency as money. */
export function inputValueText(report: TeaReport, value: number | null | undefined, unit = ""): string {
  const v = finite(value);
  if (v === null) return "";
  if (unit === "fraction") return percentText(v, 2);
  if (unit && unit === report.currency) return moneyText(v, unit);
  return unit ? `${numberText(v)} ${unit}` : numberText(v);
}

export interface BreakEvenRow extends TeaTurn {
  label: string;
  /** The value at which the metric reaches the threshold, or `never` (none in range). */
  text: string;
  /** `x 2.05` of the base, empty when never. */
  multiplierText: string;
  never: boolean;
}

/** Each input's break-even value; `never` when the metric does not reach the threshold through it. */
export function breakEvenRows(report: TeaReport): BreakEvenRow[] {
  return (report.break_even ?? []).map((turn) => {
    const value = finite(turn.value);
    return {
      ...turn,
      label: inputLabel(report, turn.input),
      text: value === null ? "never" : inputValueText(report, value, turn.unit),
      multiplierText: multiplierText(turn.multiplier),
      never: value === null,
    };
  });
}

// -- priced lines, variable items, events, operation, cost of production ---------------------

/**
 * A readable line key: `feed:POWER` -> the flow's title, `product:OFFGAS@H2` -> `Off-gas (H2)`,
 * `feed:POWER~summer` -> `Electric power, summer`, `variable:naoh` -> the item's title,
 * `emission:<id>` -> `Emission: <id>`, `allowance:carbon` -> `Free allowances: carbon`.
 */
export function lineLabel(report: TeaReport, key: string): string {
  const [kind, ...rest] = key.split(":");
  const id = rest.join(":");
  if (kind === "variable") {
    const item = (report.variable ?? []).find((v) => v.id === id);
    return item?.title || keyLabel(id);
  }
  if (kind === "emission") return `Emission: ${keyLabel(id)}`;
  if (kind === "allowance") return `Free allowances: ${keyLabel(id)}`;
  if (key === "carbon") return "Emission price (per t CO2-eq)";
  const match = /^([^~@]+)(?:~([^@]+))?(?:@(.+))?$/.exec(key);
  if (!match) return key;
  const [, base, period, component] = match;
  const flow = (report.flows ?? []).find((f) => f.key === base);
  let label = flow?.title || base!;
  if (component) label += ` (${component})`;
  if (period) label += `, ${keyLabel(period)}`;
  return label;
}

/** A category for the page: `capital_and_tax` -> `capital and tax`, `main` -> `main product`. */
export function categoryLabel(category: string): string {
  if (category === "main") return "main product";
  if (category === "fixed") return "fixed operating cost";
  return keyLabel(category);
}

export interface LineRow {
  key: string;
  label: string;
  category: string;
  revenue: boolean;
  rate: number | null;
  unit: string;
  price: number | null;
  perYear: number | null;
  /** Price multipliers by operating year, when the price moves. */
  profile: number[];
}

/** Every priced line, costs first, then revenues, in core's order within. */
export function lineRows(report: TeaReport): LineRow[] {
  const rows = (report.lines ?? []).map((l) => ({
    key: l.key,
    label: lineLabel(report, l.key),
    category: l.category ?? "",
    revenue: Boolean(l.revenue),
    rate: finite(l.rate),
    unit: l.unit ?? "",
    price: finite(l.price),
    perYear: finite(l.per_year),
    profile: (l.profile ?? []).filter((v): v is number => finite(v) !== null),
  }));
  return [...rows.filter((r) => !r.revenue), ...rows.filter((r) => r.revenue)];
}

/** A line's price per its unit: `0.0804 USD/kWh`. */
export function linePriceText(row: Pick<LineRow, "price" | "unit">, currency = ""): string {
  if (row.price === null) return "";
  const unit = [currency, row.unit].filter(Boolean).join("/");
  return unit ? `${numberText(row.price)} ${unit}` : numberText(row.price);
}

/** How often an event recurs: `every 3 a from operating year 3`, `every 40,000 operating h`, `once`. */
export function eventScheduleText(event: { every_years?: number | null; every_hours?: number | null; first_year?: number | null }): string {
  const years = finite(event.every_years);
  const hours = finite(event.every_hours);
  const first = finite(event.first_year);
  const from = first !== null ? ` from operating year ${first}` : "";
  if (years !== null) return `every ${numberText(years)} a${from}`;
  if (hours !== null) return `every ${numberText(hours)} operating h${from}`;
  return first !== null ? `once, operating year ${first}` : "once";
}

/** The operation as rows (hours, life, ramp-up, utilisation, batches, cases); empty values left out. */
export function operationRows(report: TeaReport): BasisRow[] {
  const op = report.operation;
  if (!op) return [];
  const out: BasisRow[] = [];
  const add = (key: string, label: string, value: string) => {
    if (value) out.push({ key, label, value });
  };
  const hours = finite(op.hours_per_year);
  const operating = finite(op.operating_hours);
  add("hours_per_year", "hours per year", hours !== null ? `${numberText(hours)} h/a` : "");
  add("operating_hours", "operating hours", operating !== null && operating !== hours ? `${numberText(operating)} h/a` : "");
  add("life_years", "life", finite(op.life_years) !== null ? `${op.life_years} a` : "");
  add("ramp_up", "ramp-up", op.ramp_up?.length ? op.ramp_up.map((f) => percentText(f, 0)).join(", ") : "");
  add("utilisation", "utilisation", percentText(op.utilisation, 1));
  add("batches_per_year", "batches per year", numberText(op.batches_per_year));
  add("cycle_time", "cycle time", finite(op.cycle_time) !== null ? `${numberText(op.cycle_time)} h` : "");
  const cases = op.cases ?? [];
  if (cases.length > 1 || (cases.length === 1 && finite(cases[0]!.share) !== 1)) add("cases", "cases", cases.map((c) => `${c.case} ${percentText(c.share, 0)}`).join(", "));
  return out;
}

export interface CostRow {
  category: string;
  label: string;
  perUnit: number | null;
  perYear: number | null;
  /** Its share of the LCOP (negative for a credit). */
  share: number | null;
}

export interface CostOfProduction {
  rows: CostRow[];
  /** The rows' sum per unit, and the report's LCOP (they agree). */
  total: number;
  lcop: number | null;
  unit: string;
  /** One stacked bar: costs right of 0, credits left of it; fractions of the axis. */
  segments: { category: string; from: number; to: number; colour: number; credit: boolean }[];
  /** Where 0 is on that axis, a fraction. */
  zero: number;
}

/** The cost of production per unit of the main product: the rows, their sum, and a stacked bar (credits left of 0). */
export function costOfProduction(report: TeaReport): CostOfProduction | null {
  const source = report.cost_of_production ?? [];
  if (!source.length) return null;
  const lcop = finite(resultsOf(report).lcop);
  const rows = source.map((c) => {
    const perUnit = finite(c.per_unit);
    return { category: c.category, label: categoryLabel(c.category), perUnit, perYear: finite(c.per_year), share: perUnit !== null && lcop ? perUnit / lcop : null };
  });
  const total = rows.reduce((sum, r) => sum + (r.perUnit ?? 0), 0);
  const credits = rows.reduce((sum, r) => sum + Math.min(r.perUnit ?? 0, 0), 0);
  const costs = rows.reduce((sum, r) => sum + Math.max(r.perUnit ?? 0, 0), 0);
  const span = costs - credits || 1;
  const segments: CostOfProduction["segments"] = [];
  const offset = credits === 0 ? 0 : -credits;
  let right = offset;
  let left = offset;
  rows.forEach((r, i) => {
    const v = r.perUnit ?? 0;
    const colour = (i % 8) + 1;
    if (v > 0) {
      segments.push({ category: r.category, from: right / span, to: (right + v) / span, colour, credit: false });
      right += v;
    } else if (v < 0) {
      segments.push({ category: r.category, from: (left + v) / span, to: left / span, colour, credit: true });
      left += v;
    }
  });
  return { rows, total, lcop, unit: resultsOf(report).lcop_unit ?? "", segments, zero: offset / span };
}

/** The colour index of a cost category in {@link costOfProduction} (1..8, by its row). */
export function costColour(cost: CostOfProduction, category: string): number {
  const i = cost.rows.findIndex((r) => r.category === category);
  return i < 0 ? 0 : (i % 8) + 1;
}

// -- uncertainty -------------------------------------------------------------------------------

/** The Monte Carlo statistics (empty without one). */
export function statisticsOf(report: TeaReport): TeaStatistic[] {
  return report.uncertainty?.statistics ?? [];
}

/** One metric's statistic, or null. */
export function statisticOf(report: TeaReport, metric: string): TeaStatistic | null {
  return statisticsOf(report).find((s) => s.metric === metric) ?? null;
}

/** What `UncertaintyRange` draws: an interval, the median and the deterministic value. */
export interface IntervalStats {
  low: number;
  high: number;
  median: number;
  deterministic: number;
}

/** P10..P90 with the P50 as the interval's median; null when a number is missing. */
export function toIntervalStats(stat: TeaStatistic | null | undefined): IntervalStats | null {
  if (!stat) return null;
  const low = finite(stat.p10);
  const high = finite(stat.p90);
  const median = finite(stat.p50);
  const deterministic = finite(stat.deterministic) ?? median;
  if (low === null || high === null || median === null || deterministic === null) return null;
  return { low, high, median, deterministic };
}

/** The unit for a statistic's numbers: a fraction (IRR) is shown in %. */
export function statisticUnit(report: TeaReport, stat: TeaStatistic): string {
  if (stat.unit === "fraction" || stat.metric === "irr") return "%";
  return stat.unit ?? metricUnit(report, stat.metric);
}

/** A statistic's value as text, by its unit. */
export function statisticText(report: TeaReport, stat: TeaStatistic, value: number | null | undefined): string {
  return metricText(report, stat.metric, value, stat.unit);
}

// -- anything else core adds -------------------------------------------------------------------

/** The top-level keys this page has a section for (anything else is shown generically). */
export const KNOWN_KEYS = new Set([
  "boundary",
  "rev",
  "currency",
  "cost_year",
  "example",
  "stage",
  "estimate_class",
  "expected_class",
  "decision",
  "metric",
  "threshold",
  "basis",
  "operation",
  "lines",
  "variable",
  "emissions",
  "events",
  "cost_of_production",
  "capex",
  "capex_range",
  "flows",
  "opex",
  "results",
  "cashflow",
  "scenarios",
  "inputs",
  "break_even",
  "tornado",
  "uncertainty",
  "findings",
  "source",
]);

export interface GenericTable {
  key: string;
  title: string;
  columns: string[];
  rows: Record<string, unknown>[];
}

/** Arrays of records under keys this page does not know yet, as tables (a newer core's sections show up). */
export function extraTables(report: TeaReport, known: ReadonlySet<string> = KNOWN_KEYS): GenericTable[] {
  const out: GenericTable[] = [];
  for (const [key, value] of Object.entries(report)) {
    if (known.has(key) || !Array.isArray(value) || !value.length) continue;
    const rows = value.filter((r): r is Record<string, unknown> => typeof r === "object" && r !== null && !Array.isArray(r));
    if (!rows.length) continue;
    const columns: string[] = [];
    for (const row of rows) for (const c of Object.keys(row)) if (!columns.includes(c)) columns.push(c);
    out.push({ key, title: keyLabel(key)[0]!.toUpperCase() + keyLabel(key).slice(1), columns, rows });
  }
  return out;
}

/** A generic cell: numbers with 4 digits, objects as JSON, null empty. */
export function cellText(value: unknown): string {
  if (value === null || value === undefined) return "";
  if (typeof value === "number") return numberText(value);
  if (typeof value === "boolean") return value ? "yes" : "no";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}
