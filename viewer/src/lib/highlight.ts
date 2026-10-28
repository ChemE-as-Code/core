import type { HighlightKind } from "@/api";

/** Same colours as `cheme diff` (chemeascode.domains.piping.diffview._COLOURS). */
export const HIGHLIGHT_COLOURS: Record<HighlightKind, string> = {
  added: "#1a9e3f",
  removed: "#d0312d",
  modified: "#e08a00",
};

/**
 * Escape a value for use inside a double-quoted CSS string, e.g. `[id="..."]`.
 * Backslashes, quotes and control characters (newlines would end the string) become CSS
 * escapes, and `<` is escaped so the text can never close a surrounding `<style>` element.
 */
export function cssString(value: string): string {
  let out = "";
  for (const char of value) {
    const code = char.codePointAt(0) ?? 0;
    if (char === "\\" || char === '"') out += `\\${char}`;
    else if (code < 0x20 || code === 0x7f || char === "<" || char === ">")
      out += `\\${code.toString(16)} `;
    else out += char;
  }
  return out;
}

/** Only the three known kinds produce rules; anything else is ignored. */
function isHighlightKind(kind: string): kind is HighlightKind {
  return Object.prototype.hasOwnProperty.call(HIGHLIGHT_COLOURS, kind);
}

function colourOf(kind: string): string | undefined {
  return isHighlightKind(kind) ? HIGHLIGHT_COLOURS[kind] : undefined;
}

/**
 * CSS that colours each highlighted object inside the pane with DOM id `paneId`, like
 * cheme-as-code's diffview: strokes of every descendant and the fill of its text.
 */
export function highlightCss(paneId: string, highlight: Record<string, string>): string {
  const pane = `[id="${cssString(paneId)}"]`;
  const rules: string[] = [];
  for (const objectId of Object.keys(highlight).sort()) {
    const colour = colourOf(highlight[objectId] ?? "");
    if (!colour) continue;
    const selector = `${pane} [id="${cssString(objectId)}"]`;
    rules.push(
      `${selector} *{stroke:${colour}!important;stroke-width:0.8!important}` +
        `${selector} text{fill:${colour}!important;stroke:none!important}`,
    );
  }
  return rules.join("\n");
}

/** CSS that marks one selected object (the info panel's), in any pane. */
export function selectionCss(paneId: string, objectId: string | null): string {
  if (!objectId) return "";
  const selector = `[id="${cssString(paneId)}"] [id="${cssString(objectId)}"]`;
  return `${selector}{outline:none;filter:drop-shadow(0 0 1.2px var(--accent))}`;
}
