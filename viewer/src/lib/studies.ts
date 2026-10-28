/**
 * Committed study files the layout view shows beside the model: the lifting study, the cable
 * schedule and the equipment datasheets. cheme serve has no endpoint for them; the viewer reads
 * the files core writes through `/api/tree` and `/api/file`, as they are committed at the revision.
 *
 * - `layout/lifting-study.csv`: `cheme layout lifting --write` (core's
 *   docs/framework/layout-model.md, "The lifting study"), one row per heavy item.
 * - `electrical/cable-schedule.csv`: `cheme layout cables --write` (core's
 *   `domains/spatial/trays.py`, `cable_schedule`), one row per cable of the model, by tag.
 * - `equipment/datasheets/<TAG>.yaml`: one datasheet per equipment-list item (core's
 *   `domains/equipment/datasheets.py`); a newer cheme serve also answers `GET /api/datasheets`
 *   (`src/lib/datasheets.ts`), the tree is the fallback.
 */
import type { TreeEntry } from "@/api";

export const LIFTING_STUDY_CSV = "layout/lifting-study.csv";
export const LIFTING_STUDY_MD = "layout/lifting-study.md";
export const DATASHEET_DIR = "equipment/datasheets";
export const CABLE_SCHEDULE_CSV = "electrical/cable-schedule.csv";
export const CABLE_SCHEDULE_MD = "electrical/cable-schedule.md";

/** The columns core writes, in its order (layout-model.md). */
export const LIFTING_COLUMNS = [
  "tag",
  "weight_t",
  "crane",
  "pad",
  "radius_m",
  "gross_t",
  "moment_tm",
  "required_t",
  "lift_height_m",
  "hook_height_m",
  "lane",
  "laydown",
  "chart",
  "chart_radius_m",
  "chart_capacity_t",
  "utilisation",
  "status",
] as const satisfies readonly (keyof LiftingRow)[];

/** One lift of the study: numbers where core wrote one, null where the cell is empty. */
export interface LiftingRow {
  tag: string;
  weight_t: number | null;
  /** `mobile` or `building <id>` (its overhead crane). */
  crane: string;
  /** The crane pad zone (a mobile crane), empty for a building crane. */
  pad: string;
  /** Working radius from the pad's centre (where the crane is ASSUMED to slew), m. */
  radius_m: number | null;
  gross_t: number | null;
  /** Gross load x radius, t m. */
  moment_tm: number | null;
  /** Chart capacity needed (gross / utilisation), t. */
  required_t: number | null;
  lift_height_m: number | null;
  hook_height_m: number | null;
  /** `clear`, or what blocks the lane. */
  lane: string;
  laydown: string;
  /** A crane chart of `layout/crane-chart.yaml` checked against, with its capacity at the radius
   * (for a building's overhead crane: no chart, `chart_capacity_t` its rating). */
  chart: string;
  chart_radius_m: number | null;
  chart_capacity_t: number | null;
  utilisation: number | null;
  /** Core's verdict (`lane clear`, `building crane 40 t carries it` / `... short`, a blocked lane, a capacity short, ...). */
  status: string;
}

/** Split CSV text into rows of cells (RFC 4180 quoting: `"a, b"`, `""` for a quote). */
export function parseCsv(text: string): string[][] {
  const rows: string[][] = [];
  let row: string[] = [];
  let cell = "";
  let quoted = false;
  for (let i = 0; i < text.length; i++) {
    const c = text[i]!;
    if (quoted) {
      if (c === '"' && text[i + 1] === '"') {
        cell += '"';
        i++;
      } else if (c === '"') quoted = false;
      else cell += c;
    } else if (c === '"') quoted = true;
    else if (c === ",") {
      row.push(cell);
      cell = "";
    } else if (c === "\n" || c === "\r") {
      if (c === "\r" && text[i + 1] === "\n") i++;
      row.push(cell);
      rows.push(row);
      row = [];
      cell = "";
    } else cell += c;
  }
  if (cell || row.length) {
    row.push(cell);
    rows.push(row);
  }
  return rows.filter((r) => r.some((c) => c.trim()));
}

