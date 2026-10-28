/**
 * The plant's issues of `GET /api/issues` (core: `project/issues.py`, docs/framework/issues.md):
 * their engineering names, grouping by the gate they must be closed before, the filters of the
 * issues page and the "New issue" links with the form's References field filled in.
 */
import type { Issue, IssueStatus, IssuesReport, IssueType } from "@/api";

/** The engineering names of the issue types. */
export const TYPE_LABEL: Record<IssueType, string> = {
  action: "Action item",
  hold: "Engineering hold",
  tq: "Technical query (TQ)",
  change: "Design change",
};

/** The types in the order the page offers them. */
export const ISSUE_TYPES: readonly IssueType[] = ["action", "hold", "tq", "change"];

/** The badge class of a type ("" for the plain badge). */
export function typeTone(type: IssueType | null): "pass" | "warning" | "info" | "" {
  if (type === "action") return "pass";
  if (type === "hold") return "warning";
  if (type === "change") return "info";
  return "";
}

/** How a status reads: `for-verification` as "for verification". */
export function statusLabel(status: IssueStatus): string {
  return status.replace(/-/g, " ");
}

/** How a waiting state reads. */
export function waitingLabel(waiting: Issue["waiting"]): string {
  if (waiting === "input") return "waiting for input";
  if (waiting === "work") return "waiting for other work";
  return "";
}

/** The page's filters; "" means any. `gate: "none"` keeps the issues without a gate. */
export interface IssueFilter {
  type: IssueType | "untyped" | "";
  gate: string;
  discipline: string;
  status: IssueStatus | "";
  /** Show closed issues too. */
  closed: boolean;
}

export const NO_FILTER: IssueFilter = { type: "", gate: "", discipline: "", status: "", closed: false };

/** The issues the filter keeps, in their order. */
export function filterIssues(issues: readonly Issue[], filter: IssueFilter): Issue[] {
  return issues.filter(
    (issue) =>
      (filter.closed || issue.state === "open") &&
      (!filter.type || (filter.type === "untyped" ? issue.type === null : issue.type === filter.type)) &&
      (!filter.gate || (filter.gate === "none" ? issue.gate === null : issue.gate === filter.gate)) &&
      (!filter.discipline || issue.disciplines.includes(filter.discipline)) &&
      (!filter.status || issue.status === filter.status),
  );
}

export interface GateGroup {
  /** The stage id; null for the issues without a gate. */
  gate: string | null;
  issues: Issue[];
}

/**
 * The issues by the gate they must be closed before, in stage order, then gates the plant does
 * not list (a label for an unknown stage), then those without a gate. Empty groups left out.
 */
export function groupByGate(issues: readonly Issue[], stages: readonly string[]): GateGroup[] {
  const extra = [...new Set(issues.map((i) => i.gate).filter((g): g is string => g !== null && !stages.includes(g)))].sort();
  const order: (string | null)[] = [...stages, ...extra, null];
  return order.map((gate) => ({ gate, issues: issues.filter((i) => i.gate === gate) })).filter((g) => g.issues.length > 0);
}

/** The disciplines the issues name, sorted. */
export function disciplinesOf(issues: readonly Issue[]): string[] {
  return [...new Set(issues.flatMap((i) => i.disciplines))].sort();
}

/** The open issues blocking the current stage's gate; null when the plant has no current stage. */
export function blockingCurrent(report: IssuesReport): number[] | null {
  if (!report.stage || !report.stages.includes(report.stage)) return null;
  return report.blocking[report.stage] ?? [];
}

/**
 * The link to a new issue of `type` (the action-item form by default; the template chooser
 * without forms), with the form's References field set to `refs`. Null when there is none.
 */
export function newIssueUrl(report: Pick<IssuesReport, "new"> | null, opts: { type?: IssueType; refs?: string } = {}): string | null {
  if (!report) return null;
  const base = report.new[opts.type ?? "action"] ?? report.new.choose;
  if (!base) return null;
  if (!opts.refs) return base;
  return `${base}${base.includes("?") ? "&" : "?"}refs=${encodeURIComponent(opts.refs)}`;
}

/** The "New ..." buttons: one per form type the report links, or the chooser alone. */
export function newIssueButtons(report: Pick<IssuesReport, "new">): { key: IssueType | "choose"; label: string; url: string }[] {
  const typed = ISSUE_TYPES.flatMap((t) => {
    const url = report.new[t];
    return url ? [{ key: t, label: `New ${TYPE_LABEL[t].toLowerCase().replace("(tq)", "(TQ)")}`, url }] : [];
  });
  if (typed.length) return typed;
  return report.new.choose ? [{ key: "choose", label: "New issue", url: report.new.choose }] : [];
}

/**
 * The tag of a picked P&ID object for an issue's references: the tag it was selected by
 * (`?select=`), else its first label that reads as a tag (letters and digits, `P-101`), else an
 * instrument bubble's letters and number joined (`LIA` `4107` -> `LIA-4107`), else its id.
 */
export function objectTag(picked: { id: string; texts: readonly string[] }, selectedBy?: string | null): string {
  if (selectedBy) return selectedBy;
  const tag = picked.texts.find((t) => /[A-Za-z]/.test(t) && /\d/.test(t) && !/\s/.test(t));
  if (tag) return tag;
  const [letters, number] = picked.texts;
  if (letters && number && /^[A-Z]{1,6}$/.test(letters) && /^\d+[A-Z]?$/.test(number)) return `${letters}-${number}`;
  return picked.id;
}
