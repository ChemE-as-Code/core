/**
 * A drawing (P&ID, PFD, BFD) as a vector PDF, made in the browser from the cleaned SVG the API
 * serves (never the live pane: no selection or diff highlight). jsPDF and svg2pdf.js are loaded
 * with a dynamic `import()` on the first export only, so the main bundle does not carry them.
 *
 * The page is the drawing at 1:1: `cheme render` draws in sheet millimetres (a unitless `width`,
 * `height` and viewBox of 420 x 297 is an A3 sheet), so a drawing that is an ISO A sheet gets that
 * sheet and any other (a 2557 x 297 PFD strip) a page of its own size, as an elongated sheet.
 */

/** ISO 216 A sizes in mm, portrait (width, height). */
export const ISO_A: readonly { name: string; width: number; height: number }[] = [
  { name: "A0", width: 841, height: 1189 },
  { name: "A1", width: 594, height: 841 },
  { name: "A2", width: 420, height: 594 },
  { name: "A3", width: 297, height: 420 },
  { name: "A4", width: 210, height: 297 },
  { name: "A5", width: 148, height: 210 },
];

const MM_PER_UNIT: Record<string, number> = { mm: 1, cm: 10, in: 25.4, pt: 25.4 / 72, pc: 25.4 / 6, px: 25.4 / 96 };

/** A length attribute (`420`, `420.0mm`, `29.7cm`, `1587px`) in mm, unitless as mm; null when absent, relative (%) or not a length. */
function lengthMm(value: string | null): number | null {
  const match = value?.trim().match(/^([+]?\d*\.?\d+(?:e[+-]?\d+)?)\s*(mm|cm|in|pt|pc|px)?$/i);
  if (!match) return null;
  const number = Number(match[1]);
  if (!Number.isFinite(number) || number <= 0) return null;
  const unit = match[2]?.toLowerCase();
  return number * (unit ? (MM_PER_UNIT[unit] ?? 1) : 1);
}

/**
 * The drawing's own size in mm, from the root's `width`/`height` (with their units) or else its
 * viewBox. A unitless size is sheet millimetres, as `cheme render` (pyDEXPI) writes it, however
 * long the sheet (the viewer's sanitizer leaves every drawing's size unitless).
 */
export function drawingSizeMm(svg: Pick<Element, "getAttribute">): { width: number; height: number } | null {
  const box = svg.getAttribute("viewBox")?.trim().split(/[\s,]+/).map(Number);
  const viewBox = box && box.length === 4 && box.every(Number.isFinite) && box[2]! > 0 && box[3]! > 0 ? { width: box[2]!, height: box[3]! } : null;
  let width = lengthMm(svg.getAttribute("width"));
  let height = lengthMm(svg.getAttribute("height"));
  if (viewBox) {
    // One side given: the other from the viewBox's aspect ratio.
    if (width && !height) height = (width * viewBox.height) / viewBox.width;
    if (height && !width) width = (height * viewBox.width) / viewBox.height;
    if (!width || !height) {
      width = viewBox.width;
      height = viewBox.height;
    }
  }
  return width && height ? { width, height } : null;
}

export interface PdfPage {
  /** ISO size name ("A3") when the drawing is an A sheet, else "custom". */
  size: string;
  orientation: "landscape" | "portrait";
  /** Page size in mm. */
  width: number;
  height: number;
  /** Where the drawing goes on the page, in mm. */
  x: number;
  y: number;
  drawingWidth: number;
  drawingHeight: number;
  /** Page mm per drawing mm: 1, except for a drawing longer than a PDF page can be. */
  scale: number;
}

/** Matching a sheet: within 1 mm on each side (pyDEXPI writes 420.0 x 297.0, a crop rounds). */
const SAME_SHEET_MM = 1;

/** The longest PDF page side readers open (14 400 units, 200 in), in mm. */
export const MAX_PAGE_MM = 5080;

