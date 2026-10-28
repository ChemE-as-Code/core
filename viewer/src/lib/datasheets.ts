/**
 * Equipment datasheets, `equipment/datasheets/<TAG>.yaml` (core's
 * `domains/equipment/schemas/datasheet.py`, written by `cheme datasheets draft` / `fill`), and
 * their outline drawings `equipment/datasheets/<TAG>.svg` (`cheme datasheets drawing`).
 *
 * A server with `GET /api/datasheets` (`has_datasheets` in `/api/repo`) lists them with their
 * counts, drawing state and findings, and answers each one (`/api/datasheets/{tag}`, `.svg`).
 * An older server, or a snapshot without them, has no such endpoint: the viewer then lists them
 * from `/api/tree` (`datasheetPaths` in `studies.ts`) and reads each one through `/api/yaml`.
 *
 * A value is a number, a text or a quantity `{value, unit, source, assumed, reason}`; a value
 * `cheme datasheets fill` calculated also carries its `origin` (`correlation`), the `fingerprint`
 * of its inputs and the `inputs` besides the streams (`catalyst:CAT-1`, `pipe:L-12`, ...). A field
 * without a value yet holds `TBD` (the reason in `source`), `supplier` (waiting for the
 * supplier's data) or `not_applicable` (with a `reason`); a missing or null value counts as TBD.
 */
import { api, ApiError, type DatasheetDetail, type DatasheetIndex, type DatasheetSummary, type DrawingState, type Finding, type RepoInfo } from "@/api";
import { datasheetPaths } from "@/lib/studies";
import { isRecord } from "./guards";

/** What an open field waits for; null for a known value. */
export type OpenKind = "tbd" | "supplier" | "not_applicable";

export interface DatasheetValue {
  /** A list for a value per stage or per item (a compressor's `intercooler_duties_kw`). */
  value: number | string | boolean | (number | string)[] | null;
  unit: string;
  source: string;
  assumed: boolean;
  reason: string;
  open: OpenKind | null;
  /** What kind of figure it is (core's `Origin`: `vendor`, `correlation`, ...); null when not given. */
  origin: string | null;
  /** The fingerprint of the inputs `cheme datasheets fill` calculated it from; null when not given. */
  fingerprint: string | null;
  /** The inputs besides the streams the fingerprint covers (`catalyst:CAT-1`, `pipe:L-12`, `datasheet:design.pressure_barg`). */
  inputs: string[];
}

export interface DatasheetRow extends DatasheetValue {
  key: string;
}

/** A material part: a plain value, or `{value, material_class, standard}` (core's `Material`). */
export interface DatasheetMaterial extends DatasheetRow {
  /** `carbon_steel`, `stainless_steel`, ... (core's `MaterialClass`); null when not given. */
  material_class: string | null;
  standard: string;
}

/** One main dimension or weight: its key (`support.height`), a label, the value. */
export interface DimensionRow extends DatasheetValue {
  key: string;
  label: string;
}

export type DimensionGroupKey = "shell" | "support" | "tubes" | "plates" | "machine" | "overall";

export interface DimensionGroup {
  key: DimensionGroupKey;
  title: string;
  rows: DimensionRow[];
}

/** One section of a column (trays or packing), from the bottom tangent line up. */
export interface ColumnSection {
  id: string;
  internals: DatasheetValue | null;
  bottom: DatasheetValue | null;
  height: DatasheetValue | null;
  count: DatasheetValue | null;
  spacing: DatasheetValue | null;
  notes: string;
}

export interface DatasheetDimensions {
  /** `vertical` / `horizontal`; null when not given. */
  orientation: string | null;
  /** The stated dimensions by family: shell (vessel, column, tank, exchanger shell), support, tube bundle, plates, machine, overall. */
  groups: DimensionGroup[];
  sections: ColumnSection[];
}

export interface DatasheetNozzle {
  name: string;
  /** The mark on the outline drawing and the schedule (M1, N1A); the name when not given. */
  mark: string;
  dn: number | string | null;
  lines: string[];
  service: string;
  rating: string;
  source: string;
  orientation_deg: number | null;
  offset_m: number | null;
  face: string;
  elevation_m: number | null;
  location_source: string;
  facing: string;
  standard: string;
  projection_m: number | null;
  axial_m: number | null;
  assumed: boolean;
}

