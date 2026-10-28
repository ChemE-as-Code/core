/**
 * The simulation of `GET /api/simulation` (core: `domains/process/simulation/record.py`): the
 * spec of `process/simulation.yaml`, the run `cheme process simulate --fill` recorded in
 * `process/simulation-run.json` and the stream values that run filled into the flowsheet.
 */
import type { Provenance, SimRunUnit, SimSpecQuantity, SimStreamValue, SimUnitStatus, SimulationView } from "@/api";
import { formatNumber } from "./process";
import { isRecord } from "./guards";

export const SIMULATION_FILE = "process/simulation.yaml";
export const RUN_FILE = "process/simulation-run.json";

/** What the recorded run says: converged, did not converge, or no run recorded for the case. */
export type RunState = "converged" | "failed" | "not-run";

export function runState(view: Pick<SimulationView, "run">): RunState {
  if (!view.run) return "not-run";
  return view.run.converged ? "converged" : "failed";
}

export const RUN_BADGE: Record<RunState, { badge: string; label: string; title: string }> = {
  converged: { badge: "pass", label: "converged", title: "The recorded run converged" },
  failed: { badge: "fail", label: "not converged", title: "The recorded run did not converge: no stream value was written" },
  "not-run": { badge: "", label: "not run", title: "No run recorded for this case" },
};

export const UNIT_STATUS: Record<SimUnitStatus, { badge: string; title: string }> = {
  simulated: { badge: "pass", title: "In the simulator model" },
  excluded: { badge: "info", title: "Left out of the simulation (exclude:); its streams stay as the flowsheet gives them" },
  refused: { badge: "error", title: "The simulator model refuses it: see the reason" },
  "not-simulated": { badge: "warning", title: "Not in the simulator model" },
  unknown: { badge: "", title: "The flowsheet does not load: the status is the recorded run's" },
};

/** How the recorded run left a unit: converged, failed, unknown (a run that did not converge without naming it), or not in the run. */
export function unitConvergence(run: SimRunUnit | null | undefined): "converged" | "failed" | "unknown" | null {
  if (!run || run.status !== "simulated") return null;
  if (run.converged === true) return "converged";
  if (run.converged === false) return "failed";
  return "unknown";
}

export function isQuantity(value: unknown): value is SimSpecQuantity {
  return typeof value === "object" && value !== null && "value" in value && typeof value.value === "number" && "provenance" in value;
}

/** One value of a unit's spec, flattened: `side_draws.lin.flow` = `470` (assumed, with its source). */
export interface SpecEntry {
  key: string;
  text: string;
  provenance: Provenance | null;
  source: string;
}

/**
 * A unit's spec as rows: a quantity with its unit (none: the flowsheet's) and provenance, a plain
 * value as text, a list joined, a nested map (`side_draws`, `condenser_spec`, `split`) by its
 * dotted keys.
 */
export function specEntries(spec: Record<string, unknown> | null | undefined, prefix = ""): SpecEntry[] {
  const out: SpecEntry[] = [];
  for (const [name, value] of Object.entries(spec ?? {})) {
    const key = prefix ? `${prefix}.${name}` : name;
    if (isQuantity(value)) {
      out.push({ key, text: `${formatNumber(value.value)}${value.unit ? ` ${value.unit}` : ""}`, provenance: value.provenance, source: value.source ?? "" });
    } else if (Array.isArray(value)) {
      out.push({ key, text: value.map((v) => (typeof v === "number" ? formatNumber(v) : String(v))).join(", "), provenance: null, source: "" });
    } else if (isRecord(value)) {
      out.push(...specEntries(value, key));
    } else {
      out.push({ key, text: typeof value === "number" ? formatNumber(value) : String(value), provenance: null, source: "" });
    }
  }
  return out;
}

/** The units core's result keys carry (`duty_kW`, `temperature_K`, `pressure_kPa`, `flow_kg_h`). */
const RESULT_UNITS: [string, string][] = [
  ["_kmol_h", "kmol/h"],
  ["_kg_h", "kg/h"],
  ["_m3_h", "m³/h"],
  ["_kPa", "kPa"],
  ["_kW", "kW"],
  ["_K", "K"],
];

/** A unit's results as label, number and unit: `duty_kW: 84.2` -> `duty`, `84.2`, `kW`. */
export function resultEntries(results: Record<string, number> | null | undefined): { key: string; label: string; text: string; unit: string }[] {
  return Object.entries(results ?? {}).map(([key, value]) => {
    const found = RESULT_UNITS.find(([suffix]) => key.endsWith(suffix));
    const label = (found ? key.slice(0, -found[0].length) : key).replace(/_/g, " ");
    return { key, label, text: typeof value === "number" ? formatNumber(value) : String(value), unit: found?.[1] ?? "" };
  });
}

/** `598 K`, or `mol: N2 0.7812, O2 0.2096` for a composition. */
export function formatSimValue(value: SimStreamValue | undefined): string {
  if (!value) return "";
  if ("basis" in value) {
    const basis = value.basis === "mole_fraction" ? "mol" : value.basis === "mass_fraction" ? "mass" : value.basis;
    return `${basis}: ${Object.entries(value.values)
      .map(([k, v]) => `${k} ${formatNumber(v)}`)
      .join(", ")}`;
  }
  return `${formatNumber(value.value)} ${value.unit}`.trim();
}

/**
 * Stream id -> the fields the recorded run filled (the flowsheet holds the simulated value), for
 * the stream table of `tableCase`; empty when there is no run or it is of another case.
 */
export function filledFields(view: Pick<SimulationView, "run"> | null | undefined, tableCase: string | null | undefined): Map<string, Set<string>> {
  const out = new Map<string, Set<string>>();
  const run = view?.run;
  if (!run || (tableCase && run.case !== tableCase)) return out;
  for (const stream of run.streams) if (stream.filled.length) out.set(stream.id, new Set(stream.filled));
  return out;
}

/** `2026-10-23 12:57 UTC` from the record's `run_at`. */
export function runTime(iso: string): string {
  const m = /^(\d{4}-\d{2}-\d{2})T(\d{2}:\d{2})/.exec(iso);
  return m ? `${m[1]} ${m[2]} UTC` : iso;
}
