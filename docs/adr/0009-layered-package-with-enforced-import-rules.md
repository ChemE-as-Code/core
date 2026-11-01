# 0009. One package in layers, foundation, domains, project, interfaces, with enforced imports

- **Status:** Accepted
- **Date:** 2026-10-21

## Context

`plantcode` up to 0.6 was a flat package around P&ID validation. Its scope grew to process,
equipment, layout, chemistry, safety, LCA and cost, and the same functions had to serve the CLI,
the viewer API, agents, research projects and downstream applications. Without rules, engineering
logic drifts into commands and modules import each other in cycles.

## Decision

- One installable package `chemeascode` with layers: `foundation` (findings, workspace, git
  queries, reviews, provenance, units, common schemas; no engineering knowledge), `domains/<d>`
  (ten domains, each owning its schemas, rules, calculations, generators and skills), `project`
  (composition over a workspace: validate, gates, sign-off, status, impact), `interfaces/{cli,api}`
  (parsing and formatting only), `integrations` (adapters to external programs) and `templates`.
- Imports go downward only; domain-to-domain imports follow the direction information flows,
  per the table in architecture.md. Feedback travels through files and review records.
- Optional libraries are imported inside functions and live in extras; Typer only in
  `interfaces/cli`, FastAPI and uvicorn only in `interfaces/api`.
- `tests/test_boundaries.py` parses every import with `ast` and enforces the table, the empty
  package `__init__`s and the absence of optional dependencies on basic imports. Remaining
  violations are listed in `EXCEPTIONS` with a reason, and the test fails once one is no longer
  needed.
- The pattern: a domain function with explicit inputs returns a structured result with findings
  and source revision; the command only formats it (`stream_report` is the worked example).

## Consequences

- Positive: one implementation per method, callable from Python, the CLI, the API or a worker on
  a snapshot; boundaries cannot drift unnoticed.
- Negative: three known exceptions remain (`foundation.workspace` and Typer,
  `integrations.git` rendering through piping, `Workspace.parsed_lists` and the catalogue).
- Negative: module moves change import paths with no shim
  ([0018](0018-rename-plantcode-to-cheme-as-code-without-aliases.md)).

## Evidence

- "Initial ChemE-as-Code framework structure (old module paths removed)".
- `tests/test_boundaries.py`, [architecture.md](../framework/architecture.md),
  [contributing.md](../framework/contributing.md), [SUMMARY.md](../framework/SUMMARY.md),
  [migration-table.md](../framework/migration-table.md).
