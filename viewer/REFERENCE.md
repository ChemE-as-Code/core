# cheme-as-code-viewer

Milestone 2 of cheme-as-code: a web viewer over a plant repository in git.

Renamed from chemeascode-viewer with core 0.7.0 (`plantcode` became the command `cheme`): the
finding ids it shows are `cheme.<rule>`, and the dev proxy reads `CHEME_API` (was
`PLANTCODE_API`). See `docs/framework/rename.md` in core.

- `cheme serve` (FastAPI, in the cheme-as-code package) exposes one repository: file tree, file
  contents, `git log`, branches, and P&IDs rendered to SVG on the server by pyDEXPI's SVG export.
- This app (Vue 3 + Vite) shows the plant's pages and documents; P&IDs as static SVG with pan, zoom and a
  side-by-side diff between revisions (changed items highlighted, as `cheme diff` does); YAML
  lists with schema-aware tables, other YAML documents and CSV files readable; the engineering-step
  check page from `checks/status.json`; history and branches; the raw repository files.
- Read-only. Editing stays with people and agents working on the files.
- Rendering is SVG only: no dexpi-js and no DigiCo viewer components.

Status: in use; against a server (`cheme serve`) or on a static snapshot (below).

## Pages

| Route | Shows |
| --- | --- |
| `/` | Plant name, branch, the declared project phase and the verified (evidence-based) maturity (see `/maturity`), sheets. A sign-off strip, one chip per stage: who signed it off and when, the short commit (opening the plant there), its branch, the review record it names (and its reviewer kind when not human), and "not on main" when the signed-off commit is not on the default branch (the sign-off has not taken effect). From `GET /api/status` for the working tree (loaded once per session: it validates the plant, seconds on a large one), else from `checks/status.json` at the revision (the default branch then unknown) |
| `/section/<id>` | A section of the page navigation (`process`, `pid`, `equipment`, `safety`, `layout`, `cost`, `quality`, `project`): its title, a short intro of what it holds and its pages and documents as cards (label, sheet kind, title, what the page shows or the file), each drawn sheet (BFD, PFD, P&ID) with a thumbnail of its drawing (`GET /api/pid.svg`, loaded lazily); each card opens its page at the revision shown. A section the plant has nothing in, or an unknown id, says so and links back to the overview |
| `/pid/<path>` | A P&ID as SVG: drag to pan, wheel or pinch to zoom, `+` `-` `0` and arrow keys, Fit and 1:1. Clicking an object shows its id and labels; from the keyboard, `N` steps to the next object and `P` (or `Shift+N`) to the previous one (centred, marked and announced to screen readers), `Enter` or `Space` shows the marked object's details and `Escape` clears the selection. Ctrl/Cmd/Alt shortcuts pass through to the browser. `?select=` picks and centres an object by its id, or by a printed tag (`?select=LIA-4107`: the object whose own label reads it). "PDF" downloads the drawing at the revision shown as a one-page vector PDF (made in the browser, also in a static snapshot and embedded; text stays selectable text in the standard PDF fonts, Arial and Calibri as Helvetica; the sheet's grey background left out), at 1:1, on the ISO A sheet it is (a 420 x 297 drawing on A3 landscape) or else on a page of its own size (a long PFD strip as an elongated sheet); "SVG" downloads the drawing as served. Both take the drawing from the API, never the pane, so no selection or highlight; the file is named `<plant>-<sheet id>[-<revision>].pdf` (the snapshot's commit in a snapshot, nothing for the working tree) |
| `/diff/<path>?old=&new=` | Two revisions side by side or overlaid, with synced pan/zoom. Added items are green, removed red, modified orange. Includes the change table (click a row, or `Enter` on it, to centre the object) and the pyDEXPI projection diff. The panes pick objects from the keyboard as on `/pid`. If `new` is missing, the working tree is used |
| `/yaml/<path>?filter=` | Equipment, line, instrument and check lists as tables, with columns from the JSON Schema (`filter` sets the row filter it opens with). Any other YAML mapping (the design basis, a risk matrix, a HAZOP study) as a document: its values as a key-value list, lists of objects as tables (nested values as `key: value` text), lists of values as bullets and nested mappings as sections (deeper ones as a tree); "Tree" shows the whole file as a tree |
| `/file/<path>` | Markdown rendered (no raw HTML; headings get GitHub's ids, so `[x](#design-basis)` scrolls to `## Design basis`, in a static snapshot too, and `/file/README.md#design-basis` opens there), a CSV file as a table ("Source" shows the text), other files as text with line numbers; YAML with syntax highlighting |
| `/streams?case=&tab=` | The stream table of `process/flowsheet.yaml` (`GET /api/streams`) for a case: pressure, temperature, flow, duty, composition and phase of each stream with its provenance (`G` given, `A` assumed, `C` calculated; stale values marked), its links, and the balances. A row is selected by a click or, focused, with `Enter` or `Space`. A value the recorded simulation run filled is marked `sim` (the run's `streams[].filled`; in warning colour when the run is stale), its tooltip naming the run's time, simulator and property package. With `process/simulation.yaml` a Simulation tab (`?tab=simulation`, `GET /api/simulation`): simulator and version, property package, the case, the run `cheme process simulate --fill` recorded in `process/simulation-run.json` (converged, not converged or not run; when and with which tool; the input commit, opening the plant there, and the files that were uncommitted), a warning naming the changed files when the run is stale against the inputs now (the feeds, specs, property package or simulator model changed), the run's messages when it did not converge (no stream value written), the tolerance, tear streams and excluded steps; a units table, one row per step or block: its status (simulated, excluded, refused, not simulated) and in the run converged, failed or unknown, its spec values (nested ones by dotted key) with their provenance (an assumed value with its source), its results (`duty 84.2 kW`), why it is excluded or refused, its warnings and messages; the findings. Without a run, the hint to run `cheme process simulate --fill`. The tab shows when `/api/repo` reports `has_simulation`; on a server or snapshot without it (a 404) the stream table alone, and `?tab=simulation` says there is no simulation |
| `/reactions?case=` | The reactions of `process/reactions.yaml` (`GET /api/reactions`) for a case: each reaction's id, title and sources, equation, type (the model of the reactors it runs in: `conversion`, `equilibrium`, `mixed`), phase and reversibility, key component, what sets its extent (a conversion of its key component, an equilibrium constant `ln K = a + b/T + ...` with its range, a reactor's own conversion, or K from the components' ideal-gas data) and its heat of reaction, each with its provenance and source, the catalyst, the blocks and steps it runs in (model, temperature approach, conversion and where it is given) and an element-balance badge (balanced, unbalanced with the atoms created or lost, not evaluable). The reactors (the rows of `cheme process reactors --json`): node (linked to its P&ID with the item selected, `/pid/<sheet>?select=<tag>`, from the flowsheet node's links or a tag's equipment-list sheet), its streams, model and approach, balance status, outlet temperature and pressure, per reaction the extent (and the rate at the outlet where the reaction has a rate law) and ln(Q/K) with how the outlet stands to equilibrium (at, short of, beyond), the duty and what it lacks for a duty; the reactive balances with their extents, and the findings on reactions, reactors and those balances (each linking its file and line). The kinetics (pre-release viewer issue 23): per reaction with a rate law its form, basis and driving force, the expression, k (A with its unit, Ea, n, T_ref), orders, LHHW adsorption terms, validity range, catalyst and provenance with source, and a k(T) chart over its range (or its catalyst's window); its elementary steps when core serves a mechanism, with their mean-field steady state at the outlet of the first reactor running it (`microkinetics`: the conditions, TOF, apparent Ea, orders, coverage and degree-of-rate-control bars, the step that controls the rate and the most abundant intermediate, or why there is none); each fixed bed (`reactor: pfr`, pre-release viewer issue 32): its calculation mode (adiabatic, isothermal, cooled with coolant and U), catalyst mass and volume, inlet and outlet temperature and pressure, T out − T in, pressure drop, core's peak temperature (`hot_spot_K`) and where it is: at the inlet, at the outlet (an endpoint maximum) or at a sampled point inside the bed (an interior hot spot) when it is exactly one of core's sampled points, else between two sampled points with a warning that the curve does not reach it (core reports no position, so the viewer places none), the number of sampled points; temperature and pressure against catalyst mass from the inlet in kg (never as a length), inlet and outlet marked, the peak as a marker (or a dashed line at its value when core does not place it), the coolant temperature and the catalyst's temperature window as labelled reference lines with their basis and provenance (a boundary condition and operating guidance, neither a limit: with no engineering maximum allowable temperature served the peak is shown without a safe or unsafe judgement), a crosshair reading out each sampled point (hover, or the arrow keys, Home and End on the focused chart), a profile that does not change (an isothermal bed, no pressure drop) said in words instead of drawn; the profile as a table and as CSV; core's notes (no pressure drop and why, the rate range left, a limiting transport); the bed's row of the recorded simulation run (`GET /api/simulation`, only asked with a fixed bed: peak and pressure drop, current, stale with the changed files and its values historical, or not converged with the outer loop's iterations); where the result is from (solved by the server at the revision, or the static snapshot and the cheme-as-code version that wrote it) and the scope of core's model (axial steady-state screening, no radial, particle or dynamic temperatures, no composition along the bed); a bed core could not solve shows core's reason instead, and a process without a fixed bed shows no such section; and the catalysts of `process/catalysts.yaml` (active phase, promoters, support, particle and bed data, window, space velocity, poisons, deactivation, price, each with provenance; the reactions it catalyses and the blocks and steps holding it with their bed) with their findings. A reactor whose equilibrium uses Peng–Robinson fugacities is badged so. The kinetic data of `experiments/kinetics/` (`GET /api/kinetics`, when `/api/repo` reports `has_kinetic_data`): per file its reaction, catalyst and points with provenance, the default fit (`cheme experiments fit-rate`: the law, R² of ln r, each parameter with its standard error and 95 % interval, validity) and the points against the fit, or why a file does not validate. A reaction's catalyst links to its card and the card back to the reaction; a core without kinetics (`kinetics: null`) shows no catalysts. In the page navigation (Reactions) and on the home page when `/api/repo` reports `has_reactions`; a snapshot or server without it shows "No reactions" |
| `/library` | The reaction library (`GET /api/library`, `cheme chemistry library`): each industrial process with its temperature and pressure window, components, reactions and catalysts (with window and poisons) and sources, each item marked when the plant has it (a component by its CAS number, a reaction by its stoichiometry, a catalyst by its id; ≠ when the plant's catalyst of that id has other data, so `--add` refuses it), how much of the entry the plant has, and the command that adds it; a filter (process, component, CAS, equation, catalyst) and "only processes the plant runs". Linked from the home page and the reactions page; a server or snapshot without it shows "No reaction library here" |
| `/checks` | `checks/status.json` with pass/fail/n/a badges. **Run now** evaluates the checks on the working tree without writing `status.json` (`POST /api/checks/run` with the server's per-launch token from `/api/session`; `kind: command` checks run their shell commands) |
| `/reviews` | The review register: the open findings of `reviews/*.md` (`GET /api/status`, `cheme status --json`, of the working tree) with a count per severity, the number blocking a sign-off (open `critical`, `high`, `major`, marked "blocking"), filters by severity (or blocking only) and by the record that raised a finding (both in the URL), each finding's cell as Markdown, a link to the record that raised it and to the latest one listing it open (`/file/reviews/<record>.md`) and the commit that record reviewed (its front matter's `reviewed_commit`, opening the plant at that revision). Below, every record (newest first) with topic, reviewer and kind, reviewed commit and the findings it raised by their latest status (open, closed, accepted, superseded). The records are read through `/api/tree` and `/api/file`; at another revision, on a static snapshot (which holds no `/api/status`) or on an older server the open findings are derived from them with core's rules (a finding's status is the one in the latest record listing it). The stage sign-offs as on `/`. In the page navigation (Reviews) unless the status has neither records nor sign-offs |
| `/maturity` | The evidence-based calculation maturity (core's `cheme maturity`, schema `cheme/maturity-report/v1`, docs/framework/maturity.md) beside the declared project phase: the phase is plant.yaml's `stage` (a workflow phase, not evidence), the maturity the highest of the four cumulative levels (Sourced, Balanced, Predictive, Engineering: preliminary/basic engineering, not verified detailed engineering) whose requirements all pass. Each level as achieved, not yet achieved, not assessable (blocked only by `unsupported` requirements) or not evaluated, with why; its requirements (`pass`, `fail`, `missing`, `unsupported`; required or not) with file and line links, detail, hint and evidence; the limitations, the model basis of reactors and separators, the assumptions, the manifest claim when it exceeds the evidence, and, kept apart, artifact completeness and independent review (which never raise a level). Provenance: where the report comes from, `checked_at`, core version, the input commit and uncommitted inputs, the input fingerprints. For the working tree `GET /api/maturity` (evaluated live, once per session, "Evaluate again"; some 30 s on a large plant); at another revision, on an older server or in a snapshot without it, `checks/maturity.json` (`cheme maturity --write`) of that revision, shown as current only when every input fingerprint it recorded matches that revision's file (sha256 with CRLF normalised, as core's `content_fingerprint`): else "outdated report" (an input changed) or "unconfirmed" (an input could not be read), and the levels as recorded, never as current. No report, an incompatible one or a failure is said as such and nothing shows as achieved. The header shows "Project phase: …" and "Verified maturity: …" (linking here; on phones both are on the overview instead) |
| `/validate` | `cheme validate` findings, filterable by level (errors and warnings shown, the info findings behind their toggle or "Show the n info findings"). Clicking a finding opens the file at its line |
| `/mto` | The material take-off of the committed 3D model (`GET /api/mto`, `cheme assess mto`): totals per category, a table per category (filterable), and with `estimate/rates.yaml` the estimate (factors, totals, a warning for example rates) with each row's rate and cost. "Take-off CSV" and "Estimate CSV" download the files `cheme assess mto --csv` and `assess estimate --csv` write. An Equipment tab (`?tab=equipment`) shows the equipment estimate (`GET /api/estimate/equipment`, `cheme assess equipment`: Turton et al.'s CAPCOST correlations escalated by the cost index of `estimate/cost-basis.yaml`): bare module and purchased totals with the items each covers, the AACE class (18R-97) and its accuracy range on the bare module total, a warning without a cost index, a line per equipment-list item (correlation, size, Cp0 at the base index, Fp, Fm, FBM, purchased and bare module cost) with a status chip (bare module, purchased only, project cost, excluded, not covered; the chips filter, so does a text filter), where its size comes from (expandable, ASSUMED and draft marked), links to its datasheet (`/datasheets/<TAG>`) and to the item in 3D (`/layout?select=<tag>`), the project's own costs and the findings with their hints. Without a model but with an estimate the page opens on that tab; a 404 (nothing to estimate, an older server, a snapshot without it) hides the tab and says to run `cheme assess equipment`. In the page navigation (MTO and estimate) when `/api/repo` reports `has_layout` or `has_equipment_estimate` |
| `/lca` | The life cycle assessment (`GET /api/lca`, `cheme assess lca`) per functional unit: what the result is (complete, screening, partial or unavailable, and why; a screening carbon footprint when only climate categories are given) and a notice when its sources do not permit publication; case, boundary, allocation and background; the total per category and scenario and its split by phase; a contribution Sankey (each inventory flow into its phase, the phases into the functional unit; band widths are impacts, credits hatched); stacked scenario bars with shared colours (credits left of zero); the allocation methods side by side (share and total relative to the method used, or why one does not apply); the Monte Carlo uncertainty (95 % interval with median and deterministic value, and what drives it by Spearman rank correlation; the interval also on the total card); a comparison with another revision (a branch or a commit changing `lca/`: category totals and the largest contributor changes); the contribution table (quantity, factor, background, impact, share) and the inventory (per functional unit and for the plant, provenance, background; unmapped flows marked); the gaps of the selected scenario and category (exchanges without a burden, with their quantities and why: excluded from the total, never counted as 0, no coverage percentage) and the flows outside a method's scope; the sources with version, licence, publication policy and attribution; the limitations of the boundary; the LCI readiness of the plant's dataset `lca/dataset.yaml` (pre-release viewer issue 36, all of it core's: the mass, element and carbon-by-origin closure with residuals, tolerance, the exchanges without a composition, the exchanges outside the balance and the cut-off flows listed beside it, each exchange linked to its line, from `balance` (pre-release issue 174; "not assessed" for a core that predates it); the DQR with TeR, GeR, TiR, the weakest marked, and the pedigree per exchange read from `lca/dataset.yaml`, scores 4 and 5 highlighted (pre-release issue 178); the publication-minimum fields it lacks (pre-release issue 179); emission sources without an estimate (pre-release issue 176), consumables without a disposal route and the cut-off findings (pre-release issue 180); the water withdrawal and consumption (pre-release issue 175); each linked to its file and line; hidden for a server that reports none of `data_quality`, `water` and `balance`); the findings. Category and scenario selectors; "Results CSV" downloads the file `cheme assess lca --csv` writes (`lca/results.csv`). A warning for example factors. In the page navigation (Life cycle assessment) when `/api/repo` reports `has_lca` |
| `/tea` | The techno-economic analysis (`GET /api/tea`, `cheme assess tea`): a warning for example premises (`example: true`); the decision (question, metric against its threshold with a meets / does not meet badge, P(meets) from the Monte Carlo against the confidence asked for, the AACE class claimed against the one the stage expects, the alternatives); the basis and operation; core's boundary check (`boundary`: gaps found or none, the products the operating cost counts at no cost, the steps with a duty but no energy stream, the terminals by category, the `cheme.boundary-*` gaps with their files and lines, and what the check covers and does not); result cards (the decision metric first: NPV, IRR, LCOP and cash cost in the LCOP's unit, payback, fixed capital with working capital, revenue and costs per year; NPV and IRR say when they leave out an unpriced main product's revenue); the cost of production per unit of the main product as a stacked bar (credits left of 0) and table summing to the LCOP; the capital build-up (each line in the TEA's currency, with what it was estimated in when that differs) and the AACE accuracy range; the feeds and products (rate, provenance, price, per year, source; free, main-product and unpriced flows marked, unpriced ones in a warning), every priced line, other variable costs, emissions, fixed operating costs and events; the cash flow per year as bars with the discounted cumulative line, and every column core sends as a table; scenarios (bars against the threshold and a table of all metrics); the tornado around the baseline (an end where the metric does not exist left out); break-even values (`never` when none is in range); the Monte Carlo per metric (P10, P50, P90 and the drivers by rank correlation); the inputs; arrays a newer core adds as generic tables; the findings. A 404 says how to start one (`estimate/tea.yaml`, skill `tea`), a 422 shows why it does not compute. In the page navigation (Cost and impact: Techno-economics (TEA), in place of the report `estimate/tea.md`) and on the home page when `/api/repo` reports `has_tea` |
| `/cause-effect` | The cause & effect matrix of the interlocks (`GET /api/interlocks`, `control/cause-effect.yaml`, as `cheme cause-effect` draws it): causes as rows (interlock id and title, the cause tag with its condition and sheet, SIL), effect tags as columns, the action in each cell, coloured by what it does (trip, stop, close, depressurize; open, start; alarm); a cell where one interlock has several effects on the tag (`close + alarm`, pre-release PR 269) stacks one chip per action in its own colour, the cell coloured by the most severe (stopping over starting over an alarm). The header row and the first two columns stay in view while the matrix scrolls (sideways on phones). Cause and effect tags link to their P&ID with the tag selected (`/pid/<sheet>?select=<tag>`, the sheet from the interlock's `sheet`; the P&ID picks the object whose label reads the tag). A comparison with another revision (a branch or a commit changing the file) outlines the changed cells (a changed set of actions; the order alone does not count) with the old action, marks new interlocks and changed causes, SILs and titles, and lists what only the other revision has. The interlocks' notes below; "CSV" downloads the file `cheme cause-effect` writes (`build/cause-effect.csv`). In the page navigation (Cause & effect) and on the home page when the working tree has `control/cause-effect.yaml` (from `/api/tree`); a snapshot without the endpoint shows "No interlocks" |
| `/control` | The control records of the working tree (`GET /api/control`, `cheme control report --json`, pre-release issue 140): each control file (`control/loops.yaml`, `control/sequences.yaml`, `control/cause-effect.yaml`, `process/narrative.md`, `control/philosophy.md`) with its review status from the review records (drafted, reviewed, accepted) and why, linking the file and the record that decides; the loop summary (loop id, title and section, what it measures, the controller action, the final elements with their fail positions and split ranges, the targets with unit and provenance, the modes, cascade/ratio/feedforward/override links and related C&E interlocks, its findings by level and its open points; `?` where a value is not known yet); each sequence with its mode, start permissives, the C&E trips that protect it, its steps (entry, actions, completion, timeout, next, operator), abort and reset; the narrative's sections and the philosophy's objectives and failures; the `cheme.control-*` findings, each linking its file and line. In the page navigation (Control) and on the home page when `/api/repo` reports `has_control` (the empty templates of `cheme init` do not count); a 404 shows "No control records". At another revision it says it shows the working tree, and its links open the working tree. `cheme export-static` records `/api/control` only for the working tree without `--exclude` (it names reviewers); a snapshot without it says so instead of "No control records" |
| `/issues?type=&gate=&discipline=&status=&closed=1` | The plant's issues as engineering items (`GET /api/issues`, `cheme issues --json`; GitHub issues of the repository and label `plant.yaml` `issues:` names, read live by the server): a header line with the number of open items blocking the current stage's gate (a `gate:` at or before it) and their numbers; a "New …" button per issue form (New action item, New engineering hold, New technical query (TQ), New design change; the template chooser without forms); the open items grouped by the gate they must be closed before, in stage order, then "No gate", each with its number linking the issue on GitHub, title, a type badge (Action item, Engineering hold, Technical query (TQ), Design change, or Untyped), its status (open, in progress, for verification), what it waits for (input, other work), its disciplines and source. Filters for type, gate, discipline and status, and closed items behind a toggle (all in the URL). A 404 shows "This plant does not track issues", a 503 (no token, offline) the server's message and the hint to start `cheme serve` with `GITHUB_TOKEN` / `GH_TOKEN` or after `gh auth login`. At another revision it says it shows the issues as GitHub has them now. With issues, the P&ID's selection panel (and the BFD/PFD's) offers "New issue about <tag>" (the action-item form, its References field set to `<sheet id> <tag>`) and the control page one per loop (`control/loops.yaml <loop>`); `/api/issues` is loaded once per session for them. `cheme export-static` records `/api/issues` for the working tree without `--exclude`; a snapshot without it has no "New issue" links and the page says so. In the page navigation (Issues) and on the home page when `/api/repo` reports `has_issues` |
| `/datasheets` | The equipment datasheets, `equipment/datasheets/<TAG>.yaml` (`cheme datasheets draft` / `fill`, core's `domains/equipment/schemas/datasheet.py`): totals (sheets, drafts, assumed values, TBD or missing values, values awaiting the supplier) and a table per sheet of tag, type, service, draft or final, and its counts of assumed, TBD (TBD, null or missing) and supplier values; filter by tag, type or service, a type selector, sortable columns. With a server that has `GET /api/datasheets` (`has_datasheets` in `/api/repo`, pre-release PR 95) the index comes from it in one request and adds per sheet whether it states main dimensions and weights, its outline drawing's state (current, stale, missing) and its findings by level, the plant totals of those (drawings current, stale / missing, errors / warnings) and the equipment-list items without a datasheet (with `cheme datasheets draft --tag`). An older server, or a snapshot without the endpoint (or its 404), falls back to the files: they are listed from `/api/tree` and each is read parsed through `/api/yaml` as committed at the revision (in a static snapshot from its `yaml` entries), without drawing states and findings. In the page navigation (Datasheets) and on the home page when `/api/repo` reports `has_datasheets` or the tree has `equipment/datasheets/` |
| `/datasheets/<TAG>` | One datasheet: tag, type, service and a draft badge; the counts; operating and design conditions, materials and the type-specific values as tables (parameter, value, unit, source; an assumed value marked `A` with its source or reason as tooltip, TBD rows highlighted, `supplier` and not-applicable values with their reasons; a list value such as a compressor's intercooler duties separated by semicolons, `1,500; 1,450`), the other type-specific fields (`process_streams`, ...) as a tree; the nozzle schedule (DN, lines, face, orientation, elevation, service, sheet), each line linking into the line list (`/yaml/piping/line-list.yaml?filter=<line>`, when the tree has it) and the 3D layout (`/layout?select=<line>`), each sheet to its P&ID with the item selected (`/pid/<sheet>?select=<TAG>`); the sizing basis and notes. A value `cheme datasheets fill` calculated shows, in the value tables, the main dimensions, the weights and the sizing basis (not the column sections table), its origin as a badge (`correlation`) and a disclosure `depends on: catalyst CAT-1, pipe L-12, nozzle R-101/N1, +2 more` that opens (click, tap or Enter) to the full list of inputs besides the streams and the fingerprint, which `cheme validate` checks (`cheme.datasheet-stale`). Main dimensions grouped by family (shell, support, tube bundle, plates, machine, overall; column sections as a table), each with its unit (m, deg, t for a plain number), source and assumed marker; weights (empty, operating, test); materials with their material class chip and standard; the nozzle schedule with mark, service, DN, rating, facing and flange standard, face, orientation, elevation, projection, lines and sheet. From `GET /api/datasheets/{tag}` also the sheet's findings (level, rule, message, hint, file and line) and an Outline drawing panel: `GET /api/datasheets/{tag}.svg` sanitised (as the P&IDs) in the pan/zoom pane, with a state badge (committed and current, committed and stale with a toggle for the generated preview, generated preview when none is committed), a download link and the `cheme datasheets drawing --tag <TAG> --write` hint when missing or stale; on the file path a committed `<TAG>.svg` is shown unchecked. "Show in 3D" (`/layout?select=<TAG>`, with a layout), "YAML" and "Source" open the file. The layout's selection panel links an item's datasheet here |
| `/history?path=` | Commits. For a sheet, select two commits (or one, to compare it with the working tree) and open the diff |
| `/layout` | The plant layout (`GET /api/layout`). With the generated model (`layout/plant-model.yaml`, `cheme layout build`) it draws equipment from its parts, nozzles, maintenance envelopes, pipes with elbows and insulation, valves and instruments, rack and frame steel, gratings, stairs, ladders with cages, access platforms, pipe shoes and guides, valve bodies with their operators, building and enclosure walls and zone volumes, a sleeve where a pipe passes a wall or a building roof outside its openings, and with an electrical list or `layout/hvac.yaml` the cable trays (by system, on their own tier steel), junction boxes and air handling units, ducts (by air system) and terminals; without one, the placement primitives. Layers menu, colour by type and service, pipe class or provenance (generated, pinned, declared, and what to review: fallback `direct` routes, proposed platforms, stairs, ladders, step-overs, wall openings and junction boxes), x-ray, a section box, a realistic look (physically based materials by part material, an environment map, a soft sun shadow and ambient occlusion, gratings cut by an alpha pattern) and the level of detail (`near`: an item's detail parts, `lod: 2`, replace its envelope, `lod: 1`, within 90 m of the camera; `full`; `envelopes`); orbit, walk (eye height 1.7 m, level snapping) and fly; Iso, Top, N, E, S, W views framing the plant (equipment, steel, racks, buildings and the pipes among them) and a Site view of the whole plot, focus framing the selection, measure, `.glb` export and `.stl` export for 3D printing (millimetres at 1:100 to 1:1000, with an optional base slab at ground level). Equipment tags show by default, line numbers on their own toggle; overlapping labels give way by priority (selection and its related objects, equipment, structures and racks, lines) and fade with distance. The legend starts as a compact button and groups equipment types and pipe services into families. Clicking an item, tag or list entry shows its data and "Open in P&ID" (`/pid/<sheet>?select=<id>` highlights it; the P&ID's "Show in 3D" links back with `/layout?select=<id>`). Selection, layers, mode, section and camera live in the URL. A 2D tab shows core's plan and section SVGs (hidden when the server has none). Findings (the layout's and `model_findings`, the rules on the model) are listed beside the view, grouped by rule with counts (collapsed when there are more than 10); clicking one marks its items and its 3D box. Valves and transmitters with a declared operator (`piping/routing.yaml` `operators:`) show it, drawn schematically by the viewer since the model has no geometry for it: a chain wheel with its chain down to 1 m above the floor under it, an extension spindle or remote operator as a rod to a pedestal 1 m above the nearest floor, a remote-mounted transmitter on a stand 1.2 m above the nearest floor with its impulse lines or capillary (core's heights; its head leaves the tapping). A declared `hatch` in a casing or building wall is drawn as a frame and a closed cover and is an item of its own (`/layout?select=H1`). An equipment item links its datasheet page (`/datasheets/<TAG>`, when the tree has `equipment/datasheets/<TAG>.yaml`), and with a committed `layout/lifting-study.csv` (`cheme layout lifting --write`) a Lifting study panel lists each lift (item, crane pad, radius, load moment, chart capacity needed, lane), the selected item shows its lift; With a committed `electrical/cable-schedule.csv` (`cheme layout cables --write`) a Cable schedule panel lists every cable (tag, kind, from and to, kW, length, its size, voltage and trays on hover; count and total length in the header) sortable by each column and filterable by any word (system, kind, an end, a tray, `review`), the rows to review highlighted; clicking a row selects its cable and marks its way in 3D. cheme serve has no endpoint for these, so they are read through `/api/tree` and `/api/file` as committed. Selecting a motor's item or an instrument marks its cable's way (the trays in order from its room, the junction box, and the cable drawn over the model); a cable or tray lists the other; a unit or room marks its ducts. The side panel also lists the proposals to review (each says why and the `cheme layout pin` that keeps it; a roof penetration instead says why it cannot be pinned, core's refusal, and shows its opening in the building's plan frame), the cabling and HVAC summaries, the router's summary (routes per method, rack fill per tier) and the segments it could not route, each linking to its P&ID. In the page navigation (Layout 3D) when `/api/repo` reports `has_layout` |

The sidebar is the page navigation (`src/lib/pages.ts`): Overview, then the plant's pages and
documents in engineering groups (Process: BFD, PFD, stream table, simulation, reactions, design
basis, process narrative, materials; P&IDs; Equipment and lists: datasheets, equipment, line,
instrument and electrical lists, cable schedule; Control and safety: control, cause & effect,
risk matrix, HAZOP studies and session, relief study; Layout: 3D, lifting study; Cost and
impact: MTO and estimate, cost estimate, equipment cost, TEA, LCA; Quality: checks, validation,
maturity, reviews, issues; Project: README, design notes, stages, progress, history, the reaction
library). A page is listed when the plant has something for it to show, a document when its
file (at the template's path) is in the working tree. Each group's heading (marked with a
chevron) opens its section page (`/section/<id>`), an overview of the group's pages and
documents as cards, the sheets with a thumbnail of the drawing. Below, "Files" is the raw
repository tree with its filter, for experts: folded by default, it opens by itself when a page
shows a file the navigation does not list (and keeps the choice made with its toggle in the
browser). The home page lists the same groups, each heading linking to its section page, as do
its sheet headings ("Process", "P&ID sheets"). On phones the sidebar is a drawer behind the menu
button.

Long pages (Control, MTO, LCA, TEA, Maturity, Reviews) have a section bar under the title
(`src/components/SectionBar.vue`): a link to each section, kept in view while the page scrolls,
the section in view marked; a section deep-links as `#sec-<name>` (`/control#sec-loops`), in a
snapshot too. A findings list folds its info findings away when there are more than five, the
control loops are clamped to three lines a row ("more" on a row, "all details" for all), the
sequences are folded when there are more than two, and the stream table shows a composition's
three largest fractions ("+n more"; all of it on a selected row or with "full composition").

The revision selector in the header (working tree, a branch, or any tag or sha via `…`) sets
`?rev=` for every page. While another revision or case loads, a page shows its loading state,
never the previous one's data under the new label.

Every page sets the browser tab's title (`<page> – <plant> – cheme-as-code viewer`). After a
link to another page the focus moves to its heading, and a "Skip to content" link (the first
`Tab`) leads past the header and the navigation. In-page links (Markdown `#heading` links, the MTO
total cards) scroll without changing the route, so they also work in a snapshot's hash URLs.

## Develop

Requires Node 22.22.2+ (on 22) or 24.15+ (jsdom's floor; CI tests 22.22.2 and 24) and a plant
repository with cheme-as-code installed.

```sh
npm install
# in another terminal, from the plant repository:
cheme serve            # API on http://127.0.0.1:8765
npm run dev                # http://127.0.0.1:5173, proxies /api to the server
```

To point the dev server at an API somewhere else, set
`CHEME_API=http://127.0.0.1:9000 npm run dev`.

`npm test` runs the unit tests (vitest + jsdom). They cover the API client's URL building and
errors, the highlight CSS, the SVG sanitizer, the YAML table columns and source highlighter, the
Markdown parser and renderer (heading ids, in-page links in hash history), `useAsync` (aborts,
out-of-order answers, no stale data after a source change), the case-select focus helper, the
page titles, the review-record rules (`src/lib/reviews.ts`), the maturity states (`src/lib/maturity.ts` and `loadMaturity`: level states, the badge, fingerprints as core's, recorded reports against the revision shown, on the ASU's real report), the pan/zoom maths, the datasheet parsing and counts (on the ASU's real sheets), and the simulation and reaction rules (`src/lib/simulation.ts`, `src/lib/reactions.ts`: spec flattening, filled values, run state, element balance, equilibrium approach, a reactor's P&ID, rate-law texts, a reaction's catalyst, the line chart of k(T)), the fixed beds (`src/lib/fixedBed.ts`: which reactors have a bed or why not, the declared mode and reference temperatures, where core's peak is among the sampled points, the CSV, a recorded run's state), and the catalysis rules (`src/lib/catalysis.ts`: coverages and rate control, a step's equation, the fit against its points, the library's marks and filter) and the issue rules (`src/lib/issues.ts`: grouping by gate, filters, the blocking count, new-issue links with references, a picked object's tag) on core's real answers. `npm run typecheck` runs `vue-tsc` over the app and the unit tests (`tsconfig.app.json`) and over
the Vite and Playwright configs and `e2e/` (`tsconfig.node.json`); CI runs it before the tests.

`npm run test:e2e` builds `dist/` and runs the browser tests (Playwright, Chromium) in `e2e/`:
`vite preview` serves `dist/` on port 8790 (`E2E_PORT` to change it) and every `/api` request is
answered in the browser from `e2e/fixtures.ts`, so no cheme-as-code server is needed. They check
wheel zoom, drag to pan, Fit, click-to-inspect, the title-block highlight of a metadata change
and the YAML highlighting; `e2e/keyboard.spec.ts` checks keyboard picking in a P&ID, stream rows,
page titles and focus after navigation, the skip link and what a page shows while another
revision loads (stream table, the previous pick, History's Load more), `e2e/layout.spec.ts` the
Layout 2D tab across a revision change, and `e2e/snapshot.spec.ts` Markdown `#heading` links and
the MTO total cards in a snapshot's hash URLs. Install the browser once with `npx playwright install chromium`.

## Build

```sh
npm run build              # type-checks, then writes dist/
```

## Serve

```sh
cheme serve --ui dist                    # or: CHEME_UI=$PWD/dist cheme serve
cheme serve --repo ../process-library/processes/asu-1 --ui dist --port 8765
```

`cheme serve` serves `dist/` at `/`, falls back to `index.html` for client routes, and
answers `/api/*` itself. It binds to 127.0.0.1 by default.

### Several plants (a library)

```sh
cheme serve --repo ../process-library --ui dist   # every plant below, each under /p/<id>/
```

On a folder of plants (process-library's root, or a folder of plant repositories), `cheme
serve` serves each plant under `/p/<id>/` and lists them at `/api/plants` (core's ADR 0034).
The viewer reads its plant from the page's path (`src/lib/plants.ts`, `src/main.ts`): under
`/p/<id>/` its API calls and routes are the plant's; at `/` of a library it shows the index of
the plants (`src/PlantsApp.vue`: name, path, stage, the recorded maturity, sheets, and a
`process.yaml`'s title, summary and families when there is one; filter by text, family and
stage). In a plant the header has a plant switcher and a link to the index ("<library> /").
Switching loads the other plant's page: the same page when it is a plant-wide one (stream table,
LCA, checks, ...), its overview for a page of one sheet, file or tag; `?embed` and `?theme` stay,
the revision does not. A server of one plant answers `/api/plants` with a 404 and the viewer is
as before. `npm run dev` proxies `/p/<id>/api/` too.

## Static snapshot (no server)

`cheme export-static DIR` (core) writes the API answers of one revision as files. The viewer
opens them with `?data=<snapshot directory>`; routes then live in the URL hash, so the build and
the snapshot can sit on any static host (the Process Atlas embeds it this way):

```sh
npm run build:static                       # dist-static/, relative asset paths
cheme export-static site/snapshot --repo ../my-plant
cp -R dist-static site/viewer              # open site/viewer/?data=../snapshot/#/
```

`?data=` is resolved against the page and must be on the page's own origin (a relative path
such as `../snapshot/` or `/data/asu-1/snapshot/`, or an absolute URL of the same site); a link
to a snapshot elsewhere shows an error and requests nothing from that host, so nobody can show
their plant under your site's name. To allow snapshots from other origins, list them at build
time: `VITE_SNAPSHOT_ORIGINS=https://data.example,https://cdn.example npm run build:static`
(the other host must also send CORS headers).

A snapshot is one read-only revision: the header shows "Snapshot <commit>" instead of the
revision picker, and History, Diff and "Run now" are hidden. A request the snapshot does not hold
(another revision, a file above the export's size limit, a section at arbitrary coordinates)
answers 404 with a plain reason. `src/dataSource.ts` holds the snapshot source and its key
contract (core: `docs/framework/static-snapshot.md`); `src/api.ts` switches to it with
`useSnapshot()`, so views and types are the same in both modes.

### Embedding

Two more query parameters, before the hash like `data`, are read once at startup and stay when
the route changes (`src/lib/viewerOptions.ts`; against a server, where they are part of the route,
the router carries them over to every in-app navigation). They work with and without `?data=`:

- `?embed=1`: for a frame in another page. No header and no file tree; the routed view fills the
  frame and keeps its own toolbar, and its links navigate inside the frame. A small "Open full
  viewer ↗" link in the bottom-left corner opens the same page without `embed` in a new tab.
- `?theme=light|dark|system` (default `system`): forces the colour scheme by setting
  `data-theme="light"|"dark"` on `<html>`; `system` leaves it unset and follows
  `prefers-color-scheme`.
- `?back=<url>&back_label=<text>`: a "← <text>" link at the start of the header back to the
  page that opened the viewer (the Process Atlas's process page opens its full viewer so). Only a
  link on this site is shown (a relative URL or the same origin, http or https); any other is
  ignored.

The Process Atlas frames a route of a snapshot this way:

```html
<iframe src="/viewer/?data=../snapshot/&embed=1&theme=dark#/pid/process/PFD.xml"></iframe>
```

An embedded viewer tells its page how far it is (`src/lib/embedSignal.ts`): `postMessage` to the
same origin, `{ type: "cheme-viewer", version: 1, stage, route }`, where `stage` is `app` (running
and routed), `visual` (the drawing or the 3D overview is on screen), `detail` (the 3D model is
complete) or `error`, and `route` is the view it belongs to. The page should check the message's
`origin` and `source`.

## Design notes

Architecture decisions are recorded in [docs/adr/](docs/adr/README.md); a pull request that
changes the architecture adds an ADR there.

- `src/api.ts` is the only code that talks to the server. It is typed against the API contract
  of `cheme serve`: `JsonEndpoints` maps each endpoint to the type of its answer, and every JSON
  request goes through it. An absent `rev` means the working tree.
- Everything from the API is rendered as text through Vue's escaping. Markdown is parsed into a
  data tree and rendered with `h()`, so no HTML string is ever injected.
- The SVG comes from our own server but is still cleaned before it is shown
  (`src/lib/sanitize.ts`): scripts, `foreignObject`, animation elements, `on*` attributes,
  script URLs and links or images on other sites are removed. CSS is rebuilt, not matched
  against patterns: `style` attributes and `<style>` rules keep only drawing properties (fill,
  stroke, fonts, ...) whose values call no function but colours and `url(#fragment)`, so CSS
  escapes, `url()`, `image-set()` and `@import` cannot load anything; presentation attributes
  such as `fill="url(https://...)"` are dropped the same way. `<style>` rules are kept only with
  plain type, class and id selectors, each prefixed with the drawing's own `data-svg-scope`
  attribute, so a drawing's CSS (core's datasheet sheets have `text{...}`) never styles the rest
  of the page or another drawing. The cleaned element is inserted with `importNode`, so it is
  never parsed as HTML.
- Diff highlights are CSS rules on `[id="…"]`, scoped to each pane, using the same colours as
  `cheme diff` (`src/lib/highlight.ts`). Ids are escaped for CSS strings.
  The title block and border have the id of their DEXPI Label/Border (cheme render sets it),
  and a plant metadata change is mapped to the title block by the server, so it is highlighted.
- YAML source is highlighted by a small tokenizer (`src/lib/yamlHighlight.ts`) that returns
  plain-text tokens; each is rendered as text in a `<span>`, so nothing is parsed as HTML.
- The drawing's PDF (`src/lib/pdfExport.ts`) is drawn by svg2pdf.js into jsPDF (both MIT,
  pinned to exact versions), loaded with a dynamic `import()` on the first click of "PDF", so no
  page downloads them before (jsPDF's own optional html2canvas, canvg and DOMPurify chunks are
  never loaded). The page size, the file name and the SVG it draws (fonts mapped to the standard
  PDF fonts, `dominant-baseline` turned into the alphabetic baseline, as svg2pdf places it too high, the
  sheet background dropped) are pure functions, unit tested; `e2e/pdfExport.spec.ts` checks the PDF.
- The layout view keeps the geometry rules (sizes, positions, rotations, colours, clash
  highlights) in `src/lib/layoutScene.ts`, which has no three.js and is unit tested; the
  three.js part (`src/lib/layoutThree.ts`, three pinned to an exact version) is loaded with a
  dynamic `import()` on `/layout` only, so other pages never download it. The scene uses the
  site frame directly (x east, y north, z up); equipment `position` is the plan centre and the
  bottom elevation, building `origin` the south-west corner the footprint turns about, and
  `frame.grid_x`/`grid_y` offsets from that origin. The generated model becomes mesh
  descriptions in `src/lib/layoutModel.ts` following core's contract
  (`docs/framework/layout-model.md` in cheme-as-code; pure, unit tested, also the section box, floor
  snapping and measuring); `layoutThree.ts` merges them per layer, material and opacity into a
  few meshes with vertex colours and maps a ray hit back to its item by vertex range. Envelope
  and detail parts are batched per 32 m plan cell and switched per cell by camera distance;
  repeated detail shapes and handrails are instanced (a hit maps back by instance). The
  realistic look (`src/lib/layoutRealism.ts`) renders through an effect composer (multisampled
  target, GTAO ambient occlusion, output pass) and is built on first use. `e2e/realism.spec.ts`
  measures the frame rate at full detail on the ASU fixture (`LAYOUT_SHOTS=<dir>` saves
  screenshots, `LAYOUT_FPS_MIN` sets the bound); `e2e/shots.spec.ts` saves close-ups, trays,
  cable routes, ducts and the take-off page for checking by eye (`LAYOUT_SHOTS=<dir>` only).
- Plain CSS with design tokens in `src/styles.css`. Dark mode follows `prefers-color-scheme`
  unless `?theme=` forces a scheme (`data-theme` on `<html>`); the dark tokens are written for
  both cases and a unit test keeps them equal. Code that needs the scheme in JS (the 3D
  renderer) asks `isDarkScheme()`. Sheets keep a light background so their black linework stays
  readable.

## Licence

GNU Affero General Public License v3.0 or later (AGPL-3.0-or-later); see [LICENSE](LICENSE).
Copyright and TU Delft's copyright disclaimer are in [NOTICE](NOTICE). Plant repositories shown in
the viewer keep their own licences.
