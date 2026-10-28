/**
 * Review records (`reviews/<YYYY-MM-DD>-<topic>.md`) and stage sign-offs, following core's
 * `foundation/reviews.py` and `project/signoff.py`.
 *
 * `GET /api/status` gives the open findings of the working tree. It has no `rev`, a snapshot
 * does not hold it, and it only counts the records. So the viewer also reads the records (through
 * `/api/tree` and `/api/file`, at any revision) for their front matter and status counts. Where
 * the server's list is missing it derives the open findings from the records with the same rules.
 * Records are ordered by date, then name; core puts the commit that added a record between the
 * two, so on equal dates the derived list can differ from the server's.
 */
import type { OpenReviewFinding, PlantStatus, StageSignoff } from "@/api";
import { isRecord } from "./guards";

export const REVIEWS_DIR = "reviews";
/** Severities that block a sign-off while open (core's `BLOCKING`). */
export const BLOCKING = new Set(["critical", "high", "major"]);
/** Display order, most severe first; anything else sorts after. */
export const SEVERITY_ORDER = ["critical", "high", "major", "medium", "minor", "low", "info", "note"];

export type StatusKind = "open" | "closed" | "accepted" | "superseded";

const STATUS: [StatusKind, RegExp][] = [
  ["open", /^open$/i],
  ["closed", /^closed\s+([0-9a-f]{7,40})\b/i],
  ["accepted", /^accepted:\s*\S/i],
  ["superseded", /^superseded\s+by\s+(\S+#\d+)/i],
];
const ID = /^([^\s#|]+)#(\d+)$/;
const DATE = /^(\d{4}-\d{2}-\d{2})/;
const SEPARATOR = /^\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)*\|?$/;

/** `open`, `closed`, `accepted` or `superseded`; null when not in the vocabulary (counted as open). */
export function statusKind(status: string): StatusKind | null {
  const text = status.trim().replace(/^`+|`+$/g, "").trim();
  for (const [kind, pattern] of STATUS) if (pattern.test(text)) return kind;
  return null;
}

/** The commit a `closed <commit>` status names. */
export function closingCommit(status: string): string | null {
  const match = /^closed\s+([0-9a-f]{7,40})\b/i.exec(status.trim().replace(/^`+|`+$/g, "").trim());
  return match?.[1] ?? null;
}

export function isBlocking(severity: string): boolean {
  return BLOCKING.has(severity.toLowerCase());
}

export function severityRank(severity: string): number {
  const i = SEVERITY_ORDER.indexOf(severity.toLowerCase());
  return i < 0 ? SEVERITY_ORDER.length : i;
}

/** The record a finding id names (`2026-10-18-o2-safety#3` -> `2026-10-18-o2-safety`), or null. */
export function idStem(id: string): string | null {
  const match = ID.exec(id);
  return match?.[1] ?? null;
}

/** `reviews/<stem>.md`. */
export function recordPath(stem: string): string {
  return `${REVIEWS_DIR}/${stem}.md`;
}

export function stemOf(path: string): string {
  return (path.split("/").pop() ?? path).replace(/\.md$/i, "");
}

/** Is `path` a review record: `reviews/*.md` (not in a subfolder) except README.md. */
export function isRecordPath(path: string): boolean {
  const [dir, name, ...rest] = path.split("/");
  return dir === REVIEWS_DIR && !rest.length && !!name && /\.md$/i.test(name) && name.toLowerCase() !== "readme.md";
}

/** The front matter fields the viewer shows (core's `ReviewRecord`, the scalar ones). */
export interface RecordFront {
  topic?: string;
  reviewed_commit?: string;
  reviewer?: string;
  reviewer_kind?: string;
  approved_by?: string;
  date?: string;
  branch?: string;
}

export interface FindingRow {
  id: string;
  severity: string;
  status: string;
  finding: string;
  /** `findings`, `previous` (## Previous findings) or the heading of another section. */
  section: string;
  line: number;
  record: string;
}

export interface ReviewRecord {
  /** Repo path. */
  path: string;
  stem: string;
  /** Null without front matter (no `kind: review` gate accepts the record). */
  front: RecordFront | null;
  date: string;
  rows: FindingRow[];
}

function unquote(value: string): string {
  const v = value.trim();
  if ((v.startsWith('"') && v.endsWith('"')) || (v.startsWith("'") && v.endsWith("'"))) return v.slice(1, -1);
  return v.replace(/\s+#.*$/, "");
}

/** Top-level scalar `key: value` lines of the front matter; null without front matter. */
function frontMatter(lines: string[]): { front: RecordFront | null; bodyStart: number } {
  if ((lines[0] ?? "").trim() !== "---") return { front: null, bodyStart: 0 };
  let end = -1;
  for (let i = 1; i < lines.length; i++) {
    const t = (lines[i] ?? "").trim();
    if (t === "---" || t === "...") {
      end = i;
      break;
    }
  }
  if (end < 0) return { front: null, bodyStart: 0 };
  const front: Record<string, string> = {};
  for (const line of lines.slice(1, end)) {
    const match = /^([A-Za-z_][\w-]*):\s*(.*)$/.exec(line);
    const [, key, value] = match ?? [];
    if (!key || !value || /^[[{|>]/.test(value)) continue;
    front[key] = unquote(value);
  }
  const keys: (keyof RecordFront)[] = ["topic", "reviewed_commit", "reviewer", "reviewer_kind", "approved_by", "date", "branch"];
  const out: RecordFront = {};
  for (const key of keys) {
    const value = front[key];
    if (value) out[key] = value;
  }
  return { front: out, bodyStart: end + 1 };
}

function cells(line: string): string[] {
  let body = line.trim();
  if (body.startsWith("|")) body = body.slice(1);
  if (body.endsWith("|")) body = body.slice(0, -1);
  return body.split(/(?<!\\)\|/).map((c) => c.trim());
}

const stripMarks = (s: string) => s.replace(/^[*_ ]+|[*_ ]+$/g, "");

/** Parse one record: front matter and every table with an `id` and a `status` column. */
export function parseRecord(path: string, text: string): ReviewRecord {
  const stem = stemOf(path);
  const lines = text.split(/\r?\n/);
  const { front, bodyStart } = frontMatter(lines);
  const rows: FindingRow[] = [];
  let section = "";
  let i = bodyStart;
  while (i < lines.length) {
    const line = lines[i] ?? "";
    const heading = /^#{2,6}\s+(.*?)\s*#*\s*$/.exec(line);
    if (heading) {
      section = (heading[1] ?? "").trim();
      i++;
      continue;
    }
    if (line.trimStart().startsWith("|") && SEPARATOR.test((lines[i + 1] ?? "").trim())) {
      const header = cells(line).map((h) => stripMarks(h.toLowerCase()));
      i += 2;
      const body: [number, string[]][] = [];
      while ((lines[i] ?? "").trimStart().startsWith("|")) {
        body.push([i + 1, cells(lines[i] ?? "")]);
        i++;
      }
      if (!header.includes("id") || !header.includes("status")) continue;
      const lower = section.toLowerCase();
      let kind = lower.startsWith("previous") ? "previous" : "findings";
      if (kind === "findings" && section && !lower.startsWith("finding")) kind = lower;
      for (const [number, values] of body) {
        const row: Record<string, string> = {};
        header.forEach((h, k) => (row[h] = values[k] ?? ""));
        rows.push({
          id: (row.id ?? "").replace(/^`+|`+$/g, ""),
          severity: stripMarks((row.severity ?? "").replace(/`/g, "")).toLowerCase(),
          status: (row.status ?? "").trim(),
          finding: row.finding ?? "",
          section: kind,
          line: number,
          record: path,
        });
      }
      continue;
    }
    i++;
  }
  const date = front?.date ?? DATE.exec(stem)?.[1] ?? "";
  return { path, stem, front, date, rows };
}

/** Oldest first: by date, then path. */
export function sortRecords(records: ReviewRecord[]): ReviewRecord[] {
  return [...records].sort((a, b) => (a.date < b.date ? -1 : a.date > b.date ? 1 : a.path.localeCompare(b.path)));
}

/** Each finding id with the row of the latest record listing it (*records* oldest first). */
export function latestRows(records: ReviewRecord[]): Map<string, FindingRow> {
  const latest = new Map<string, FindingRow>();
  for (const record of records) for (const row of record.rows) if (ID.test(row.id)) latest.set(row.id, row);
  return latest;
}

/** Findings whose latest status is open (or not in the vocabulary), as `/api/status` lists them. */
export function openFindings(records: ReviewRecord[]): OpenReviewFinding[] {
  const out: OpenReviewFinding[] = [];
  for (const row of latestRows(records).values()) {
    const kind = statusKind(row.status);
    if (kind === "open" || kind === null) out.push({ id: row.id, severity: row.severity, record: row.record, finding: row.finding });
  }
  return out;
}

export interface RecordSummary {
  record: ReviewRecord;
  /** Findings this record raised (ids `<its stem>#n`), by their latest status. */
  raised: number;
  open: number;
  closed: number;
  accepted: number;
  superseded: number;
  /** Open findings it raised that block a sign-off. */
  blocking: number;
}

/** Per record (newest first), the findings it raised by their latest status. */
export function summarizeRecords(records: ReviewRecord[], open?: OpenReviewFinding[]): RecordSummary[] {
  const sorted = sortRecords(records);
  const latest = latestRows(sorted);
  const openIds = open ? new Set(open.map((f) => f.id)) : null;
  const byStem = new Map<string, RecordSummary>(
    sorted.map((r) => [r.stem, { record: r, raised: 0, open: 0, closed: 0, accepted: 0, superseded: 0, blocking: 0 }]),
  );
  for (const [id, row] of latest) {
    const summary = byStem.get(idStem(id) ?? "");
    if (!summary) continue;
    summary.raised++;
    const kind = statusKind(row.status);
    const isOpen = openIds ? openIds.has(id) : kind === "open" || kind === null;
    if (isOpen) {
      summary.open++;
      if (isBlocking(row.severity)) summary.blocking++;
    } else if (kind === "closed" || kind === "accepted" || kind === "superseded") summary[kind]++;
  }
  return [...byStem.values()].reverse();
}

export interface RegisterRow extends OpenReviewFinding {
  /** The record that raised it (from the id), when it is in the repository. */
  origin: string | null;
  blocking: boolean;
  /** The commit the listing record reviewed, from its front matter. */
  reviewedCommit: string | null;
}

/** The open findings, most severe first (then by id), with their origin record and reviewed commit. */
export function register(open: OpenReviewFinding[], records: ReviewRecord[]): RegisterRow[] {
  const byPath = new Map(records.map((r) => [r.path, r]));
  const stems = new Set(records.map((r) => r.stem));
  return open
    .map((f) => {
      const stem = idStem(f.id);
      return {
        ...f,
        origin: stem && stems.has(stem) ? recordPath(stem) : null,
        blocking: isBlocking(f.severity),
        reviewedCommit: byPath.get(f.record)?.front?.reviewed_commit ?? null,
      };
    })
    .sort((a, b) => severityRank(a.severity) - severityRank(b.severity) || a.id.localeCompare(b.id, undefined, { numeric: true }));
}

export interface RegisterFilter {
  severity?: string | null;
  /** Repo path of the record that raised the finding. */
  record?: string | null;
}

/** `severity` is a severity, `blocking` (critical, high, major) or empty for all. */
export function filterRegister(rows: RegisterRow[], filter: RegisterFilter): RegisterRow[] {
  return rows.filter((r) => {
    if (filter.severity === "blocking" ? !r.blocking : filter.severity && r.severity !== filter.severity) return false;
    if (filter.record && r.origin !== filter.record) return false;
    return true;
  });
}

/** Count per severity, in display order. */
export function severityCounts(rows: OpenReviewFinding[]): { severity: string; count: number }[] {
  const counts = new Map<string, number>();
  for (const r of rows) counts.set(r.severity, (counts.get(r.severity) ?? 0) + 1);
  return [...counts]
    .sort(([a], [b]) => severityRank(a) - severityRank(b) || a.localeCompare(b))
    .map(([severity, count]) => ({ severity, count }));
}

/** A finding cell as Markdown: table rows use `<br>` for line breaks. */
export function findingMarkdown(cell: string): string {
  return cell
    .replace(/\\\|/g, "|")
    .replace(/<br\s*\/?>\s*/gi, "\n")
    .replace(/\n(?=[-*] |\d+\. )/, "\n\n");
}

/**
 * The sign-offs of a `checks/status.json` text (its `stages`), for a revision or a snapshot
 * without `/api/status`; whether each commit is on the default branch is not known (null).
 */
export function signoffsFromStatusFile(text: string | null): Record<string, StageSignoff> {
  if (!text) return {};
  let data: unknown;
  try {
    data = JSON.parse(text);
  } catch {
    return {};
  }
  const stages = isRecord(data) ? data.stages : undefined;
  if (!isRecord(stages)) return {};
  const out: Record<string, StageSignoff> = {};
  const str = (v: unknown) => (typeof v === "string" && v ? v : null);
  for (const [stage, entry] of Object.entries(stages)) {
    if (!entry || typeof entry !== "object") continue;
    const e = entry as Record<string, unknown>;
    out[stage] = {
      commit: str(e.commit) ?? "",
      date: str(e.date),
      signed_by: str(e.signed_by),
      branch: str(e.branch),
      review: str(e.review),
      reviewer_kind: str(e.reviewer_kind),
      on_default_branch: null,
    };
  }
  return out;
}

/** Whether the header should offer the Reviews page: unknown status (still loading, none) shows it. */
export function hasReviewData(status: PlantStatus | null): boolean {
  if (!status) return true;
  return status.reviews.records > 0 || Object.keys(status.signoffs).length > 0;
}