export interface SizingItem extends DatasheetValue {
  parameter: string;
  reference: string;
}

export interface Datasheet {
  tag: string;
  type: string | null;
  service: string;
  draft: boolean;
  operating: DatasheetRow[];
  design: DatasheetRow[];
  materials: DatasheetMaterial[];
  /** Main dimensions; null when the sheet states none. */
  dimensions: DatasheetDimensions | null;
  /** Weights (empty, operating, test), t; null when the sheet states none. */
  weights: DimensionRow[] | null;
  nozzles: DatasheetNozzle[];
  sizing_basis: SizingItem[];
  /** The type-specific fields that are values (pump: NPSHr, ...), as rows. */
  type_specific: DatasheetRow[];
  /** The other type-specific fields (lists, nested objects such as `process_streams`). */
  type_other: Record<string, unknown>;
  notes: string;
}

export interface DatasheetCounts {
  /** Values on the sheet (operating, design, materials, type-specific, sizing basis, dimensions, weights); null when the server counted (it counts fields, not values). */
  values: number | null;
  assumed: number;
  /** TBD or missing. */
  tbd: number;
  supplier: number;
  not_applicable: number;
}

/** The value sections of a datasheet, in core's order. */
export const VALUE_SECTIONS = [
  { key: "operating", title: "Operating conditions" },
  { key: "design", title: "Design conditions" },
  { key: "materials", title: "Materials" },
  { key: "type_specific", title: "Type-specific" },
] as const;

export type ValueSection = (typeof VALUE_SECTIONS)[number]["key"];

const str = (v: unknown): string => (typeof v === "string" ? v : v === null || v === undefined ? "" : String(v));
const num = (v: unknown): number | null => (typeof v === "number" && Number.isFinite(v) ? v : null);

/** The fields of core's datasheet `Quantity` (`domains/equipment/schemas/datasheet.py`): mirror any field core adds. */
const QUANTITY_KEYS = ["value", "unit", "assumed", "source", "reason", "fingerprint", "inputs", "origin"];

/** A quantity mapping: has `value` and nothing a quantity does not have. */
export function isQuantity(raw: unknown): raw is Record<string, unknown> {
  if (!isRecord(raw) || !("value" in raw)) return false;
  return Object.keys(raw).every((k) => QUANTITY_KEYS.includes(k));
}

/** The open marker of a raw value: TBD (also null, missing or empty), supplier, not_applicable. */
export function openKind(value: unknown): OpenKind | null {
  if (value === null || value === undefined) return "tbd";
  if (typeof value !== "string") return null;
  const v = value.trim().toLowerCase();
  if (v === "" || v === "tbd") return "tbd";
  if (v === "supplier") return "supplier";
  if (v === "not_applicable") return "not_applicable";
  return null;
}

/** One value of a datasheet: a number or text, or a quantity, normalised. */
export function parseValue(raw: unknown): DatasheetValue {
  const q = isQuantity(raw) ? raw : { value: raw };
  const value = q.value;
  const scalar =
    typeof value === "number" || typeof value === "string" || typeof value === "boolean"
      ? value
      : Array.isArray(value) && value.length && value.every((x) => typeof x === "number" || typeof x === "string")
        ? (value as (number | string)[])
        : null;
  return {
    value: scalar,
    unit: str(q.unit),
    source: str(q.source),
    assumed: q.assumed === true,
    reason: str(q.reason),
    open: openKind(value),
    origin: typeof q.origin === "string" && q.origin ? q.origin : null,
    fingerprint: typeof q.fingerprint === "string" && q.fingerprint ? q.fingerprint : null,
    inputs: Array.isArray(q.inputs) ? q.inputs.filter((i): i is string => typeof i === "string" && i !== "") : [],
  };
}

/** One input `cheme datasheets fill` names (core's `Quantity.inputs`) as words: `catalyst:CAT-1` -> `catalyst CAT-1`, `residence_time:R-101` -> `residence time R-101`. */
export function inputText(input: string): string {
  const i = input.indexOf(":");
  if (i <= 0) return input;
  return `${input.slice(0, i).replace(/_/g, " ")} ${input.slice(i + 1)}`;
}

