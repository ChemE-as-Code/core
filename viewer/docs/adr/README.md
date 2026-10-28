# Architecture decision records

This folder records the architecture decisions of the viewer: what was decided, why, and what
it costs. Each record (ADR) is short, numbered and immutable once accepted; a later decision
that changes an earlier one supersedes it with a new record instead of editing it.

ADRs 0002 to 0013 were written retroactively on 2026-10-25 from the README, the code and the git
history. Each one is dated by the commit that took the decision and lists that evidence.

## Adding a decision

A pull request that changes the architecture (a new data source, a new rendering path, a new
dependency of weight, a change to the embedding interface, ...) adds an ADR in the same pull
request:

1. Copy [the template](template.md) to `NNNN-kebab-title.md`, with the next free number.
2. Fill in Context, Decision, Consequences (the negative ones too) and Evidence; status
   `Proposed`, then `Accepted` when the pull request is merged.
3. If it replaces an earlier decision, set that record's status to `Superseded by NNNN` (the only
   edit an accepted ADR gets).
4. Add it to the index below and to the `nav` of `mkdocs.yml` (`mkdocs build --strict` fails on a
   page left out).

## Index

| ADR | Decision | Status | Date |
| --- | --- | --- | --- |
| [0001](0001-record-architecture-decisions.md) | Record architecture decisions | Accepted | 2026-10-25 |
| [0002](0002-read-only-viewer.md) | The viewer is read-only | Accepted | 2026-10-17 |
| [0003](0003-data-only-through-the-api-client.md) | Data only through the `cheme serve` API, behind one typed client | Accepted | 2026-10-17 |
| [0004](0004-static-snapshots-same-origin.md) | Static snapshots as a second data source, same-origin only | Accepted | 2026-10-22 |
| [0005](0005-server-rendered-svg-pids.md) | P&IDs as server-rendered SVG from pyDEXPI, sanitized in the browser | Accepted | 2026-10-17 |
| [0006](0006-schema-driven-yaml-tables.md) | YAML lists as tables driven by their JSON Schema | Accepted | 2026-10-17 |
| [0007](0007-diff-semantics-shared-with-cheme-diff.md) | Visual diff semantics shared with `cheme diff` | Accepted | 2026-10-17 |
| [0008](0008-embed-mode-for-the-atlas.md) | Embed mode and theme override for the Process Atlas | Accepted | 2026-10-23 |
| [0009](0009-threejs-3d-layout.md) | three.js for the 3D layout, loaded on demand, with pure scene logic | Accepted | 2026-10-17 |
| [0010](0010-accessibility-and-keyboard-model.md) | Accessibility and keyboard model | Accepted | 2026-10-25 |
| [0011](0011-testing-with-api-fixtures-and-playwright.md) | Tests on real API fixtures: vitest units and Playwright with a mocked API | Accepted | 2026-10-17 |
| [0012](0012-rename-to-cheme-as-code-viewer.md) | Rename from plantcode-viewer to cheme-as-code-viewer | Accepted | 2026-10-22 |
| [0013](0013-agpl-licence.md) | AGPL-3.0-or-later licence | Accepted | 2026-10-25 |