/**
 * The page for a drawing of `width` x `height` mm, at 1:1, landscape when it is wider than tall:
 * the ISO A sheet it is (within 1 mm), else a page of exactly its size (an elongated sheet for a
 * long PFD strip, which plotters print and viewers zoom). Only a drawing longer than
 * `MAX_PAGE_MM` is scaled down to fit. An unknown size gives A3 landscape.
 */
export function pdfPage(size: { width: number; height: number } | null): PdfPage {
  const width = size && size.width > 0 ? size.width : 420;
  const height = size && size.height > 0 ? size.height : 297;
  const landscape = width >= height;
  const sheets = ISO_A.map((s) => ({ name: s.name, width: landscape ? s.height : s.width, height: landscape ? s.width : s.height }));
  const exact = sheets.find((s) => Math.abs(s.width - width) <= SAME_SHEET_MM && Math.abs(s.height - height) <= SAME_SHEET_MM);
  const scale = exact ? 1 : Math.min(1, MAX_PAGE_MM / Math.max(width, height));
  const pageWidth = exact ? exact.width : width * scale;
  const pageHeight = exact ? exact.height : height * scale;
  return {
    size: exact?.name ?? "custom",
    orientation: landscape ? "landscape" : "portrait",
    width: pageWidth,
    height: pageHeight,
    x: 0,
    y: 0,
    drawingWidth: pageWidth,
    drawingHeight: pageHeight,
    scale,
  };
}

/** A file-name part: letters, digits, `.`, `_` and `-`; anything else (spaces, `/`, `@`) becomes `-`. */
function namePart(text: string): string {
  return text
    .trim()
    .replace(/[^A-Za-z0-9._-]+/g, "-")
    .replace(/-{2,}/g, "-")
    .replace(/^[-.]+|-+$/g, "");
}

/**
 * `<plant>-<sheet id or file stem>[-<rev>].<ext>`: `asu-P-01-3f2a9c1b.pdf`. `rev` is the short
 * revision shown (none for the working tree).
 */
export function drawingFileName(opts: { plant?: string | null | undefined; sheet?: string | null | undefined; path: string; rev?: string | null | undefined; ext: "pdf" | "svg" }): string {
  const stem = opts.path.split("/").pop()?.replace(/\.[^.]*$/, "") ?? "";
  const parts = [opts.plant, opts.sheet || stem, opts.rev].map((p) => namePart(p ?? "")).filter(Boolean);
  return `${parts.join("-") || "drawing"}.${opts.ext}`;
}

const SANS = /^(arial|helvetica|calibri|verdana|tahoma|segoe ui|liberation sans|dejavu sans|noto sans|open sans|roboto|inter|system-ui|sans-serif)$/;
const SERIF = /^(times|times new roman|georgia|cambria|liberation serif|dejavu serif|noto serif|serif)$/;
const MONO = /^(courier|courier new|consolas|menlo|monaco|liberation mono|dejavu sans mono|monospace)$/;

/**
 * The standard PDF font (jsPDF's built-in, no embedding) for a CSS `font-family` list: the first
 * family that is a known sans (Arial, Calibri, ... -> Helvetica), serif (-> Times) or monospace
 * (-> Courier) face; Helvetica when none is known, since the drawings are lettered sans.
 */