/** The inputs of a value, compact: `catalyst CAT-1, pipe L-12, +2 more` (at most `max` named); "" without inputs. */
export function inputsText(v: Pick<DatasheetValue, "inputs">, max = 3): string {
  const named = v.inputs.slice(0, max).map(inputText);
  const more = v.inputs.length - named.length;
  return [...named, ...(more > 0 ? [`+${more} more`] : [])].join(", ");
}

function rows(raw: unknown): DatasheetRow[] {
  if (!isRecord(raw)) return [];
  return Object.entries(raw).map(([key, v]) => ({ key, ...parseValue(v) }));
}

const MATERIAL_KEYS = ["value", "unit", "material_class", "standard", "assumed", "source", "reason"];

/** One material part: a plain value or quantity, or `{value, material_class, standard}`. */
export function parseMaterial(key: string, raw: unknown): DatasheetMaterial {
  const structured = isRecord(raw) && "value" in raw && Object.keys(raw).every((k) => MATERIAL_KEYS.includes(k));
  if (!structured) return { key, ...parseValue(raw), material_class: null, standard: "" };
  const { material_class: cls, standard, ...quantity } = raw;
  return { key, ...parseValue(quantity), material_class: typeof cls === "string" && cls ? cls : null, standard: str(standard) };
}

/** A material class as words: `low_temperature_carbon_steel` -> `low temperature carbon steel`. */
export const materialClassText = (cls: string): string => cls.replace(/_/g, " ");

/**
 * The main dimensions of core's `DatasheetDimensions` by family, with labels and the unit a plain
 * number has (m unless stated; counts and passes have none, tube sizes may be m or mm).
 */
const DIMENSION_GROUPS: { key: DimensionGroupKey; title: string; path: string | null; fields: [string, string, string][] }[] = [
  {
    key: "shell",
    title: "Shell",
    path: null,
    fields: [
      ["inside_diameter", "inside diameter", "m"],
      ["outside_diameter", "outside diameter", "m"],
      ["tangent_length", "tangent length (T-T)", "m"],
      ["head", "head", ""],
      ["shell_passes", "shell passes", ""],
      ["axis_deg", "axis direction", "deg"],
    ],
  },
  { key: "support", title: "Support", path: "support", fields: [["type", "type", ""], ["height", "height", "m"], ["count", "count", ""]] },
  {
    key: "tubes",
    title: "Tube bundle",
    path: "tubes",
    fields: [["count", "tubes", ""], ["outside_diameter", "tube OD", ""], ["length", "tube length", "m"], ["passes", "tube passes", ""], ["pitch", "tube pitch", ""]],
  },
  { key: "plates", title: "Plates", path: "plates", fields: [["height", "plate height", "m"], ["width", "plate width", "m"], ["count", "plates", ""]] },
  { key: "machine", title: "Machine", path: null, fields: [["baseplate.length", "baseplate length", "m"], ["baseplate.width", "baseplate width", "m"], ["shaft_height", "shaft height", "m"]] },
  { key: "overall", title: "Overall", path: null, fields: [["overall_length", "overall length", "m"], ["overall_width", "overall width", "m"], ["overall_height", "overall height", "m"]] },
];

const WEIGHTS: [string, string][] = [
  ["empty", "empty (erection)"],
  ["operating", "operating"],
  ["test", "test (full of water)"],
];

/** A field present in `obj` (by a dotted path) as a value with the default unit for a plain number. */
function dimensionRow(obj: Record<string, unknown>, path: string, label: string, unit: string, key = path): DimensionRow | null {
  let node: unknown = obj;
  for (const part of path.split(".")) {
    if (!isRecord(node) || !(part in node)) return null;
    node = node[part];
  }
  const v = parseValue(node);
  return { key, label, ...v, unit: v.unit || (typeof v.value === "number" ? unit : "") };
}

function maybeValue(raw: Record<string, unknown>, key: string): DatasheetValue | null {
  return key in raw ? parseValue(raw[key]) : null;
}

