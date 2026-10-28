/**
 * The SVG comes from our own server, but it is still parsed and cleaned before it is put into
 * the page: no scripts, no foreign HTML, no event handlers, no script URLs, nothing that loads a
 * resource from elsewhere, and no CSS that reaches outside the drawing.
 *
 * CSS is never matched with a pattern against the raw text (escapes such as `u\72l(` would get
 * through). Declarations are rebuilt from an allow-list of drawing properties whose values may
 * call no function but colours and `url(#fragment)`, and `<style>` rules are kept only when their
 * selectors are plain type, class and id selectors, which are then prefixed with the drawing's
 * own scope attribute.
 */

const SVG_NS = "http://www.w3.org/2000/svg";

/** Elements that are removed with their content. */
const FORBIDDEN = new Set([
  "script",
  "foreignobject",
  "iframe",
  "object",
  "embed",
  "audio",
  "video",
  "animate",
  "animatemotion",
  "animatetransform",
  "set",
  "handler",
  "listener",
]);

const XLINK_NS = "http://www.w3.org/1999/xlink";

/** Attributes holding a URL, by local name; checked in no namespace and in XLink, any prefix. */
const URL_ATTRS = new Set(["href", "src", "action", "formaction"]);

function unsafeUrl(value: string): boolean {
  // Strip whitespace and control characters browsers ignore inside a scheme.
  const compact = value.replace(/[\u0000- \u007f]+/g, "").toLowerCase();
  if (compact.startsWith("#")) return false;
  if (compact.startsWith("data:image/") && !compact.startsWith("data:image/svg")) return false;
  return /^[a-z][a-z0-9+.-]*:/.test(compact) || compact.startsWith("//");
}

/** CSS properties a drawing may set, in `style` attributes and `<style>` rules. */
const CSS_PROPERTIES = new Set([
  "fill",
  "fill-opacity",
  "fill-rule",
  "stroke",
  "stroke-width",
  "stroke-opacity",
  "stroke-dasharray",
  "stroke-dashoffset",
  "stroke-linecap",
  "stroke-linejoin",
  "stroke-miterlimit",
  "opacity",
  "color",
  "display",
  "visibility",
  "vector-effect",
  "paint-order",
  "shape-rendering",
  "text-rendering",
  "pointer-events",
  "clip-path",
  "clip-rule",
  "mask",
  "filter",
  "marker",
  "marker-start",
  "marker-mid",
  "marker-end",
  "stop-color",
  "stop-opacity",
  "flood-color",
  "flood-opacity",
  "lighting-color",
  "font",
  "font-family",
  "font-size",
  "font-style",
  "font-variant",
  "font-weight",
  "font-stretch",
  "letter-spacing",
  "word-spacing",
  "text-anchor",
  "text-decoration",
  "dominant-baseline",
  "alignment-baseline",
  "baseline-shift",
  "white-space",
]);

/** CSS functions a value may call besides `url(#fragment)`: colours, and transforms in attributes. */
const CSS_FUNCTIONS = new Set(["rgb", "rgba", "hsl", "hsla"]);
const TRANSFORM_FUNCTIONS = new Set([...CSS_FUNCTIONS, "matrix", "translate", "scale", "rotate", "skewx", "skewy"]);

/** Attributes that are names or text, never parsed as CSS. */
const PLAIN_ATTRS = /^(?:id|class|role|lang|data-.*|aria-.*)$/;

/**
 * Whether a CSS value can load nothing: no escapes (the CSS tokenizer would decode them after any
 * check on the text) and no function call except `functions` and `url()` of a fragment, which
 * refers to an element of the page itself.
 */
