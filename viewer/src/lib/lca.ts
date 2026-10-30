/**
 * The LCA page (`GET /api/lca`): contributions per category and scenario, the contribution
 * Sankey (flows -> phase -> functional unit), the scenario bars, and the CSV that
 * `cheme assess lca --csv` writes (byte for byte: `lca/results.csv`).
 *
 * Everything here is pure: the page and the chart components only draw what these functions
 * return, so the geometry is tested without a browser.
 */
import type { LcaGap, LcaImpact, LcaReport, LcaStatistics } from "@/api";
import { csvCell, pyG } from "@/lib/mto";

export const BASELINE = "baseline";
/** Contributors shown by name; the rest are summed into one "other" entry. */
export const TOP = 7;
export const OTHER = "other";
/** Whether *key* is the "other" bucket (`other`, or `other:<phase>` in the Sankey). */
export const isOther = (key: string) => key === OTHER || key.startsWith(`${OTHER}:`);

/**
 * The scenario ids in core's order, baseline first: `scenario_ids`, else (older servers) the order
 * the impacts first name them in, then any other key of `scenarios`. Object keys alone would put
 * ids like `2030` first.
 */
export function scenarioIds(report: Pick<LcaReport, "scenarios"> & Partial<Pick<LcaReport, "scenario_ids" | "impacts">>): string[] {
  const ordered = report.scenario_ids ?? [...(report.impacts ?? []).map((i) => i.scenario), ...Object.keys(report.scenarios ?? {})];
  return [BASELINE, ...ordered].filter((s, i, all) => all.indexOf(s) === i);
}

/** The total of *category* in *scenario* (0 when unknown). */
export function total(report: Pick<LcaReport, "scenarios" | "totals">, scenario: string, category: string): number {
  const totals = report.scenarios?.[scenario] ?? (scenario === BASELINE ? report.totals : undefined);
  return totals?.[category] ?? 0;
}

/** The impacts of one category and scenario. */
export function impactsOf(report: Pick<LcaReport, "impacts">, scenario: string, category: string): LcaImpact[] {
  return report.impacts.filter((i) => i.scenario === scenario && i.category === category);
}

/** A readable name of an inventory key: the row's title, else the key without its prefix. */
export function labelOf(report: Pick<LcaReport, "inventory">, key: string): string {
  if (isOther(key)) return "Other";
  const row = report.inventory.find((r) => r.key === key);
  return row?.title || key.replace(/^[a-z]+:/, "");
}

export interface Contribution {
  key: string;
  label: string;
  phase: string;
  value: number;
  /** Of the scenario's total (signed; empty total: 0). */
  share: number;
}

/**
 * The contributions of *category* in *scenario*, largest magnitude first; beyond *top* they are
 * summed into one `other` entry per phase (`other:operation`, `other:construction`), so each
 * phase's sum stays exact.
 */
export function contributions(report: Pick<LcaReport, "impacts" | "inventory">, scenario: string, category: string, top = TOP): Contribution[] {
  const byKey = new Map<string, Contribution>();
  for (const impact of impactsOf(report, scenario, category)) {
    const found = byKey.get(impact.key);
    if (found) found.value += impact.value;
    else byKey.set(impact.key, { key: impact.key, label: labelOf(report, impact.key), phase: impact.phase, value: impact.value, share: 0 });
  }
  const sorted = [...byKey.values()].sort((a, b) => Math.abs(b.value) - Math.abs(a.value) || a.key.localeCompare(b.key));
  const sum = sorted.reduce((s, c) => s + c.value, 0);
  let shown = sorted;
  if (sorted.length > top + 1) {
    const rest = sorted.slice(top);
    const phases = [...new Set(rest.map((c) => c.phase))];
    shown = [
      ...sorted.slice(0, top),
      ...phases.map((phase) => {
        const members = rest.filter((c) => c.phase === phase);
        return {
          key: phases.length > 1 ? `${OTHER}:${phase}` : OTHER,
          label: `Other (${members.length}${phases.length > 1 ? `, ${phase}` : ""})`,
          phase,
          value: members.reduce((s, c) => s + c.value, 0),
          share: 0,
        };
      }),
    ];
  }
  return shown.map((c) => ({ ...c, share: sum ? c.value / sum : 0 }));
}