/**
 * The rows of a lifting study CSV, by its header (columns it does not know are left out, ones it
 * lacks are empty). Throws when there is no `tag` column: not a lifting study.
 */
export function parseLiftingStudy(text: string): LiftingRow[] {
  const [header, ...body] = parseCsv(text);
  if (!header || !header.includes("tag")) throw new Error(`${LIFTING_STUDY_CSV} has no tag column`);
  const at = new Map(header.map((h, i) => [h.trim(), i]));
  return body.map((cells) => {
    const cell = csvCells<LiftingRow>(at, cells);
    return {
      tag: cell.text("tag"),
      weight_t: cell.number("weight_t"),
      crane: cell.text("crane"),
      pad: cell.text("pad"),
      radius_m: cell.number("radius_m"),
      gross_t: cell.number("gross_t"),
      moment_tm: cell.number("moment_tm"),
      required_t: cell.number("required_t"),
      lift_height_m: cell.number("lift_height_m"),
      hook_height_m: cell.number("hook_height_m"),
      lane: cell.text("lane"),
      laydown: cell.text("laydown"),
      chart: cell.text("chart"),
      chart_radius_m: cell.number("chart_radius_m"),
      chart_capacity_t: cell.number("chart_capacity_t"),
      utilisation: cell.number("utilisation"),
      status: cell.text("status"),
    };
  });
}

/** A CSV row's cells by column name (`at`: column -> index): trimmed text ("" when absent), or a number (null when empty or not one). */
function csvCells<Row>(at: ReadonlyMap<string, number>, cells: readonly string[]) {
  const text = (column: keyof Row & string): string => {
    const i = at.get(column);
    return (i === undefined ? "" : (cells[i] ?? "")).trim();
  };
  const number = (column: keyof Row & string): number | null => {
    const raw = text(column);
    const n = raw === "" ? NaN : Number(raw);
    return Number.isFinite(n) ? n : null;
  };
  return { text, number };
}

/** Whether the lift's lane is clear (core writes `clear`, else what blocks it). */
export function laneClear(row: Pick<LiftingRow, "lane">): boolean {
  return row.lane.trim().toLowerCase() === "clear";
}

/** Equipment tag -> its datasheet's repo path, from a tree listing. */
export function datasheetPaths(tree: readonly TreeEntry[]): Map<string, string> {
  const out = new Map<string, string>();
  for (const entry of tree) {
    if (entry.type !== "file" || !entry.path.startsWith(`${DATASHEET_DIR}/`)) continue;
    const name = entry.path.slice(DATASHEET_DIR.length + 1);
    const match = /^([^/]+)\.ya?ml$/.exec(name);
    if (match && match[1] !== "README") out.set(match[1]!, entry.path);
  }
  return out;
}

/** The cable schedule's columns, in core's order (`SCHEDULE_COLUMNS`). */
export const CABLE_COLUMNS = [
  "tag",
  "system",
  "kind",
  "from",
  "to",
  "size",
  "od_mm",
  "voltage_v",
  "power_kw",
  "current_a",
  "pairs",
  "route_length_m",
  "length_m",
  "trays",
  "review_needed",
] as const satisfies readonly (keyof CableRow)[];
export type CableColumn = (typeof CABLE_COLUMNS)[number];

/** One cable of the schedule: numbers where core wrote one, null where the cell is empty. */
export interface CableRow {
  tag: string;
  /** `power` or `instrument`. */
  system: string;
  /** `motor`, `feeder`, `field` (instrument to junction box) or `multipair` (junction box to the control room). */
  kind: string;
  from: string;
  to: string;
  /** Catalogue size (ASSUMED for tray sizing), e.g. `4C x 25 mm2`. */
  size: string;
  od_mm: number | null;
  voltage_v: number | null;
  power_kw: number | null;
  current_a: number | null;
  pairs: number | null;
  route_length_m: number | null;
  /** With terminations and slack, m. */
  length_m: number | null;
  /** Tray ids in order from its room. */
  trays: string[];
  /** A fallback route or a proposal to review (core writes `yes`). */
  review_needed: boolean;
}

