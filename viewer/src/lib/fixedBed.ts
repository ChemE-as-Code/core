/**
 * The fixed beds of `GET /api/reactions`: each `reactor: pfr` row of `cheme process
 * reactors` with the bed core solved (core: `domains/process/fixed_bed.py`, `reactors.reactor_entry`:
 * catalyst mass, outlet, `hot_spot_K` and the temperature and pressure along the catalyst mass)
 * or why it could not, the bed as the flowsheet declares it (calculation mode, coolant) and its
 * catalyst's temperature window from `kinetics`, and the bed's row of a recorded simulation run
 * (`process/simulation-run.json`, `GET /api/simulation`).
 *
 * Everything shown is core's. The viewer finds no extremum, interpolates nothing and judges no
 * limit: where the peak lies is only said when core's `hot_spot_K` is exactly one of the sampled
 * points (the inlet, the outlet or a point between); otherwise it lies between sampled points and
 * core does not say where.
 */
import type { CatalystEntry, ReactionsKinetics, ReactorBed, ReactorRow, SimulationView } from "@/api";

/** How core's `missing` names why a bed could not be solved (`the bed: <BedError>`). */
export const BED_FAILURE_PREFIX = "the bed: ";

export interface BedEntry {
  node: string;
  row: ReactorRow;
  /** Core's solved bed; null when it could not be solved. */
  bed: ReactorBed | null;
  /** Why core could not solve it (its `missing` about the bed, without the prefix); empty when solved. */
  failure: string[];
}

/**
 * The fixed beds among the reactors: every row with a solved bed and every `reactor: pfr` row
 * whose bed core could not solve. Rows of a core before beds (no `bed` key) and reactors of the
 * other models give none: they have no profile to show.
 */
export function fixedBeds(reactors: readonly ReactorRow[]): BedEntry[] {
  return reactors
    .filter((r) => r.bed || (r.model === "pfr" && "bed" in r))
    .map((row) => ({
      node: row.node,
      row,
      bed: row.bed ?? null,
      failure: row.bed ? [] : row.missing.filter((m) => m.startsWith(BED_FAILURE_PREFIX)).map((m) => m.slice(BED_FAILURE_PREFIX.length)),
    }));
}

/** The bed of a block or step as the flowsheet declares it (`kinetics.catalysts[].units[].bed`), with the catalyst it holds. */
export interface DeclaredBed {
  bed: Record<string, unknown> & { provenance?: string; source?: string };
  catalyst: CatalystEntry;
}

export function declaredBed(node: string, kinetics: ReactionsKinetics | null | undefined): DeclaredBed | null {
  for (const catalyst of kinetics?.catalysts ?? []) {
    const unit = catalyst.units.find((u) => u.unit === node && u.bed);
    if (unit) return { bed: unit.bed!, catalyst };
  }
  return null;
}

const numberOf = (v: unknown): number | null => (typeof v === "number" && Number.isFinite(v) ? v : null);

/** The calculation mode as declared (`adiabatic`, `isothermal`, `cooled`), null when the server does not say (no `kinetics`). */
export function bedMode(declared: DeclaredBed | null): string | null {
  return typeof declared?.bed.heat === "string" ? declared.bed.heat : null;
}

/**
 * A temperature drawn as a reference line on the bed's temperature profile. They are not
 * interchangeable: the coolant temperature is a boundary condition of a cooled bed, the catalyst
 * window is operating-range guidance. Neither is an engineering maximum allowable temperature,
 * which core does not serve with the bed: no reference line is a limit, and none is judged.
 */
export interface TemperatureReference {
  kind: "coolant" | "catalyst-max" | "catalyst-min";
  value_K: number;
  label: string;
  /** What the value is and where it is declared. */
  basis: string;
  provenance: string | null;
  source: string | null;
}