// -- Sankey -----------------------------------------------------------------------------------

export interface SankeyNodeInput {
  id: string;
  label: string;
  column: number;
  /** For styling: `flow`, `phase`, `total`. */
  kind: string;
}

export interface SankeyLinkInput {
  source: string;
  target: string;
  /** Signed: a negative value is a credit, drawn with its magnitude. */
  value: number;
  /** The contributor it carries (for colour and the tooltip). */
  key: string;
}

export interface SankeyNode extends SankeyNodeInput {
  x: number;
  y: number;
  width: number;
  height: number;
  /** Signed sum of what enters it (sources: what leaves it). */
  value: number;
}

export interface SankeyLink extends SankeyLinkInput {
  width: number;
  /** Centre of the band at the source and at the target. */
  y0: number;
  y1: number;
  x0: number;
  x1: number;
  credit: boolean;
  /** The band as a closed SVG path. */
  path: string;
}

export interface SankeyLayout {
  width: number;
  height: number;
  nodes: SankeyNode[];
  links: SankeyLink[];
}

export interface SankeyOptions {
  width: number;
  height: number;
  nodeWidth?: number;
  /** Vertical gap between nodes of a column. */
  gap?: number;
  /**
   * The least vertical room a node takes in its column (its label's two lines): a node smaller
   * than this keeps its height but the next one starts below the slot, so labels do not overlap.
   */
  slot?: number;
}

/**
 * A left-to-right Sankey of *nodes* in columns, joined by *links*. A node is as tall as the
 * larger of the magnitudes entering and leaving it; one scale for all columns, set by the
 * fullest column. Nodes keep their input order within a column; at a node, links leave in the
 * order of their targets and arrive in the order of their sources, so bands do not cross
 * needlessly.
 */
