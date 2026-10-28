/**
 * A small YAML tokenizer for syntax highlighting the source view. It produces plain-text tokens
 * (never HTML): the view renders each token's text through Vue's escaping, in a `<span>` whose
 * class is the token type. It is line-based with one piece of state carried between lines, the
 * block scalar (`key: |` / `key: >`), whose more-indented lines are all string content.
 *
 * It is a highlighter, not a parser: anything it does not recognise is `plain`, and the tokens
 * of a line always join back to exactly that line.
 */

export type YamlTokenType =
  | "plain"
  | "key"
  | "punct"
  | "comment"
  | "string"
  | "number"
  | "literal"
  | "anchor"
  | "tag"
  | "document";

export interface YamlToken {
  type: YamlTokenType;
  text: string;
}

const NUMBER = /^[-+]?(?:0x[0-9a-fA-F]+|0o[0-7]+|(?:\d[\d_]*)?\.?\d[\d_]*(?:[eE][-+]?\d+)?|\.inf|\.Inf|\.INF|\.nan|\.NaN|\.NAN)$/;
const LITERAL = /^(?:true|false|True|False|TRUE|FALSE|yes|no|Yes|No|YES|NO|on|off|On|Off|ON|OFF|null|Null|NULL|~)$/;
const BLOCK_SCALAR = /^[|>][-+0-9]*$/;

function push(tokens: YamlToken[], type: YamlTokenType, text: string): void {
  if (!text) return;
  const last = tokens[tokens.length - 1];
  if (last && last.type === type) last.text += text;
  else tokens.push({ type, text });
}

/** Where a quoted string starting at `start` ends (index after the closing quote, or line end). */
function quoteEnd(line: string, start: number): number {
  const quote = line[start];
  for (let i = start + 1; i < line.length; i++) {
    if (quote === '"' && line[i] === "\\") {
      i++;
      continue;
    }
    if (line[i] === quote) {
      if (quote === "'" && line[i + 1] === "'") {
        i++;
        continue;
      }
      return i + 1;
    }
  }
  return line.length;
}

/** The type of a plain (unquoted) scalar. */
function scalarType(text: string): YamlTokenType {
  const value = text.trim();
  if (NUMBER.test(value)) return "number";
  if (LITERAL.test(value)) return "literal";
  return "plain";
}

/** Index of a `#` that starts a comment (at the start or after whitespace), or -1. */
function commentStart(line: string, from: number): number {
  for (let i = from; i < line.length; i++) {
    if (line[i] === "#" && (i === 0 || line[i - 1] === " " || line[i - 1] === "\t")) return i;
  }
  return -1;
}

/** Index of the `:` ending a plain mapping key (followed by a space or the line end), or -1. */
function keyColon(line: string, from: number): number {
  const char = line[from];
  if (char === undefined || "[]{},#&*!|>%@`".includes(char)) return -1;
  for (let i = from; i < line.length; i++) {
    const c = line[i];
    if (c === "#" && (line[i - 1] === " " || line[i - 1] === "\t")) return -1;
    if (c === ":" && (i + 1 === line.length || line[i + 1] === " " || line[i + 1] === "\t")) return i;
  }
  return -1;
}

