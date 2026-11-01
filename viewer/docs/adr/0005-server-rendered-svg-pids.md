# 0005. P&IDs as server-rendered SVG from pyDEXPI, sanitized in the browser

- **Status:** Accepted
- **Date:** 2026-10-17

## Context

P&IDs are DEXPI XML. Drawing them in the browser would need a DEXPI renderer in JavaScript
(such as dexpi-js) or an existing viewer component (such as DigiCo's), each a second rendering
of the same drawing that can disagree with what core's `cheme render` produces, and a large
dependency. Core already renders DEXPI to SVG through pyDEXPI's SVG export. An SVG inserted into
the page is, however, active content.

## Decision

Rendering is SVG only, done on the server: `cheme serve` renders P&IDs to SVG with pyDEXPI's
SVG export (other drawings, such as datasheet sheets, also arrive as SVG from core), and the
viewer shows that SVG with its own pan, zoom, picking and diff highlighting. No dexpi-js and no DigiCo viewer components.

The SVG is cleaned before it is shown (`src/lib/sanitize.ts`): scripts, `foreignObject`,
animation elements, `on*` attributes, script URLs and links or images on other sites are
removed; CSS is rebuilt from an allow-list of drawing properties with inert values, and
`<style>` rules are scoped to the drawing's `data-svg-scope`. The cleaned element is inserted
with `importNode`, never parsed as HTML. The same stance applies to all API content: rendered
as text through Vue's escaping, Markdown parsed to a tree and rendered with `h()`.

## Consequences

- One rendering for the CLI, the viewer and the Atlas previews; what the viewer shows is what
  `cheme render` writes.
- Diff highlighting relies on object ids in the SVG (`[id="..."]` rules), so core's renderer
  must keep DEXPI ids on the drawn elements (the title block gets its Label id for that).
- Drawing quality and features are limited by pyDEXPI's export; the viewer cannot restyle
  symbols. Every drawing costs a server round trip (or a file in a snapshot).
- The sanitizer is security-critical code that needs its own tests (`tests/sanitize.test.ts`).

## Evidence

- "Milestone 2 scope": "Rendering is SVG only: no dexpi-js and no DigiCo viewer
  components."
- "sanitized inline SVG"; title-block ids.
- "Rebuild SVG CSS from an allow-list and scope
  <style> rules to the drawing".