export function layoutSankey(nodesIn: readonly SankeyNodeInput[], linksIn: readonly SankeyLinkInput[], options: SankeyOptions): SankeyLayout {
  const { width } = options;
  const nodeWidth = options.nodeWidth ?? 12;
  const gap = options.gap ?? 10;
  const slot = options.slot ?? 0;
  const ids = new Set(nodesIn.map((n) => n.id));
  const links = linksIn.filter((l) => ids.has(l.source) && ids.has(l.target) && Number.isFinite(l.value) && l.value !== 0);
  const magnitudeIn = new Map<string, number>();
  const magnitudeOut = new Map<string, number>();
  const signedIn = new Map<string, number>();
  const signedOut = new Map<string, number>();
  for (const l of links) {
    const m = Math.abs(l.value);
    magnitudeOut.set(l.source, (magnitudeOut.get(l.source) ?? 0) + m);
    magnitudeIn.set(l.target, (magnitudeIn.get(l.target) ?? 0) + m);
    signedOut.set(l.source, (signedOut.get(l.source) ?? 0) + l.value);
    signedIn.set(l.target, (signedIn.get(l.target) ?? 0) + l.value);
  }
  const size = (id: string) => Math.max(magnitudeIn.get(id) ?? 0, magnitudeOut.get(id) ?? 0);
  const columns = [...new Set(nodesIn.map((n) => n.column))].sort((a, b) => a - b);
  const byColumn = new Map(columns.map((c) => [c, nodesIn.filter((n) => n.column === c && size(n.id) > 0)]));
  // Slots and gaps that cannot fit make the chart taller rather than overflowing it.
  const fixed = Math.max(0, ...columns.map((c) => byColumn.get(c)!.length * slot + gap * Math.max(0, byColumn.get(c)!.length - 1)));
  const height = Math.max(options.height, fixed);
  /** The height a column takes at *s* (nodes, their slots and the gaps). */
  const used = (column: number, s: number) => {
    const members = byColumn.get(column)!;
    return members.reduce((sum, n) => sum + Math.max(size(n.id) * s, slot), 0) + gap * Math.max(0, members.length - 1);
  };
  // the largest scale at which every column fits: bisection, since slots make it non-linear
  let low = 0;
  // no column fits above height / (its sum), so the smallest positive sum bounds the scale
  const sums = columns.map((c) => byColumn.get(c)!.reduce((s, n) => s + size(n.id), 0)).filter((v) => v > 0);
  let high = sums.length ? height / Math.min(...sums) : 0;
  for (let i = 0; i < 60; i++) {
    const mid = (low + high) / 2;
    if (columns.every((c) => used(c, mid) <= height)) low = mid;
    else high = mid;
  }
  const scale = low;
  const step = columns.length > 1 ? (width - nodeWidth) / (columns.length - 1) : 0;

  const nodes: SankeyNode[] = [];
  const at = new Map<string, SankeyNode>();
  columns.forEach((column, index) => {
    const members = byColumn.get(column)!;
    let y = (height - used(column, scale)) / 2;
    for (const n of members) {
      const node: SankeyNode = {
        ...n,
        x: index * step,
        y,
        width: nodeWidth,
        height: size(n.id) * scale,
        value: signedIn.has(n.id) ? signedIn.get(n.id)! : (signedOut.get(n.id) ?? 0),
      };
      nodes.push(node);
      at.set(n.id, node);
      y += Math.max(node.height, slot) + gap;
    }
  });

  const order = new Map(nodes.map((n, i) => [n.id, i]));
  const outOffset = new Map<string, number>();
  const inOffset = new Map<string, number>();
  const sortedOut = [...links].sort((a, b) => order.get(a.source)! - order.get(b.source)! || order.get(a.target)! - order.get(b.target)!);
  const placed = new Map<SankeyLinkInput, { y0: number; width: number }>();
  for (const l of sortedOut) {
    const source = at.get(l.source)!;
    const w = Math.abs(l.value) * scale;
    const offset = outOffset.get(l.source) ?? 0;
    placed.set(l, { y0: source.y + offset + w / 2, width: w });
    outOffset.set(l.source, offset + w);
  }
  const sortedIn = [...links].sort((a, b) => order.get(a.target)! - order.get(b.target)! || order.get(a.source)! - order.get(b.source)!);
  const out: SankeyLink[] = [];
  for (const l of sortedIn) {
    const source = at.get(l.source)!;
    const target = at.get(l.target)!;
    const { y0, width: w } = placed.get(l)!;
    const offset = inOffset.get(l.target) ?? 0;
    const y1 = target.y + offset + w / 2;
    inOffset.set(l.target, offset + w);
    const x0 = source.x + source.width;
    const x1 = target.x;
    out.push({ ...l, width: w, y0, y1, x0, x1, credit: l.value < 0, path: bandPath(x0, y0, x1, y1, w) });
  }
  // the input order of the links (stable keys and drawing order)
  const index = new Map(links.map((l, i) => [l, i]));
  const drawn = sortedIn.map((l, i) => [index.get(l)!, out[i]!] as const);
  return { width, height, nodes, links: drawn.sort((a, b) => a[0] - b[0]).map(([, l]) => l) };
}

const r = (v: number) => Math.round(v * 100) / 100;

/** A band of width *w* from (x0, y0) to (x1, y1), centre line a horizontal S-curve. */
export function bandPath(x0: number, y0: number, x1: number, y1: number, w: number): string {
  const xm = (x0 + x1) / 2;
  const h = w / 2;
  return (
    `M${r(x0)},${r(y0 - h)} C${r(xm)},${r(y0 - h)} ${r(xm)},${r(y1 - h)} ${r(x1)},${r(y1 - h)} ` +
    `L${r(x1)},${r(y1 + h)} C${r(xm)},${r(y1 + h)} ${r(xm)},${r(y0 + h)} ${r(x0)},${r(y0 + h)} Z`
  );
}

