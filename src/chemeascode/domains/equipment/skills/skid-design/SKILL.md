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
`type_specific`. The layout model, the datasheets and the LCA then follow by rerunning their
commands. Use this skill to size a new skid for a product rate, to bring a skid up to date
after a change of the cell, the duty or a stack input, or to answer what a change does to the
stacks, tanks and footprint. It follows the skills `electrochemical-cell-modelling` and
`electrolysis-duty-assessment`.

## Required inputs and missing inputs

- **The cell** in `process/cells.yaml` with its active area, current, voltage and Faradaic
  efficiency, measured (`performance: measured`, inside the measured range) or specified with
  an `operating_range.current_density`. The stack is never sized outside that range.
- **The stack design** under `stacks:` (docs/framework/electrolyser-stacks.md): the product
  component and rate (kg/h or mol/s, purity and pressure as declared data), the electrical
  limits (the stack voltage or DC bus; optional stack current, rectifier efficiency and
  current), the envelope per cell (pitch, end plates, frame margin), access clearances, the
  replacement interval, the equipment-list tags of the stacks.
- **The skid equipment** under `equipment:`: the duty id, and per tag the reservoir, dosing
  and bleed tank margins and H/D, the recirculation pump's anolyte flow per area (or per cell),
  density, viscosity, reservoir pressure and stack pressure drop, the dosing pump's margin.
- **The duty** in `process/duties.yaml`, at the stack's cell and current density (the cell's
  current over its active area): the reservoir, dosing, bleed, the stated pH threshold with its
  source and the horizon (the campaign). Leave `cells_in_series` and `stacks` out: the sizing
  sets them.
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
   pump inputs into their datasheets; never over a value written by hand.
6. The control P&ID: draft or change the skid sheet (skills `pid-draft`, `pid-edit`; a
   generated sheet with `cheme regen`, a new one with `cheme sheet new`), then
   `cheme control report` for the loops and sequences (dosing on pH, level, recirculation).
7. `cheme datasheets draft` for new tags, then `cheme datasheets fill --tag TAG` for the
   tanks' volume and the pumps' head, NPSH and power along the routed lines.
8. `cheme layout build`, then `cheme layout render --plan` and `--section x=...` (or `y=...`):
   look at the PNGs, check the stacks' clearances and the tanks against the placement (skills
   `layout-yaml`, `pipe-routing`).
9. `cheme assess lca` with the stacks' electricity per kg and the dosing (skill `lca`).
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
- `cheme.stack-schema` (error): a unit or a value out of range (a zero rectifier current, a
  negative pitch, flow, density or margin): the value is not used.
- `cheme.stack-outdated` (warning): `cheme process stack --write`, then steps 7 and 8.
- `cheme.stack-kept` (warning): a hand-written size differs from the calculated one. Keep it
  only with its source (a vendor drawing); otherwise remove it and write.
- `cheme.stack-tags` (warning): one equipment-list tag per stack; add or remove items in the
  list and in `tags:`.
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