export function temperatureReferences(declared: DeclaredBed | null): TemperatureReference[] {
  if (!declared) return [];
  const out: TemperatureReference[] = [];
  const coolant = numberOf(declared.bed.coolant_temperature);
  if (bedMode(declared) === "cooled" && coolant !== null) {
    out.push({
      kind: "coolant",
      value_K: coolant,
      label: "Coolant",
      basis: "the cooled bed's boundary condition (process/flowsheet.yaml bed.coolant_temperature), not a limit",
      provenance: declared.bed.provenance ?? null,
      source: declared.bed.source || null,
    });
  }
  const window = declared.catalyst.window;
  if (window?.temperature) {
    const [lo, hi] = window.temperature;
    const basis = `operating-range guidance of catalyst ${declared.catalyst.id} (process/catalysts.yaml window.temperature), not an engineering maximum allowable temperature`;
    out.push({ kind: "catalyst-max", value_K: hi, label: "Catalyst window, upper", basis, provenance: window.provenance, source: window.source || null });
    out.push({ kind: "catalyst-min", value_K: lo, label: "Catalyst window, lower", basis, provenance: window.provenance, source: window.source || null });
  }
  return out;
}

/**
 * Which sampled points have core's peak value (`hot_spot_K`, the highest temperature over every integration step) is among
 * the sampled points of the profile, by exact equality: the solver keeps the very values it
 * samples, so an equal point is the peak itself. `between`: equal to no sampled point, so it lies
 * between two of them inside the bed (the inlet and the outlet are sampled) and core does not
 * report where. `uniform`: every sampled point has the peak temperature.
 */
export interface PeakPlace {
  uniform: boolean;
  inlet: boolean;
  outlet: boolean;
  /** Catalyst masses (kg) of the sampled points inside the bed at the peak temperature. */
  interior: number[];
  between: boolean;
}

export function peakPlace(bed: Pick<ReactorBed, "hot_spot_K" | "profile">): PeakPlace | null {
  const points = bed.profile;
  if (!points.length) return null;
  const hot = bed.hot_spot_K;
  const at = points.map((p, i) => (p.temperature_K === hot ? i : -1)).filter((i) => i >= 0);
  const last = points.length - 1;
  return {
    uniform: at.length === points.length,
    inlet: at.includes(0),
    outlet: at.includes(last),
    interior: at.filter((i) => i !== 0 && i !== last).map((i) => points[i]!.catalyst_mass_kg),
    between: at.length === 0,
  };
}

/** Whether every sampled point has the inlet's value: a profile with nothing to draw (an isothermal bed, a bed without pressure drop). */
export function isConstant(bed: Pick<ReactorBed, "profile">, of: "temperature_K" | "pressure_kPa"): boolean {
  const points = bed.profile;
  return points.length > 0 && points.every((p) => p[of] === points[0]![of]);
}

/** The profile as CSV, every value as core gives it. */
export function profileCsv(bed: Pick<ReactorBed, "profile">): string {
  const rows = bed.profile.map((p) => [p.catalyst_mass_kg, p.temperature_K, p.pressure_kPa].map(String).join(","));
  return ["catalyst_mass_kg,temperature_K,pressure_kPa", ...rows].join("\n") + "\n";
}

/** A bed's row of the recorded simulation run (a kinetic reactor coupled as an external unit). */
export interface BedRunRecord {
  /** `failed`: the run (or its outer loop around the bed) did not converge, no converged bed result; `stale`: the inputs changed since the run; `unknown`: core cannot tell (`stale: null`). */
  state: "current" | "stale" | "failed" | "unknown";
  /** The inputs changed since the run (also for a failed run). */
  stale: boolean;
  hot_spot_K: number | null;
  pressure_drop_kPa: number | null;
  run_at: string;
  tool: string;
  commit: string | null;
  model_fingerprint: string;
  /** The files changed since the run, when stale. */
  changed: string[];
  /** The outer loop: iterations of how many, converged. */
  loop: { iterations: number | null; max_iterations: number | null; converged: boolean | null } | null;
  messages: string[];
}

