# 0044. Stack sizing in process/cells.yaml, skid equipment inputs through the equipment list

- **Status:** Accepted
- **Date:** 2026-11-06 (proposed 2026-11-04)
- **Amended:** 2026-11-04, skid inputs for the CO2 pilot skids (see "Amendment" below)

## Context

[ADR 0041](0041-measured-electrochemical-performance-and-membrane-block.md) gave a cell of
`process/cells.yaml` its measured voltage and efficiencies at its current density, and
[ADR 0043](0043-dynamic-electrolysis-duties-and-anolyte-models.md) the dynamic duty of the
anolyte reservoir it feeds. What a skid design needs next (core#139, tracker core#136) is the
number of cells and stacks for a product duty, their electrical arrangement and envelope, and
the reservoir, pump and dosing sizes the duty implies, reaching the equipment, the datasheets
and the 3D layout without a second design basis that someone keeps by hand.

How an equipment size travels today:

1. **The equipment list** (`equipment/equipment-list.yaml`, schema
   `domains/equipment/schemas/equipment.py`) gives each item an optional `dimensions`: overall
   sizes in metres (`diameter` with `height` or `length`, or `length`, `width`, `height`; head,
   support, weight). Its docstring calls it "the one source of its 3D shape". The values are
   plain numbers, without a source.
2. **The layout build** (`cheme layout build`, `domains/spatial/model.py`
   `build_model`) resolves each placement of `layout/equipment-placement.yaml` with its listed
   item (`layout_validate.resolve`: the list's `dimensions`, else the placement's `size`, else
   the family's defaults; `size_from: list | placement | default`) into a body of parts and
   writes `layout/plant-model.yaml`, each item with its `dimensions`, `bbox` and parts. The
   model records the fingerprint of every input file, so a changed list makes it
   `cheme.layout-model-outdated`.
3. **The datasheets** (`cheme datasheets draft`, `domains/equipment/datasheets.py`
   `draft_datasheet`; `cheme datasheets fill`, `domains/equipment/fill.py`) take their main
   dimensions from the list and the parsed layout model through
   `domains/equipment/outline.py` `derived_dimensions(item, model)`: outside diameter, overall
   height or length from the list, the tangent length and support height of the generated
   shell from the model (marked assumed). A draft writes a vessel's `volume_m3` from the list's
   dimensions; the fill recomputes it from the sheet's dimensions (`_shell_volume`) and sizes
   the rest from the flowsheet streams or declared `type_specific` parameters: a pump no stream
   links from `mass_flow_kg_h`, `density_kg_m3`, `viscosity_mpa_s`, `suction_pressure_kpa`,
   `discharge_pressure_kpa`, `suction_from`, `discharge_to` and the routed lines
   (`pumps.size_pump`). A value the fill writes carries its source and fingerprint and is
   reported stale when its inputs change.

So there is one route already: list `dimensions` -> layout model -> datasheet dimensions, and
datasheet `type_specific` -> the fill. What it lacks is a way for a calculated size to say
where it came from before it reaches a datasheet.

Options for the inputs: an optional section of `process/cells.yaml`, or a new
`process/stacks.yaml` with its own versioned schema. For the outputs: a second, generated
design file the layout and datasheets would also read; or writing into the existing inputs.

## Decision

- The stack designs are an optional `stacks:` section of `process/cells.yaml`, in the
  unchanged schema `cheme/electrochemical-cells/v1` (optional fields only). A stack names a
  cell of the same file; the cells and their stacks are one design basis with the duties of
  `process/duties.yaml` (and `process/design-basis.yaml` for the rest). Its models live with the
  file's (`domains/process/electrochemical_cell.py`: one module owns the file's schema); the
  Faraday balance does not read them. Each stack states the product duty (kg/h or mol/s, purity
  and pressure as declared data), the electrical limits (stack voltage or DC bus, stack current,
  rectifier efficiency and current), the assumed envelope per cell (pitch, end plates, frame
  margin), access clearances, the replacement interval and, under `equipment:`, the duty and
  the equipment tags it sizes.
- The calculation is an equipment method, `domains/equipment/electrolyser_stack.py` (model
  `electrolyser-stack` v1), reading the cells through `cell_report`: `A = n F Ndot /
  (nu FE j)`, `ceil(A / A_cell)` cells, at most `floor(U_max / U)` in series per stack, the
  stacks, the cells shared evenly, the reconciled voltage, current, DC power, output and margin
  (never below the duty), kWh per kg, the envelope. The cell's operating point is the one the
  cell report gives: a measured cell outside its validity range, or a specified cell outside
  its declared operating range, refuses the stack (`cheme.stack-cell`); nothing is
  extrapolated. Every value carries its provenance and source; a missing assumption leaves a
  value TBD with the reason.
- The skid equipment comes from the named duty, run at the sized arrangement
  (`electrolysis_duty.run_duty` replaces the duty's cells in series and stacks: the arrangement
  is never stated twice) over its horizon, the campaign: the reservoir's working volume (the
  largest over the duty) with its margin, the dosing and bleed tanks (what is dosed and bled
  over the campaign), each a vertical cylinder of the stated H/D; the recirculation pump from
  the anolyte flow per area or per cell (declared: the measured series records none), with the
  pressures and the end points the pump fill of a pump no stream links needs (`suction_from`
  the reservoir's tag, `discharge_to` the first stack's: the stacks in parallel share the inlet
  header), and the dosing pump from the duty's dosing rate with a margin (its end points and
  pressures are declared by hand). A duty that is not feasible there gives
  no tank inputs (`cheme.stack-duty`, error).
