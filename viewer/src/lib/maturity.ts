// Evidence-based calculation maturity (core's `cheme maturity`, schema cheme/maturity-report/v1;
// docs/framework/maturity.md) and how the viewer presents it beside the declared project phase.
//
// Nothing is scored here: the levels, their requirements and the reached level are core's. This
// module names them, maps core's statuses onto the states the viewer (and the Process Atlas)
// show, and decides whether a report may be shown as the maturity of the revision on screen:
// a live `GET /api/maturity` of the working tree is; a recorded `checks/maturity.json` is only
// when the input fingerprints it recorded match that revision's files.

import type { MaturityLevel, MaturityReport, MaturityRequirement } from "@/api";

export const REPORT_SCHEMA = "cheme/maturity-report/v1";
/** Where `cheme maturity --write` records the report. */
export const MATURITY_FILE = "checks/maturity.json";

/** The four cumulative levels, lowest first, with the short names both viewer and Atlas show. */
export const LEVELS = [
  { id: "sourced", name: "Sourced", scope: "Sourced process description" },
  { id: "balanced", name: "Balanced", scope: "Balanced conceptual PFD" },
  { id: "predictive", name: "Predictive", scope: "Converged predictive simulation" },
  {
    id: "engineering",
    name: "Engineering",
    // core's own title; the level never covers detailed engineering
    scope: "Preliminary/basic engineering package (not verified detailed engineering)",
  },
] as const;

/** The short name of a level id (`balanced` -> `Balanced`); an unknown id as it is. */
export function levelName(id: string | null | undefined): string {
  return LEVELS.find((l) => l.id === id)?.name ?? String(id ?? "");
}

/** What a level stands for; for `engineering` it says it is not verified detailed engineering. */
export function levelScope(id: string): string | null {
  return LEVELS.find((l) => l.id === id)?.scope ?? null;
}

/** A level as shown: achieved, not yet achieved, not assessable (blocked by unsupported requirements) or not evaluated. */
export type LevelState = "achieved" | "not-achieved" | "not-assessable" | "not-evaluated";

export const LEVEL_STATE_LABEL: Record<LevelState, string> = {
  achieved: "Achieved",
  "not-achieved": "Not yet achieved",
  "not-assessable": "Not assessable",
  "not-evaluated": "Not evaluated",
};

/** The required requirements of a level that do not pass. */
export function blockers(level: MaturityLevel): MaturityRequirement[] {
  return level.requirements.filter((r) => r.required && r.status !== "pass");
}

/**
 * The state of a level from core's `status` and `reached`. Achieved only when core says it is
 * reached and passes; not assessable when everything blocking it is `unsupported` (core cannot
 * check it, so it is not claimed); a level whose own requirements pass while a lower one does
 * not is not yet achieved.
 */
export function levelState(level: MaturityLevel): LevelState {
  if (level.status === "not-evaluated") return "not-evaluated";
  if (level.reached === true && level.status === "pass") return "achieved";
  const open = blockers(level);
  if (open.length && open.every((r) => r.status === "unsupported")) return "not-assessable";
  return "not-achieved";
}

/** Why a level that is not achieved is not, in one line. */
export function levelReason(level: MaturityLevel, levels: readonly MaturityLevel[]): string {
  const state = levelState(level);
  if (state === "achieved") return "Every required requirement of this level and of the levels below passes.";
  if (state === "not-evaluated") return "Not evaluated by this report.";
  const open = blockers(level);
  if (!open.length) {
    const below = levels.slice(0, levels.indexOf(level)).find((l) => levelState(l) !== "achieved");
    return below
      ? `Its own requirements pass, but ${levelName(below.id)} below it is not achieved (the levels are cumulative).`
      : "Not reached according to the report.";
  }
  const counts = new Map<string, number>();
  for (const r of open) counts.set(r.status, (counts.get(r.status) ?? 0) + 1);
  const parts = [...counts].map(([status, n]) => `${n} ${status}`);
  return `${open.length} required requirement${open.length === 1 ? "" : "s"} not passing: ${parts.join(", ")}.`;
}