const PHASE_TITLES: Record<string, string> = { operation: "Operation", construction: "Construction" };

/**
 * The contribution Sankey of *category* in *scenario*: each contributor (column 0) flows into
 * its phase (column 1), the phases into the functional unit (column 2).
 */
export function contributionSankey(report: Pick<LcaReport, "impacts" | "inventory" | "functional_unit">, scenario: string, category: string, options: SankeyOptions, top = TOP): SankeyLayout {
  const parts = contributions(report, scenario, category, top);
  const phases = [...new Set(parts.map((c) => c.phase))].sort((a, b) => (a === "operation" ? -1 : b === "operation" ? 1 : a.localeCompare(b)));
  const nodes: SankeyNodeInput[] = [
    ...parts.map((c) => ({ id: `flow:${c.key}`, label: c.label, column: 0, kind: "flow" })),
    ...phases.map((p) => ({ id: `phase:${p}`, label: PHASE_TITLES[p] ?? p, column: 1, kind: "phase" })),
    { id: "total", label: report.functional_unit, column: 2, kind: "total" },
  ];
  const links: SankeyLinkInput[] = [
    ...parts.map((c) => ({ source: `flow:${c.key}`, target: `phase:${c.phase}`, value: c.value, key: c.key })),
    ...phases.map((p) => ({
      source: `phase:${p}`,
      target: "total",
      value: parts.filter((c) => c.phase === p).reduce((s, c) => s + c.value, 0),
      key: `phase:${p}`,
    })),
  ];
  return layoutSankey(nodes, links, options);
}

// -- scenario bars ----------------------------------------------------------------------------

export interface BarSegment {
  key: string;
  label: string;
  value: number;
  /** Fractions of the bar axis, 0..1 (left to right). */
  from: number;
  to: number;
}

export interface Bar {
  scenario: string;
  total: number;
  segments: BarSegment[];
  /** Exchanges the baseline characterises in the category that are gaps in this scenario
   * (pre-release issue 172): its total leaves them out, so no bar is drawn. Empty: comparable. */
  dropped: string[];
  /** No total at all: data the baseline has is missing, or every contribution is a gap. */
  none: boolean;
}

export interface Bars {
  bars: Bar[];
  /** Where zero is on the axis, 0..1 (left of it: credits). */
  zero: number;
  /** The axis' lower and upper bound, in the category's unit. */
  min: number;
  max: number;
  /** The contributors in colour order (the baseline's largest first, then `other`). */
  keys: string[];
}

type Standing = Pick<LcaReport, "impacts"> & Partial<Pick<LcaReport, "gaps" | "not_comparable">>;

/**
 * The exchanges the baseline characterises in *category* that are gaps in *scenario*: a total
 * without them (a regional scenario without an electricity factor) is not a lower footprint.
 * core's `not_comparable` when the server gives it, else derived from the impacts and gaps.
 */
export function droppedIn(report: Standing, scenario: string, category: string): string[] {
  if (scenario === BASELINE) return [];
  const stated = report.not_comparable?.[scenario]?.[category];
  if (stated) return stated;
  const base = new Set(impactsOf(report, BASELINE, category).map((i) => i.key));
  const mine = new Set(impactsOf(report, scenario, category).map((i) => i.key));
  const gapped = (report.gaps ?? []).filter(
    (g) => g.scenario === scenario && g.category === category && !OUTSIDE_METHOD.has(g.reason),
  );
  return [...new Set(gapped.map((g) => g.key))].filter((k) => base.has(k) && !mine.has(k)).sort();
}

/**
 * Whether *scenario* has a total in *category* at all (pre-release issue 172): not when it lacks data the
 * baseline has ({@link droppedIn}), nor when every contribution is a gap (no total, never 0).
 */