/** The `dimensions` mapping of a datasheet, by family; null when there is none. */
export function parseDimensions(raw: unknown): DatasheetDimensions | null {
  if (!isRecord(raw)) return null;
  const groups: DimensionGroup[] = [];
  for (const g of DIMENSION_GROUPS) {
    const base = g.path ? raw[g.path] : raw;
    if (!isRecord(base)) continue;
    const rows = g.fields
      .map(([path, label, unit]) => dimensionRow(base, path, label, unit, g.path ? `${g.path}.${path}` : path))
      .filter((r): r is DimensionRow => r !== null);
    if (rows.length) groups.push({ key: g.key, title: g.title, rows });
  }
  const sections: ColumnSection[] = Array.isArray(raw.sections)
    ? raw.sections.map((item) => {
        const s = isRecord(item) ? item : {};
        const metres = (key: string) => {
          const v = maybeValue(s, key);
          return v && !v.unit && typeof v.value === "number" ? { ...v, unit: "m" } : v;
        };
        return {
          id: str(s.id),
          internals: maybeValue(s, "internals"),
          bottom: metres("bottom"),
          height: metres("height"),
          count: maybeValue(s, "count"),
          spacing: metres("spacing"),
          notes: str(s.notes),
        };
      })
    : [];
  const orientation = typeof raw.orientation === "string" && raw.orientation ? raw.orientation : null;
  return { orientation, groups, sections };
}

/** The `weights` mapping (t); null when there is none. */
export function parseWeights(raw: unknown): DimensionRow[] | null {
  if (!isRecord(raw)) return null;
  return WEIGHTS.map(([key, label]) => dimensionRow(raw, key, label, "t")).filter((r): r is DimensionRow => r !== null);
}

/** Every dimension value of the sheet (the groups and the column sections), and its weights. */
function dimensionValues(sheet: Datasheet): DatasheetValue[] {
  const dims = sheet.dimensions;
  const out: DatasheetValue[] = [];
  if (dims) {
    for (const g of dims.groups) out.push(...g.rows);
    for (const s of dims.sections) for (const v of [s.internals, s.bottom, s.height, s.count, s.spacing]) if (v) out.push(v);
  }
  return [...out, ...(sheet.weights ?? [])];
}

function nozzle(raw: unknown): DatasheetNozzle {
  const n = isRecord(raw) ? raw : {};
  const dn = n.dn;
  return {
    name: str(n.name),
    mark: str(n.mark) || str(n.name),
    dn: typeof dn === "number" || typeof dn === "string" ? dn : null,
    lines: Array.isArray(n.lines) ? n.lines.map(str).filter(Boolean) : [],
    service: str(n.service),
    rating: str(n.rating),
    source: str(n.source),
    orientation_deg: num(n.orientation_deg),
    offset_m: num(n.offset_m),
    face: str(n.face),
    elevation_m: num(n.elevation_m),
    location_source: str(n.location_source),
    facing: str(n.facing),
    standard: str(n.standard),
    projection_m: num(n.projection_m),
    axial_m: num(n.axial_m),
    assumed: n.assumed === true,
  };
}

/**
 * A datasheet as `/api/yaml` returns its `data`, normalised so the views need no checks.
 * `fallbackTag` (the file name) stands in for a missing tag.
 */
export function parseDatasheet(data: unknown, fallbackTag = ""): Datasheet {
  const d = isRecord(data) ? data : {};
  const typeSpecific: DatasheetRow[] = [];
  const typeOther: Record<string, unknown> = {};
  if (isRecord(d.type_specific)) {
    for (const [key, v] of Object.entries(d.type_specific)) {
      if (isQuantity(v) || v === null || ["number", "string", "boolean"].includes(typeof v)) typeSpecific.push({ key, ...parseValue(v) });
      else typeOther[key] = v;
    }
  }
  return {
    tag: str(d.tag) || fallbackTag,
    type: typeof d.type === "string" && d.type ? d.type : null,
    service: str(d.service),
    draft: d.draft === true,
    operating: rows(d.operating),
    design: rows(d.design),
    materials: isRecord(d.materials) ? Object.entries(d.materials).map(([key, v]) => parseMaterial(key, v)) : [],
    dimensions: parseDimensions(d.dimensions),
    weights: parseWeights(d.weights),
    nozzles: Array.isArray(d.nozzles) ? d.nozzles.map(nozzle) : [],
    sizing_basis: Array.isArray(d.sizing_basis)
      ? d.sizing_basis.map((item) => {
          const s = isRecord(item) ? item : {};
          return { parameter: str(s.parameter), reference: str(s.reference), ...parseValue(s.value) };
        })
      : [],
    type_specific: typeSpecific,
    type_other: typeOther,
    notes: str(d.notes),
  };
}