export function pdfFont(fontFamily: string | null): "helvetica" | "times" | "courier" {
  for (const raw of (fontFamily ?? "").split(",")) {
    const family = raw.trim().replace(/^['"]|['"]$/g, "").trim().toLowerCase();
    if (SANS.test(family)) return "helvetica";
    if (SERIF.test(family)) return "times";
    if (MONO.test(family)) return "courier";
  }
  return "helvetica";
}

/**
 * Font-size factor for a family drawn as its standard PDF font. Calibri, which the P&IDs ask for,
 * has caps 0.89 the height of Helvetica's and is narrower, so its text is set in Helvetica at 0.89
 * of its size: as tall as on screen and nearly as wide (measured in Chromium).
 */
const FONT_SCALE: Record<string, number> = { calibri: 0.89 };

/**
 * How far below `y` a `dominant-baseline` puts the alphabetic baseline, in em of the PDF font.
 * `middle` centres capitals and digits (Helvetica's are 0.718 em tall) on `y`, where `cheme render`
 * puts the middle of a tag; Chromium's `middle`, half the x-height (0.26 em), leaves them 0.1 em
 * higher, unseen on screen behind its hairlines but onto a bubble's border and divider at print
 * widths. Chromium draws `text-bottom` on the alphabetic baseline, so it and any value not listed
 * is 0. svg2pdf's own mapping (to jsPDF's `middle`, `bottom`) sits text higher still.
 */
const BASELINE_EM: Record<string, number> = {
  middle: 0.36,
  central: 0.35,
  mathematical: 0.35,
  hanging: 0.72,
  "text-before-edge": 0.75,
  "text-top": 0.75,
  ideographic: -0.21,
  "text-after-edge": -0.21,
};

/** The first family of a CSS `font-family` list, lower case and unquoted. */
function firstFamily(fontFamily: string | null): string {
  return (fontFamily ?? "").split(",")[0]!.trim().replace(/^['"]|['"]$/g, "").trim().toLowerCase();
}

/** The declarations of a `style` attribute, by property (lower case), in order. */
function styleOf(el: Element): Map<string, string> {
  const map = new Map<string, string>();
  for (const decl of (el.getAttribute("style") ?? "").split(";")) {
    const at = decl.indexOf(":");
    if (at > 0) map.set(decl.slice(0, at).trim().toLowerCase(), decl.slice(at + 1).trim());
  }
  return map;
}

function setStyle(el: Element, map: Map<string, string>): void {
  const text = [...map].map(([k, v]) => `${k}: ${v}`).join("; ");
  if (text) el.setAttribute("style", text);
  else el.removeAttribute("style");
}

/** A property of `el` or of the nearest ancestor that sets it, in its `style` or as an attribute. */
function inherited(el: Element, name: string): string | null {
  for (let node: Element | null = el; node; node = node.parentElement) {
    const value = styleOf(node).get(name) ?? node.getAttribute(name);
    if (value) return value.replace(/\s*!important\s*$/i, "");
  }
  return null;
}

/** The family list at the end of a `font` shorthand (after the size), mapped by `pdfFont`. */
function mapFontShorthand(value: string): string {
  return value.replace(/^(.*?\d[\d.]*[a-z%]*(?:\s*\/\s*[\d.]+[a-z%]*)?\s+)(\S.*)$/i, (_, head: string, family: string) => `${head}${pdfFont(family)}`);
}

/** `font-family` and `font` declarations in CSS rules, mapped by `pdfFont`. */
function mapCssFonts(css: string): string {
  return css
    .replace(/(font-family\s*:\s*)([^;}]+?)(\s*(?:!important)?\s*[;}]|$)/gi, (_, head: string, family: string, tail: string) => `${head}${pdfFont(family)}${tail}`)
    .replace(/(\bfont\s*:\s*)([^;}]+?)(\s*(?:!important)?\s*[;}]|$)/gi, (_, head: string, value: string, tail: string) => `${head}${mapFontShorthand(value)}${tail}`);
}

/** Every number of a `y` list moved by `by`. */
function shiftList(value: string, by: number): string {
  return value
    .trim()
    .split(/[\s,]+/)
    .map((v) => String(Math.round((Number.parseFloat(v) + by) * 1e4) / 1e4))
    .join(" ");
}

/**
 * A copy of the drawing ready for svg2pdf, so the PDF reads like the screen:
 * - every `dominant-baseline` (which svg2pdf ignores, and maps too high when it is an
 *   `alignment-baseline`) turned into the alphabetic baseline, `y` moved down by `BASELINE_EM`;
 * - fonts mapped to the standard PDF fonts (`pdfFont`) in attributes, `style` attributes and
 *   `<style>` rules, and on the root (so unlettered text is not Times), Calibri text at 0.89 of
 *   its size (`FONT_SCALE`);
 * - the sheet background (a rect over the whole viewBox, pyDEXPI's light grey) dropped, so the
 *   page prints white.
 */