export function hasTotal(report: Standing, scenario: string, category: string): boolean {
  if (droppedIn(report, scenario, category).length) return false;
  if (report.not_comparable && category in (report.not_comparable[scenario] ?? {})) return false;
  const gapped = (report.gaps ?? []).some(
    (g) => g.scenario === scenario && g.category === category && !OUTSIDE_METHOD.has(g.reason),
  );
  return !gapped || impactsOf(report, scenario, category).length > 0;
}

/**
 * One stacked bar per scenario of *category*: the baseline's largest contributors each keep one
 * segment (and colour) in every scenario, the rest is `other`. Positive values stack right of
 * zero, credits left of it; the axis spans the largest stack of either sign. A scenario without
 * a total ({@link hasTotal}) gets no bar.
 */

export function scenarioBars(
  report: Pick<LcaReport, "impacts" | "inventory" | "scenarios" | "totals"> & Partial<Pick<LcaReport, "gaps" | "not_comparable">>,
  category: string,
  top = TOP,
): Bars {
  const named = contributions(report, BASELINE, category, top)
    .map((c) => c.key)
    .filter((k) => k !== OTHER);
  const keys = [...named];
  const raw = scenarioIds(report).map((scenario) => {
    const sums = new Map<string, number>();
    const dropped = droppedIn(report, scenario, category);
    const none = !hasTotal(report, scenario, category);
    if (none) return { scenario, sums, dropped, none };
    for (const i of impactsOf(report, scenario, category)) {
      const key = named.includes(i.key) ? i.key : OTHER;
      sums.set(key, (sums.get(key) ?? 0) + i.value);
    }
    if (sums.has(OTHER) && !keys.includes(OTHER)) keys.push(OTHER);
    return { scenario, sums, dropped, none };
  });
  let low = 0;
  let high = 0;
  for (const { sums } of raw) {
    const values = [...sums.values()];
    high = Math.max(high, values.filter((v) => v > 0).reduce((s, v) => s + v, 0));
    low = Math.min(low, values.filter((v) => v < 0).reduce((s, v) => s + v, 0));
  }
  const span = high - low || 1;
  const pos = (v: number) => (v - low) / span;
  const bars = raw.map(({ scenario, sums, dropped, none }) => {
    let up = 0;
    let down = 0;
    const segments: BarSegment[] = [];
    for (const key of keys) {
      const value = sums.get(key);
      if (!value) continue;
      if (value > 0) {
        segments.push({ key, label: labelOf(report, key), value, from: pos(up), to: pos(up + value) });
        up += value;
      } else {
        segments.push({ key, label: labelOf(report, key), value, from: pos(down + value), to: pos(down) });
        down += value;
      }
    }
    return { scenario, total: total(report, scenario, category), segments, dropped, none };
  });
  return { bars, zero: pos(0), min: low, max: high, keys };
}

/** The colour slot (1..8, CSS `--chart-n`) of a contributor in *keys*; `other` is grey (0). */
export function colourOf(key: string, keys: readonly string[]): number {
  if (isOther(key)) return 0;
  const index = keys.indexOf(key);
  return index < 0 ? 0 : (index % 8) + 1;
}

// -- numbers and CSV --------------------------------------------------------------------------

/**
 * Python's `f"{value:.4f}"`: the exact binary value rounded half to even (JavaScript's `toFixed`
 * rounds an exact tie up), and `-0.0000` for a negative value that rounds to zero.
 */
export function pyFixed4(value: number): string {
  if (!Number.isFinite(value)) return value > 0 ? "inf" : value < 0 ? "-inf" : "nan";
  const magnitude = Math.abs(value);
  // toFixed rounds the exact binary value like Python, except an exact tie, which it rounds up.
  // A double half-way between two 4-decimal numbers is m/20000 (m odd) and binary, so it is an
  // odd multiple of 1/32; times 32 is exact in floating point.
  let text = magnitude.toFixed(4);
  const k = magnitude * 32;
  if (Number.isInteger(k) && k % 2 === 1) {
    const down = Math.floor(magnitude * 1e4);
    text = ((down % 2 === 0 ? down : down + 1) / 1e4).toFixed(4);
  }
  return value < 0 || Object.is(value, -0) ? `-${text}` : text;
}

