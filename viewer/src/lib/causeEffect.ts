/**
 * The cause & effect matrix of `GET /api/interlocks` (core: `domains/control/interlocks.py`):
 * where its tags are drawn, the tone of each action, and the changes against another revision.
 */
import type { InterlockAction, InterlockMatrix, InterlockRow, Sheet, TreeEntry } from "@/api";
import { sheetFile } from "./format";

/** The file core reads the interlocks from (`LIST_FILES["interlocks"]`). */
export const INTERLOCKS_FILE = "control/cause-effect.yaml";

/** Whether a `/api/tree` listing has the interlocks file (the C&E page has something to show). */
export function hasInterlocks(tree: readonly TreeEntry[]): boolean {
  return tree.some((e) => e.type === "file" && e.path === INTERLOCKS_FILE);
}

export type ActionTone = "stop" | "start" | "alarm";

/** How an action reads: stopping something (trip, stop, close, depressurize), starting or opening it, or an alarm. */
export function actionTone(action: InterlockAction | (string & {})): ActionTone | null {
  if (!action) return null;
  if (action === "open" || action === "start") return "start";
  if (action === "alarm") return "alarm";
  return "stop";
}

/**
 * The actions of a matrix cell, in order: none for "", several where one interlock has more than
 * one effect on the tag and core joined them with " + " (`close + alarm`). The words are
 * core's {@link InterlockAction}s as the matrix spells them, not checked against that list.
 */
export function cellActions(cell: string): string[] {
  return cell
    .split(" + ")
    .map((a) => a.trim())
    .filter(Boolean);
}

/** Severity of a tone: stopping something over starting it over an alarm. */
const TONE_RANK: Record<ActionTone, number> = { stop: 3, start: 2, alarm: 1 };

/** The tone of a cell: that of its most severe action ({@link TONE_RANK}); null when it has none. */
export function cellTone(cell: string): ActionTone | null {
  let tone: ActionTone | null = null;
  for (const action of cellActions(cell)) {
    const t = actionTone(action);
    if (t && (!tone || TONE_RANK[t] > TONE_RANK[tone])) tone = t;
  }
  return tone;
}

/** Whether two cells do the same: the same set of actions, in whatever order they are listed. */
function sameActions(a: string, b: string): boolean {
  const set = (cell: string) => [...new Set(cellActions(cell))].sort().join(" + ");
  return set(a) === set(b);
}

/**
 * The sheet file each tag of the matrix is drawn on, as far as the list says: a cause on its
 * interlock's sheet, an effect on the sheet of the first interlock acting on it. Tags of an
 * interlock without a (known) sheet are left out.
 */
export function tagSheets(matrix: Pick<InterlockMatrix, "columns" | "rows">, sheets: readonly Sheet[]): Map<string, string> {
  const out = new Map<string, string>();
  for (const row of matrix.rows) {
    const file = sheetFile(row.sheet, sheets);
    if (!file) continue;
    if (!out.has(row.cause)) out.set(row.cause, file);
  }
  matrix.columns.forEach((tag, i) => {
    if (out.has(tag)) return;
    for (const row of matrix.rows) {
      const file = row.cells[i] ? sheetFile(row.sheet, sheets) : null;
      if (file) {
        out.set(tag, file);
        return;
      }
    }
  });
  return out;
}

/** Key of a cell: interlock id and effect tag. */
export const cellKey = (row: string, column: string): string => `${row}\u0000${column}`;

/** The action(s) of each cell that has any, by {@link cellKey}. */
function cellMap(matrix: Pick<InterlockMatrix, "columns" | "rows">): Map<string, string> {
  const out = new Map<string, string>();
  for (const row of matrix.rows)
    matrix.columns.forEach((column, i) => {
      const action = row.cells[i];
      if (action) out.set(cellKey(row.id, column), action);
    });
  return out;
}

const ROW_FIELDS = ["title", "cause", "condition", "sheet", "sil"] as const;
export type RowField = (typeof ROW_FIELDS)[number];

export interface MatrixComparison {
  /** Cells whose set of actions differs: the other revision's cell ("" when it had none), by {@link cellKey}. */
  cells: Map<string, string>;
  /** Interlocks the other revision does not have. */
  addedRows: Set<string>;
  /** Per interlock both have: the fields that differ. */
  changedFields: Map<string, RowField[]>;
  /** Interlocks only the other revision has. */
  removedRows: InterlockRow[];
  /** Actions only the other revision has, on an interlock or effect tag this one lacks (not shown as a cell here). */
  removedCells: { row: string; column: string; action: string }[];
  /** Whether anything differs at all. */
  same: boolean;
}

/** What changed from `other` (the older revision, usually) to `current`. */
export function compareMatrix(current: Pick<InterlockMatrix, "columns" | "rows">, other: Pick<InterlockMatrix, "columns" | "rows">): MatrixComparison {
  const now = cellMap(current);
  const before = cellMap(other);
  const rowsNow = new Map(current.rows.map((r) => [r.id, r]));
  const rowsBefore = new Map(other.rows.map((r) => [r.id, r]));
  const cells = new Map<string, string>();
  for (const row of current.rows)
    for (const column of current.columns) {
      const key = cellKey(row.id, column);
      const a = now.get(key) ?? "";
      const b = before.get(key) ?? "";
      if (!sameActions(a, b)) cells.set(key, b);
    }
  const addedRows = new Set(current.rows.filter((r) => !rowsBefore.has(r.id)).map((r) => r.id));
  const changedFields = new Map<string, RowField[]>();
  for (const row of current.rows) {
    const old = rowsBefore.get(row.id);
    if (!old) continue;
    const fields = ROW_FIELDS.filter((f) => String(row[f] ?? "") !== String(old[f] ?? ""));
    if (fields.length) changedFields.set(row.id, fields);
  }
  const removedRows = other.rows.filter((r) => !rowsNow.has(r.id));
  const columnsNow = new Set(current.columns);
  const removedCells: MatrixComparison["removedCells"] = [];
  for (const row of other.rows) {
    if (!rowsNow.has(row.id)) continue; // listed with its interlock
    other.columns.forEach((column, i) => {
      const action = row.cells[i];
      if (action && !columnsNow.has(column)) removedCells.push({ row: row.id, column, action });
    });
  }
  const same = !cells.size && !addedRows.size && !changedFields.size && !removedRows.length && !removedCells.length;
  return { cells, addedRows, changedFields, removedRows, removedCells, same };
}

const csvField = (v: unknown): string => {
  const text = v === null || v === undefined ? "" : String(v);
  return /[",\n\r]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
};

/** The matrix as `cheme cause-effect` writes `build/cause-effect.csv`. */
export function matrixCsv(matrix: Pick<InterlockMatrix, "columns" | "rows">): string {
  const lines = [["id", "cause", "condition", "sheet", "sil", ...matrix.columns]];
  for (const row of matrix.rows) lines.push([row.id, row.cause, row.condition, row.sheet ?? "", row.sil === null || row.sil === undefined ? "" : String(row.sil), ...row.cells]);
  return lines.map((l) => l.map(csvField).join(",")).join("\n") + "\n";
}
