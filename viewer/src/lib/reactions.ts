/**
 * The reactions of `GET /api/reactions` (core: `domains/process/reaction_view.py`): how a
 * reaction reads (equation, conversion or equilibrium constant, heat of reaction, element
 * balance), how close a reactor is to equilibrium, and where its node is drawn; the kinetics:
 * a rate law's parameters, the catalyst it is for, and the line charts of k(T) (a fixed bed has its own: src/lib/fixedBed.ts).
 */
import type { CatalystEntry, ProcessNode, Provenance, RateLaw, Reaction, ReactionHeat, ReactionsKinetics, ReactionsView, Sheet } from "@/api";
import { sheetFile } from "./format";
import { formatNumber } from "./process";
import { isRecord } from "./guards";

export const REACTIONS_FILE = "process/reactions.yaml";
/** The equipment list core reads (`LIST_FILES["equipment"]`): a tag's sheet when a link names none. */
export const EQUIPMENT_LIST = "equipment/equipment-list.yaml";

/** The reaction's equation as written, else from its stoichiometry (`N2 + 3 H2 -> 2 NH3`). */
export function equationText(r: Pick<Reaction, "equation" | "stoichiometry" | "reversible">): string {
  if (r.equation) return r.equation;
  const side = (sign: number) =>
    Object.entries(r.stoichiometry)
      .filter(([, v]) => Math.sign(v) === sign)
      .map(([n, v]) => (Math.abs(v) === 1 ? n : `${formatNumber(Math.abs(v))} ${n}`))
      .join(" + ");
  return `${side(-1)} ${r.reversible ? "<=>" : "->"} ${side(1)}`;
}

/** `N +1, H +3`: the atoms a reaction creates (positive) or loses. */
export function changeText(change: Record<string, number>): string {
  return Object.entries(change)
    .map(([el, v]) => `${el} ${v > 0 ? "+" : ""}${formatNumber(v)}`)
    .join(", ");
}

export function elementBadge(r: Pick<Reaction, "element_balance">): { badge: string; label: string; title: string } {
  const eb = r.element_balance;
  if (!eb.evaluable) return { badge: "", label: "not evaluable", title: "A component has no formula: the atoms cannot be counted" };
  if (eb.balanced) return { badge: "pass", label: "balanced", title: "The atoms of reactants and products are the same" };
  return { badge: "error", label: "unbalanced", title: `Atoms created or lost: ${changeText(eb.change)}` };
}

/** What sets how far a reaction goes: its conversion, an equilibrium constant, or what its units use. */
export interface Extent {
  kind: "conversion" | "K" | "ideal-gas" | null;
  text: string;
  provenance: Provenance | null;
  source: string;
}

export function extentOf(r: Pick<Reaction, "conversion" | "equilibrium_constant" | "units" | "type">): Extent {
  if (r.conversion) {
    return { kind: "conversion", text: `X = ${formatNumber(r.conversion.value)} of ${r.conversion.key}`, provenance: r.conversion.provenance, source: r.conversion.source };
  }
  const k = r.equilibrium_constant;
  if (k) {
    const terms = [formatNumber(k.a), k.b ? `${formatNumber(k.b)}/T` : "", k.c ? `${formatNumber(k.c)} ln T` : "", k.d ? `${formatNumber(k.d)} T` : ""].filter(Boolean);
    const range = k.temperature_range ? ` (${formatNumber(k.temperature_range[0])}–${formatNumber(k.temperature_range[1])} K)` : "";
    return { kind: "K", text: `ln K = ${terms.join(" + ").replace(/\+ -/g, "− ")}${range}`, provenance: k.provenance, source: k.source };
  }
  const given = r.units.find((u) => u.conversion);
  if (given?.conversion) {
    const provenance: Provenance = "given";
    return { kind: "conversion", text: `X = ${formatNumber(given.conversion.value)} in ${given.unit}`, provenance, source: given.conversion.from };
  }
  if (r.type === "equilibrium") return { kind: "ideal-gas", text: "K from the components' ideal-gas data", provenance: null, source: "" };
  return { kind: null, text: "", provenance: null, source: "" };
}

/** `-91116 kJ/kmol at 298.15 K`. */
export function heatText(h: ReactionHeat | null | undefined): string {
  if (!h) return "";
  return `${formatNumber(h.value)} ${h.unit} at ${formatNumber(h.temperature)} K`;
}

/** How a reactor's outlet stands to equilibrium, from ln(Q/K): at it (|ln(Q/K)| < 0.01), short of it, or beyond. */
export function approachOf(lnQK: number | null | undefined): { text: string; tone: "pass" | "warning" | "error" | "" } {
  if (lnQK === null || lnQK === undefined) return { text: "", tone: "" };
  if (Math.abs(lnQK) < 0.01) return { text: "at equilibrium", tone: "pass" };
  if (lnQK < 0) return { text: "short of equilibrium", tone: "warning" };
  return { text: "beyond equilibrium", tone: "error" };
}

/** ln(Q/K) for the table: small values in exponent form. */
export function lnText(v: number | null | undefined): string {
  if (v === null || v === undefined) return "";
  return Math.abs(v) > 0 && Math.abs(v) < 1e-3 ? v.toExponential(2) : formatNumber(Number(v.toFixed(4)));
}

