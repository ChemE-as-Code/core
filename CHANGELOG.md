# Changelog

## 1.4.0 (2026-11-02)

Minor release: IDAES as an optional second simulation backend, energy closure with component
separators, and pyDEXPI from PyPI, so installing cheme-as-code no longer needs access to a private
repository. No breaking change: `simulator` defaults to `dwsim`, and DWSIM models keep their
fingerprints. Simulation runs recorded before this release report energy closure as unsupported
until they are simulated again.

### Changed

- pyDEXPI comes from PyPI: `pydexpi==2.1.0`, the public release of the version that was pinned
  from the private `pyDEXPI-dev` (#111, ADR 0004 amended). Installing cheme-as-code no longer
  needs access to pyDEXPI, and CI and the plant template drop the `DEPLOY_KEY_PYDEXPI` secret;
  plants keep `PLANTCODE_READ_TOKEN` while this repository is private.
- The simulation's energy audit closes the plant with component separators in it (#60, ADR
  0038). A specified split's imbalance is stated, not judged: `status: stated`, `imbalance_kW`
  = enthalpy out minus in from the solved streams (positive: heat the unit would have to take
  in). DWSIM's `EnergyImb` is recorded with the sign each run shows (`simulator_convention`;
  `indeterminate` when the stated value is at most twice the tolerance) and not relied on. The plant record gains `stated_kW` and `stated`, its residual takes them
  as stated heat; the plant tolerance counts each stated magnitude. New rule `cheme.process-sim-energy-stated` (info). `predictive.energy-closure`
  passes such a plant and names the stated values; runs recorded earlier stay unsupported until
  simulated again, and `cheme process energy` says so.
- Licence: one statement everywhere. The skills and scripts `cheme init` writes into a plant
  repository are AGPL-3.0-or-later; plant data and models are the user's, and running the tools
  does not put AGPL on what they produce. `REFERENCE.md` said otherwise before.

### Added

- `cheme init` writes `.claude/skills/NOTICE.md`, which states this in the plant repository;
  `cheme skills status` and `update` track it.
- IDAES as a second simulation backend (#12, #104, ADR 0039): `simulator: idaes` in
  `process/simulation.yaml` runs the same translated model through an out-of-process IDAES/Pyomo
  worker (`CHEME_IDAES_PYTHON` or `CHEME_IDAES_COMMAND`); IDAES is never a dependency of
  cheme-as-code.

### Fixed

- IDAES backend, `IDAES ideal VLE`: a subcooled near-pure liquid (a pure toluene feed) did not
  converge, so neither did any flowsheet with one (#12). The package now takes its phase
  equilibrium in the complementarity form (Dabadghao et al., doi:10.1002/aic.18029) instead of
  IDAES's smooth VLE, whose bubble-to-dew smoothing exceeds such a stream's bubble-dew gap. Its
  liquid heat capacities of benzene and toluene were a thousandth of their value (IDAES's
  `BT_ideal` labels kJ/kmol/K coefficients J/kmol/K); a liquid mixer or heater had a wrong
  energy balance. Results of the ideal package change (the HDA example's heater duty 48.84 to
  48.60 kW).

## 1.3.0 (2026-10-31)

Minor release: the Viewer tells an embedding page how far it is and shows large 3D models in stages
(website#136, website#137). No breaking change.

### Added

- Viewer: an embedded Viewer reports its stage (`app`, `visual`, `detail`, `error`) and the object
  picked (`select`) to its page by `postMessage`, to the same origin only (`REFERENCE.md`, Embedding).
- Viewer: the 3D view shows the plan drawing as a poster while the model loads.
- Viewer: the 3D view names its stage on screen and sets `performance.mark`s (`layout:*`).

### Changed

- Viewer: a 3D model of 2000 meshes or more draws its overview first and builds the fine geometry
  afterwards in short slices. Exports and the benchmark complete the model first.

## 1.2.1 (2026-10-30)

Patch release: a branch starts exactly at its tee on a battery-limit header (#95). No breaking change.

### Fixed

- `cheme layout build`: a branch starts exactly where its header's run is cut for the tee. The
  run's end and the branch's start were computed apart and could fall on either side of a
  millimetre when rounded (x 219.652 against 219.653 on a battery-limit header with a jog to
  its lane), so the branch did not leave its header at the tee and was a 0.00 m
  `cheme.layout-clash-pipe`. Each tee is now one point, the end of one piece, the start of the
  next and of the branch (#95, a regression of #72).

## 1.2.0 (2026-10-30)

Minor release: buried lines with a cover rule (#70, ADR 0036), several power trays per rack
(#71, ADR 0037), and lines with battery limits at both ends are routed (#72). No breaking change.

### Added

- Several power trays per rack: `power_trays: [{rack, trays}]` in
  `electrical/tray-rules.yaml` (a count, or one voltage class per tray: `hv`, `lv`, `any`;
  `lv_max_v` 1000 V). The trays stand side by side on the rack's tray tier. The build shares
  the cables out by voltage class, then by fill, and splits the room legs and links with
  them. The cable schedule names each cable's tray. A `tray-fill` hint on a rack's power trunk
  names the number of trays the rack needs. New rule `cheme.layout-tray-voltage`; model trays
  gain an optional `voltage`. Without `power_trays` the model is unchanged (#71, ADR 0037).
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
- Viewer: drawings can be downloaded as vector PDF and SVG (#93).

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
in one repository, under AGPL-3.0-or-later. Earlier development is not part of this repository's
history ([docs/framework/monorepo-baseline.md](docs/framework/monorepo-baseline.md)).

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