export function bedRunRecord(view: SimulationView | null | undefined, node: string): BedRunRecord | null {
  if (!view?.run) return null;
  const run = view.run;
  const unit = run.units.find((u) => u.id === node);
  if (!unit || unit.status !== "simulated") return null;
  const results = unit.results ?? {};
  if (unit.unit !== "kinetic_pfr" && !("hot_spot_K" in results)) return null;
  const loop = unit.outer_loop;
  const failed = !run.converged || unit.converged === false || loop?.converged === false;
  return {
    state: failed ? "failed" : view.stale ? "stale" : view.stale === null ? "unknown" : "current",
    stale: view.stale === true,
    hot_spot_K: numberOf(results.hot_spot_K),
    pressure_drop_kPa: numberOf(results.pressure_drop_kPa),
    run_at: run.run_at,
    tool: run.tool,
    commit: run.inputs.commit,
    model_fingerprint: run.model_fingerprint,
    changed: view.stale ? view.staleness.changed_files : [],
    loop: loop ? { iterations: loop.iterations ?? null, max_iterations: loop.max_iterations ?? null, converged: loop.converged ?? null } : null,
    // the unit's messages are among the run's (core: record.unit_rows): each once
    messages: [...new Set([...(unit.messages ?? []), ...(failed ? run.messages : [])])],
  };
}

export interface ChartScale {
  x: [number, number];
  y: [number, number];
  /** Value -> SVG coordinate inside `width` x `height` (y up). */
  px: (x: number) => number;
  py: (y: number) => number;
  /** SVG path through the points. */
  d: string;
  /** Round values for the y axis inside the range. */
  yTicks: number[];
}

/** 1, 2 or 5 times a power of ten: a tick step giving about *count* ticks over *span*. */
function tickStep(span: number, count: number): number {
  const raw = span / count;
  const power = 10 ** Math.floor(Math.log10(raw));
  const unit = raw / power;
  return (unit >= 5 ? 10 : unit >= 2 ? 5 : unit >= 1 ? 2 : 1) * power;
}

/**
 * Scales *points* into `width` x `height`, y spanning them and the *extra* values (reference
 * lines, the solver's peak) with a margin of 5 %. Null with fewer than two finite points or no
 * range of x.
 */
export function chartScale(points: readonly [number, number][], extra: readonly number[], width: number, height: number): ChartScale | null {
  const finite = points.filter(([x, y]) => Number.isFinite(x) && Number.isFinite(y));
  if (finite.length < 2) return null;
  const xs = finite.map(([x]) => x);
  const ys = [...finite.map(([, y]) => y), ...extra.filter(Number.isFinite)];
  const [x0, x1] = [Math.min(...xs), Math.max(...xs)];
  if (x1 === x0) return null;
  let [y0, y1] = [Math.min(...ys), Math.max(...ys)];
  const pad = (y1 - y0 || Math.abs(y0) || 1) * 0.05;
  [y0, y1] = [y0 - pad, y1 + pad];
  const px = (x: number) => ((x - x0) / (x1 - x0)) * width;
  const py = (y: number) => height - ((y - y0) / (y1 - y0)) * height;
  const d = finite.map(([x, y], i) => `${i ? "L" : "M"}${px(x).toFixed(1)},${py(y).toFixed(1)}`).join(" ");
  const step = tickStep(y1 - y0, 4);
  const yTicks: number[] = [];
  for (let t = Math.ceil(y0 / step) * step; t <= y1; t += step) yTicks.push(Number(t.toPrecision(12)));
  return { x: [x0, x1], y: [y0, y1], px, py, d, yTicks };
}

/** The sampled point nearest to catalyst mass *x* (for the chart's crosshair; not a peak finder). */
export function nearestIndex(points: readonly [number, number][], x: number): number {
  let best = 0;
  points.forEach(([px], i) => {
    if (Math.abs(px - x) < Math.abs(points[best]![0] - x)) best = i;
  });
  return best;
}
