/**
 * A YAML document that is not one list (the design basis, a risk matrix, a HAZOP study, the TEA
 * inputs) as readable blocks: its scalar fields as a key-value list, lists of objects as tables,
 * lists of values as bullets and nested mappings as sections. Deeper structure stays a tree.
 */
import { isRecord } from "./guards";
import { cellText } from "./yamlTable";

export type DocBlock =
  | { kind: "fields"; fields: { key: string; text: string }[] }
  | { kind: "list"; key: string; items: string[] }
  | { kind: "table"; key: string; columns: string[]; rows: string[][] }
  | { kind: "section"; key: string; title: string; blocks: DocBlock[] }
  | { kind: "tree"; key: string; value: unknown };

/** Sections nest this deep; a mapping below is shown as a tree. */
const MAX_DEPTH = 2;

/** `design_basis` -> `Design basis`. */
export function keyTitle(key: string): string {
  const words = key.replace(/[_-]+/g, " ").trim();
  return words ? words[0]!.toUpperCase() + words.slice(1) : key;
}

const isScalar = (value: unknown) => value === null || typeof value !== "object";

/** A cell: a value as text, a nested mapping as `key: value; ...` (not JSON). */
export function docText(value: unknown): string {
  if (isRecord(value)) return Object.entries(value).map(([k, v]) => `${k}: ${docText(v)}`).join("; ");
  if (Array.isArray(value)) return value.map(docText).join(", ");
  return cellText(value);
}

function table(key: string, rows: Record<string, unknown>[]): DocBlock {
  const columns = [...new Set(rows.flatMap((row) => Object.keys(row)))];
  return { kind: "table", key, columns, rows: rows.map((row) => columns.map((c) => docText(row[c]))) };
}

/** The blocks of a mapping, in document order (consecutive scalars share one field list). */
export function documentBlocks(data: Record<string, unknown>, depth = 0): DocBlock[] {
  const blocks: DocBlock[] = [];
  let fields: { key: string; text: string }[] | null = null;
  for (const [key, value] of Object.entries(data)) {
    if (isScalar(value) || (Array.isArray(value) && !value.length)) {
      if (!fields) blocks.push({ kind: "fields", fields: (fields = []) });
      fields.push({ key, text: Array.isArray(value) ? "none" : cellText(value) });
      continue;
    }
    fields = null;
    if (Array.isArray(value) && value.every(isScalar)) blocks.push({ kind: "list", key, items: value.map(cellText) });
    else if (Array.isArray(value) && value.every(isRecord)) blocks.push(table(key, value));
    else if (isRecord(value) && depth < MAX_DEPTH)
      blocks.push({ kind: "section", key, title: keyTitle(key), blocks: documentBlocks(value, depth + 1) });
    else blocks.push({ kind: "tree", key, value });
  }
  return blocks;
}