/** Every value of the sheet: the four value sections, the sizing basis, the main dimensions and the weights. */
export function allValues(sheet: Datasheet): DatasheetValue[] {
  return [...sheet.operating, ...sheet.design, ...sheet.materials, ...sheet.type_specific, ...sheet.sizing_basis, ...dimensionValues(sheet)];
}

/** How many values are assumed, TBD (or missing), waiting for the supplier, not applicable. */
export function countValues(sheet: Datasheet): DatasheetCounts {
  const out: DatasheetCounts = { values: 0, assumed: 0, tbd: 0, supplier: 0, not_applicable: 0 };
  for (const v of allValues(sheet)) {
    out.values!++;
    if (v.assumed) out.assumed++;
    if (v.open) out[v.open]++;
  }
  return out;
}

/** The value as text: numbers in en format, open markers as they are written. */
export function valueText(v: DatasheetValue): string {
  if (v.open === "tbd") return v.value === null || v.value === "" ? "TBD (missing)" : "TBD";
  if (v.open === "not_applicable") return "not applicable";
  const one = (x: unknown) => (typeof x === "number" ? x.toLocaleString("en", { maximumFractionDigits: 6 }) : str(x));
  return Array.isArray(v.value) ? v.value.map(one).join("; ") : one(v.value);
}

export interface DatasheetEntry {
  tag: string;
  path: string;
  /** The sheet as read through `/api/yaml` (the tree path); null from `/api/datasheets` or when it failed. */
  sheet: Datasheet | null;
  counts: DatasheetCounts | null;
  /** Why the file could not be read, or that it does not validate. */
  error: string | null;
  /** The server's summary (`/api/datasheets`): drawing state, findings. */
  summary?: DatasheetSummary;
}

/** An index entry from the server's summary. */
export function summaryEntry(s: DatasheetSummary): DatasheetEntry {
  return {
    tag: s.tag,
    path: s.file,
    sheet: null,
    counts: { values: null, ...s.counts },
    error: s.valid ? null : "does not validate (cheme validate names the problem)",
    summary: s,
  };
}

export const entryType = (e: DatasheetEntry): string | null => e.summary?.type ?? e.sheet?.type ?? null;
export const entryService = (e: DatasheetEntry): string => e.summary?.service ?? e.sheet?.service ?? "";
export const entryDraft = (e: DatasheetEntry): boolean | null => (e.summary ? e.summary.draft : e.sheet ? e.sheet.draft : null);
/** Whether the sheet states main dimensions / weights; null when unknown (it failed to load). */
export const entryHasDimensions = (e: DatasheetEntry): boolean | null => (e.summary ? e.summary.has_dimensions : e.sheet ? e.sheet.dimensions !== null : null);
export const entryHasWeights = (e: DatasheetEntry): boolean | null => (e.summary ? e.summary.has_weights : e.sheet ? e.sheet.weights !== null : null);

/** The state of an outline drawing from a summary; null when the server did not say (the tree path). */
export function drawingState(s: Pick<DatasheetSummary, "valid" | "has_drawing" | "drawing_current"> | undefined): DrawingState | null {
  if (!s) return null;
  if (!s.valid) return "none";
  if (!s.has_drawing) return "missing";
  return s.drawing_current ? "current" : "stale";
}

/** The findings count of an entry (errors and warnings weigh more); -1 when unknown. */
function findingsWeight(e: DatasheetEntry): number {
  const f = e.summary?.findings;
  return f ? f.error * 10000 + f.warning * 100 + f.info : -1;
}