/** Tag -> sheet of an equipment list (`/api/yaml` data of `equipment/equipment-list.yaml`). */
export function equipmentSheets(data: unknown): Map<string, string> {
  const out = new Map<string, string>();
  const items = isRecord(data) ? data.equipment : undefined;
  if (!Array.isArray(items)) return out;
  for (const item of items) {
    if (!isRecord(item)) continue;
    const { tag, sheet } = item;
    if (typeof tag === "string" && typeof sheet === "string") out.set(tag, sheet);
  }
  return out;
}

/**
 * The P&ID a reactor node is drawn on and what to select there: its first link naming a sheet
 * (equipment, instrument, line; a sheet link opens the sheet), or a linked or own tag whose
 * equipment-list entry names one. Null when nothing says.
 */
export function nodePidLink(
  node: string,
  nodes: readonly Pick<ProcessNode, "id" | "links">[],
  sheets: readonly Sheet[],
  tagSheets: ReadonlyMap<string, string> = new Map(),
): { file: string; select: string | null } | null {
  const links = nodes.find((n) => n.id === node)?.links ?? [];
  for (const link of links) {
    if (link.target === "sheet") {
      const file = sheetFile(link.ref, sheets);
      if (file) return { file, select: null };
      continue;
    }
    const file = sheetFile(link.sheet ?? tagSheets.get(link.ref), sheets);
    if (file) return { file, select: link.ref };
  }
  const own = sheetFile(tagSheets.get(node), sheets);
  return own ? { file: own, select: node } : null;
}

// -- kinetics -------------------------------------------------------------------------------

/** `kinetics` of a response, empty when an older core serves null. */
export function kineticsOf(view: Pick<ReactionsView, "kinetics"> | null | undefined): ReactionsKinetics {
  return view?.kinetics ?? { file: null, catalysts: [], findings: [] };
}

/** `power law, per kg of catalyst, on partial pressures (bar)`. */
export function rateFormText(law: Pick<RateLaw, "form" | "basis" | "driving">): string {
  const form = law.form === "lhhw" ? "LHHW" : "power law";
  const basis = law.basis === "catalyst_mass" ? "per kg of catalyst" : "per m³ of reactor";
  const driving = law.driving === "partial_pressure" ? "on partial pressures (bar)" : "on concentrations (kmol/m³)";
  return `${form}, ${basis}, ${driving}`;
}

/** `CO 1, CO2 -0.36, H2 -0.09`. */
export function ordersText(orders: Record<string, number>): string {
  return Object.entries(orders)
    .map(([n, a]) => `${n} ${formatNumber(a)}`)
    .join(", ");
}

/** The Arrhenius parameters: `A 1000 kmol/(kg s) / bar^0.55, Ea 111000 kJ/kmol` (n and T_ref only when set). */
export function arrheniusText(k: RateLaw["k"], unit = ""): string {
  const parts = [`A ${formatNumber(k.A)}${unit ? ` ${unit}` : ""}`, `Ea ${formatNumber(k.Ea)} kJ/kmol`];
  if (k.n) parts.push(`n ${formatNumber(k.n)}`);
  if (k.n && k.T_ref !== 1) parts.push(`T_ref ${formatNumber(k.T_ref)} K`);
  return parts.join(", ");
}

/** `573.15–773.15 K`. */
export function rangeText(range: [number, number] | null | undefined, unit: string): string {
  return range ? `${formatNumber(range[0])}–${formatNumber(range[1])} ${unit}` : "";
}

/** The catalyst a reaction names (its rate's, else its own) and its entry of `process/catalysts.yaml`, if declared. */
export function catalystOf(r: Pick<Reaction, "catalyst" | "rate">, catalysts: readonly CatalystEntry[]): { id: string; entry: CatalystEntry | null } | null {
  const id = r.rate?.catalyst || r.catalyst;
  if (!id) return null;
  return { id, entry: catalysts.find((c) => c.id === id) ?? null };
}

/** The element id of a catalyst's card (and of a reaction's row) on the page. */
export const catalystAnchor = (id: string) => `catalyst-${id}`;
export const reactionAnchor = (id: string) => `reaction-${id}`;

export interface ChartGeometry {
  /** SVG path of the line, inside `width` x `height`. */
  d: string;
  x: [number, number];
  y: [number, number];
  /** y on a log scale (all values positive). */
  log: boolean;
}

/**
 * A line through *points* scaled into `width` x `height` (y up), on a log y scale when asked and
 * every y is positive. Null with fewer than two points or no finite range of x.
 */
export function chartGeometry(points: readonly [number, number][], width: number, height: number, log = false): ChartGeometry | null {
  const finite = points.filter(([x, y]) => Number.isFinite(x) && Number.isFinite(y));
  if (finite.length < 2) return null;
  const useLog = log && finite.every(([, y]) => y > 0);
  const ys = finite.map(([, y]) => (useLog ? Math.log10(y) : y));
  const xs = finite.map(([x]) => x);
  const [x0, x1] = [Math.min(...xs), Math.max(...xs)];
  const [y0, y1] = [Math.min(...ys), Math.max(...ys)];
  if (x1 === x0) return null;
  const span = y1 - y0 || Math.abs(y0) || 1;
  const lo = y1 === y0 ? y0 - span / 2 : y0;
  const d = finite
    .map(([x], i) => {
      const px = ((x - x0) / (x1 - x0)) * width;
      const py = height - ((ys[i]! - lo) / (y1 === y0 ? span : y1 - y0)) * height;
      return `${i ? "L" : "M"}${px.toFixed(1)},${py.toFixed(1)}`;
    })
    .join(" ");
  const back = (v: number) => (useLog ? 10 ** v : v);
  return { d, x: [x0, x1], y: [back(y0), back(y1)], log: useLog };
}