/** An impact for the page: 4 significant digits, digits grouped. */
export function impactText(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return "";
  if (value === 0) return "0";
  const magnitude = Math.abs(value);
  if (magnitude >= 1e-3 && magnitude < 1e7) return Number(value.toPrecision(4)).toLocaleString("en-US", { maximumFractionDigits: 6 });
  return value.toExponential(3);
}

/** A share for the page, e.g. `98.8 %`. */
export function shareText(share: number): string {
  return `${(share * 100).toFixed(1)} %`;
}

export const RESULT_COLUMNS = [
  "scenario",
  "category",
  "category_unit",
  "key",
  "basis",
  "quantity",
  "unit",
  "factor",
  "impact",
  "share",
  "phase",
  "status",
  "source",
  "year",
] as const;

/** The impacts as `cheme assess lca --csv` writes them (`lca/results.csv`). */
export function lcaCsv(report: LcaReport): string {
  const lines = [RESULT_COLUMNS.join(",")];
  for (const scenario of scenarioIds(report)) {
    for (const category of report.categories) {
      const sum = total(report, scenario, category.id);
      for (const i of impactsOf(report, scenario, category.id))
        lines.push(
          [
            scenario,
            category.id,
            category.unit,
            i.key,
            i.basis,
            pyG(i.quantity),
            i.unit,
            pyG(i.factor),
            pyG(i.value),
            sum ? pyFixed4(i.value / sum) : "",
            i.phase,
            i.status,
            i.source,
            i.year === null ? "" : String(i.year),
          ]
            .map(csvCell)
            .join(","),
        );
      lines.push([scenario, category.id, category.unit, "total", "", "", "", "", pyG(sum), sum ? "1.0000" : "", "", "", "", ""].map(csvCell).join(","));
    }
  }
  return lines.join("\n") + "\n";
}

// -- allocation, uncertainty, revisions -------------------------------------------------------

export interface AllocationRow {
  method: string;
  current: boolean;
  /** The functional unit's share (null when the method does not apply). */
  share: number | null;
  total: number | null;
  /** Of the method used (1 for it; null when either total is missing or zero). */
  relative: number | null;
  problem: string;
}

/** Every allocation method's total in *category*, with its ratio to the method used. */
export function allocationRows(report: Pick<LcaReport, "allocation">, category: string): AllocationRow[] {
  const methods = report.allocation.comparison ?? [];
  const used = methods.find((m) => m.current)?.totals?.[category] ?? null;
  return methods.map((m) => {
    const total = m.totals?.[category] ?? null;
    return {
      method: m.method,
      current: m.current,
      share: m.share,
      total,
      relative: total !== null && used ? total / used : null,
      problem: m.problem,
    };
  });
}

/** The Monte Carlo statistics of *category*, if the study has them. */
export function statisticsOf(report: Pick<LcaReport, "uncertainty">, category: string): LcaStatistics | null {
  return report.uncertainty?.statistics.find((s) => s.category === category) ?? null;
}

export interface IntervalGeometry {
  /** Fractions 0..1 along the bar. */
  low: number;
  high: number;
  median: number;
  deterministic: number;
  /** The axis' bounds, in the category's unit. */
  min: number;
  max: number;
}

/** Where the 95 % interval, the median and the deterministic value sit on one axis. */
export function intervalGeometry<T extends Pick<LcaStatistics, "low" | "high" | "median" | "deterministic">>(stats: T): IntervalGeometry {
  const lo = Math.min(stats.low, stats.deterministic, 0);
  const hi = Math.max(stats.high, stats.deterministic, 0);
  const span = hi - lo || 1;
  const pos = (v: number) => (v - lo) / span;
  return { low: pos(stats.low), high: pos(stats.high), median: pos(stats.median), deterministic: pos(stats.deterministic), min: lo, max: hi };
}