/** Text for a requirement status; never colour alone. */
export const REQUIREMENT_LABEL: Record<string, string> = {
  pass: "pass",
  fail: "fail",
  missing: "missing",
  unsupported: "unsupported",
};

/** The CSS badge class of a requirement status: only `pass` looks like a success. */
export function requirementClass(status: string): string {
  return status === "pass" ? "pass" : status === "fail" ? "fail" : status === "missing" ? "warning" : "";
}

/** The report, or why it cannot be read as one (another schema, not an object). */
export function parseReport(data: unknown): { report: MaturityReport } | { incompatible: string } {
  if (!data || typeof data !== "object" || Array.isArray(data)) return { incompatible: "not a maturity report" };
  const schema = (data as { schema?: unknown }).schema;
  if (schema !== REPORT_SCHEMA) return { incompatible: typeof schema === "string" ? schema : "no schema" };
  const report = data as MaturityReport;
  if (!Array.isArray(report.levels) || !report.levels.every((l) => l && typeof l === "object" && Array.isArray(l.requirements)))
    return { incompatible: `${REPORT_SCHEMA} without levels and requirements` };
  const fingerprints = report.source?.fingerprints;
  if (fingerprints != null && (typeof fingerprints !== "object" || Object.values(fingerprints).some((v) => typeof v !== "string")))
    return { incompatible: `${REPORT_SCHEMA} with malformed fingerprints` };
  return { report };
}

// -- recorded reports: do their inputs match the revision shown? ----------------------------------

/** Core's `content_fingerprint`: `sha256:<hex>` of the bytes with CRLF normalised to LF. */
export async function fingerprint(bytes: Uint8Array): Promise<string> {
  const out = new Uint8Array(bytes.length);
  let n = 0;
  for (let i = 0; i < bytes.length; i++) {
    if (bytes[i] === 0x0d && bytes[i + 1] === 0x0a) continue;
    out[n++] = bytes[i]!;
  }
  const digest = await globalThis.crypto.subtle.digest("SHA-256", out.subarray(0, n));
  return `sha256:${[...new Uint8Array(digest)].map((b) => b.toString(16).padStart(2, "0")).join("")}`;
}

export interface InputCheck {
  /** Inputs whose fingerprint matches. */
  matching: string[];
  /** Inputs that differ, or no longer exist. */
  changed: string[];
  /** Inputs that could not be read (too large, not in a snapshot, no Web Crypto): not known either way. */
  unreadable: string[];
}

/**
 * Compare the report's recorded input fingerprints with the files now. `read` gives a file's
 * bytes, null when it does not exist, and throws when it cannot be read.
 */
export async function checkInputs(
  fingerprints: Record<string, string>,
  read: (path: string) => Promise<Uint8Array | null>,
): Promise<InputCheck> {
  const result: InputCheck = { matching: [], changed: [], unreadable: [] };
  const paths = Object.keys(fingerprints).sort();
  await Promise.all(
    paths.map(async (path) => {
      let bytes: Uint8Array | null;
      try {
        bytes = await read(path);
      } catch {
        result.unreadable.push(path);
        return;
      }
      if (bytes === null) {
        result.changed.push(path);
        return;
      }
      let now: string;
      try {
        now = await fingerprint(bytes);
      } catch {
        result.unreadable.push(path); // no Web Crypto (an insecure context)
        return;
      }
      (now === fingerprints[path] ? result.matching : result.changed).push(path);
    }),
  );
  for (const list of [result.matching, result.changed, result.unreadable]) list.sort();
  return result;
}

// -- the state shown -----------------------------------------------------------------------------

/** Where a report comes from. */
export type ReportOrigin =
  /** `GET /api/maturity`: evaluated now on the working tree. */
  | "live"
  /** A static snapshot's `/api/maturity`, evaluated when the snapshot was written. */
  | "snapshot"
  /** `checks/maturity.json` at the revision shown. */
  | "recorded";

/**
 * Whether the report is the maturity of the revision shown: `current` (evaluated on it, or
 * every recorded input matches), `stale` (an input changed since), `unverified` (recorded, but
 * its inputs could not all be compared).
 */
