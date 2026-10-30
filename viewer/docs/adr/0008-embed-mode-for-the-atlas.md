# 0008. Embed mode and theme override for the Process Atlas

- **Status:** Accepted
- **Date:** 2026-10-23

## Context

The Process Atlas (ChemE-as-Code/website) shows the engineering model of each process. Copying
the viewer's rendering code into the Atlas would fork it. Framing the full viewer shows a second
header and file tree inside the Atlas page, and its colour scheme may not match the page around
it.

## Decision

The Atlas frames the viewer itself (its static build on a snapshot, ADR 0004). Two query
parameters, before the hash and read once at startup (`src/lib/viewerOptions.ts`), adapt it:

- `?embed=1`: no header and no file tree; the routed view fills the frame and keeps its
  toolbar; a small "Open full viewer" link opens the same page without `embed` in a new tab.
- `?theme=light|dark|system`: sets `data-theme` on `<html>`; `system` follows
  `prefers-color-scheme`.

Both survive in-app navigation, with and without `?data=`.

## Consequences

- One viewer, no copied rendering code; the Atlas gets new viewer pages by rebuilding.
- The dark tokens are written twice (media query and `data-theme`); a unit test keeps them
  equal. Code that needs the scheme in JS asks `isDarkScheme()`.
- Embedding is a public interface: query parameters and routes the Atlas deep-links must stay
  stable.

## Evidence

- pre-release viewer commit ac41eb3 (pre-release viewer PR 29) "Embed mode and theme override: ?embed=1, ?theme=light|dark|system".
- pre-release viewer commit d1a43a2 (pre-release viewer PR 30) keep them across in-app navigation against a server.
- `e2e/embed.spec.ts`, `tests/viewerOptions.test.ts`; REFERENCE.md (formerly the README), "Embedding".
