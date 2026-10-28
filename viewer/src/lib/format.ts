import type { FileKind, Sheet } from "@/api";

export const KIND_ICON: Record<FileKind | "dir", string> = {
  dir: "\u{1F4C1}",
  pid: "⦿",
  yaml: "☰",
  markdown: "¶",
  json: "{}",
  other: "□",
};

export const KIND_LABEL: Record<FileKind | "dir", string> = {
  dir: "folder",
  pid: "P&ID sheet",
  yaml: "YAML",
  markdown: "Markdown",
  json: "JSON",
  other: "file",
};

/** Route name that shows a file of `kind`. */
export function viewFor(kind: FileKind): "pid" | "yaml" | "file" {
  if (kind === "pid") return "pid";
  if (kind === "yaml") return "yaml";
  return "file";
}

/** Guess a kind from a file name (for links built without the tree, e.g. from findings). */
export function kindFromPath(path: string): FileKind {
  const lower = path.toLowerCase();
  if (lower.endsWith(".xml") && (lower.startsWith("pid/") || lower.includes("/pid/"))) return "pid";
  if (lower.endsWith(".yaml") || lower.endsWith(".yml")) return "yaml";
  if (lower.endsWith(".md") || lower.endsWith(".markdown")) return "markdown";
  if (lower.endsWith(".json")) return "json";
  return "other";
}

/** `pid/P-01.xml` -> ["pid", "P-01.xml"] for repeatable route params. */
export function pathSegments(path: string): string[] {
  return path.split("/").filter(Boolean);
}

/** Route param (string or repeated segments) back to a repo-relative path. */
export function paramPath(param: string | string[] | undefined): string {
  if (Array.isArray(param)) return param.join("/");
  return param ?? "";
}

export function formatDate(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  return date.toLocaleString(undefined, { year: "numeric", month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
}

export function shortRev(rev: string | null | undefined): string {
  if (!rev) return "working tree";
  return /^[0-9a-f]{12,40}$/i.test(rev) ? rev.slice(0, 8) : rev;
}

/** Repo path of the P&ID for `sheet` (a sheet id or a file path), or null. */
export function sheetFile(sheet: string | null | undefined, sheets: readonly Sheet[] = []): string | null {
  if (!sheet) return null;
  const byId = sheets.find((s) => s.id === sheet || s.file === sheet);
  if (byId) return byId.file;
  return /\.xml$/i.test(sheet) ? sheet : null;
}
