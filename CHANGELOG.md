# Changelog

## Unreleased

### Added

- Batch and conversion models write and check their energy streams (ADR 0059, #180). `cheme
  process propagate --fill` writes the year-average duty (kW per hour of the flowsheet's
  flows, `calculated` with a fingerprint) of an isothermal `reactor: batch` or `semibatch` (the
  heat its reactions release and the doses warmed), a `still:` (its boil-up's latent heat), a
  `crystallizer:` with `energy:` and a conversion step, batch or continuous (its declared heats
  of reaction at their own `heat_of_reaction.temperature`, the streams brought to and from it at
  their heat capacities; or, with no stream said to hold a liquid and no liquid or mixed
  reaction, ideal-gas `H(out) - H(in)`; less the work its other energy streams bring in, such
  as an electrolyser's DC power; a component going from vapour to liquid across the step leaves
  it unknown). It goes on the energy stream at the step's new `energy_port:`, else on its one
  heat stream to or from a heating or cooling utility; an energy stream to or from another
  block or step (a furnace's coil, a rectifier's power) is heat only where `energy_port` names
  it. A duty is positive in its stream's direction; a model whose heat flows against it is a
  warning, never a negative duty. A given or assumed duty is never overwritten: one beyond the
  flowsheet's relative tolerance is `cheme.process-duty` (warning, naming both values), from
  `propagate` and now also from `cheme validate`; two models that give one stream different
  duties are a warning naming both, neither written; several heat streams or missing data are
  info. `validate` adds `cheme.process-energy-port`. A flow-style energy stream is written in
  place. `cheme process reactors` shows a batch's or conversion step's duty and its stream where
  the ideal-gas duty was `?`, and adds `model_duty` to `--json` where the model knows a duty or
  a stream wants one; `cheme process stills` shows the year-average duty.
  **Behaviour change**: `propagate --check` can newly exit 1, and `validate` newly warns, where
  a hand-typed duty differs from the model. In the process library seven entries do (scratch
  copies, 1.8.0 exit 0): benzyl-chloroformate-1 R101 Q2 and sodium-azide-1 R102 Q2 (batch),
  ethylene-1 H102 Q102, formic-acid-1 R201 Q10, hydrogen-bromide-1 R101 Q2,
  hydrogen-chloride-1 R101 Q1 and phosphorus-oxychloride-1 R201 Q3 (continuous conversion
  steps). `process reactors` text and JSON change for 44 of its 73 entries (the model's duty
  line). Plants without heat streams or given duties on these steps solve and fingerprint as in
  1.8.0. Every BFD/PFD needs `cheme process build` once (the process generator's code changed).

## 1.8.0 (2026-11-05)

Minor release: batch work-up (#165) and gas evolution (#174). A batch or semi-batch vents the
gas it forms and doses a gas only partly absorbed (`batch.vent`, `dosing.absorbed`; ADR 0054);
`still:` is a batch Rayleigh still or solvent swap whose boil-up time a recipe `distil` takes
(ADR 0055); a crystallizer precipitates from a mixed liquor with `spectators:` and a solubility
measured in that liquor or salted out, and `kind: phase-change` keeps phase changes out of the
reaction screening (ADR 0056); `dryer:` dries a cake to a residual moisture with its duty and
drying time, a filter gives Ruth's time, and a recipe unit procedure may hold several steps of
one vessel as `units:` (ADR 0057). Plants that use none of them solve and fingerprint as in
1.7.0, except that a recipe unit naming a block now sizes the vessel of the one batch step in
it. Every BFD/PFD needs `cheme process build` once (the process generator's code changed).

### Added

- Gas evolution and gas dosing in a batch or semi-batch (ADR 0054, #174): `batch.vent:
  {stream, components, fraction}` on a liquid `reactor: batch` or `semibatch`. The listed
  components (HCl, CO2, HBr) leave the liquid as they form, a `fraction` of what forms (default
  1, a share of the gross formation, reaction by reaction: a reaction that consumes a vented gas
  takes it from the liquid, never back from the vent), by the vent stream, a second outlet of
  the step: they do not accumulate in the liquid and
  count in neither its volume, concentrations nor heat capacity, and their `heat_of_reaction`
  forms them as gas at the vessel's temperature. A dose may give `absorbed: share` (a dosed gas
  such as phosgene or Cl2): that share dissolves on entry, the rest passes through to the vent,
  its sensible heat to the vessel's temperature from its ideal-gas cp (else noted). `process
  propagate` writes both outlets (composition, flow, temperature, pressure) and the balance
  closes over them; `process reactors` reports the vent (kmol/h, peak kmol/(s m3) and when),
  `process recipe` the off-gas per batch (peak kmol/s and m3/h at the vessel's conditions, kg
  and kmol per batch), and `process reactor-hazards` leaves the vented and passing gas out of
  the MTSR and the MTT (what stays in the liquid, a charged vent component and a dose's
  absorbed share included, sets the MTT), with a note of the peak gas rate. New `cheme.process-reactor` findings:
  the vent stream no outlet of the step or its only one, more than two outlets, an undeclared
  vent component, a vented batch on gas-phase reactions, a vent stream whose template lacks a
  vent component or a passing dose's component, (warning) a vent component no reaction forms,
  a dose with `absorbed` below 1 and no vent. A dissolving dose adds no heat of absorption or
  condensation: write its reactions' `heat_of_reaction` with the dosed gas as a gas. `process
  simulate` refuses a vented batch. An unvented batch or semi-batch solves and fingerprints as
  before. Every BFD/PFD needs `cheme process build` once (the process generator's code changed).
- Precipitation from a mixed liquor (ADR 0056, core#165): `crystallizer.spectators: [ids]`
  carries other dissolved components (salts, base, unreacted reagent) unchanged in the mother
  liquor. The solubility is either measured in that liquor (`solubility.measured_in:
  mother_liquor`, units `kg/kg_solvent`, `mass_fraction` or the new `kg/kg_liquor`), or the
  pure solvent's corrected by `solubility.salting_out: {coefficients: {id: k}}` (Setschenow,
  molal scale). A pure-solvent value alone is `cheme.process-crystallizer` (error) and refused
  by propagate. A crystallizer takes several inlets together, so a reslurry wash is a
  crystallizer fed by the cake and the wash. `cheme process crystallizers` (text and `--json`)
  reports the spectators' balances and molalities; with spectators its
  `solubility_kg_per_kg_solvent` is the mother liquor's per kg of free solvent (the declared
  value under `mother_liquor.declared_solubility`). A block holding a crystallizer next to a
  reacting step (a precipitation in the reactor vessel) balances, the crystallization fitted
  as a phase change beside the block's reactions. Every BFD/PFD needs `cheme process build`
  once (the process schema changed).
- `kind: phase-change` on a reaction of `process/reactions.yaml`. A reaction of one component
  into one other with the same formula, one of them `phase: solid`, counts as one without the
  field unless it declares a `heat_of_reaction` (then it stays screened, its heat in dT_ad).
  `cheme process reactor-hazards` no longer screens a step whose reactions are all
  phase changes (`cheme.reactor-hazard-phase-change`, info; JSON `phase_changes`), and takes the
  dT_ad and MTT of a step with both from its reactions alone; a semi-batch's MTSR stays its
  model's, the phase changes included, and a note says so.
- Filter-dryer and vacuum dryer (ADR 0057, core#165): a block or step may give `dryer:
  {volatiles, residual_moisture, temperature, energy, drying_rate | drying_time, cake_density,
  outlets: {product, vapour}}`. `cheme process propagate` writes the dried product (the
  volatiles down to the residual moisture, the dissolved solids dried onto the crystals) and
  the vapour. `cheme process crystallizers` reports the duty: the cake's sensible heat, the
  latent heat (declared, else Pitzer's correlation from the critical constants) and the
  vessel's heat per batch, over an efficiency. It compares the duty with the heating stream at
  `energy.port` (`cheme.process-dryer-duty`). Model basis `residual-moisture`; rules
  `cheme.process-dryer`. A
  `solid_separation:` may give `filtration:` (specific cake resistance and more) for Ruth's
  filtration time.
- Recipe (ADR 0057): a `dry` operation takes `from:` a dryer (one batch's vapour over the
  drying rate times the vessel's heated area, or its drying time) and a `filter` operation
  takes `from:` a filter with `filtration:`. A unit procedure may give `units: [steps]` that
  share one vessel (a filter-dryer: filter, wash, re-filter, dry), its occupancy counted once
  (NBS lesson L-3). `vessel.heated_area` is new, and a filter-dryer's vessel is sized from the
  largest content of one batch: the dryer's wet cake over its `cake_density`, or the slurry or
  reslurry wash a step of the vessel takes in. A `unit:` that is a block holding one batch or
  semi-batch step now sizes the vessel from that step (1.7.0 gave `cheme.recipe-reference`);
  a block or `units:` holding several is `cheme.recipe-reference` (name one as `unit:`). A
  filter or dryer in the vessel of a batch step takes its filter area and heated area from it. Every BFD/PFD needs `cheme process build` once
  (the process generator's code changed).
- Batch still and solvent swap (ADR 0055, core#165): a block or step with `still:` is a batch
  (Rayleigh) still, shortcut level (one equilibrium stage, total condenser, no reflux). The
  vapour comes from Raoult's law with the components' new Antoine `vapour_pressure` in
  `materials.yaml` (the NIST form by default), or from a constant relative volatility
  (`volatility: {model: constant, alpha}`). The boil-up is constant: kmol/h, kmol/s, kg/h, kW
  (with the new `heat_of_vaporization`) or 1/h of the charge. The still stops at its `end`
  (a share `distilled`, a `residue` key's mole fraction, a `time` or a `temperature`), or
  collects `cuts` in turn. `feed: {stream, mode: constant_level | portions, down_to}` makes
  it a solvent swap. `cheme process propagate --fill` writes the cuts and the residue.
  **`cheme process stills [--case] [--json]`** reports the charge, feed, cuts and residue per
  batch, the boil-up time, the duty and the energy per batch (one batch from
  `process/recipe.yaml`'s batch size) and the still's temperatures. A recipe `distil`
  operation takes its time `from:` the still. `cheme validate` checks it
  (`cheme.process-still`): the ports, the charge and feed, and the missing vapour pressures,
  relative volatilities or heats of vaporization. Qualified against Rayleigh's binary closed
  form, the Rayleigh integral with Raoult's law, and the constant-level swap's closed form
  (`tests/test_batch_still.py`). PharmaPy was reviewed and not used (Assimulo is not
  installable with uv on Python 3.12+). Every BFD/PFD needs `cheme process build` once (the
  process generator's code changed). One stage covers solvent strips and swaps
  (`examples/process-solvent-swap`: methanol to toluene under vacuum at constant level, the
  recipe's distil from the still; illustrative, since methanol-toluene forms an azeotrope and the
  ideal liquid is declared `assumed`). Product purification by fractional batch distillation still
  needs a column (`process simulate` or a specified split) until the constant-reflux
  follow-up (core#173).

### Fixed

- Batch work-up features together (the integrated review of #169 to #172): a step with both
  `still:` and `dryer:` is `cheme.process-still` (error), not a still in propagate and a dryer
  in `process crystallizers`. `cheme process crystallizers` prints the
  `cheme.process-dryer-duty` warning in its text output too. A semi-batch's MTT counts what
  stays in the liquid (a dose's absorbed share, a charged vent component). A recipe vessel
  holding a batch step and a filter or dryer gives the filter and dry times its plate and
  heated area. `datasheets fill` finds a batch reactor's recipe vessel inside `units:`. The
  REFERENCE.md recipe paragraph and command list, the maturity table (`rayleigh`) and ADR
  0055's Rayleigh example are corrected.

## 1.7.0 (2026-11-05)

Minor release: batch and semi-batch processes (#158). `reactor: semibatch` doses feeds into a
charge and gives the thermal screening the accumulation of the dosed reactant and the MTSR at
the worst moment (ADR 0050); `process/recipe.yaml` and `cheme process recipe` derive the cycle
time, the batches per year and a Gantt chart, and the TEA takes them (ADR 0051); the recipe
sizes batch vessels and checks their jackets (ADR 0052); LCA consumables may be given
`per_batch` (ADR 0053). Every BFD/PFD needs `cheme process build` once (the process
generator's code changed).

### Added

- Per-batch LCA exchanges (ADR 0053, core#158 package 5): an `lca.yaml` consumable may give
  `per_batch` instead of `per_year`: per hour of the flowsheet's year averages it is per batch x
  batches per year / hours of `process/recipe.yaml`, the arithmetic in the exchange's source;
  without a recipe that gives a cycle it is `cheme.lca-per-batch` (error).
- Batch vessels and jackets (ADR 0052, core#158 package 3): a unit procedure of
  `process/recipe.yaml` on a batch or semi-batch step may give `vessel: {fill_fraction,
  aspect_ratio, nominal, volume, jacket: {u, area, coolant_temperature, heating_temperature}}`.
  `cheme process recipe` sizes it from the batch content (the model's content times batch size /
  the flowsheet's rate), rounded up to the R10 preferred numbers, and checks the jacket against
  the model's peak duty (`cheme.recipe-jacket`, `cheme.recipe-vessel`). A `heat` or `cool`
  operation may give `temperatures: [start, end]` instead of a duration: its time from the
  jacket's UA and medium temperature. `cheme datasheets fill` takes a batch reactor's volume and
  peak duty from the recipe's vessel (input `recipe:<unit procedure>`).
- Batch recipe (ADR 0051, core#158): `process/recipe.yaml` (`cheme/recipe/v1`) declares the
  batch size (kg, t or m3 of one stream), the operating hours and the unit procedures with their
  ordered operations (charge, heat, dose, react, cool, transfer, filter, dry, clean, hold,
  other), each with a duration or, for dose and react, `from:` a batch or semi-batch step.
  `cheme process recipe [--svg FILE] [--json]` derives each unit's occupancy, the cycle time and
  bottleneck (with parallel units), the batches per year, one batch's timeline and its Gantt
  chart (SVG, light and dark). `cheme.recipe-basis` (warning) when the flowsheet's rate of the
  batch-size stream differs from batch size x batches / hours; `-schema`, `-reference`,
  `-duration` (errors). `cheme schema process-recipe`. The TEA's `operation.batch: {recipe:
  true}` takes its cycle time and batches per year from it (`cheme.tea-batch-recipe`); the
  hand-entered form stays valid. `examples/process-semibatch` has a recipe.
- `reactor: semibatch` (ADR 0050, core#158): a liquid batch with feeds dosed into its charge,
  `batch.dosing: [{stream, time | profile, start}]`, each dosed stream an inlet of the step and
  the other inlet the charge; `batch.time` or `target` is the post-reaction. The same rate laws
  and integrator as `reactor: batch` (`stirred_tank.solve_batch` with doses, the doses'
  sensible heat in the energy balance). `cheme process reactors` reports the accumulation of
  the dosed reactant over time and its maximum, the cooling-failure temperature at the worst
  moment and the peak cooling duty per m3. `cheme process reactor-hazards` takes `X_ac` from
  that maximum and the MTSR from the worst moment (Stoessel's semi-batch treatment), so a
  dosing-controlled step no longer screens as an all-charged batch; a batch keeps `X_ac = 1`.
  `process propagate --fill`, `process reactor-uncertainty`, `datasheets fill` (volume and duty
  TBD, as a batch) and the model basis take it; `process simulate` refuses it (DWSIM's reactors
  take one inlet). Rules: a batch with `dosing`, a semi-batch without it, a dosed stream that is
  no inlet, not one charge stream, a gas-phase reaction (`cheme.process-reactor`, errors).
  Example `examples/process-semibatch` (acetic anhydride dosed into water).

## 1.6.0 (2026-11-05)

Minor release: the PFD drawn as an engineering sheet (ADR 0046) with per-step symbols, the
drawing lint `cheme.line-through-valve` and orthogonal measuring and signal lines in the
authoring API, and `cheme export-static --exclude` keeping excluded review records out of the
checks answer. Every BFD/PFD needs `cheme process build` once (generator 6); repositories made
with an earlier template keep their own `drawing-clean` gate.

### Changed

- The PFD is drawn as an engineering sheet (ADR 0046; generator 6: every BFD/PFD needs
  `cheme process build`): the smallest ISO 216 or ISO 5457 elongated sheet that holds it, with
  frame, zone markers and a title block; a stream table (phase, °C, bar, mass flow, the
  largest component flows, duties) below the drawing; utility terminals drawn as short stubs
  with the utility's id on each step they serve instead of boxes with a line to every user;
  mixing and splitting steps as junction tees; inlets aligned with their source (no small
  jogs); wrapped titles; heavier process lines with arrowheads; process areas as light
  dash-dot boundaries; layouts wider than an A0 wrapped into rows; each feed placed just before
  its first consumer. The BFD gets the frame and
  title block.
- `cheme render` paints the backdrop in the sheet's own `BackgroundColor` (white) instead of
  pyDEXPI's viewer grey, unless a filled shape on the sheet has that colour.

### Added

- A flowsheet step's optional `symbol:` (an ISO symbol name, `junction` or `box`) overrides
  the drawing of its class on the PFD; an unknown name is `cheme.process-symbol` (warning).
  `GeneratingFlow` and `TransportingFluids` steps are drawn as pumps, `SteeringFlow` as a
  control valve, `Crystallizing` as a jacketed vessel, `SeparatingMechanically` as a
  separator.
- Drawing lint: `cheme.line-through-valve` (warning), a signal or measuring line through the
  body of a valve, a pipe of another segment through a valve, or any line through an actuator's
  head: the most common defect left on the process library's ammonia-1 P&IDs (a control valve's
  signal drawn up through the valve to its actuator, an actuator drawn up the pipe of a
  vertical valve), which `line-through-symbol` never saw (it checks bubbles and equipment
  bodies only). The valve's own pipes, a line ending on the valve or actuator and the actuator's
  stem do not count; the finding names the valve an actuator operates (`Context.actuated`).
  `cheme.line-on-pipe` (warning): a signal or measuring line drawn on top of a pipe.
  `cheme.line-not-orthogonal` (info): a signal or measuring line with a slanted stretch (a hop's
  short legs excepted). On the process library's 26 asu-1, hda-1 and ammonia-1 sheets before
  their drawing clean-up: 56 line-through-valve, 14 line-on-pipe and 88 line-not-orthogonal;
  after it 1, 0 and 0 (the one left, on asu-1 P-03, is real).
- The fragment router (`cheme fragment instrument/signal --sheet`) keeps signal and measuring
  lines off valve bodies, actuator heads and the top of pipes; the template's example generator
  draws its measuring lines orthogonal.

### Changed

- The template's `drawing-clean` gate also fails on `cheme.line-through-valve`,
  `cheme.line-on-pipe` and `cheme.line-not-orthogonal` (`fail_on: info` for the last). A plant
  repository made with an earlier template keeps its own `checks/checks.yaml`: add the three
  rules there to get the stricter gate.
- The authoring API's `instrument` (`chemeascode.domains.piping.authoring`) draws the actuator
  at right angles to the valve's line on the bubble's side (down when the bubble is below a
  horizontal line, sideways on a vertical line; it was always up) and routes the signal line
  out of the bubble's side into the actuator's stem, so it never crosses the valve body. The
  measuring line leaves its line at right angles and stays orthogonal (it was a slanted straight
  line); `sensing_points=[...]` gives its bends. Generator scripts that relied on the old drawing
  draw differently when rerun (`cheme regen`).

### Fixed

- `cheme export-static --exclude`: the `checks` answer no longer names an excluded file. A
  stage sign-off's `review` is null when its review record is excluded, a check's `evidence`
  loses the excluded `path`, and its `detail` says "(a file not in this snapshot)" instead;
  the results stay. The Process Atlas's public check failed on ammonia-1, whose sign-offs name
  their `reviews/` records.

## 1.5.0 (2026-11-04)

Minor release: electrochemical measurements, measured-performance cells, dynamic electrolysis
duties with an anolyte model, stack sizing with skid equipment inputs, and design case LCI
datasets (tracker #136: #137, #138, #139; ADRs 0041 to 0045). No breaking change: every new
schema field is optional, and the outputs of existing water-electrolysis, chlor-alkali and LCA
fixtures are unchanged.

### Added

- Skid inputs for pilot skids (follow-up to #139, ADR 0044 amended), optional fields only:
  a dosing tank's `refill_interval` and a bleed tank's `empty_interval` size the tank for the
  most dosed or bled in any window of min(campaign, interval) and report the fills or emptyings
  per campaign; a duty's `stack:` runs a comparison duty at that stack's arrangement in
  `cheme process duty` and `--compare` (another `cells_in_series` or `stacks` on it, or a
  stack that is not there, is refused: `cheme.duty-arrangement`, error); `reservoir.size:
  to_horizon` (with an optional `time_margin`) gives the exact volume that reaches the horizon,
  `V0 Q(target) / Q*` (raised to keep a stated minimum inventory and the anolyte model's
  validity to the target, `limited_by`), in the duty's `required_volume` and the stack's
  `reservoir_required_volume_l`, which `cheme process stack --write` writes (rounded up to 4
  significant figures) into `process/duties.yaml`, then the tanks from the duty at it; refused
  with dosing, bleed, make-up, degassing or more than one operating point (`cheme.duty-size`);
  a stack's `product.recovery` (default 1) sizes the stacks for the rate over the recovery
  formed and reports formed and delivered output and kWh per kg. Every duty's totals are split
  by route (`initial_*`, `dosing_cation_mol`, `membrane_cation_mol`, `membrane_carbon_mol`,
  `bleed_cation_mol`, `bleed_carbon_mol`), so the cation and carbon balances close on their own;
  they are quadratures outside the integrator's error control (`foundation/ode.py`
  `solve(..., error_components=)`), so every existing value is unchanged.
- `cheme process stack [IDS] [--json] [--write]` (#139, ADR 0044): electrolyser stacks sized
  for a product duty from the optional `stacks:` section of `process/cells.yaml` (schema
  `cheme/electrochemical-cells/v1` unchanged, optional fields only), at the cell's operating
  point (a measured cell refused outside its measured range, never extrapolated): total active
  area, cells, cells per stack from the voltage limit, stacks, stack voltage and current, DC and
  AC power, rectifiers, output and its margin, kWh per kg, heat, the stack envelope and
  footprint, cell replacements. The skid equipment inputs come from the named duty of
  `process/duties.yaml`, run at the sized arrangement over its horizon: the reservoir, dosing
  and bleed tanks (vertical cylinders of the stated H/D, `head: flat`, `support: none`) and the
  recirculation and dosing pumps' inputs to the pump sizing (the recirculation pump's with its
  end points, the reservoir and the first stack). A duty at another current density or of another cell than
  the stack's, or not feasible there, gives none (`cheme.stack-duty`, error). `--write` puts
  them into the equipment-list `dimensions` (edited in place, comments kept) and the pumps'
  datasheet `type_specific`, never over a value written by hand; `cheme layout build` and
  `cheme datasheets draft`/`fill` take them from there. A value it wrote that the design basis
  no longer gives is reported outdated and cleared on `--write`; a tag two stacks or roles name
  is written by neither, and a second stack naming a skid duty gets no inputs from it;
  `--write --json` reports `written`. `cheme.stack-*` findings; `cheme validate` reports those
  that need no duty run. Docs: `docs/framework/electrolyser-stacks.md`.
- `cheme datasheets fill` gives a pump no flowsheet stream links its `flow_m3_h` from the
  declared mass flow and density when its lines are not routed yet (the head, NPSH and power
  stay TBD with the reason), and names `suction_from`/`discharge_to` when a declared pump has
  no end points.
- The equipment list's `dimensions` take optional `source`, `assumed` and `fingerprint` for
  sizes a tool calculated; `cheme datasheets draft` and `fill` carry `source` and `assumed`
  onto the datasheet's main dimensions.
- `cheme process duty` (and `--compare`) runs a duty a stack names at the arrangement that
  stack is sized at (`cheme.duty-arrangement`, info), as `cheme process stack` does: one result
  per duty id.
- Skill `skid-design` (domains/equipment): the skid chain from `cheme process build` through
  the cell, duty and stack sizing, the control P&ID, the datasheets and the layout, what goes
  into the LCA's flowsheet streams by hand, and what a human must judge.
- `cheme assess lca --dataset|--write|--check --case <id>` (#136, ADR 0045): the unallocated
  LCI dataset of another computed flowsheet case, with the study's scope, reference product
  and functional unit. Its id (`<dataset id>-<case>`), title (`<title>, case <case>`) and
  uuid (`uuid5(<base uuid>, "case:<case>")`) name the case, so two datasets of one process
  stay distinct. `--write --case` writes `lca/datasets/<dataset id>-<case>.yaml` (generated:
  header comment and provenance; never over a file it did not generate,
  `cheme.lca-dataset-not-generated`), and `--check --case` reports `cheme.lca-dataset-stale`
  (plain `--check` now reports a stale `lca/dataset.yaml` with it too). A review the study
  states is `unreviewed` in the case dataset, `superseded_by` is dropped and `parent` is the
  study dataset's uuid. Two cases whose ids give one identifier (`Hot`, `hot`) are the error
  `cheme.lca-case-id-clash`.
  An undeclared case exits 2 and lists the declared ones. `lca/dataset.yaml` is unchanged,
  and naming the study's case is the same as no `--case`. Python: `lca_report(root,
  case=...)`, `domains/assessment/lca/case_dataset.py`.
- `cheme process duty [IDS] [--json] [--plot DIR] [--compare ID,ID --co KG]` (#138,
  ADR 0043): dynamic electrolysis duties in `process/duties.yaml` (schema
  `cheme/electrolysis-duties/v1`, catalogue key `process-duties`). Current, power and on/off
  schedules against a cell of `process/cells.yaml` (measured performance looked up at each
  instant, never extrapolated: the transient stops at the first exit from the measured range
  and the time outside is summed), the anolyte reservoir's pH and inventory, product, charge,
  energy, dosing (on a pH trigger or continuous) and bleed over time, the time to the stated
  pH threshold, comparison at equal delivered product, aligned time plots and an operating
  map. `cheme.duty-*` findings; `cheme validate` reports the schema, cell and model ones
  (every error a duty is refused on before it is integrated).
- An anolyte model interface (`domains/chemistry/anolyte.py`: protocol and registry by id, no
  default) and its first model `well-mixed-carbonate` v1 (`domains/chemistry/carbonate.py`):
  moles of cation and inorganic carbon and the volume, equilibrium carbonate speciation from
  the charge balance on a concentration basis, optional CO2 degassing. Agrees with the
  process-library#329 reproduction of the authors' model (322.30 h to pH 12 at 1 L) and lies
  within its validation envelope. The NaCl electrolyte route is unchanged.
- `foundation/ode.py`: an adaptive Dormand-Prince 5(4) integrator with dense output and
  event location (pure Python).
- `cheme experiments electrochem FILE [--json] [--plot DIR]` (#137, ADR 0041): measured
  electrochemical series in `experiments/electrochemistry/*.yaml` (schema
  `cheme/electrochemical-measurements/v1`). Per replicate and point (mean, sd, n): Faradaic
  efficiency per product from the outlet flow (standard conditions required, never assumed)
  and mole fractions, partial current densities, the charge balance, the water dissociation
  efficiency of a bipolar membrane from the Warder double end-point titration of the anolyte,
  power, the heat at an isothermal boundary and the carbon balance; the charge balance and the
  `fe-sum-high` (above `max(1 + 3 sd, 1.05)`) and `fe-sum-low` checks per electrode;
  `cheme.electrochem-*` findings, also in `cheme validate`; SVG plots only for supported
  inputs.
  `MeasuredPerformance.at(j)` interpolates the point means and never extrapolates.
- `process/cells.yaml` (schema unchanged, optional fields): `performance: measured` with
  `measurements:` takes the voltage and Faradaic efficiencies from a measured series at the
  cell's current density, refused outside its range (`cheme.cell-operating-range`), with
  `cheme.cell-measured-conflict` and `cheme.cell-measurement`; a `membrane:` block reports the
  water dissociation efficiency, co-ion fluxes and the anolyte hydroxide deficit apart from
  the Faradaic efficiency (`cheme.cell-membrane`). The measured product must be formed by the
  cell's reaction; measured efficiencies above 1 within the measurement's tolerance are scaled
  to 1. A side reaction's `current_fraction` is optional (a specified cell without one is
  refused with `cheme.cell-input-missing`). Cells without the new fields report as
  before. ADR 0042 records why no WaterTAP or IDAES model is used for this.
- `cheme process pinch --dt-min X` (#134, ADR 0040): whole-plant pinch targets of the case's
  recorded simulation run. One thermal stream per duty with class (utility, recovery,
  constrained, excluded) and quality (linearised or insufficient), reconciled against the run's
  duties; the current utility demand, the theoretical minimum utility demand at dTmin and the
  theoretical energy-saving potential, the hot-side, cold-side and shifted pinch, utility-use
  pinch violations apart from cross-pinch transfer, `--json`, `--md`, `--include-constrained`
  for the reactors, and `--write` to `process/pinch-run.json`, refused while the reconciliation
  has a finding. The extraction (`heat_integration/streams.py`) also serves the simulation's
  energy audit, which is unchanged.

### Fixed

- Electrolysis duties: a stated `minimum_inventory` above the reservoir's initial one ended
  nothing (its event fires on a crossing only), so the duty ran on and could be reported
  feasible; it now ends at 0 h (`cheme.duty-inventory-low`, not feasible).
- IDAES runs: the energy audit labelled the enthalpy reference as DWSIM's
  (`energy.reference.source` "DWSIM mass enthalpy", `formation_enthalpy_included: false`, and
  DWSIM's database as the formation basis) (#125). The reference now comes from the backend
  (`energy.REFERENCES`): an IDAES record says its enthalpies include the formation enthalpies
  at 298.15 K, and its `energy.formation` states the IDAES reference and that no reacting closure
  is evaluated. The closure itself is unchanged: an IDAES reactor, and the plant with one, stay
  `unsupported`; no formation term is added. Records simulated earlier keep the old label until
  simulated again.

## 1.4.1 (2026-11-02)

Patch release: the IDAES backend converges on near-pure liquids and gives liquids their heat
capacity (#124).

### Fixed

- IDAES backend, `IDAES ideal VLE`: a subcooled near-pure liquid (a pure toluene feed) did not
  converge, so neither did any flowsheet with one (#12). The package now takes its phase
  equilibrium in the complementarity form (Dabadghao et al., doi:10.1002/aic.18029) instead of
  IDAES's smooth VLE, whose bubble-to-dew smoothing exceeds such a stream's bubble-dew gap. Its
  liquid heat capacities of benzene and toluene were a thousandth of their value (IDAES's
  `BT_ideal` labels kJ/kmol/K coefficients J/kmol/K); a liquid mixer or heater had a wrong
  energy balance. Results of the ideal package change (the HDA example's heater duty 48.84 to
  48.60 kW).

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
