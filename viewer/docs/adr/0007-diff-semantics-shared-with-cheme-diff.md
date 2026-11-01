# 0007. Visual diff semantics shared with `cheme diff`

- **Status:** Accepted
- **Date:** 2026-10-17

## Context

Reviewing a change to a P&ID is a central use of the viewer. Core already has `cheme diff`,
which decides what counts as added, removed or modified and colours it. A viewer with its own
diff rules would show reviewers a different answer from the CLI and the CI.

## Decision

The viewer computes no diff of its own. The server answers the diff (changed ids, the change
table and the pyDEXPI projection diff); the viewer highlights the changed objects in the two
SVGs with CSS rules on `[id="..."]`, scoped to each pane and escaped for CSS strings, in the
same colours as `cheme diff` (added green, removed red, modified orange; `src/lib/highlight.ts`).
A plant metadata change is mapped to the title block by the server. Side-by-side and overlay
views share pan and zoom.

## Consequences

- The CLI, the CI and the viewer agree on what changed.
- Changes to diff semantics happen in core; the viewer follows.
- Diff needs two revisions and therefore a server; it is hidden in static snapshots (ADR 0004).

## Evidence

- "changed items highlighted, as plantcode diff does".
- "highlight CSS in plantcode diff colours, change table and
  projection diff"; title-block highlight; plant item of each changed object.