/** Tokens of a value (after `key: ` or `- `), up to the line end. */
function valueTokens(tokens: YamlToken[], line: string, start: number): boolean {
  let i = start;
  let blockScalar = false;
  // Unclosed `[` / `{`: flow indicators and `key:` only mean something inside a collection.
  let depth = 0;
  while (i < line.length) {
    const char = line[i] ?? "";
    if (char === " " || char === "\t") {
      push(tokens, "plain", char);
      i++;
    } else if (char === "#" && (i === 0 || line[i - 1] === " " || line[i - 1] === "\t")) {
      push(tokens, "comment", line.slice(i));
      break;
    } else if (char === '"' || char === "'") {
      const end = quoteEnd(line, i);
      push(tokens, "string", line.slice(i, end));
      i = end;
    } else if (char === "&" || char === "*") {
      const match = /^[&*][^\s,[\]{}]+/.exec(line.slice(i));
      const text = match ? match[0] : char;
      push(tokens, "anchor", text);
      i += text.length;
    } else if (char === "!") {
      const text = /^!\S*/.exec(line.slice(i))?.[0] ?? char;
      push(tokens, "tag", text);
      i += text.length;
    } else if (char === "[" || char === "{" || (depth > 0 && "]},".includes(char))) {
      if (char === "[" || char === "{") depth++;
      else if (char !== ",") depth--;
      push(tokens, "punct", char);
      i++;
    } else if (depth === 0) {
      // A block-context plain scalar: everything up to a comment (commas and brackets included).
      const comment = commentStart(line, i);
      const word = line.slice(i, comment < 0 ? line.length : comment).trimEnd() || char;
      if (BLOCK_SCALAR.test(word)) {
        push(tokens, "punct", word);
        blockScalar = true;
      } else push(tokens, scalarType(word), word);
      i += word.length;
    } else {
      // A plain scalar inside a flow collection: up to a comment or a flow indicator.
      const rest = line.slice(i);
      const word = /^[^\s,[\]{}#]+(?:[ \t]+[^\s,[\]{}#]+)*/.exec(rest)?.[0] ?? char;
      // `key: value` inside a flow mapping: colour the key.
      const flowKey = /^([^\s,[\]{}:#][^,[\]{}:#]*?)(:)(?=\s|$)/.exec(word);
      if (flowKey && (flowKey[1]?.length ?? 0) < word.length) {
        push(tokens, "key", flowKey[1] ?? "");
        push(tokens, "punct", ":");
        i += (flowKey[1]?.length ?? 0) + 1;
        continue;
      }
      push(tokens, scalarType(word), word);
      i += word.length;
    }
  }
  return blockScalar;
}

function indentOf(line: string): number {
  return /^ */.exec(line)?.[0].length ?? 0;
}

/** Highlight tokens for every line of `text` (split on `\n`; a `\r` stays in the last token). */
export function highlightYaml(text: string): YamlToken[][] {
  const out: YamlToken[][] = [];
  // Indent of the line that opened a block scalar; its content is more indented.
  let blockIndent: number | null = null;
  for (const line of text.split("\n")) {
    const tokens: YamlToken[] = [];
    const indent = indentOf(line);
    if (blockIndent !== null) {
      if (line.trim() === "" || indent > blockIndent) {
        push(tokens, "string", line);
        out.push(tokens);
        continue;
      }
      blockIndent = null;
    }
    if (/^(?:---|\.\.\.)(?:\s|$)/.test(line)) {
      push(tokens, "document", line.slice(0, 3));
      valueTokens(tokens, line, 3);
      out.push(tokens);
      continue;
    }
    if (line.startsWith("%")) {
      push(tokens, "tag", line);
      out.push(tokens);
      continue;
    }
    let i = 0;
    push(tokens, "plain", line.slice(0, indent));
    i = indent;
    // Sequence entries: `- `, possibly several on one line (`- - a`).
    let parentColumn = indent;
    while (line[i] === "-" && (i + 1 === line.length || line[i + 1] === " ")) {
      parentColumn = i;
      push(tokens, "punct", "-");
      i++;
      const spaces = /^ */.exec(line.slice(i))?.[0] ?? "";
      push(tokens, "plain", spaces);
      i += spaces.length;
    }
    // A block scalar's content is indented past its key's column (or its entry's dash).
    const keyColumn = i;
    const comment = commentStart(line, i);
    if (comment === i) {
      push(tokens, "comment", line.slice(i));
      out.push(tokens);
      continue;
    }
    let colon = -1;
    if (line[i] === '"' || line[i] === "'") {
      const end = quoteEnd(line, i);
      if (line[end] === ":" && (end + 1 === line.length || line[end + 1] === " ")) {
        push(tokens, "key", line.slice(i, end));
        colon = end;
      }
    } else {
      colon = keyColon(line, i);
      if (colon >= 0) push(tokens, "key", line.slice(i, colon));
    }
    if (colon >= 0) {
      push(tokens, "punct", ":");
      i = colon + 1;
    }
    if (valueTokens(tokens, line, i)) blockIndent = colon >= 0 ? keyColumn : parentColumn;
    out.push(tokens);
  }
  return out;
}