/** A readable sensitivity input: `amount:feed:POWER` -> amount of the row's title. */
export function sensitivityLabel(report: Pick<LcaReport, "inventory">, name: string): string {
  const [kind, ...rest] = name.split(":");
  const key = rest.join(":");
  if (kind === "amount") return `Amount: ${labelOf(report, key)}`;
  if (kind === "factor") return `Factor: ${key}`;
  return name;
}

export interface RevisionRow {
  key: string;
  label: string;
  /** This revision, the other one, and this minus the other (null: the category is absent in
   * one of them, or its unit differs, and the change means nothing). */
  value: number | null;
  other: number | null;
  delta: number | null;
  /** Why the row does not compare (absent here or there, another unit). */
  note: string;
}

/** Category totals of the baseline in *report* against *other* (by category id; categories
 * only one revision has are listed with the other side null). */
export function compareTotals(report: LcaReport, other: LcaReport): RevisionRow[] {
  const theirs = new Map(other.categories.map((c) => [c.id, c]));
  const rows: RevisionRow[] = report.categories.map((c) => {
    const value = total(report, BASELINE, c.id);
    const match = theirs.get(c.id);
    const label = `${c.title || c.id} (${c.unit})`;
    if (!match) return { key: c.id, label, value, other: null, delta: null, note: "absent in the other revision" };
    const previous = total(other, BASELINE, c.id);
    if (match.unit !== c.unit) return { key: c.id, label, value, other: previous, delta: null, note: `unit there: ${match.unit}` };
    return { key: c.id, label, value, other: previous, delta: value - previous, note: "" };
  });
  const mine = new Set(report.categories.map((c) => c.id));
  for (const c of other.categories) {
    if (!mine.has(c.id)) rows.push({ key: c.id, label: `${c.title || c.id} (${c.unit})`, value: null, other: total(other, BASELINE, c.id), delta: null, note: "absent in this revision" });
  }
  return rows;
}

/** Each contributor's change in *category* (baseline), largest change first. */
export function compareContributions(report: LcaReport, other: LcaReport, category: string, top = 10): RevisionRow[] {
  const sum = (r: LcaReport) => {
    const out = new Map<string, number>();
    for (const i of impactsOf(r, BASELINE, category)) out.set(i.key, (out.get(i.key) ?? 0) + i.value);
    return out;
  };
  const mine = sum(report);
  const theirs = sum(other);
  const keys = [...new Set([...mine.keys(), ...theirs.keys()])];
  return keys
    .map((key) => {
      const value = mine.get(key) ?? 0;
      const previous = theirs.get(key) ?? 0;
      return { key, label: labelOf(mine.has(key) ? report : other, key), value, other: previous, delta: value - previous, note: "" };
    })
    .filter((r) => r.delta !== 0)
    .sort((a, b) => Math.abs(b.delta!) - Math.abs(a.delta!) || a.key.localeCompare(b.key))
    .slice(0, top);
}

/** Gap reasons that are no gaps: a flow a method does not list contributes nothing by the method's definition. */
export const OUTSIDE_METHOD = new Set(["elementary-uncharacterised", "biosphere-uncharacterised"]);

/** What each gap reason means (core's GAP_REASONS). */
export const GAP_REASONS: Record<string, string> = {
  unmapped: "no background in lca/lca.yaml",
  "no-weight": "an equipment item of the construction has no weight: amount unknown",
  unmatched: "no construction entry counts this take-off row or item: amount unknown",
  missing: "declared missing: no background available",
  "factor-category": "its factor has no value in this category",
  "elementary-unlinked": "the category names no packaged method for direct emissions",
  "elementary-uncharacterised": "outside the method: it has no factor for this emission",
  "biosphere-uncharacterised": "outside the method: the Brightway method does not characterise this flow",
  "dataset-category": "the referenced dataset has no score in this category",
  "dataset-unlinked": "an exchange of the referenced dataset has no background",
};

