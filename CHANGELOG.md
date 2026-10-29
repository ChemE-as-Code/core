# Changelog

## Unreleased

- Safety: three HAZOP skills, guidance only (no new command): `hazop-node-breakdown` (nodes
  by named boundary rules, with members and design intent), `hazop-scenario-propagation`
  (causes inside the node, consequences followed object by object over the P&ID to a top
  event, then the fluid's outcome) and `hazop-risk-classification` (severity and likelihood
  codes suggested from the project's risk matrix, with their basis). Everything they write
  is `status: proposed`.
- Safety: `cheme safety hazop propagate STUDY --node N [--deviation D] [--json]` walks each
  failure mode of a node's objects over the study's analysed P&IDs (pyDEXPI objects, no graph
  library) to a top event, a study limit or an object that absorbs it, with the candidate
  safeguards on the path and the questions the files leave open; read-only. The failure modes
  are project data in `safety/failure-modes.yaml` (new kind `failure-modes`,
  `cheme/failure-modes/v1`); none are shipped (ADR 0032).

## 0.8.0 (2026-10-28): initial public release

The first public version of cheme-as-code: the `cheme` toolkit, the viewer and the agent runner
in one repository, under AGPL-3.0-or-later. Earlier, pre-release development is not part of this
repository's history; references to it read "pre-release issue 123", "pre-release viewer PR 49",
"pre-release commit 4e3f477" and the like ([docs/framework/monorepo-baseline.md](docs/framework/monorepo-baseline.md)).

### Toolkit (`cheme`, package `cheme-as-code`, import `chemeascode`)

- Plant repositories as plain files in git: `cheme init` (also generates the
  project-template repository), DEXPI 2.0.1 P&IDs through pyDEXPI, engineering lists in YAML with
  versioned JSON schemas (`cheme schema`, `cheme migrate`), decisions in Markdown.
- P&ID work: `cheme validate` with `file:line` findings and stable finding ids, `cheme fmt`,
  `cheme render` (SVG, PNG), a visual `cheme diff` and git integration (`cheme git-setup`,
  textconv), `cheme show`, `copy`, `move`, `rename`, `set`, `fragment`, `sheet` and the authoring
  API, ISO 10628-2 symbols with their registration numbers.
- Process engineering (`cheme process`): BFD/PFD, stream tables and balances, properties through
  thermo, separations, reactors and reactions, furnaces, electrochemical cells, simulation
  through DWSIM where installed.
- Chemistry, kinetics and microkinetics (`cheme chemistry`), control and cause-and-effect
  (`cheme control`, `cheme cause-effect`), safety and HAZOP studies (`cheme safety`), layout and
  3D models (`cheme layout`), datasheets (`cheme datasheets`), experiments (`cheme experiments`).
- Assessment (`cheme assess`): techno-economic analysis and life cycle assessment with
  provenance per value, uncertainty (Monte Carlo) and data-quality reporting; licensed
  databases are optional backends, never shipped (`cheme data fetch` for optional downloads).
- Engineering-step gates and sign-offs (`cheme check`, `status`, `impact`, `maturity`), GitHub
  issues (`cheme issues`), skills for coding agents copied into plant repositories
  (`cheme skills`), run records per agent or interactive session (`cheme runs`).
- `cheme serve`: the read-only HTTP API for the viewer; `cheme export-static` for snapshots.

### Viewer (`viewer/`)

- Vue 3 web viewer over a plant repository through `cheme serve` or a static snapshot: file tree,
  P&IDs as SVG with pan, zoom and side-by-side diff, schema-aware YAML tables, checks, maturity,
  process, reactions, layout (three.js), datasheets, LCA, cause and effect, control, issues,
  history and branches. Read-only.

### Agent runner (`agent-cli/`)

- Runs Claude agents (Claude Agent SDK) on ChemE-as-Code repositories with a hard dollar cap and
  guards on destructive commands, a supervisor for parallel jobs (`jobs.py`) and the orchestration
  of process-library case studies (`night.py`). Each run writes a run record through
  `cheme runs record` with the revisions of the toolkit and the runner, each from its own source.