- One operating point: the stack is sized at the cell's current density of the `cells:`
  section, and the duty states its own schedule. A duty that runs the cell at another current
  density, or runs another cell than the stack's, gives no reservoir, dosing or bleed inputs
  (`cheme.stack-duty`, error), as an infeasible one does: its run, feasibility included, says
  nothing about the stack's operating point. (Taking the duty's current from the stack was the
  alternative; a duty's schedule may vary over time, so the duty stays the one place it is
  stated and a mismatch is refused.)
- One arrangement in every command: `cheme process duty` (and `--compare`) runs a duty a stack
  names at the arrangement that stack is sized at (`electrolysis_duty.Arrangement`, from
  `electrolyser_stack.stack_arrangements`; `cheme.duty-arrangement`, info), so one duty id gives
  one result in both commands. The first stack naming a duty has it; a later stack naming the
  same duty gets no inputs from it (`cheme.stack-duty`, error), and a tag two stacks or two
  roles name is written by neither (`cheme.stack-tags`, error): one item, one size. The process domain takes the arrangement as a parameter and
  does not import the stack sizing; the command layer joins them.
- The results go through the existing route, not a second file: the stacks' and tanks'
  equipment-list `dimensions`, and the pumps' datasheet `type_specific` parameters the pump
  fill already reads. `Dimensions` gains optional `source`, `assumed` and `fingerprint`;
  `derived_dimensions` and `draft_datasheet` carry `source` and `assumed` onto the datasheet's
  main dimensions. The `fingerprint` stays in the list (and on the pumps' `type_specific`
  values), where `cheme process stack` compares it to report a stale size; the datasheets do
  not carry it. A tank is written with `head: flat` and `support: none`, so the layout's shell,
  and the fill's volume from it, hold the calculated volume over the whole height; a list that
  states another head or a support for it keeps its sizes (`cheme.stack-kept`), since the 3D
  model would put them inside that height.