export function pdfReadySvg(source: SVGSVGElement): SVGSVGElement {
  const svg = source.cloneNode(true) as SVGSVGElement;
  for (const text of Array.from(svg.querySelectorAll("text"))) {
    const size = Number.parseFloat(inherited(text, "font-size") ?? "") || 16;
    const factor = FONT_SCALE[firstFamily(inherited(text, "font-family"))] ?? 1;
    if (factor !== 1) {
      // The text's own size, and that of any tspan sizing itself.
      for (const el of [text, ...Array.from(text.querySelectorAll("tspan"))]) {
        const style = styleOf(el);
        const own = Number.parseFloat(style.get("font-size") ?? el.getAttribute("font-size") ?? "");
        if (el !== text && !own) continue;
        el.setAttribute("font-size", String(Math.round((own || size) * factor * 1e4) / 1e4));
        if (style.delete("font-size")) setStyle(el, style);
      }
    }
    const baseline = inherited(text, "dominant-baseline") ?? inherited(text, "alignment-baseline") ?? "";
    const shift = (BASELINE_EM[baseline.trim().toLowerCase()] ?? 0) * size * factor;
    if (shift) {
      text.setAttribute("y", shiftList(text.getAttribute("y") ?? "0", shift));
      for (const tspan of Array.from(text.querySelectorAll("tspan[y]"))) tspan.setAttribute("y", shiftList(tspan.getAttribute("y")!, shift));
    }
  }
  for (const el of [svg, ...Array.from(svg.querySelectorAll("*"))]) {
    el.removeAttribute("dominant-baseline");
    el.removeAttribute("alignment-baseline");
    if (el.hasAttribute("font-family")) el.setAttribute("font-family", pdfFont(el.getAttribute("font-family")));
    if (el.hasAttribute("style")) {
      const style = styleOf(el);
      style.delete("dominant-baseline");
      style.delete("alignment-baseline");
      const family = style.get("font-family");
      if (family !== undefined) style.set("font-family", pdfFont(family));
      const font = style.get("font");
      if (font !== undefined) style.set("font", mapFontShorthand(font));
      setStyle(el, style);
    }
  }
  for (const style of Array.from(svg.querySelectorAll("style"))) style.textContent = mapCssFonts(style.textContent ?? "");
  svg.setAttribute("font-family", pdfFont(source.getAttribute("font-family")));
  const box = svg.getAttribute("viewBox")?.trim().split(/[\s,]+/).map(Number);
  const first = Array.from(svg.children).find((child) => !["metadata", "title", "desc", "defs", "style"].includes(child.localName));
  if (first?.localName === "rect" && box?.length === 4) {
    const n = (name: string) => Number.parseFloat(first.getAttribute(name) ?? "0") || 0;
    const covers = n("x") <= box[0]! && n("y") <= box[1]! && n("x") + n("width") >= box[0]! + box[2]! && n("y") + n("height") >= box[1]! + box[3]!;
    if (covers) first.remove();
  }
  return svg;
}

/** What goes into the PDF's document information. */
export interface PdfInfo {
  title: string;
  subject?: string;
}

/** The drawing as a one-page vector PDF (text stays text). Loads jsPDF and svg2pdf.js on first use. */
export async function drawingPdf(source: SVGSVGElement, info: PdfInfo): Promise<Blob> {
  const [{ jsPDF }, { svg2pdf }] = await Promise.all([import("jspdf"), import("svg2pdf.js")]);
  const page = pdfPage(drawingSizeMm(source));
  const doc = new jsPDF({ orientation: page.orientation, unit: "mm", format: [page.width, page.height], compress: true });
  doc.setDocumentProperties({ title: info.title, subject: info.subject ?? "", creator: "cheme-as-code viewer" });
  await svg2pdf(pdfReadySvg(source), doc, { x: page.x, y: page.y, width: page.drawingWidth, height: page.drawingHeight, loadImages: false });
  return doc.output("blob");
}

/** Save `blob` as `name` through a temporary object URL. */
export function saveBlob(blob: Blob, name: string): void {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
