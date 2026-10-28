/**
 * A tiny Markdown parser that produces a plain data tree (never HTML strings). The tree is
 * rendered with Vue's `h()`, so all text is escaped by construction and raw HTML in the source
 * is shown as text.
 */

export type Inline =
  | { t: "text"; text: string }
  | { t: "code"; text: string }
  | { t: "strong"; children: Inline[] }
  | { t: "em"; children: Inline[] }
  | { t: "link"; href: string; children: Inline[] };

export type Block =
  | { t: "heading"; level: number; children: Inline[] }
  | { t: "paragraph"; children: Inline[] }
  | { t: "code"; lang: string; text: string }
  | { t: "quote"; children: Block[] }
  | { t: "list"; ordered: boolean; items: Block[][] }
  | { t: "table"; header: Inline[][]; rows: Inline[][][] }
  | { t: "hr" };

/** Only http(s), mailto and relative links survive; everything else becomes plain text. */
export function safeHref(href: string): string | null {
  const value = href.trim();
  if (/^(https?:|mailto:)/i.test(value)) return value;
  if (/^[a-z][a-z0-9+.-]*:/i.test(value) || value.startsWith("//")) return null;
  return value;
}

export function parseInline(src: string): Inline[] {
  const out: Inline[] = [];
  let text = "";
  const flush = () => {
    if (text) out.push({ t: "text", text });
    text = "";
  };
  let i = 0;
  while (i < src.length) {
    const rest = src.slice(i);
    let m: RegExpExecArray | null;
    if (rest[0] === "\\" && rest.length > 1 && /[\\`*_[\]()#+\-.!|<>]/.test(rest[1] ?? "")) {
      text += rest[1];
      i += 2;
    } else if ((m = /^(`+)([\s\S]*?[^`])\1(?!`)/.exec(rest))) {
      flush();
      out.push({ t: "code", text: (m[2] ?? "").trim() });
      i += m[0].length;
    } else if ((m = /^\[([^\]]*)\]\(([^)\s]*)(?:\s+"[^"]*")?\)/.exec(rest))) {
      flush();
      const href = safeHref(m[2] ?? "");
      const children = parseInline(m[1] ?? "");
      if (href) out.push({ t: "link", href, children });
      else out.push(...children);
      i += m[0].length;
    } else if ((m = /^(\*\*|__)(?=\S)([\s\S]*?\S)\1/.exec(rest))) {
      flush();
      out.push({ t: "strong", children: parseInline(m[2] ?? "") });
      i += m[0].length;
    } else if ((m = /^(\*|_)(?=\S)([\s\S]*?\S)\1(?![*_])/.exec(rest)) && (m[1] === "*" || !/\w/.test(src[i - 1] ?? ""))) {
      flush();
      out.push({ t: "em", children: parseInline(m[2] ?? "") });
      i += m[0].length;
    } else {
      text += rest[0];
      i += 1;
    }
  }
  flush();
  return out;
}

/** The text of inline nodes without their markup (a heading's text, for its id). */
export function inlineText(nodes: Inline[]): string {
  return nodes.map((node) => (node.t === "text" || node.t === "code" ? node.text : inlineText(node.children))).join("");
}

/**
 * Rendered headings' DOM ids carry GitHub's prefix, so a heading never takes one of the app's own
 * ids (`# Main` would be `main`, the skip link's target); links name them without it.
 */
export const HEADING_ID_PREFIX = "user-content-";

/**
 * Heading ids as GitHub gives them, so `[x](#design-basis)` links written for GitHub work here:
 * lower case, punctuation dropped, spaces as hyphens, and `-1`, `-2` ... for repeated headings
 * of one document. Make one slugger per document.
 */
export function createSlugger(): (text: string) => string {
  const seen = new Map<string, number>();
  return (text) => {
    const base = text
      .trim()
      .toLowerCase()
      .replace(/[^\p{L}\p{M}\p{N}\p{Pc}\- ]/gu, "")
      .replace(/ /g, "-");
    let slug = base;
    while (seen.has(slug)) {
      const count = (seen.get(base) ?? 0) + 1;
      seen.set(base, count);
      slug = `${base}-${count}`;
    }
    seen.set(slug, 0);
    return slug;
  };
}