- `cheme process stack [IDS] [--json] [--write]` is the thin command (with `cheme process
  cell` and `duty`, which it builds on). Without `--write` it writes nothing and reports each
  target that differs (`cheme.stack-outdated`); `--write` edits the equipment list in place
  (comments kept; the edit must change only those dimensions, or nothing is written) and the
  datasheets as `cheme datasheets fill` does, and only a value that is missing, TBD or written
  by `cheme process stack` before. A value written by hand is kept and reported
  (`cheme.stack-kept`). A value it wrote that the design basis no longer gives (an input
  removed, a duty no longer feasible) is `cheme.stack-outdated`, and `--write` clears it: a
  datasheet value set TBD with the reason, the list sizes removed (left, they would read as
  current). `cheme validate` reports the stack findings that need no duty run. A
  value out of its range (a zero rectifier current, a negative pitch, flow, density or margin)
  is a `cheme.stack-schema` error and is not used. The rest of the chain (layout build,
  datasheets draft and fill) stays the existing commands; the skill `skid-design` chains them.
- The LCA is not fed by this tool: `cheme assess lca` reads the flowsheet's energy and material
  streams, and the stack power and the dosing are entered there by hand (the skill names the
  streams). Writing them into `process/flowsheet.yaml` would be a second writer of the
  flowsheet, whose electricity stream the cell's Faraday balance already checks against the
  cell's own power; that link is a follow-up.

## Amendment (2026-11-04): skid inputs for pilot skids

What the CO2 pilot skids of process-library#330 need beyond the first version, each an
optional field (schemas unchanged in version), without changing a value of a plant that
does not state them:

- **Tank intervals.** A dosing tank's `refill_interval` and a bleed tank's `empty_interval`
  (their own models, `DosingTank` and `BleedTank`, so an interval on another tank is a schema
  error) size the tank for the most dosed or bled in any window of min(campaign, interval) of
  the duty's transient (exact: the rates are constant between its samples), with the margin,
  and report the fills or emptyings per campaign `ceil(campaign / interval)`. Without an
  interval the tank holds the campaign's total, as before.
- **A duty names its stack.** `stack:` on a duty of `process/duties.yaml` runs it at that
  stack's arrangement in `cheme process duty` and `--compare` (`stack_arrangements`), as the
  duty a stack's `equipment.duty` names, so comparison duties on a skid's hardware need no
  copied arrangement. The equipment's claim wins: a duty a stack's equipment runs that names
  another stack, a duty stating `cells_in_series` or `stacks` other than its stack's, or naming
  a stack that is not there, of another cell, or refused, is refused
  (`cheme.duty-arrangement`, error) rather than run at either arrangement; `cheme process
  stack` refuses a skid duty that names its own stack with another arrangement in the same
  way (`cheme.stack-duty`, error), so the two commands agree. The stack's own
  skid inputs still come from its `equipment.duty` only. `Arrangement` carries the stack id.