const DRAWING_ORDER: Record<DrawingState, number> = { none: 3, missing: 2, stale: 1, current: 0 };

export type SortKey = "tag" | "type" | "service" | "draft" | "assumed" | "tbd" | "dimensions" | "weights" | "drawing" | "findings";

/** Entries whose tag, type or service contains `query` (any case). */
export function filterEntries(entries: readonly DatasheetEntry[], query: string, type = ""): DatasheetEntry[] {
  const q = query.trim().toLowerCase();
  return entries.filter((e) => {
    if (type && (entryType(e) ?? "") !== type) return false;
    if (!q) return true;
    return [e.tag, entryType(e) ?? "", entryService(e)].some((s) => s.toLowerCase().includes(q));
  });
}

const flag = (v: boolean | null) => (v === null ? -1 : v ? 1 : 0);

/** Entries sorted by `key` (`dir` 1 ascending, -1 descending); ties by tag. */
export function sortEntries(entries: readonly DatasheetEntry[], key: SortKey, dir: 1 | -1 = 1): DatasheetEntry[] {
  const byTag = (a: DatasheetEntry, b: DatasheetEntry) => a.tag.localeCompare(b.tag, "en", { numeric: true });
  const value = (e: DatasheetEntry): string | number => {
    switch (key) {
      case "tag":
        return e.tag;
      case "type":
        return entryType(e) ?? "";
      case "service":
        return entryService(e);
      case "draft":
        return entryDraft(e) ? 1 : 0;
      case "assumed":
        return e.counts?.assumed ?? -1;
      case "tbd":
        return e.counts?.tbd ?? -1;
      case "dimensions":
        return flag(entryHasDimensions(e));
      case "weights":
        return flag(entryHasWeights(e));
      case "drawing": {
        const state = drawingState(e.summary);
        return state ? DRAWING_ORDER[state] : -1;
      }
      case "findings":
        return findingsWeight(e);
    }
  };
  return [...entries].sort((a, b) => {
    const x = value(a);
    const y = value(b);
    const c = typeof x === "number" && typeof y === "number" ? x - y : String(x).localeCompare(String(y), "en", { numeric: true });
    return c * dir || byTag(a, b);
  });
}

/** Plant totals of an index. */
export interface DatasheetTotals {
  sheets: number;
  drafts: number;
  assumed: number;
  tbd: number;
  supplier: number;
  /** Sheets stating main dimensions / weights; null when unknown for every sheet. */
  dimensions: number;
  weights: number;
  /** Drawing states (from the server; zero on the tree path). */
  drawings: Record<DrawingState, number>;
  findings: { error: number; warning: number; info: number };
}

export function totalsOf(entries: readonly DatasheetEntry[]): DatasheetTotals {
  const out: DatasheetTotals = {
    sheets: entries.length,
    drafts: 0,
    assumed: 0,
    tbd: 0,
    supplier: 0,
    dimensions: 0,
    weights: 0,
    drawings: { current: 0, stale: 0, missing: 0, none: 0 },
    findings: { error: 0, warning: 0, info: 0 },
  };
  for (const e of entries) {
    if (entryDraft(e)) out.drafts++;
    out.assumed += e.counts?.assumed ?? 0;
    out.tbd += e.counts?.tbd ?? 0;
    out.supplier += e.counts?.supplier ?? 0;
    if (entryHasDimensions(e)) out.dimensions++;
    if (entryHasWeights(e)) out.weights++;
    const state = drawingState(e.summary);
    if (state) out.drawings[state]++;
    const f = e.summary?.findings;
    if (f) for (const level of ["error", "warning", "info"] as const) out.findings[level] += f[level] ?? 0;
  }
  return out;
}

/** The line list the nozzle schedule links its lines into (core's `foundation/workspace.py`). */
export const LINE_LIST = "piping/line-list.yaml";

/** Read one datasheet through `/api/yaml` (the tree path). */
export async function loadDatasheet(path: string, tag: string, rev: string | null | undefined, signal?: AbortSignal): Promise<Datasheet> {
  const doc = await api.yaml(path, rev, signal);
  return parseDatasheet(doc.data, tag);
}