export type Currency = "current" | "stale" | "unverified";

export type MaturityState =
  | { kind: "loading" }
  | { kind: "missing"; message: string }
  | { kind: "incompatible"; schema: string; origin: ReportOrigin }
  | { kind: "error"; message: string }
  | { kind: "report"; report: MaturityReport; origin: ReportOrigin; currency: Currency; inputs: InputCheck | null };

/** A live or snapshot report: evaluated on what is shown. */
export function evaluatedState(data: unknown, origin: "live" | "snapshot"): MaturityState {
  const parsed = parseReport(data);
  if ("incompatible" in parsed) return { kind: "incompatible", schema: parsed.incompatible, origin };
  return { kind: "report", report: parsed.report, origin, currency: "current", inputs: null };
}

/** A recorded report with the comparison of its inputs against the revision shown. */
export function recordedState(data: unknown, inputs: InputCheck | null): MaturityState {
  const parsed = parseReport(data);
  if ("incompatible" in parsed) return { kind: "incompatible", schema: parsed.incompatible, origin: "recorded" };
  const currency: Currency = !inputs
    ? "unverified"
    : inputs.changed.length
      ? "stale"
      : inputs.unreadable.length || !inputs.matching.length
        ? "unverified"
        : "current";
  return { kind: "report", report: parsed.report, origin: "recorded", currency, inputs };
}

/** The header badge: its text, a tone (a badge class) and the tooltip that explains it. */
export interface MaturityBadge {
  text: string;
  value: string;
  tone: "" | "pass" | "warning" | "info";
  title: string;
}

const BADGE_PREFIX = "Verified maturity";
const AXES_NOTE =
  "Evidence-based calculation maturity from core's cheme maturity report. Artifacts, the project phase and review sign-offs never raise it.";

export function maturityBadge(state: MaturityState): MaturityBadge {
  const make = (value: string, tone: MaturityBadge["tone"], why: string): MaturityBadge => ({
    text: `${BADGE_PREFIX}: ${value}`,
    value,
    tone,
    title: `${why} ${AXES_NOTE}`,
  });
  switch (state.kind) {
    case "loading":
      return make("checking…", "", "The maturity report is being evaluated or read.");
    case "missing":
      return make("no report", "", `${state.message}`);
    case "incompatible":
      return make("incompatible report", "warning", `The maturity report has schema ${state.schema}; this viewer reads ${REPORT_SCHEMA}.`);
    case "error":
      return make("unavailable", "warning", `The maturity report could not be loaded: ${state.message}`);
    case "report": {
      const { report, currency } = state;
      if (currency === "stale")
        return make("outdated report", "warning", `${MATURITY_FILE} was recorded for other inputs (changed since: ${state.inputs?.changed.join(", ")}); its level is not shown as current.`);
      if (currency === "unverified")
        return make("unconfirmed", "", `${MATURITY_FILE} is here, but its inputs could not be compared with this revision; its level is not shown as current.`);
      if (!report.level) return make("Not established", "", "No maturity level is reached: not even the lowest level's requirements all pass.");
      if (state.origin === "recorded")
        return make(
          `${levelName(report.level)} (recorded)`,
          "info",
          `${levelName(report.level)} as recorded in ${MATURITY_FILE}; the inputs it fingerprints match this revision, but core fingerprints no datasheets, P&IDs or validation inputs, so it is not a live evaluation.`,
        );
      const partial = report.evaluated_through !== LEVELS[LEVELS.length - 1]!.id && report.level === report.evaluated_through;
      return make(
        levelName(report.level),
        "pass",
        `${levelName(report.level)}: ${levelScope(report.level) ?? report.level} reached${partial ? ` (levels above ${levelName(report.evaluated_through)} not evaluated)` : ""}.`,
      );
    }
  }
}

/** The declared project phase (plant.yaml `stage`): a workflow phase, not evidence. */
export const PHASE_NOTE =
  "The project phase is the workflow stage plant.yaml declares. It is not evidence that the design or engineering has been verified.";