function inertValue(value: string, functions: ReadonlySet<string>): boolean {
  if (value.includes("\\")) return false;
  const rest = value.replace(/url\(\s*(["']?)#[-\w.:]*\1\s*\)/gi, "");
  for (const call of rest.matchAll(/([-\w]*)\s*\(/g)) {
    if (!functions.has((call[1] ?? "").toLowerCase())) return false;
  }
  return true;
}

/** The allowed, inert declarations of a CSS declaration list, rebuilt as `prop:value;...`. */
function cleanDeclarations(text: string): string {
  const kept: string[] = [];
  for (const declaration of text.replace(/\/\*[\s\S]*?\*\//g, " ").split(";")) {
    const colon = declaration.indexOf(":");
    if (colon < 0) continue;
    const property = declaration.slice(0, colon).trim().toLowerCase();
    const value = declaration.slice(colon + 1).trim();
    // strings must be closed on the same declaration, or the browser reads on into the next one
    const balanced = !/["']/.test(value.replace(/"[^"\n]*"|'[^'\n]*'/g, ""));
    if (CSS_PROPERTIES.has(property) && value && balanced && inertValue(value, CSS_FUNCTIONS)) kept.push(`${property}:${value}`);
  }
  return kept.join(";");
}

const IDENT = "-?[_a-zA-Z][-\\w]*";
const COMPOUND = `(?:(?:[a-zA-Z][-\\w]*|\\*)(?:[.#]${IDENT})*|(?:[.#]${IDENT})+)`;
/** Type, class and id selectors joined by descendant or child combinators; nothing else. */
const SELECTOR = new RegExp(`^${COMPOUND}(?:\\s*>\\s*${COMPOUND}|\\s+${COMPOUND})*$`);

/**
 * The rules of a `<style>` sheet that only style the drawing, each selector prefixed with
 * `scope`, so no rule can match outside it. At-rules (`@import`, `@font-face`, `@media`, ...)
 * and selectors with pseudo-classes, attributes or sibling combinators are dropped; parsing stops
 * at the first thing that is not a plain `selectors { declarations }` rule.
 */
function cleanStyleSheet(text: string, scope: string): string {
  const rules: string[] = [];
  const rule = /\s*([^{}]*)\{([^{}]*)\}/y;
  const css = text.replace(/\/\*[\s\S]*?\*\//g, " ");
  let match: RegExpExecArray | null;
  while ((match = rule.exec(css))) {
    const selectors = (match[1] ?? "").split(",").map((selector) => selector.trim());
    const declarations = cleanDeclarations(match[2] ?? "");
    if (!declarations || !selectors.every((selector) => SELECTOR.test(selector))) continue;
    rules.push(`${selectors.map((selector) => `${scope} ${selector}`).join(", ")}{${declarations}}`);
  }
  return rules.join("\n");
}

/** Attribute on the root `<svg>` that its own `<style>` rules are scoped to. */
export const SCOPE_ATTR = "data-svg-scope";
let scopes = 0;

export interface SanitizedSvg {
  /**
   * The cleaned `<svg>` element (in its own XML document). Insert it with
   * `document.importNode(element, true)`, never through innerHTML, so it is not re-parsed as HTML.
   */
  element: SVGSVGElement;
  /** Serialized, cleaned `<svg>` markup. */
  markup: string;
  /** Size from the viewBox (or width/height); 0 when unknown. */
  width: number;
  height: number;
}

function cleanElement(element: Element, scope: string): void {
  for (const child of Array.from(element.children)) {
    if (FORBIDDEN.has(child.localName.toLowerCase()) || child.namespaceURI !== SVG_NS) {
      child.remove();
      continue;
    }
    cleanElement(child, scope);
  }
  for (const attr of Array.from(element.attributes)) {
    // Compare namespace + local name, never the qualified name: `x:href` with xmlns:x bound to
    // XLink is an XLink href too.
    const local = attr.localName.toLowerCase();
    const ns = attr.namespaceURI;
    const remove = () => element.removeAttributeNode(attr);
    if (local.startsWith("on")) remove();
    else if (ns === XLINK_NS && local !== "href") remove(); // no XLink behaviour but links
    else if (URL_ATTRS.has(local) && (ns === null || ns === XLINK_NS) && unsafeUrl(attr.value)) remove();
    else if (URL_ATTRS.has(local) && ns !== null && ns !== XLINK_NS) remove(); // foreign-namespace URL
    else if (local === SCOPE_ATTR) remove(); // only the root carries it, set by sanitizeSvg
    else if (local === "style" && ns === null) {
      const declarations = cleanDeclarations(attr.value);
      if (declarations) attr.value = declarations;
      else remove();
    } else if (!PLAIN_ATTRS.test(local) && !inertValue(attr.value, local.endsWith("transform") ? TRANSFORM_FUNCTIONS : CSS_FUNCTIONS)) {
      remove(); // a presentation attribute such as fill="url(https://...)" or cursor="url(...)"
    }
  }
  if (element.localName.toLowerCase() === "style") {
    const css = cleanStyleSheet(element.textContent ?? "", scope);
    if (css) element.textContent = css;
    else element.remove();
  }
}

function sizeOf(svg: Element): { width: number; height: number } {
  const viewBox = svg.getAttribute("viewBox")?.trim().split(/[\s,]+/).map(Number);
  if (viewBox && viewBox.length === 4 && viewBox.every(Number.isFinite)) {
    return { width: viewBox[2] ?? 0, height: viewBox[3] ?? 0 };
  }
  const width = Number.parseFloat(svg.getAttribute("width") ?? "");
  const height = Number.parseFloat(svg.getAttribute("height") ?? "");
  return { width: Number.isFinite(width) ? width : 0, height: Number.isFinite(height) ? height : 0 };
}

/** Parse `text` as SVG and return cleaned markup; throws if it is not an SVG document. */
export function sanitizeSvg(text: string): SanitizedSvg {
  const doc = new DOMParser().parseFromString(text, "image/svg+xml");
  const root = doc.documentElement;
  if (!root || root.localName !== "svg" || root.namespaceURI !== SVG_NS || doc.querySelector("parsererror")) {
    throw new Error("The server did not return a valid SVG document.");
  }
  const scope = `s${++scopes}`;
  cleanElement(root, `svg[${SCOPE_ATTR}="${scope}"]`);
  root.setAttribute(SCOPE_ATTR, scope);
  const { width, height } = sizeOf(root);
  if (!root.getAttribute("viewBox") && width && height) root.setAttribute("viewBox", `0 0 ${width} ${height}`);
  // The pan/zoom layer sizes the drawing; the intrinsic size is kept as the viewBox.
  root.setAttribute("width", String(width || 1000));
  root.setAttribute("height", String(height || 700));
  root.setAttribute("preserveAspectRatio", "xMidYMid meet");
  return {
    element: root as unknown as SVGSVGElement,
    markup: new XMLSerializer().serializeToString(root),
    width,
    height,
  };
}