/** Read every datasheet of `paths` (tag -> path); a file that fails keeps its error, the others load. */
export async function loadDatasheets(paths: ReadonlyMap<string, string>, rev: string | null | undefined, signal?: AbortSignal): Promise<DatasheetEntry[]> {
  return Promise.all(
    [...paths].map(async ([tag, path]): Promise<DatasheetEntry> => {
      try {
        const sheet = await loadDatasheet(path, tag, rev, signal);
        return { tag, path, sheet, counts: countValues(sheet), error: null };
      } catch (error) {
        if (error instanceof DOMException && error.name === "AbortError") throw error;
        return { tag, path, sheet: null, counts: null, error: error instanceof Error ? error.message : String(error) };
      }
    }),
  );
}

/** Whether to ask `/api/datasheets` first: the server says it has them (an older one leaves `has_datasheets` out). */
export const serverHasDatasheets = (repo: RepoInfo | null | undefined): boolean => repo?.has_datasheets !== undefined;

const notFound = (error: unknown) => error instanceof ApiError && error.status === 404;

/** Where the index came from: the server's datasheet endpoint, or the tree and `/api/yaml`. */
export type DatasheetSourceKind = "server" | "tree";

export interface DatasheetIndexView {
  source: DatasheetSourceKind;
  entries: DatasheetEntry[];
  /** Listed items without a datasheet (the server only; empty on the tree path). */
  missing: string[];
  index: DatasheetIndex | null;
}

/**
 * The datasheet index at `rev`: `/api/datasheets` when the server has it (`useServer`), else (an
 * older server, a snapshot without it, or a 404) the tree and each sheet through `/api/yaml`.
 */
export async function loadDatasheetIndex(rev: string | null | undefined, useServer: boolean, signal?: AbortSignal): Promise<DatasheetIndexView> {
  if (useServer) {
    try {
      const index = await api.datasheets(rev, signal);
      return { source: "server", entries: index.datasheets.map(summaryEntry), missing: index.missing ?? [], index };
    } catch (error) {
      if (!notFound(error)) throw error;
    }
  }
  const entries = await loadDatasheets(datasheetPaths(await api.tree(rev, signal)), rev, signal);
  return { source: "tree", entries, missing: [], index: null };
}

/** One datasheet page's data, from either source. */
export interface DatasheetPage {
  source: DatasheetSourceKind;
  /** Repo path of the datasheet; null when there is none for the tag. */
  path: string | null;
  sheet: Datasheet | null;
  /** The server's answer (summary, drawing state, findings); null on the tree path. */
  detail: DatasheetDetail | null;
  findings: Finding[];
  /** Repo path of a committed outline drawing on the tree path (state not known); null when none. */
  treeDrawing: string | null;
  /** The repository file kinds (the tree path; for the P&ID and line-list links). */
  treeKinds: Map<string, string> | null;
}

/**
 * The datasheet of `tag` at `rev`: `/api/datasheets/{tag}` when the server has it, else (or on a
 * 404: an unknown tag, an older server, a snapshot without it) the tree and `/api/yaml`.
 */
export async function loadDatasheetPage(tag: string, rev: string | null | undefined, useServer: boolean, signal?: AbortSignal): Promise<DatasheetPage> {
  if (useServer) {
    try {
      const detail = await api.datasheet(tag, rev, signal);
      return {
        source: "server",
        path: detail.file,
        sheet: detail.data !== null && detail.data !== undefined ? parseDatasheet(detail.data, detail.tag) : null,
        detail,
        findings: detail.findings ?? [],
        treeDrawing: null,
        treeKinds: null,
      };
    } catch (error) {
      if (!notFound(error)) throw error;
    }
  }
  const tree = await api.tree(rev, signal);
  const treeKinds = new Map(tree.map((e) => [e.path, e.kind] as const));
  const path = datasheetPaths(tree).get(tag) ?? null;
  const svg = path ? path.replace(/\.ya?ml$/, ".svg") : null;
  const sheet = path ? await loadDatasheet(path, tag, rev, signal) : null;
  return { source: "tree", path, sheet, detail: null, findings: [], treeDrawing: svg && treeKinds.has(svg) ? svg : null, treeKinds };
}