function splitRow(line: string): string[] {
  let row = line.trim();
  if (row.startsWith("|")) row = row.slice(1);
  if (row.endsWith("|") && !row.endsWith("\\|")) row = row.slice(0, -1);
  return row.split(/(?<!\\)\|/).map((cell) => cell.trim().replace(/\\\|/g, "|"));
}

const LIST_ITEM = /^(\s*)([-*+]|\d+[.)])\s+(.*)$/;

export function parseMarkdown(src: string): Block[] {
  const lines = src.replace(/\r\n?/g, "\n").split("\n");
  return parseBlocks(lines);
}

function parseBlocks(lines: string[]): Block[] {
  const blocks: Block[] = [];
  let i = 0;
  while (i < lines.length) {
    const line = lines[i] ?? "";
    let m: RegExpExecArray | null;
    if (!line.trim()) {
      i++;
    } else if ((m = /^\s*(```+|~~~+)\s*([\w+-]*)/.exec(line))) {
      const fence = m[1] ?? "```";
      const body: string[] = [];
      i++;
      while (i < lines.length && !(lines[i] ?? "").trim().startsWith(fence)) body.push(lines[i++] ?? "");
      i++;
      blocks.push({ t: "code", lang: m[2] ?? "", text: body.join("\n") });
    } else if ((m = /^(#{1,6})\s+(.*?)\s*#*\s*$/.exec(line))) {
      blocks.push({ t: "heading", level: (m[1] ?? "#").length, children: parseInline(m[2] ?? "") });
      i++;
    } else if (/^\s*([-*_])(\s*\1){2,}\s*$/.test(line)) {
      blocks.push({ t: "hr" });
      i++;
    } else if (/^\s*>/.test(line)) {
      const body: string[] = [];
      while (i < lines.length && /^\s*>/.test(lines[i] ?? "")) body.push((lines[i++] ?? "").replace(/^\s*>\s?/, ""));
      blocks.push({ t: "quote", children: parseBlocks(body) });
    } else if (line.includes("|") && /^\s*\|?\s*:?-+:?\s*(\|\s*:?-+:?\s*)*\|?\s*$/.test(lines[i + 1] ?? "")) {
      const header = splitRow(line).map(parseInline);
      i += 2;
      const rows: Inline[][][] = [];
      while (i < lines.length && (lines[i] ?? "").includes("|") && (lines[i] ?? "").trim())
        rows.push(splitRow(lines[i++] ?? "").map(parseInline));
      blocks.push({ t: "table", header, rows });
    } else if ((m = LIST_ITEM.exec(line))) {
      const ordered = /\d/.test(m[2] ?? "");
      const indent = (m[1] ?? "").length;
      const items: string[][] = [];
      while (i < lines.length) {
        const current = lines[i] ?? "";
        const item = LIST_ITEM.exec(current);
        if (item && (item[1] ?? "").length <= indent) {
          if (/\d/.test(item[2] ?? "") !== ordered) break;
          items.push([item[3] ?? ""]);
          i++;
        } else if (current.trim() && (/^\s+/.test(current) || !items.length)) {
          items[items.length - 1]?.push(current.replace(new RegExp(`^\\s{0,${indent + 4}}`), ""));
          i++;
        } else if (!current.trim() && /^\s+\S/.test(lines[i + 1] ?? "")) {
          // A blank line followed by an indented line continues the current item.
          items[items.length - 1]?.push("");
          i++;
        } else break;
      }
      blocks.push({ t: "list", ordered, items: items.map((body) => parseBlocks(body)) });
    } else {
      const body: string[] = [];
      while (
        i < lines.length &&
        (lines[i] ?? "").trim() &&
        !/^(#{1,6}\s|\s*```|\s*~~~|\s*>)/.test(lines[i] ?? "") &&
        !(body.length && LIST_ITEM.test(lines[i] ?? ""))
      )
        body.push((lines[i++] ?? "").trim());
      blocks.push({ t: "paragraph", children: parseInline(body.join(" ")) });
    }
  }
  return blocks;
}
