# Changelog

## Unreleased

### Added

- A line or segment in `piping/routing.yaml` can be declared `buried` (`true` or
  `{cover_m, basis}`). Its runs below grade get no road or escape-route headroom finding, no
  clash with steel, items, envelopes or zones above grade, no ladder-clearance finding and no
  span finding. The new `cheme.layout-buried-cover` (warning) checks their soil cover instead:
  at least `cover_m`, and under a road at least `rules.road_cover_m` (1.2 m, ASSUMED). The
  gates' `clashes` requirement counts it. Model pipes gain an optional `buried`. The take-off
  lists buried pipe as `group: buried`. Without the field nothing changes (#70, ADR 0036).
- Viewer: the layout view exports the visible model as a binary STL for 3D printing ("Export
  .stl"), in millimetres at 1:100, 1:200, 1:500 or 1:1000, with an optional base slab whose top
  is at ground level, so everything standing on the ground prints as one piece. No thickening
  or simplification: parts below the printer's resolution are left to the slicer.

### Fixed

- `cheme layout build` routes a line with battery limits at both ends, such as a cooling water
  header from the battery limit to its users' dead end (#72). It used to stay unrouted ("no
  other end to start from"), with every branch waiting for its tee. The line now runs along a
  rack from end to end: the rack of its `rack` intent, else of its `battery_limits` rule, else
  the rack nearest its branches. It runs on its tier or at its `elevation` intent, with its
  tees in the order of its branches. A second matching `battery_limits` rule places its other
  end. When the line still cannot be placed, it stays unrouted and the reason says why
  (`battery limits at both ends (...): ...`). Pinned routes stay as they are.

## 1.1.0 (2026-10-30)

Minor release: a motor's `cable_entry` ends its tray beside the machine, so crane lanes over
machines stay clear (#73, ADR 0035). No breaking change.

### Added

- A motor's `cable_entry` in `electrical/electrical-list.yaml` (a side of the driven item's
  footprint with `offset_m` and `clearance_m`, or a `point`; `elevation_m` optional) ends its
  tray beside the machine. The cable drops from there to the terminal box, and that drop counts
  in its length. A crane lane over the machine no longer counts the motor's tray. Any tray still
  inside the lane counts. An impossible entry is `cheme.electrical-cable-entry` (error). Model
  trays gain an optional `drop_to` (#73, ADR 0035).

## 1.0.1 (2026-10-29)

Patch release: multi-recycle loops converge through DWSIM (#57, ADR 0033) and `cheme process build`
builds Pumping steps (#59). No breaking change.

### Fixed

- `cheme process simulate` converges flowsheets with several recycles and a small purge, such as an
  ammonia loop (#57). DWSIM 9.0.5's Recycle only copies the tear into its copy, and such a loop
  closes only about its purge fraction of the gap per circuit, so 500 passes were never enough.
  When a Recycle hit its limit DWSIM also stopped the pass, which left the later copies looking
  stuck at their guess. The worker now runs the tear iteration itself: one DWSIM pass per step,
  all copies set at once with Anderson acceleration over every tear. It then connects DWSIM's
  Recycle blocks, whose own test passes on the result. The ammonia-1 loop (tears S44, S46, S48)
  converges in 51 passes instead of failing after 500. A tear that does not converge is reported
  with how far its copy is off. The mass-flow criterion is now 1e-7 kg/s or 1e-5 of the tear's
  flow, whichever is larger: DWSIM's unit models (the equilibrium converter above all) reproduce
  a loop's flows only to about 1e-6, so 1e-7 kg/s on a large stream was met only by chance
  (ADR 0033).
- `cheme process build` builds a PFD step of DEXPI class `Pumping` (and the other step classes
  whose `method` is optional: `Boiling`, `DrivingByEngine`, `DrivingByMotor`, `GeneratingSteam`,
  `HeatingElectrical`, `HeatingInFurnace`, `SupplyingThermalEnergy`) instead of crashing on its
  `method` field (#59). The committed example sheets are regenerated (generator code changed).
- `cheme process rules` (`cheme.process-class`) refuses a step or block `method:` that is not a
  member of its class's DEXPI method enum, or that is given on a class without a method, and lists
  the valid methods. Before, the method was silently dropped (`Pumping`) or the build crashed
  (`Compressing`, `Cooling`) (#59).

## 1.0.0 (2026-10-29)

First stable release: from here on cheme-as-code follows semantic versioning (ADR 0032). The
public interface (commands, plant-repository file formats and schemas, run records, the
`cheme serve` API and the documented Python API) changes incompatibly only in a new major
version. No breaking change since 0.8.0.

### Fixed

- Viewer fixtures carry a fixed `run_at`; the live API test names the failing answer (#48).
- Smoke test: CI gets a git identity for the run record's commit and checks it is committed (#49).
- `agent-cli/run.sh` is executable again (the repository's first commit dropped the bit) (#50).

### Changed

- Agent runner (`agent-cli/`): CI-fix runs are back, `night.py --since` sets the ledger start,
  design prompts research sources online with locators and keep per-process LCI overrides in the
  process folder (#52).
- Versioning: semantic versioning from 1.0.0 (ADR 0032); the contributing guide's "Moving a
  module" no longer relies on being pre-1.0.

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
