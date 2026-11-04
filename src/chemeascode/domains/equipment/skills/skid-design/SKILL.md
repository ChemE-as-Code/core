---
name: skid-design
description: Design an electrolyser skid from one design basis - the product duty, the cell of process/cells.yaml and its measured or specified operating point, a duty of process/duties.yaml - by chaining cheme process build, cell, duty and stack (cells, stacks, arrangement, DC power, output margin, envelope; reservoir, pump and tank inputs written into the equipment list and datasheets with --write), the control P&ID, cheme control report, cheme datasheets draft and fill, cheme layout build and render, and cheme assess lca. Use when stacks or a skid are sized for a product rate, when a stack or skid tank size is missing or outdated (cheme.stack-*), or after the cell, the duty or the stack inputs changed.
---

# Electrolyser skid design

## Purpose and when to use

A skid of electrolyser stacks is sized from one design basis: `process/design-basis.yaml`
for the plant, `process/cells.yaml` for the cell and its `stacks:` section for the stack
designs, and `process/duties.yaml` for how the cell is operated against its anolyte reservoir.
`cheme process stack` turns them into the number of cells and stacks, their electrical
arrangement, the DC power, the output margin and the envelope, and the reservoir, pump and tank
inputs of the duty run at that arrangement. With `--write` it puts them where the existing
tools read sizes: the equipment list's `dimensions` (stacks, tanks) and the pumps' datasheet
`type_specific`. The layout model and the datasheets then follow by rerunning their
commands; the LCA reads the flowsheet, so the stacks' power and the dosing are entered there
by hand (step 9). Use this skill to size a new skid for a product rate, to bring a skid up to date
after a change of the cell, the duty or a stack input, or to answer what a change does to the
stacks, tanks and footprint. It follows the skills `electrochemical-cell-modelling` and
`electrolysis-duty-assessment`.

## Required inputs and missing inputs

- **The cell** in `process/cells.yaml` with its active area, current, voltage and Faradaic
  efficiency, measured (`performance: measured`, inside the measured range) or specified with
  an `operating_range.current_density`. The stack is never sized outside that range.
- **The stack design** under `stacks:` (docs/framework/electrolyser-stacks.md): the product
  component and rate (kg/h or mol/s, purity and pressure as declared data; the `recovery` of
  the product formed at the skid boundary, when gas conditioning loses some: the stacks are
  sized for rate / recovery formed), the electrical
  limits (the stack voltage or DC bus; optional stack current, rectifier efficiency and
  current), the envelope per cell (pitch, end plates, frame margin), access clearances, the
  replacement interval, the equipment-list tags of the stacks.
- **The skid equipment** under `equipment:`: the duty id, and per tag the reservoir, dosing
  and bleed tank margins and H/D, the recirculation pump's anolyte flow per area (or per cell),
  density, viscosity, reservoir pressure and stack pressure drop, the dosing pump's margin. A
  dosing tank refilled (a bleed tank emptied) during the campaign states its
  `refill_interval` (`empty_interval`): it then holds what any such interval needs, not the
  whole campaign.
- **The duty** in `process/duties.yaml`, at the stack's cell and current density (the cell's
  current over its active area): the reservoir, dosing, bleed, the stated pH threshold with its
  source and the horizon (the campaign). Leave `cells_in_series` and `stacks` out: the sizing
  sets them. An undosed duty (no dosing, bleed, make-up or degassing) can state
  `reservoir.size: to_horizon` (and a `time_margin`): `cheme process stack --write` then writes
  the exact reservoir volume that reaches the horizon into it. Comparison duties on the same
  hardware (on/off, part load) name the stack (`stack: ID`) to run at its arrangement.
- The equipment list items for every tag (skill `lists-sync`) and the pump datasheets
  (`cheme datasheets draft`).

Envelope, clearances, margins, H/D, anolyte flow and replacement interval are assumptions
until a vendor states them: write them with `provenance: assumed` and a source (a vendor
enquiry, a rule of thumb, DESIGN.md D-NNN). Never invent a value to make a finding go away;
leave it out and the value stays TBD with the reason.

## Workflow and tools

1. `cheme process build` and `cheme validate`: the flowsheet and the lists are clean.
2. `cheme process cell`: the cell's operating point, inside its measured or declared range.
3. `cheme process duty ID`: the duty runs at the arrangement the stack is sized at
   (`cheme.duty-arrangement`), so it gives the same result as the stack command. Make it
   feasible (no threshold, inventory or range exit within the horizon).
4. `cheme process stack [ID]`: read the cells required, cells per stack, stacks, stack voltage
   and current, DC power, output margin, kWh/kg, the envelope and footprint, and every
   equipment input with its status (`outdated`, `current`, `kept`, `tbd`, `no-target`). Fix
   the errors first: an error on the duty leaves the tanks and the dosing pump TBD.
5. `cheme process stack --write`: writes the outdated stack and tank dimensions into
   `equipment/equipment-list.yaml` (only the named dimensions change; comments kept) and the
   pump inputs into their datasheets (the recirculation pump's with its end points,
   `suction_from` the reservoir and `discharge_to` the first stack); never over a value written
   by hand. A value it wrote that is no longer given is cleared (a datasheet value set TBD,
   list sizes removed). With `--json` the output's `written` names the files and tags.
6. The control P&ID: draft or change the skid sheet (skills `pid-draft`, `pid-edit`; a
   generated sheet with `cheme regen`, a new one with `cheme sheet new`), then
   `cheme control report` for the loops and sequences (dosing on pH, level, recirculation).
