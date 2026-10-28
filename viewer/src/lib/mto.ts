/**
 * The material take-off page (`GET /api/mto`): rows grouped by category, totals, and the CSV
 * files `cheme assess mto --csv` and `assess estimate --csv` write (byte for byte, so a
 * download from the viewer is the file a project commits as `estimate/mto.csv`).
 */
import type { EstimateLine, MtoRow } from "@/api";

/** Core's order of the take-off categories, with a title for each. */
export const CATEGORIES: [string, string][] = [
  ["pipe", "Pipe"],
  ["elbow", "Elbows and bends"],
  ["tee", "Tees"],
  ["reducer", "Reducers"],
  ["flange", "Flanges"],
  ["gasket", "Gaskets and bolt sets"],
  ["valve", "Valves"],
  ["inline", "Other in-line items"],
  ["steel", "Structural steel"],
  ["grating", "Grating"],
  ["insulation", "Insulation"],
  ["concrete", "Concrete"],
];
const TITLES = new Map(CATEGORIES);
const ORDER = new Map(CATEGORIES.map(([c], i) => [c, i]));

export interface MtoGroup {
  category: string;
  title: string;
  rows: MtoRow[];
  /** Sum of the quantities per unit. */
  totals: Record<string, number>;
  /** Sum of the counts (pipes, members, items). */
  count: number;
}

/** The rows by category in core's order (unknown categories after, alphabetically), each with its totals. */
export function groupRows(rows: readonly MtoRow[]): MtoGroup[] {
  const groups = new Map<string, MtoGroup>();
  for (const row of rows) {
    let g = groups.get(row.category);
    if (!g) {
      g = { category: row.category, title: TITLES.get(row.category) ?? row.category, rows: [], totals: {}, count: 0 };
      groups.set(row.category, g);
    }
    g.rows.push(row);
    g.totals[row.unit] = round3((g.totals[row.unit] ?? 0) + row.quantity);
    g.count += row.count;
  }
  const rank = (c: string) => ORDER.get(c) ?? ORDER.size;
  return [...groups.values()].sort((a, b) => rank(a.category) - rank(b.category) || a.category.localeCompare(b.category));
}

/** Whether a row matches a filter text (any of its words in item, DN, class, spec, group or key). */
export function rowMatches(row: MtoRow, query: string): boolean {
  const words = query.toLowerCase().split(/\s+/).filter(Boolean);
  if (!words.length) return true;
  const text = [row.category, row.item, row.dn != null ? `dn${row.dn} dn ${row.dn}` : "", row.dn2 != null ? `dn${row.dn2}` : "", row.class, row.spec, row.group, row.key].join(" ").toLowerCase();
  return words.every((w) => text.includes(w));
}

const round3 = (v: number) => Math.round(v * 1000) / 1000;

/**
 * Python's `f"{value:g}"`: six significant digits, trailing zeros dropped, an exponent from
 * 1e-5 down or 1e6 up (`1.5e+06`).
 */
export function pyG(value: number): string {
  if (!Number.isFinite(value)) return value > 0 ? "inf" : value < 0 ? "-inf" : "nan";
  if (value === 0) return Object.is(value, -0) ? "-0" : "0";
  const exponent = Math.floor(Math.log10(Math.abs(Number(value.toPrecision(6)))));
  if (exponent < -4 || exponent >= 6) {
    const [mantissa, exp] = value.toExponential(5).split("e") as [string, string];
    const m = mantissa.includes(".") ? mantissa.replace(/0+$/, "").replace(/\.$/, "") : mantissa;
    const n = Number(exp);
    return `${m}e${n < 0 ? "-" : "+"}${String(Math.abs(n)).padStart(2, "0")}`;
  }
  const fixed = value.toFixed(Math.max(5 - exponent, 0));
  return fixed.includes(".") ? fixed.replace(/0+$/, "").replace(/\.$/, "") : fixed;
}

/** Core's `_num`: rounded to 3 decimals, then `:g`; empty for none. */
export function csvNumber(value: number | null | undefined): string {
  if (value === null || value === undefined) return "";
  return pyG(Number(value.toFixed(3)));
}

/** A CSV cell as Python's csv module writes it (quoted when it holds a comma, quote or line break). */
export function csvCell(text: string): string {
  return /[",\r\n]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
}

export const MTO_COLUMNS = ["category", "item", "dn", "dn2", "class", "spec", "group", "count", "quantity", "unit", "length_m"] as const;

/** The take-off as `cheme assess mto --csv` writes it (`estimate/mto.csv`). */
export function mtoCsv(rows: readonly MtoRow[]): string {
  const lines = [MTO_COLUMNS.join(",")];
  for (const r of rows)
    lines.push(
      [r.category, r.item, csvNumber(r.dn), csvNumber(r.dn2), r.class, r.spec, r.group, String(r.count), csvNumber(r.quantity), r.unit, csvNumber(r.length_m)].map(csvCell).join(","),
    );
  return lines.join("\n") + "\n";
}

export const ESTIMATE_COLUMNS = ["section", "id", "description", "quantity", "unit", "rate", "basis", "cost", "status", "source", "year"] as const;

/** The estimate as `cheme assess estimate --csv` writes it (`estimate/estimate.csv`). */
export function estimateCsv(lines: readonly EstimateLine[]): string {
  const out = [ESTIMATE_COLUMNS.join(",")];
  for (const l of lines)
    out.push(
      [
        l.section,
        l.id,
        l.description,
        l.section !== "material" ? l.quantity.toFixed(2) : pyG(Number(l.quantity.toFixed(3))),
        l.unit,
        l.rate === null ? "" : pyG(l.rate),
        l.basis,
        l.cost === null ? "" : l.cost.toFixed(2),
        l.status,
        l.source,
        l.year === null ? "" : String(l.year),
      ]
        .map(csvCell)
        .join(","),
    );
  return out.join("\n") + "\n";
}

/** A quantity for the tables: up to 3 decimals, digits grouped. */
export function quantity(value: number | null | undefined, digits = 3): string {
  if (value === null || value === undefined) return "";
  return value.toLocaleString("en", { maximumFractionDigits: digits });
}

/** Money: two decimals, digits grouped, with the currency (`XXX` is no currency). */
export function money(value: number | null | undefined, currency = ""): string {
  if (value === null || value === undefined) return "";
  const text = value.toLocaleString("en", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  return currency ? `${text} ${currency}` : text;
}

/** A DN cell: `DN 100`, a reducing one `DN 100 x 50`. */
export function dnText(row: Pick<MtoRow, "dn" | "dn2">): string {
  if (row.dn === null) return "";
  return `DN ${pyG(row.dn)}${row.dn2 !== null ? ` x ${pyG(row.dn2)}` : ""}`;
}