/** The gaps of a scenario and category (exchanges without a burden), or the flows outside the method with `outside`. */
export function gapsOf(report: LcaReport, scenario: string, category: string, outside = false): LcaGap[] {
  return (report.gaps ?? []).filter(
    (g) => g.scenario === scenario && g.category === category && OUTSIDE_METHOD.has(g.reason) === outside,
  );
}

/** Whether a scenario has gaps in any category (its totals leave something out). */
export function scenarioHasGaps(report: LcaReport, scenario: string): boolean {
  return (report.gaps ?? []).some((g) => g.scenario === scenario && !OUTSIDE_METHOD.has(g.reason));
}

/** Why a gap is one, in words, with its detail. */
export function gapText(gap: LcaGap): string {
  const why = GAP_REASONS[gap.reason] ?? gap.reason;
  return gap.detail ? `${why} (${gap.detail})` : why;
}

/** The badge class of a contribution's status: a proxy or an estimate is flagged. */
export function statusClass(status: string): string {
  return status === "PROXY" || status === "ESTIMATE" ? "warning" : "";
}

/**
 * The link target of a source's `url` (free text in `lca/factors.yaml`): the normalised URL when
 * it is an absolute http(s) URL, else null so the title is shown as plain text. Parsed the way the
 * browser parses an href, so `java\tscript:` and the like cannot pass as a link.
 */
export function sourceHref(url: string | null | undefined): string | null {
  if (!url) return null;
  try {
    const parsed = new URL(url.trim());
    return parsed.protocol === "http:" || parsed.protocol === "https:" ? parsed.href : null;
  } catch {
    return null;
  }
}

export type VerdictKind = "baseline" | "like-for-like" | "proxy" | "not-comparable" | "not-assessed";

export interface Verdict {
  kind: VerdictKind;
  label: string;
  /** The `.badge` class of src/styles.css. */
  badge: "pass" | "warning" | "fail" | "info";
  text: string;
  reasons: string[];
}

const VERDICTS: Record<VerdictKind, Omit<Verdict, "kind" | "reasons">> = {
  baseline: { label: "baseline", badge: "info", text: "the reference the other scenarios are compared with" },
  "like-for-like": { label: "like-for-like", badge: "pass", text: "with the baseline: the declared basis of its factors matches" },
  proxy: { label: "proxy", badge: "warning", text: "with the baseline: a declared proxy stands in, a screening sensitivity" },
  "not-comparable": { label: "not comparable", badge: "fail", text: "with the baseline: do not read the difference as a higher or lower footprint, nor as a country footprint" },
  "not-assessed": { label: "not assessed", badge: "info", text: "no verdict from this server (older core): not shown as comparable" },
};

/**
 * The comparison verdict of *scenario* against the baseline (pre-release issue 306): core's `comparability`,
 * never more favourable than the data allow. A scenario whose total does not stand (data the
 * baseline has are missing: {@link hasTotal}) is not comparable whatever the factors say, and a
 * report without a verdict (an older core) is "not assessed", never like-for-like.
 */
export function verdictOf(report: Standing & Partial<Pick<LcaReport, "comparability">>, scenario: string, category?: string): Verdict {
  const stated = report.comparability?.[scenario]?.verdict?.toLowerCase().replace(/[\s_]+/g, "-");
  const gapped = category !== undefined && !hasTotal(report, scenario, category);
  let kind: VerdictKind;
  if (scenario === BASELINE || stated === "baseline") kind = "baseline";
  else if (gapped) kind = "not-comparable";
  else if (stated === "like-for-like") kind = "like-for-like";
  else if (stated === "proxy") kind = "proxy";
  else if (stated === "not-comparable") kind = "not-comparable";
  else kind = "not-assessed";
  return { kind, ...VERDICTS[kind], reasons: report.comparability?.[scenario]?.reasons ?? [] };
}