- **A reservoir sized to the horizon.** `reservoir.size: to_horizon` (optional
  `time_margin`, a fraction of the horizon or a time) on a duty asks for the volume that
  reaches the horizon at the stated threshold. It is computed in the duty module, not by
  probing: without dosing, bleed, make-up and degassing and at one operating point (one WDE and
  co-ion split while on), the state moves along the charge, so `V = V0 Q(target) / Q*` is
  exact (ADR 0043); `Q*` comes from the run's threshold, or by following the run's straight
  path in the charge with the model's speciation when the stated volume does not reach it.
  The volume is raised, exactly on the same path, where the duty would otherwise stop or
  leave the model's claim before the target: a stated `minimum_inventory` is absolute and does
  not scale with the volume, and the anolyte model's validity holds along the path to the
  target (`limited_by`), so the written volume is a feasible one. A duty where it is not
  exact is refused that field (`cheme.duty-size`, error), not approximated. `cheme process stack --write` writes the volume, rounded up to 4 significant
  figures (at least 1e-6 above the exact one, so the run at it reaches the target within the
  integration's tolerance), into the duty's `reservoir.volume` in `process/duties.yaml`: a
  second, narrow writer of a hand-maintained file, in place (comments kept, the edit checked
  to change that volume only), and only for a duty that asks for it. The tanks then follow
  from the duty at that volume in the same `--write`.
- **Product recovery.** `product.recovery` (default 1, 0 < r <= 1) sizes the stacks for
  rate / recovery formed and reports the output formed and delivered and kWh per kg of each.
  A stated recovery out of range refuses the stack. Its fingerprint leaves out a recovery not
  given, so the sizes written before stay current.
- **Duty totals by route.** Every duty also integrates the cation leaving and the carbon
  entering through the membrane and the cation and carbon leaving with the bleed, and reports
  the initial inventories and the cation dosed, so the cation and the carbon balance close
  independently (the LCI reconciliation is not closed by difference). They are quadratures:
  `foundation/ode.py` `solve(..., error_components=n)` keeps them out of the error control, so
  the steps, and every value reported before, are unchanged bit for bit.

## Consequences

- Positive: a changed product duty, cell operating point, envelope or duty reaches the stack
  count, the equipment list, the 3D model and the datasheets by rerunning commands, with the
  calculation, its inputs and its ASSUMED marking on every value; a test demonstrates it.
- Positive: the duty runs at the arrangement the sizing chose, in `cheme process stack` and in
  `cheme process duty`, and at the stack's current density and cell or not at all, so the
  reservoir and dosing inputs cannot silently belong to another number of cells or another
  operating point.
- Negative: a duty whose schedule varies (a ramp, on/off at another current) cannot size a
  skid's tanks through this command; it is refused, not approximated.
- Negative: `cheme process stack --write` writes into a hand-maintained file (the equipment
  list); it edits only the `dimensions` of the tags it names and refuses an edit that would
  change anything else, but a reviewer sees tool edits in it.
- Negative: the envelope is a square active area with an assumed pitch and margins; a tank is
  its volume's cylinder; the pump head is the stack's declared pressure drop plus the routed
  lines. None of these is a vendor design. Hazardous areas, gas handling and venting are not
  sized.
- Negative: the stacks' power and dosing reach the LCA by hand, and nothing reports them stale
  when the stacks change.
- Negative (amendment): `cheme process stack --write` also edits `process/duties.yaml`, for
  a duty with `reservoir.size: to_horizon` only; the written volume is rounded up, so the duty
  lasts slightly beyond its target. A comparison duty's own reservoir is not tied to the skid
  duty's (it is stated, or sized to its own horizon). Dosing and bleed still run while the
  current is off.
- Follow-ups: the stack power and dosing into the flowsheet streams the LCA reads, with a
  stale check; the anolyte flow per area as part of a measured series; series strings of stacks
  on a higher bus voltage; a stale check of the written values in `cheme validate` that does
  not need the duty run (the tanks' list sizes depend on the duty, so `cheme validate` does
  not report them stale yet: rerun `cheme process stack` after a duty change); the
  fingerprint carried onto the datasheets.

## Evidence

- core#139; tracker core#136.
- `src/chemeascode/domains/equipment/electrolyser_stack.py`,
  `src/chemeascode/domains/process/electrochemical_cell.py` (`Stack`, `load_cells`,
  `cell_product`), `src/chemeascode/domains/process/electrolysis_duty.py` (`run_duty`,
  `load_duties`, `duty_report(..., arrangements)`, `Arrangement`),
  `src/chemeascode/domains/equipment/schemas/equipment.py`,
  `src/chemeascode/domains/equipment/outline.py`, `src/chemeascode/interfaces/cli/process.py`
  (`stack`).
- `tests/test_electrolyser_stack.py`, `tests/data/electrochemical/co2-skid/`.
- Amendment: `src/chemeascode/domains/process/electrolysis_duty.py` (`_required_volume`,
  `_ROUTES`, `_arrange`), `src/chemeascode/foundation/ode.py` (`error_components`),
  `electrolyser_stack.py` (`_interval_tank`, `_reservoir_volume`, `set_duty_volume`,
  `stack_arrangements`); `tests/test_electrolysis_duty.py`, `tests/test_electrolyser_stack.py`,
  `tests/test_ode.py`; the design note of process-library#330 (core gaps A1 to A5).
- `docs/framework/electrolyser-stacks.md`; skill `skid-design`
  (`src/chemeascode/domains/equipment/skills/skid-design/SKILL.md`).