7. `cheme datasheets draft` for new tags, then `cheme datasheets fill --tag TAG` for the
   tanks' volume and the recirculation pump: its flow from the written mass flow and density,
   its head, NPSH and power along the lines from the reservoir to the stack routed in the
   layout model (they need the skid P&ID of step 6 and `cheme layout build`; until then they
   stay TBD with that reason). The dosing pump gets its capacity only: declare its
   `suction_from`, `discharge_to`, viscosity and pressures on its datasheet by hand.
8. `cheme layout build`, then `cheme layout render --plan` and `--section x=...` (or `y=...`):
   look at the PNGs, check the stacks' clearances and the tanks against the placement (skills
   `layout-yaml`, `pipe-routing`).
9. `cheme assess lca` (skill `lca`): it reads the flowsheet, not the stacks. Set the duty of
   the electricity stream into the electrolysis step (the stream the cell's
   `flowsheet.electricity` names, in `process/flowsheet.yaml`) to the stacks' DC power (the AC
   power with the rectifier inside the boundary), and the dosing stream to the duty's dosing
   rate, each with its source `cheme process stack: stack ID`. Nothing reports them stale:
   compare them with `cheme process stack` after every change.
10. Rerun from step 2 after any change of the cell, the stack inputs or the duty; rerun
    `cheme process stack` without `--write` to see what is outdated.

## Validation and failure handling

- `cheme.stack-cell` (error, refused): the cell is outside its measured or declared range, or
  lacks an input. Move the operating point inside, or have the point measured; never size on an
  extrapolation.
- `cheme.stack-electrical` (error): the cell voltage or current is above the stack limit:
  a higher bus voltage, a smaller cell or a lower current density.
- `cheme.stack-duty` (error): the duty is missing, runs another cell or another current density
  than the stack, or is not feasible at the sized arrangement. Correct the duty (its schedule at
  the stack's current density, its cell), or size the stack at the duty's operating point; for
  an undosed duty the hint gives the reservoir volume that reaches the horizon.
- `cheme.stack-cell` (error) on the product: a side reaction forms it too (O2 of a CO2
  cell); size on the cell's main or measured product.
- `cheme.stack-duty` (error): an earlier stack names the same duty. One duty runs at one
  arrangement: give the second skid its own duty. Also when the skid duty names its own stack
  (`stack:`) and states another `cells_in_series` or `stacks`: drop them from the duty.
- `cheme.duty-size` (error): `reservoir.size: to_horizon` on a duty whose volume does not
  scale exactly (dosing, bleed, make-up, degassing, two operating points): size the reservoir
  by hand, or drop those from the duty.
- `cheme.duty-arrangement` (error): a duty naming a stack also states another
  `cells_in_series` or `stacks`, names a stack that is not there or of another cell, or is
  another stack's skid duty: drop the arrangement from the duty, or correct `stack:`.
- `cheme.stack-schema` (error): a unit or a value out of range (a zero rectifier current, a
  negative pitch, flow, density or margin): the value is not used.
- `cheme.stack-outdated` (warning): `cheme process stack --write`, then steps 7 and 8. Also
  when a value written before is no longer given (an input removed): give the input, or let
  `--write` clear it.
- `cheme.stack-kept` (warning): a hand-written size differs from the calculated one. Keep it
  only with its source (a vendor drawing); otherwise remove it and write. A tank stating a
  head or a support is kept too (the calculated cylinder is flat-ended over its whole height):
  remove them, or size the tank by hand.
- `cheme.stack-tags` (warning): one equipment-list tag per stack; add or remove items in the
  list and in `tags:`. (error): a tag given twice, by two stacks or two roles: give each its
  own tag.
- `cheme.stack-envelope`, `stack-input-missing`, `stack-unsourced` (info): an input is
  missing or unsourced; the value stays TBD.

## Outputs and provenance

`process/cells.yaml` and `process/duties.yaml` as written by hand; the equipment list's
`dimensions` and the pumps' `type_specific` values written by `--write`, each with a source
starting `cheme process stack:` (stack, duty, arrangement and campaign), `assumed: true` where
an input is assumed, and the fingerprint of its inputs; the layout model and the datasheets
regenerated from them. `cheme process stack --json` records the model (`electrolyser-stack`
v1), assumptions, limitations, every value's provenance and source, the duty run's fingerprint
and the sha256 of every input. Review the tool's edits to the equipment list in the diff.
Quote a stack count or a tank size with its basis: the cell's operating point, the arrangement
and the duty.

## Required human judgment

- The stack vendor's envelope, cell pitch, end plates and frame against the assumed ones; the
  replacement interval against the warranty.
- Access clearances for stack removal and maintenance, and the skid layout around them.
- The hazardous area classification around the stacks and the gas outlets (skill
  `area-classification`); hydrogen and CO handling, venting and gas detection (skill
  `process-safety`): none of it is sized here.
- The DC bus voltage, rectifier and cabling (skill `electrical-cabling`); series strings of
  stacks are not sized.
- Whether the measured cell applies to the plant cell (scale, ageing) and the pH threshold and
  campaign of the duty.

## References

- `cheme process stack`, `cheme process cell`, `cheme process duty`, `cheme datasheets fill`,
  `cheme layout build`; docs/framework/electrolyser-stacks.md, electrochemical-cells.md,
  electrolysis-duties.md; ADR 0041, ADR 0043, ADR 0044.
- Skills `electrochemical-cell-modelling`, `electrolysis-duty-assessment`, `datasheets`,
  `layout-yaml`, `lists-sync`, `pid-draft`, `lca`.