/**
 * The rows of a cable schedule CSV, by its header (unknown columns are left out, missing ones
 * empty). Throws when there is no `tag` column: not a cable schedule.
 */
export function parseCableSchedule(text: string): CableRow[] {
  const [header, ...body] = parseCsv(text);
  if (!header || !header.map((h) => h.trim()).includes("tag")) throw new Error(`${CABLE_SCHEDULE_CSV} has no tag column`);
  const at = new Map(header.map((h, i) => [h.trim(), i]));
  return body.map((cells) => {
    const cell = csvCells<CableRow>(at, cells);
    return {
      tag: cell.text("tag"),
      system: cell.text("system"),
      kind: cell.text("kind"),
      from: cell.text("from"),
      to: cell.text("to"),
      size: cell.text("size"),
      od_mm: cell.number("od_mm"),
      voltage_v: cell.number("voltage_v"),
      power_kw: cell.number("power_kw"),
      current_a: cell.number("current_a"),
      pairs: cell.number("pairs"),
      route_length_m: cell.number("route_length_m"),
      length_m: cell.number("length_m"),
      trays: cell.text("trays").split(/\s+/).filter(Boolean),
      review_needed: /^(yes|true|1)$/i.test(cell.text("review_needed")),
    };
  });
}

/** Whether a cable matches a filter text: each word in its tag, system, kind, ends, size or trays; `review` the ones to review. */
export function cableMatches(row: CableRow, query: string): boolean {
  const words = query.toLowerCase().split(/\s+/).filter(Boolean);
  if (!words.length) return true;
  const text = [row.tag, row.system, row.kind, row.from, row.to, row.size, ...row.trays, row.review_needed ? "review" : ""].join(" ").toLowerCase();
  return words.every((w) => text.includes(w));
}

/** The rows sorted by a column (numbers numerically with empty cells last, text naturally: `C-2` before `C-10`), tag as the tie-break. */
export function sortCables(rows: readonly CableRow[], column: CableColumn, descending = false): CableRow[] {
  const natural = (a: string, b: string) => a.localeCompare(b, "en", { numeric: true, sensitivity: "base" });
  const sign = descending ? -1 : 1;
  return [...rows].sort((a, b) => {
    const x = a[column];
    const y = b[column];
    let c = 0;
    if (typeof x === "number" || typeof y === "number" || x === null || y === null) {
      if (x === null && y === null) c = 0;
      else if (x === null) return 1;
      else if (y === null) return -1;
      else c = sign * (Number(x) - Number(y));
    } else if (typeof x === "boolean") c = sign * (Number(y) - Number(x));
    else if (Array.isArray(x) && Array.isArray(y)) c = sign * (x.length - y.length);
    else c = sign * natural(String(x), String(y));
    return c || natural(a.tag, b.tag);
  });
}

/** Count, total length (m) and cables to review of the rows, per system and in all. */
export function cableTotals(rows: readonly CableRow[]): { count: number; length_m: number; review: number; systems: Record<string, { count: number; length_m: number }> } {
  const systems: Record<string, { count: number; length_m: number }> = {};
  let length = 0;
  let review = 0;
  for (const r of rows) {
    const s = (systems[r.system || "other"] ??= { count: 0, length_m: 0 });
    s.count += 1;
    s.length_m = Math.round((s.length_m + (r.length_m ?? 0)) * 10) / 10;
    length += r.length_m ?? 0;
    if (r.review_needed) review += 1;
  }
  return { count: rows.length, length_m: Math.round(length * 10) / 10, review, systems };
}
