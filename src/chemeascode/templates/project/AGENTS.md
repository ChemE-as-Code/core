# Working in this plant repository

This repository is a process plant design. The files are the design; there is no other database.

## Ground rules

- P&IDs are DEXPI 2.0.1 XML in `pid/`. Edit them **directly as text** (skills `dexpi-xml`,
  `pid-edit`, `pid-draft`). Do not type the verbose drawing XML: `cheme copy` duplicates an
  object with its drawing (a spare pump, a second valve), `cheme fragment` prints equipment
  with nozzles, lines, segments, valves, tees, pipes, instruments, signal lines (with the
  actuating system), off-page connectors, notes and missing catalogue shapes ready to paste,
  enough to draft a whole sheet. Change what is already on a sheet with `cheme move` (an
  object's drawing), `cheme rename` (an id with every reference, or a tag with its labels)
  and `cheme set` (one data value and the labels showing it) before reaching for a hand
  edit; hand edits remain for re-pointing references and moving blocks. For what fragments
  cannot express, a generator script in
  `scripts/draft_<sheet>.py` uses the Python API `chemeascode.domains.piping.authoring` (the same builders as
  `fragment`; example `scripts/example_draft.py`). Run it with `cheme run`: `python3` and
  `uv run python` have no pyDEXPI in this repository. Never write your own XML helpers.
- Every sheet is either **hand-maintained** (the default: the XML is the source; a script in
  `scripts/` is provenance only and is never rerun over the sheet) or **generated** (its
  `plant.yaml` entry has `generator: {script, frame}`: the script is the source, the XML is not
  edited by hand, `cheme regen <sheet>` rebuilds it). `cheme regen --detach <sheet>`
  turns a generated sheet into a hand-maintained one. `cheme validate` warns
  (`generated-sheet-drift`) when a generated sheet no longer matches its script.
- The block and process flow diagrams (`process/BFD.xml`, `process/PFD.xml`, `kind: bfd|pfd` in
  `plant.yaml`) are **generated** from `process/materials.yaml` and `process/flowsheet.yaml` by
  `cheme process build` (skill `process-design`). Change the YAML and rebuild, never the XML
  (`cheme.generated-edited`). Stream values carry their provenance (`given` with a `source`,
  `assumed`, `calculated` by `cheme process propagate --fill`, `cheme process simulate
  --fill` or `cheme process props --fill` only); `DESIGN.md` keeps the
  decisions, not a second copy of the numbers. P&IDs start from the PFD (skill `pid-draft`).
- After every change: `cheme fmt <sheet>`, then `cheme validate`. Fix every `error`. Do not
  commit with errors; the pre-commit hook and CI refuse it anyway. Never bypass the hook
  (`git commit --no-verify`, `-c core.hooksPath=...`): fix what it reports, or stop and say so.
- One logical change per commit. Say what changed on which sheet and why. Append the change to
  `PROGRESS.md`.
- Keep the lists in step with the P&IDs (skill `lists-sync`), and the 3D layout in `layout/`
  in step with the equipment list (skill `layout-yaml`; routes `pipe-routing`, steel and access
  `structures-access`, zones `area-classification`).
- In a HAZOP study (`safety/`), propose and never accept: everything an agent writes stays
  `status: proposed` until the team accepts it. Never invent equipment, safeguards,
  frequencies or approvals, and never write a `band:` by hand (`cheme safety hazop rate`).
- Record decisions and assumptions in `DESIGN.md`, with the reason. Mark assumed values
  `ASSUMED` in the YAML or the decision text, never present a guess as data.
- **Branches and merges.** Each stage, and any change larger than one fix, goes on its own
  branch `stage/<stage>-<topic>` (e.g. `stage/basic-p04-products`); small fixes may go straight
  to the default branch (`main`). The branch is reviewed with `cheme diff main --list`, quoted
  in the review record, and merged by a human or the reviewer, never by its author. Merge once
  the review's critical and high findings are closed. A stage sign-off is the last commit on
  its branch and counts only once it is merged: a stage is reached when its sign-off is on the
  default branch. End your summary by saying whether a merge is pending.
- Do not edit `checks/status.json` or `build/` by hand; they are generated. `build/` is ignored.
- `runs/<run-id>/` holds one record per design session (`run.yaml`, `task.md`, `report.md`,
  `session.jsonl.gz`), written by `cheme runs record` (the Claude Code hooks in
  `.claude/settings.json` do it at the end of a session). Never edit or delete an existing run
  record; a correction is a new run.
- `checks/status.json` records stage sign-offs: `cheme check` only prints the gates;
  `cheme check --stage <stage> --write --review reviews/<record>.md` adds that stage's entry
  (commit, date, signer, branch, review record, the gates of every stage up to it). It refuses
  on uncommitted changes, a failing gate, a review you wrote yourself (without a human
  `approved_by`) or an open critical/high finding, counting one closed by a commit not in
  HEAD's history (skill `review`, step 7). Never sign off your
  own review, and never edit `status.json` by hand.

- **How to run commands** (also headless, where every denied command costs a turn):
  - change files with the Edit and Write tools only -- never `sed -i`, `awk`, `perl -i`, `cp`
    over a sheet, heredocs (`cat > f <<EOF`, `python3 - <<EOF`) or shell redirection into
    repository files. A shell rewrite of a 50,000-line DEXPI file is unreviewable and fails
    silently when a pattern matches zero or several times;
  - one command per Bash call: no `for` loops, `&&` / `;` chains, pipes into files or
    `VAR=...;` prefixes. Read with `cheme show`, `grep`, `sed -n 'A,Bp'`, `head`, `wc`;
  - scratch files go in `build/` (ignored), never next to the sheets.

## Commands

| | |
|---|---|
| `cheme status [--json]` | start here: stage, each sheet drawn / empty / planned with the listed items it does not draw yet, the next sheet to draw, findings by sheet, gates per stage, sign-offs (and whether merged), open review findings, branch state |
| `cheme impact [--json]` | review needed (info, read-only): review records whose scope or `basis` changed since, generated sheets whose `process/*.yaml` changed, stale calculated values; nothing is regenerated |
| `cheme validate [files] [--json] [--ignore RULE[,RULE]] [--only RULE] [--skip-generators]` | all P&IDs and lists, and lists vs P&IDs (equipment, lines and DN, instruments), drawing geometry (lines through labels, crossings, overlapping and misplaced labels, each with a `[crop ...]`) and tags named in texts; a `drawing <sheet>:` count line per sheet; the last line says what was compared; rules may be globs (`cheme.*-not-on-pid`); generated sheets are rebuilt in a scratch copy and compared unless `--skip-generators` |
| `cheme sheet new <ID> [--title T] [--file F]` | a new sheet from the template with its title block filled from `plant.yaml` (project block), added to `sheets:` (a planned one becomes drafted) |
| `cheme sheet meta <ID> [Key=Value ...]` | show or set title-block values (`Revision=B`, `Title=...`, `Status=...`, any MetaData property, `ModelName`, `DiagramName`): MetaData and the title-block texts together |
| `cheme fmt [files] [--check]` | canonical XML, readable id on every object |
| `cheme show <id or tag> [--sheet F] [--layout]` | `file:start-end` of an object and its drawing, owner chain, references in and out; `instrumentation:` the loop, actuating and signal chains it is part of; for equipment the lines, segments and branches at each nozzle; for a line number its segments, items and nodes with DN; `--layout` the measured plot-plan distances around a placed item |
| `cheme render [files] [--png] [--crop X0,Y0,X1,Y1 \| --tiles CxR] [--findings] [--scale S] [--rev R]` | `build/<sheet>.svg` (`.png` with `--png`, `<sheet>@<rev>` with `--rev`, `<sheet>_crop-X0-Y0-X1-Y1` with `--crop`, so a crop never overwrites the full sheet); `--crop` in sheet mm, Y down; `--tiles 4x3` (or `auto`) overlapping tiles `<sheet>_tile-B3` covering the sheet, each with its `--crop`; `--findings` marks the drawing findings |
| `cheme diff <old> [new] [--list [--verbose \| --flat] \| --json]` | HTML report in `build/diff.html`; `--list` one line per changed plant item with its added/removed/modified counts, `--verbose` each change under it, `--flat` one line per changed object with the drawing that shows it; `--json` the data |
| `cheme check [--stage S [--only-stage]] [--write --review R]` | engineering-step gates in `checks/checks.yaml` of every stage up to S; `--write` only at sign-off. For what a P&ID must show write `kind: on-sheet` gates (printed tags and classes in the model), not `grep` over the XML |
| `cheme issues [--all] [--json]` | the plant's issues (plant.yaml `issues:`): actions, engineering holds, technical queries and design changes by the gate they must close before, and links to open new ones; the gates of kind `issues` fail while one for the stage is open |
| `cheme cause-effect` | the cause-and-effect matrix of `control/cause-effect.yaml` to `build/cause-effect.html` and `.csv` |
| `cheme safety hazop init \| check \| rate \| report \| stamp \| review ID` | HAZOP studies in `safety/hazop/<id>/study.yaml` (skills `hazop-study`, `hazop-assessment`, `hazop-review`; `safety/README.md`): start a draft, findings and state (draft / assessed / reviewed), bands looked up in the risk matrix (`--write` records them, `--target` one node or scenario), `build/hazop/<id>.md`/`.html`, the analysed inputs' revisions, a review record to complete |
| `cheme control report [--json] [-o DIR]` | the loop summary (`build/control-loops.html`, `.csv`) and the sequence report (`build/control-sequences.html`) with each control file's review status (drafted, reviewed, accepted) and the `cheme.control-*` findings (skills `control-loops`, `control-sequences`, `control-narrative`) |
| `cheme schema [kind]` | JSON Schema of a YAML file kind; no kind lists them |
| `cheme runs list [--json]` | the run records in `runs/`: run id, kind, cost, wall time, complete, turns |
| `cheme runs record [--session-id ID] [--kind K] [--slug S] [--task-file F] [--cost USD] [--checks] [--commit]` | write `runs/<run-id>/` for a session (the hooks do it for interactive sessions, a runner for its own); a record that exists is never rewritten |
| `cheme skills status \| update [NAME...] [--force]` | the bundled skills in `.claude/skills/`: current, outdated, modified (changed here) or missing; `update` installs missing and outdated files and keeps a modified one (reported) unless `--force` |
| `cheme git-setup` | once per clone: `git diff` shows P&IDs as review text with their XML ids, pre-commit hook |
| `cheme copy <id or tag> --prefix NEWID [--tag T] [--offset DX,DY] [--into PARENT] [--rename OLD=NEW] [--renumber A:B] [--set PROP=VALUE] [--connect PIPE=ITEM:NODE] [--sense-at ID[:X,Y]] [--print]` | duplicate an object with its parts and everything that draws it, every id renamed from `NEWID`; `--rename`/`--renumber` give inner valves their own tags, `--set` e.g. the fluid code, `--connect` closes an open pipe end, `--sense-at` re-points an instrument's sensing location; prints the new ids, the lines written, what was not copied and the tags still duplicated |
| `cheme move <id or tag> --offset DX,DY [--print]` | move an object's drawing (symbol, node positions, labels); attached lines follow, bends that stay are listed |
| `cheme rename OLD NEW [--children] [--ids] [--tag] [--print]` | an id and every `#OLD` reference (`--children`: also `OLD_*`); given a tag, the tag data and its labels (`--ids`: and the ids that spell it); `--tag`: NEW is the new tag of the object with the id OLD (retag one of two objects sharing a tag; an instrument's sensor and actuator follow); a valve and its own actuation chain sharing a tag are retagged together |
| `cheme set <id or tag> PROP=VALUE... [--print]` | data values by DEXPI name, typed (string, number, enumeration, `'50 mm'` quantity, `Stroke.Width`), and the label texts showing them; `PROP=` removes one |
| `cheme run [--fmt SHEET] SCRIPT [ARGS]` | run a Python script in cheme-as-code's interpreter (pyDEXPI and `chemeascode.domains.piping.authoring` import), cwd the repository root; arguments and exit code pass through; `--fmt` goes before SCRIPT (after it, it goes to the script) |
| `cheme regen [SHEET...] [--force \| --detach \| --list]` | rebuild generated sheets (frame -> script -> fmt); refuses a sheet edited by hand and names the items; `--detach` makes a sheet hand-maintained |
| `cheme layout build [--check] [--force]` | derive `layout/plant-model.yaml` (generated, never edited): equipment parts from `type` and `dimensions`, nozzles from the P&IDs with DN and lines, maintenance envelopes, steel, platforms, zones, a pipe route per P&ID segment with in-line items, cable trays (with `electrical/`) and HVAC ducts (with `layout/hvac.yaml`); prints clashes, headroom and access findings; rebuild after changing the layout, the lists or a P&ID (`layout-model-outdated`) |
| `cheme layout route [--line L] \| pin LINE\|TAG/platform-N \| report [--json]` | reroute some lines keeping the rest; copy a generated route or platform into `piping/routing.yaml` / the placement; routed and unrouted lines with reasons, lengths, how and why each was routed (counts per method and per reason), battery limit ends, rack fill, clash counts |
| `cheme layout render --plan [--level ID \| --z A,B] \| --section x=V\|y=V [--depth D] [--crop X0,Y0,X1,Y1] [--png]` | plot plan, level plans and sections of the model into `build/layout-*.svg\|png` |
| `cheme layout cables [--csv \| --json] [--write \| --check]` | the cable schedule of `layout/plant-model.yaml` (every motor, feeder, instrument and junction box cable: from, to, size, trays, length; trays with width and fill); `--write` into `electrical/cable-schedule.*` (skill `electrical-cabling`) |
| `cheme assess mto \| estimate [--csv \| --json] [--write \| --check]` | the material take-off of `layout/plant-model.yaml` (pipe by DN, class and insulation, fittings, flanges, valves, steel tonnage, grating, insulation, concrete) and its estimate with `estimate/rates.yaml` (factor method); `--write` into `estimate/` (skill `mto-estimate`) |
| `cheme datasheets draft \| fill [--tag T] [--param name=value] [--dry-run]` | `draft`: a draft datasheet per listed item without one; `fill`: the sizes a draft leaves TBD (exchanger area, pump head and NPSH, compressor power, column stages, residence time) calculated with their basis, never over a given value (skill `datasheets`) |
| `cheme assess lca [--csv \| --inventory \| --dataset \| --coverage \| --json] [--write \| --check]` | the LCA per functional unit (skill `lca`): operation (the flowsheet's feeds and products in the case of `lca/lca.yaml`) and construction (take-off, equipment weights), allocated between co-products, characterised with `lca/factors.yaml` or a Brightway project, baseline and scenarios; every exchange without a burden is a gap (`lca/gaps.csv`), never 0; the result is classified complete, screening, partial or unavailable (`--coverage` says why); `--inventory` / `--dataset` alone export the foreground without any background; `--write` into `lca/` |
| `cheme assess lca-search TEXT [--database DB]` | activities of the Brightway project (extra `lca`), as `activity:` mappings for `lca/lca.yaml` |
| `cheme assess lca-map [KEY...] [--query T] [--apply KEY=N --source S]` | the exchanges without a background (unmapped or `missing:`) with numbered candidate activities of the Brightway project and the query that found them; writes nothing unless `--apply` names the approved candidates, and then only their `activity:` (other text and comments kept; refused when the unit kind differs or the file would not validate) |
| `cheme process build [SHEET...] [--force]` | generate the BFD and PFD from `process/*.yaml`; refuses while the flowsheet has errors, and over a sheet edited by hand unless `--force` |
| `cheme process streams [--case C] [--md \| --csv \| --json]` | the stream table (value, unit, provenance G/A/C per property, stale calculated values) and the balance of every block and step |
| `cheme process propagate --fill \| --check [--case C]` | compositions and flows through pass-through steps, mixers and splitters (`split:` fractions); separators and reactors only checked; never overwrites given or assumed values; `--check` writes nothing |
| `cheme process simulate --fill \| --check [--case C] [--save F.dwxmz]` | the flowsheet solved by DWSIM (skill `process-simulation`): property package and step specs from `process/simulation.yaml`; temperatures, pressures, flows, compositions and duties of the streams downstream of the feeds; never overwrites given or assumed values, a deviation from them is a warning; `--check` writes nothing |
| `cheme process furnace [ID] [--json]` | the energy basis of a lime kiln or calciner in `process/furnaces.yaml`: element balance, off-gas, reaction enthalpy and furnace energy closure from condensed-phase data (extra `cantera`); the degree of calcination is given, never predicted; other solid reactions are refused; `method: specific-energy` is a labelled fallback |
| `cheme process cell [--json]` | the Faraday balance of each cell of `process/cells.yaml` (electrolysers, chlor-alkali): products, charge and element balances, DC power counted once, thermoneutral voltage, heat duty and kWh per kg, from a specified current, current efficiency and voltage; a missing input refuses the cell, never assumed |
| `cheme process methods [--json]` | which thermodynamic models the phase calculation and the simulation run, the explicit substitute for the others, and the unsupported regimes (electrolytes, solids, pseudocomponents) |
| `cheme process electrolyte --temperature T --pressure P --molality M [--json]` | aqueous NaCl only (extras `cantera`, `props`): mean ionic activity coefficient, osmotic coefficient, water activity and vapour pressure, heat of dilution, inside the benchmarked range of `electrolytes.yml`; anything else is refused (exit 3) |
| `cheme process phase COMPONENT... --model EOS \| --liquid M --vapor V [--temperature T --pressure P] [--accept-zero A:B] [--check]` | binary interaction parameters per pair: sourced, missing (zero used) or accepted zero; with T and P a flash (extra `props`, skill `phase-calculation`) |
| `cheme process extract [UNIT] [--systems] [--json]` | liquid-liquid extraction stages of `process/extraction.yaml` on NRTL (extra `props`): raffinate, extract, recovery, solvent loss, distribution, selectivity, closure and whether the result is qualified; refused without a two-phase region or with a missing pair; writes nothing (skill `separation-method-selection`) |
| `cheme process props --fill \| --check \| --coverage [--case C]` | phase, molar mass, density, enthalpy (extra `props`) with the process's benchmarked property package, inside its validated range only; never overwrites given or assumed values; `--check` writes nothing; `--coverage` lists which package covers each stream or why none does |
| `cheme process layout [IDS...] [--view bfd\|pfd] [--pin]` | the generated positions; `--pin` writes them into `layout.<view>` of `flowsheet.yaml` |
| `cheme chemistry evidence [--json]` | the route comparison of `process/reaction-evidence.yaml` (sources, observations, reported ranges with conversion, selectivity and yield kept apart, kinetics, conflicts, unread sources, gaps) and the model basis; gather the evidence before choosing a reaction model (skills `reaction-evidence-search`, `route-selection`) |
| `cheme fragment KIND --id ID [--sheet F] ...` | ready-to-paste XML, a CONCEPTUAL and a DRAWING part each saying where it goes; KIND `valve`, `tee`, `node`, `pipe`, `segment`, `line`, `label`, `equipment`, `nozzle`, `instrument`, `signal`, `offpage`, `note`, `shape` (`cheme fragment --help`, skill `dexpi-xml`) |

## YAML files and their schema kind

| file | kind |
|---|---|
| `plant.yaml` | `plant` (sheets, each optionally with `generator: {script, frame}`) |
| `process/design-basis.yaml` | `design_basis` |
| `process/materials.yaml` | `process-materials` (components, templates, the property method `props --fill` records) |
| `process/simulation.yaml` | `process-simulation` (property package with its `method_selection` facts, specs per step, tear streams; optional) |
| `process/flowsheet.yaml` | `process-flowsheet` (units, cases, tolerance, feeds, products, blocks, steps, streams with per-case state and provenance, links, `layout.bfd`/`layout.pfd`) |
| `equipment/equipment-list.yaml` | `equipment` (tag, type, service, sheet, design data, `dimensions`, notes) |
| `piping/line-list.yaml` | `lines` (number, from, to, nominal_diameter, ..., notes, `segments` with a DN each) |
| `control/instrument-list.yaml` | `instruments` (tag as printed, service, sheet, notes) |
| `control/cause-effect.yaml` | `interlocks` (id, cause tag and condition, effects with actions, sheet, sil; optional logic, delay, latching, reset, bypass): every trip, instead of literal sheet text |
| `control/loops.yaml` | `loops` (regulatory loops: measurement, controller, final elements with fail positions, action, targets with units and provenance, modes, links, alarms; not safeguards) |
| `control/sequences.yaml` | `sequences` (startup, shutdown, abnormal modes: permissives, steps, abort, reset; trips by C&E id) |
| `process/narrative.md`, `control/philosophy.md` front matter | `narrative`, `control_philosophy` (sections, objectives and failures by id, with the loops, sequences and interlocks they rest on) |
| `piping/special-items.yaml` (optional) | `piping_items` (tag, type, line, sheet, set_pressure_barg, relief_case: safety valves, silencers) |
| `checks/checks.yaml` | `checks` |
| `equipment/datasheets/<TAG>.yaml` | `datasheet` (one per equipment item: conditions, materials, sizing basis, `assumed` values) |
| `reviews/<date>-<topic>.md` front matter | `review` (topic, reviewed_commit, scope, reviewer, reviewer_kind) |
| `checks/status.json` (generated) | `status` |
| `runs/<run-id>/run.yaml` (written by `cheme runs record`) | `process-run` (one design session: commits, times, cost, model, turns, tokens, cheme commands, checks after the run) |
| `layout/site-plan.yaml` | `site_plan` (site box, areas, roads, pipe racks, `separations`, `max_unsupported_length`) |
| `layout/building.yaml` | `building` (buildings, levels, column grid) |
| `layout/equipment-placement.yaml` | `placement` (tag, position, rotation, `mount` building/structure level, nozzle overrides, `access` platforms; size only without dimensions) |
| `layout/structures.yaml` | `structures` (steel frames: spans, levels, bracing, stairs, ladders, enclosure) |
| `layout/zones.yaml` | `zones` (keep-clear, laydown, maintenance, escape, hazardous, O2-enriched/-deficient; explicit or from release sources) |
| `layout/hvac.yaml` (optional) | `hvac` (air handling units in buildings with intake and exhaust louvres, ventilated rooms with air changes and terminals, duct rules: velocity limits, sizes, ceiling gap, spacing) |
| `piping/routing.yaml` | `routing` (router rules: tiers, battery limits, pipe-way elevation, local and rack limits; per-line intent: rack, tier, via, elevation, pinned route, skip) |
| `piping/pipe-specs.yaml` (optional) | `pipe_specs` (pipe classes, insulation thickness) |
| `layout/plant-model.yaml` (generated by `cheme layout build`) | `layout_model` |
| `electrical/electrical-list.yaml` | `electrical` (substations, transformers, rooms in buildings, defaults, the motor list's powers and rooms, feeders, junction boxes, instrument cabling) |
| `electrical/tray-rules.yaml` (optional) | `trays` (tray widths, depth, fill, power/instrument separation, rack tray tiers, power trays per rack (`power_trays`), branch elevation, cable allowances) |
| `estimate/rates.yaml` | `rates` (the project's unit rates and estimate factors, each with status, source and year; the one `cheme init` writes is an example) |
| `lca/lca.yaml` | `lca` (goal and scope of the LCA: functional unit, case, allocation, categories, and the background of each feed, product and emitted component) |
| `safety/risk-matrix.yaml` | `risk-matrix` (bands lowest risk first, likelihood and severity codes, categories, the band of every cell; the one `cheme init` writes is an example) |
| `safety/hazop/<id>/study.yaml` | `hazop-study` (scope, modes, analysed inputs and their revisions, nodes, deviations, scenarios with ratings, safeguards, actions; `status: proposed` until the team accepts) |
| `lca/mapping-profiles/*.yaml` (optional) | `lca_mapping_profile` (a background provider's activity names for the study's flows, by key or utility kind; selected with `brightway.mapping_profiles`) |
| `lca/factors.yaml` | `lca_factors` (the project's characterised factors, each with status, source, year, geography and its `sources:` registry entry (licence, publication policy); the one `cheme init` writes includes the packaged open profile `desnz-ghg-2026`: a screening carbon footprint) |

`cheme schema <kind>` prints the full JSON Schema.
