/**
 * The catalysis results of core's API: a mechanism's microkinetic analysis at its reactor's
 * outlet (`microkinetics` of `/api/reactions`), the kinetic data with their default fits
 * (`/api/kinetics`) and the reaction library marked by what the plant has (`/api/library`).
 */
import type { FitParameter, KineticDataFile, LibraryEntry, Microkinetics, ReactorRow } from "@/api";
import { formatNumber } from "./process";
import { equationText } from "./reactions";

/** Four significant digits, small and large values in exponent form (`7.718e-7`). */
export function sig(v: number | null | undefined, digits = 4): string {
  if (v === null || v === undefined || !Number.isFinite(v)) return "";
  const a = Math.abs(v);
  return a !== 0 && (a < 1e-3 || a >= 1e6) ? v.toExponential(digits - 1) : formatNumber(Number(v.toPrecision(digits)));
}

/** `CO 0.01005 bar, O2 0.09548 bar`. */
export function pressuresText(pressures: Record<string, number>): string {
  return Object.entries(pressures)
    .map(([n, p]) => `${n} ${sig(p)} bar`)
    .join(", ");
}

export interface Bar {
  id: string;
  value: number;
  /** The bar's length as a fraction of the track, 0..1. */
  width: number;
  text: string;
}

/** Coverages, largest first: the share of the sites each adsorbate (and `*`, free) holds. */
export function coverageBars(coverages: Record<string, number> | undefined): Bar[] {
  return Object.entries(coverages ?? {})
    .sort(([, a], [, b]) => b - a)
    .map(([id, v]) => ({ id, value: v, width: Math.min(Math.max(v, 0), 1), text: v >= 1e-3 ? `${formatNumber(Number((v * 100).toPrecision(4)))} %` : v.toExponential(2) }));
}

/** Degrees of rate control, by size: |X| as the bar (capped at 1), the sign kept in the text. */
export function rateControlBars(control: Record<string, number> | undefined): Bar[] {
  return Object.entries(control ?? {})
    .sort(([, a], [, b]) => Math.abs(b) - Math.abs(a))
    .map(([id, v]) => ({ id, value: v, width: Math.min(Math.abs(v), 1), text: Math.abs(v) < 1e-3 ? "≈ 0" : formatNumber(Number(v.toFixed(3))) }));
}

/** The step that controls the rate (degree of rate control above 0.5), if one does. */
export function rateDeterminingStep(mk: Pick<Microkinetics, "rate_control"> | null | undefined): string | null {
  const [top] = rateControlBars(mk?.rate_control);
  return top && top.value > 0.5 ? top.id : null;
}

/** The most abundant surface intermediate (the free sites `*` aside) when it holds over half the sites. */
export function masi(mk: Pick<Microkinetics, "coverages"> | null | undefined): string | null {
  const top = coverageBars(mk?.coverages).find((b) => b.id !== "*");
  return top && top.value > 0.5 ? top.id : null;
}

/** A step's equation as written, else from its stoichiometry (`CO + * <=> CO*`, `->` when it has no reverse). */
export function stepEquation(step: { equation?: string; stoichiometry: Record<string, number>; reverse?: unknown; energies?: unknown }): string {
  return equationText({ equation: step.equation ?? "", stoichiometry: step.stoichiometry, reversible: Boolean(step.reverse || step.energies) });
}

/** `Peng–Robinson` for a reactor whose equilibrium uses fugacities; empty for the ideal gas (or an older server). */
export function fugacityText(row: Pick<ReactorRow, "fugacity">): string {
  return row.fugacity === "peng_robinson" ? "Peng–Robinson" : "";
}

// -- kinetic data -----------------------------------------------------------------------------

/** `Ea`, `ln A`, `order CO`: a fit parameter's name as the page shows it. */
export function parameterName(name: string): string {
  if (name === "ln_A") return "ln A";
  if (name.startsWith("order_")) return `order ${name.slice(6)}`;
  if (name.startsWith("K_")) return `K ${name.slice(2)}`;
  return name;
}

