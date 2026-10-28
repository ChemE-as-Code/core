/**
 * The LCI readiness of the plant's dataset (pre-release viewer issue 36): how far `lca/dataset.yaml` is from
 * publishable quality, from what core reports. Nothing is calculated here: the balance, the data
 * quality rating, the water and the findings are core's (`/api/lca`, `cheme assess lca --json`);
 * these helpers only pick and group them for the page, and read the pedigree scores core wrote
 * into the dataset.
 */
import type { Finding, LcaBalance, LcaReport } from "@/api";
import { isRecord } from "./guards";

/** The plant's LCI dataset, as `cheme assess lca --write` writes it (core `DATASET_FILE`). */
export const DATASET_FILE = "lca/dataset.yaml";

/** The balance gates of pre-release issue 174, in the order core reports them. */
export const BALANCE_REQUIREMENTS: { id: string; label: string }[] = [
  { id: "lci-mass-balance", label: "mass" },
  { id: "lci-element-balance", label: "elements" },
  { id: "lci-carbon-origin", label: "carbon by origin" },
];

export type ReadinessTopic = "balance" | "documentation" | "emissions" | "consumables";

/** Which findings belong to which part of the readiness, by core's rule ids. */
const TOPIC_RULES: Record<ReadinessTopic, (rule: string) => boolean> = {
  // pre-release issue 174
  balance: (r) => ["cheme.lci-mass-balance", "cheme.lci-element-balance", "cheme.lci-carbon-origin", "cheme.lci-balance-unassessable"].includes(r),
  // pre-release issue 179 (the publication minimum), pre-release issue 175 (flow identities), the dataset's location
  documentation: (r) => ["cheme.lca-dataset-undocumented", "cheme.lca-dataset-v1", "cheme.lca-flow-identity", "cheme.lca-flow-uuid", "cheme.lca-unchecked"].includes(r),
  // pre-release issue 176
  emissions: (r) => r === "cheme.lci-emissions-incomplete",
  // pre-release issue 180: consumables without a disposal route, the cut-off criteria
  consumables: (r) => r === "cheme.lca-disposal" || r === "cheme.lca-disposal-fraction" || r.startsWith("cheme.lca-cutoff-"),
};

export const TOPIC_TITLES: Record<ReadinessTopic, string> = {
  balance: "Balance",
  documentation: "Documentation",
  emissions: "Emission sources without an estimate",
  consumables: "Consumables and cut-off",
};

/** The topic of a finding, or null when it is not about the dataset's readiness. */
export function topicOf(finding: Finding): ReadinessTopic | null {
  for (const [topic, test] of Object.entries(TOPIC_RULES) as [ReadinessTopic, (r: string) => boolean][]) {
    if (test(finding.rule)) return topic;
  }
  return null;
}

/** The readiness findings per topic, in core's order within each. */
export function readinessFindings(report: LcaReport): Record<ReadinessTopic, Finding[]> {
  const out: Record<ReadinessTopic, Finding[]> = { balance: [], documentation: [], emissions: [], consumables: [] };
  for (const f of report.findings ?? []) {
    const topic = topicOf(f);
    if (topic) out[topic].push(f);
  }
  return out;
}

/**
 * Whether the server reports the dataset's readiness at all: a core with the data quality
 * rating (pre-release issue 178), the water (pre-release issue 175) or the balance (pre-release issue 174). An older server leaves
 * every one of these keys out; the section is then hidden, not shown empty.
 */
export function hasReadiness(report: LcaReport | null | undefined): boolean {
  if (!report) return false;
  return report.data_quality !== undefined || report.water !== undefined || report.balance !== undefined;
}

/** The publication-minimum fields the dataset lacks: the ids of core's `cheme.lca-dataset-undocumented`. */
export function missingMetadata(report: LcaReport): { fields: string[]; finding: Finding | null } {
  const finding = (report.findings ?? []).find((f) => f.rule === "cheme.lca-dataset-undocumented") ?? null;
  return { fields: finding?.ids ?? [], finding };
}

/** `closed`, `open`, `not-assessable` or `unknown` (not reported) for one balance requirement. */
export function balanceState(balance: LcaBalance | null | undefined, requirement: string): string {
  return balance?.status?.[requirement] ?? "unknown";
}

/** The badge class of a balance state. */
export function stateClass(state: string): string {
  return state === "closed" ? "pass" : state === "open" ? "warning" : "info";
}

/** A balance state for the page. */
export function stateText(state: string): string {
  return state === "not-assessable" ? "not assessable" : state === "unknown" ? "not assessed" : state;
}

/** A relative residual for the page, e.g. `+0.37 %` (core gives the fraction). */
export function relativeText(relative: number): string {
  return `${relative > 0 ? "+" : ""}${(relative * 100).toFixed(2)} %`;
}

/** The pedigree indicators in the order of `pedigree.scores` (core `Pedigree`). */
export const PEDIGREE_INDICATORS = ["reliability", "completeness", "temporal", "geographical", "technological"];

/** A pedigree score of 4 or 5 (of 1 best .. 5 worst): highlighted as weak. */
export function weakScore(score: number): boolean {
  return score >= 4;
}

/** One exchange of `lca/dataset.yaml` with the pedigree core gave it. */
export interface PedigreeRow {
  key: string;
  title: string;
  type: string;
  scores: number[];
  /** The default rule that gave them, or the reason they were set by hand. */
  basis: string;
  /** Its line in `lca/dataset.yaml` (1-based), or null when not found. */
  line: number | null;
}

/**
 * The line (1-based) of each `- key: <key>` in the dataset's text: its exchanges and its cut-off
 * flows (core writes `cutoff:` before `exchanges:`; keys are distinct, the first one wins).
 */
export function exchangeLines(text: string | null | undefined): Map<string, number> {
  const out = new Map<string, number>();
  if (!text) return out;
  text.split("\n").forEach((line, index) => {
    const m = /^\s*-\s+key:\s*(?:'([^']*)'|"([^"]*)"|(\S.*?))\s*$/.exec(line);
    const key = m ? (m[1] ?? m[2] ?? m[3]) : undefined;
    if (key && !out.has(key)) out.set(key, index + 1);
  });
  return out;
}

/** The exchanges of the dataset (`/api/yaml` data) that carry a pedigree, in file order, with their *lines* (`exchangeLines`). */
export function pedigreeRows(dataset: unknown, lines: Map<string, number> = new Map()): PedigreeRow[] {
  const exchanges = isRecord(dataset) ? dataset.exchanges : undefined;
  if (!Array.isArray(exchanges)) return [];
  const out: PedigreeRow[] = [];
  for (const e of exchanges) {
    if (!isRecord(e)) continue;
    const pedigree = isRecord(e.pedigree) ? e.pedigree : undefined;
    const scores = pedigree?.scores;
    if (!Array.isArray(scores) || scores.length !== 5 || !scores.every((s): s is number => typeof s === "number")) continue;
    const key = String(e.key ?? "");
    out.push({
      key,
      title: String(e.title ?? ""),
      type: String(e.type ?? ""),
      scores,
      basis: String(pedigree?.reason || pedigree?.rule || ""),
      line: lines.get(key) ?? null,
    });
  }
  return out;
}
