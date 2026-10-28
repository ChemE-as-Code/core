import type { JsonSchema, YamlDoc } from "@/api";
import { isRecord } from "./guards";

export interface Column {
  key: string;
  title: string;
  description: string;
  /** Short type summary, e.g. `string`, `number?`. Empty when the schema says nothing. */
  type: string;
  required: boolean;
  /** True for keys that rows have but the schema does not list. */
  extra: boolean;
}

export interface YamlTable {
  /** The top-level key the rows live under (`equipment`, `lines`, ...), or null for a bare list. */
  key: string | null;
  columns: Column[];
  rows: Record<string, unknown>[];
}

type Obj = Record<string, unknown>;

function isRowList(value: unknown): value is Obj[] {
  return Array.isArray(value) && value.every(isRecord);
}

/** Follow a local `$ref` (`#/$defs/X` or `#/definitions/X`) against the root schema. */
export function resolveRef(schema: JsonSchema | undefined, root: JsonSchema): JsonSchema | undefined {
  let current = schema;
  for (let depth = 0; current?.$ref && depth < 16; depth++) {
    const match = /^#\/(\$defs|definitions)\/(.+)$/.exec(current.$ref);
    if (!match) return current;
    const defs = match[1] === "$defs" ? root.$defs : root.definitions;
    current = defs?.[decodeURIComponent(match[2] ?? "").replace(/~1/g, "/").replace(/~0/g, "~")];
  }
  return current;
}

/** `string`, `number?` (nullable), `string[]`, `a | b`, or `enum`. */
export function typeSummary(schema: JsonSchema | undefined, root: JsonSchema): string {
  const resolved = resolveRef(schema, root);
  if (!resolved) return "";
  if (resolved.enum) return "enum";
  const variants = resolved.anyOf ?? resolved.oneOf;
  if (variants) {
    const parts = variants.map((v) => typeSummary(v, root)).filter(Boolean);
    const nullable = parts.includes("null");
    const rest = [...new Set(parts.filter((p) => p !== "null"))];
    return rest.join(" | ") + (nullable ? "?" : "");
  }
  const type = resolved.type;
  if (Array.isArray(type)) {
    const nullable = type.includes("null");
    return type.filter((t) => t !== "null").join(" | ") + (nullable ? "?" : "");
  }
  if (type === "array") {
    const inner = typeSummary(resolved.items, root);
    return inner ? `${inner}[]` : "array";
  }
  if (type === "integer") return "number";
  return type ?? (resolved.properties ? "object" : "");
}

/** The item schema of the array property `key` of `schema`, resolved. */
function itemSchema(schema: JsonSchema | null, key: string | null): JsonSchema | undefined {
  if (!schema) return undefined;
  if (key === null) return resolveRef(resolveRef(schema, schema)?.items, schema);
  const top = resolveRef(schema, schema);
  const prop = resolveRef(top?.properties?.[key], schema);
  return resolveRef(prop?.items, schema);
}

/**
 * The rows of `data` and the key that holds them: the list kind's own key (`equipment: [...]`),
 * the document itself when it is a list of objects (key null), or the only key of a one-key
 * document. Other documents (e.g. the design basis, which has lists inside it) are not tables.
 */
function tableRows(doc: YamlDoc): { key: string | null; rows: Obj[] } | undefined {
  const { data, kind } = doc;
  if (isRowList(data)) return { key: null, rows: data };
  if (!isRecord(data)) return undefined;
  const ofKind = kind ? data[kind] : undefined;
  if (kind && isRowList(ofKind)) return { key: kind, rows: ofKind };
  const [only, ...others] = Object.keys(data);
  const rows = only === undefined ? undefined : data[only];
  if (!kind && only !== undefined && others.length === 0 && isRowList(rows) && rows.length > 0) return { key: only, rows };
  return undefined;
}

/**
 * Columns for `rows`: the schema's item properties in schema order, then any keys the rows
 * have that the schema does not list, in first-seen order.
 */
export function tableColumns(rows: Obj[], item: JsonSchema | undefined, root: JsonSchema | null): Column[] {
  const columns: Column[] = [];
  const seen = new Set<string>();
  const required = new Set(item?.required ?? []);
  for (const [key, prop] of Object.entries(item?.properties ?? {})) {
    const resolved = root ? resolveRef(prop, root) : prop;
    columns.push({
      key,
      title: prop.title ?? resolved?.title ?? key,
      description: prop.description ?? resolved?.description ?? "",
      type: root ? typeSummary(prop, root) : "",
      required: required.has(key),
      extra: false,
    });
    seen.add(key);
  }
  for (const row of rows) {
    for (const key of Object.keys(row)) {
      if (seen.has(key)) continue;
      seen.add(key);
      columns.push({ key, title: key, description: "", type: "", required: false, extra: item !== undefined });
    }
  }
  return columns;
}

/** A table for list-like YAML documents, or null when the document should be shown as a tree. */
export function yamlTable(doc: YamlDoc): YamlTable | null {
  const found = tableRows(doc);
  if (found === undefined) return null;
  const { key, rows } = found;
  const item = itemSchema(doc.schema, key);
  return { key, columns: tableColumns(rows, item, doc.schema), rows };
}

/** The list sections of the process files, each shown as its own table. */
export const PROCESS_SECTIONS: Record<string, string[]> = {
  materials: ["components", "templates"],
  flowsheet: ["streams", "blocks", "steps", "feeds", "products", "cases"],
};

function compactCell(key: string, value: unknown): unknown {
  if (!Array.isArray(value) && !isRecord(value)) return value;
  if (key === "state" && isRecord(value)) return Object.keys(value).join(", ");
  if (key === "ports" && Array.isArray(value))
    return value.map((p) => (isRecord(p) ? `${String(p.id)} (${String(p.direction ?? "")})` : cellText(p))).join(", ");
  if (key === "links" && Array.isArray(value))
    return value.map((l) => (isRecord(l) ? `${String(l.target)} ${String(l.ref)}` : cellText(l))).join(", ");
  return value;
}

/**
 * Tables for a process file (`kind: materials` or `kind: flowsheet`): one per list section that
 * the document has, with nested values (stream state, ports, links) shortened; null for other kinds.
 */
export function processSections(doc: YamlDoc): YamlTable[] | null {
  const sections = doc.kind ? PROCESS_SECTIONS[doc.kind] : undefined;
  if (!sections || !isRecord(doc.data)) return null;
  const data = doc.data;
  const tables: YamlTable[] = [];
  for (const key of sections) {
    const list = data[key];
    if (!Array.isArray(list)) continue;
    const rows = list.filter(isRecord).map((row): Obj => Object.fromEntries(Object.entries(row).map(([k, v]) => [k, compactCell(k, v)])));
    tables.push({ key, columns: tableColumns(rows, itemSchema(doc.schema, key), doc.schema), rows });
  }
  return tables.length ? tables : null;
}

/** Text for one table cell. */
export function cellText(value: unknown): string {
  if (value === undefined || value === null) return "";
  if (typeof value === "string") return value;
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  if (Array.isArray(value) && value.every((v) => typeof v !== "object" || v === null))
    return value.map((v) => cellText(v)).join(", ");
  return JSON.stringify(value);
}