/** `111000 ± 1.86e-9 (95 %: 111000–111000)` with the parameter's unit. */
export function parameterText(name: string, p: FitParameter): string {
  const unit = name === "Ea" ? " kJ/kmol" : "";
  const se = p.standard_error === null ? "" : ` ± ${sig(p.standard_error, 3)}`;
  const ci = p.interval_95 ? ` (95 %: ${sig(p.interval_95[0])} to ${sig(p.interval_95[1])})` : "";
  return `${sig(p.value, 6)}${unit}${se}${ci}`;
}

export interface FitRow {
  temperature: number;
  pressures: Record<string, number>;
  measured: number;
  /** The fit's rate at the point (from its residual of ln r), null without a fit. */
  fitted: number | null;
  /** fitted / measured - 1. */
  deviation: number | null;
}

/** The points of a data file with the fit's rate at each (ln r measured - ln r fitted = residual). */
export function fitRows(file: Pick<KineticDataFile, "data" | "fit">): FitRow[] {
  const points = file.data?.points ?? [];
  const residuals = file.fit && file.fit.residuals.length === points.length ? file.fit.residuals : null;
  return points.map((p, i) => {
    const fitted = residuals ? p.rate * Math.exp(-residuals[i]!) : null;
    return { temperature: p.temperature, pressures: p.partial_pressures, measured: p.rate, fitted, deviation: fitted === null || p.rate === 0 ? null : fitted / p.rate - 1 };
  });
}

/** The largest |fitted / measured - 1| of the points, null without a fit. */
export function worstDeviation(rows: readonly FitRow[]): number | null {
  const d = rows.map((r) => r.deviation).filter((v): v is number => v !== null);
  return d.length ? Math.max(...d.map(Math.abs)) : null;
}

/** `kmol/(kg s)` or `kmol/(m³ s)`: the unit of a data file's rates. */
export function rateUnit(basis: string | undefined): string {
  return basis === "volume" ? "kmol/(m³ s)" : "kmol/(kg s)";
}

// -- reaction library -------------------------------------------------------------------------

export interface LibraryMatch {
  /** Of the entry's components, reactions and catalysts: how many the plant has. */
  have: number;
  of: number;
  /** all: the plant has every item; some; none. */
  state: "all" | "some" | "none";
  /** The plant has one of its reactions or catalysts (a shared component such as water alone does not count). */
  runs: boolean;
}

export function libraryMatch(entry: Pick<LibraryEntry, "components" | "reactions" | "catalysts">): LibraryMatch {
  const marks = [...entry.components.map((c) => c.in_plant !== null), ...entry.reactions.map((r) => r.in_plant), ...entry.catalysts.map((c) => c.in_plant)];
  const have = marks.filter(Boolean).length;
  const runs = entry.reactions.some((r) => r.in_plant) || entry.catalysts.some((c) => c.in_plant && !c.differs);
  return { have, of: marks.length, state: have === 0 ? "none" : have === marks.length ? "all" : "some", runs };
}

/** The entries whose id, title, components, reactions or catalysts contain *query* (any case). */
export function filterLibrary<T extends LibraryEntry>(entries: readonly T[], query: string): T[] {
  const q = query.trim().toLowerCase();
  if (!q) return [...entries];
  return entries.filter((e) =>
    [e.id, e.title, ...e.components.flatMap((c) => [c.id, c.name, c.formula, c.cas]), ...e.reactions.flatMap((r) => [r.id, r.equation]), ...e.catalysts.flatMap((c) => [c.id, c.name, c.active_phase])]
      .filter(Boolean)
      .some((t) => t.toLowerCase().includes(q)),
  );
}

/** `cheme chemistry library <id> --add`: what adds an entry to the plant. */
export const addCommand = (id: string) => `cheme chemistry library ${id} --add`;
