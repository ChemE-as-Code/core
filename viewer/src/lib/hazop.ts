/**
 * HAZOP studies, `safety/hazop/<id>/study.yaml` (core: `domains/safety/`, schema `hazop-study`).
 * cheme serve has no endpoint for them: the tree names the files and `/api/yaml` reads each one,
 * as committed at the revision, so the page works on a server and on a static snapshot alike.
 */
import { api, type TreeEntry } from "@/api";

export const HAZOP_DIR = "safety/hazop";
const STUDY_FILE = /^safety\/hazop\/([^/]+)\/study\.yaml$/;

/** Study id -> repo path of every study in a `/api/tree` listing, sorted by id. */
export function hazopPaths(tree: readonly TreeEntry[]): Map<string, string> {
  const found: [string, string][] = [];
  for (const e of tree) {
    const m = e.type === "file" ? STUDY_FILE.exec(e.path) : null;
    if (m) found.push([m[1]!, e.path]);
  }
  return new Map(found.sort(([a], [b]) => a.localeCompare(b)));
}

/** A tag as printed, `{tag, sheet}` or `{sheet, object}` (an untagged DEXPI object). */
export type HazopRef = string | { tag?: string; sheet?: string; object?: string };

export interface HazopRating {
  category: string;
  severity?: string;
  likelihood?: string;
  basis?: string;
  status?: string;
  band?: { value?: string } | null;
}

export interface HazopScenario {
  id: string;
  cause?: string;
  consequence?: string;
  refs?: HazopRef[];
  safeguards?: string[];
  actions?: string[];
  modes?: string[];
  status?: string;
  by?: string;
  notes?: string;
  risk?: { initial?: HazopRating[]; residual?: HazopRating[] };
}

export interface HazopDeviation {
  id: string;
  guide_word?: string;
  parameter?: string;
  scenarios?: HazopScenario[];
  notes?: string;
}

export interface HazopNode {
  id: string;
  title?: string;
  design_intent?: string;
  members?: HazopRef[];
  status?: string;
  by?: string;
  notes?: string;
  deviations?: HazopDeviation[];
}

export interface HazopSafeguard {
  id: string;
  title?: string;
  kind?: string;
  interlock?: string;
  refs?: HazopRef[];
  status?: string;
}

export interface HazopAction {
  id: string;
  text?: string;
  owner?: string;
  status?: string;
}

export interface HazopStudy {
  id: string;
  title?: string;
  example?: boolean;
  scope?: string;
  modes?: { id: string; title?: string }[];
  analysed?: { path: string; revision?: string }[];
  risk_matrix?: string;
  assessment_basis?: string;
  team?: { name?: string; role?: string }[];
  nodes?: HazopNode[];
  safeguards?: HazopSafeguard[];
  actions?: HazopAction[];
}

export interface HazopEntry {
  id: string;
  path: string;
  study: HazopStudy | null;
  error: string | null;
}

/** A parsed study; a file that is not a mapping with an id is refused (the page shows why). */
export function parseStudy(data: unknown, id: string): HazopStudy {
  if (!data || typeof data !== "object" || Array.isArray(data)) throw new Error(`${id}: not a HAZOP study (no mapping)`);
  const study = data as HazopStudy;
  return { ...study, id: study.id ?? id };
}

/** Every study of the tree; one that fails to read keeps its error, the others load. */
export async function loadStudies(rev: string | null | undefined, signal?: AbortSignal): Promise<HazopEntry[]> {
  const paths = hazopPaths(await api.tree(rev, signal));
  return Promise.all(
    [...paths].map(async ([id, path]): Promise<HazopEntry> => {
      try {
        return { id, path, study: parseStudy((await api.yaml(path, rev, signal)).data, id), error: null };
      } catch (error) {
        if (error instanceof DOMException && error.name === "AbortError") throw error;
        return { id, path, study: null, error: error instanceof Error ? error.message : String(error) };
      }
    }),
  );
}

/** How a reference reads: the tag, else `sheet:object`. */
export function refLabel(ref: HazopRef): string {
  if (typeof ref === "string") return ref;
  return ref.tag ?? [ref.sheet, ref.object].filter(Boolean).join(":");
}

/** One worksheet row: a scenario under its deviation (a deviation without scenarios is one empty row). */
export interface WorksheetRow {
  deviation: HazopDeviation;
  scenario: HazopScenario | null;
  /** First row of its deviation, and how many rows it spans. */
  first: boolean;
  span: number;
}

export function worksheetRows(node: HazopNode): WorksheetRow[] {
  return (node.deviations ?? []).flatMap((deviation): WorksheetRow[] => {
    const scenarios = deviation.scenarios ?? [];
    if (!scenarios.length) return [{ deviation, scenario: null, first: true, span: 1 }];
    return scenarios.map((scenario, i) => ({ deviation, scenario, first: i === 0, span: scenarios.length }));
  });
}

/** Counts for the study's summary cards: scenarios, and entries still proposed (not accepted by the team). */
export function studyTotals(study: HazopStudy): { nodes: number; scenarios: number; proposed: number; openActions: number } {
  const nodes = study.nodes ?? [];
  const scenarios = nodes.flatMap((n) => (n.deviations ?? []).flatMap((d) => d.scenarios ?? []));
  const entries = [...nodes, ...scenarios, ...(study.safeguards ?? [])];
  return {
    nodes: nodes.length,
    scenarios: scenarios.length,
    // The schema's default status is `proposed`.
    proposed: entries.filter((e) => (e.status ?? "proposed") === "proposed").length,
    openActions: (study.actions ?? []).filter((a) => a.status !== "closed" && a.status !== "rejected").length,
  };
}
