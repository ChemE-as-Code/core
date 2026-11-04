# Electrolyser stacks: sizing and the skid equipment inputs

The optional `stacks:` section of `process/cells.yaml` sizes electrolyser stacks of a cell of
the same file for a product duty, and names the skid equipment a duty of
`process/duties.yaml` sizes. `cheme process stack` evaluates each stack design: the cells and
stacks, their electrical arrangement, DC power, output and envelope, and the reservoir, pump
and tank inputs from the duty run at that arrangement. The results go into the files the
existing tools already read (the equipment list's `dimensions`, the pumps' datasheet
`type_specific`), so `cheme layout build` and `cheme datasheets draft`/`fill` take them from
there. The code is `chemeascode.domains.equipment.electrolyser_stack` (model
`electrolyser-stack` v1); the decision is
[ADR 0044](../adr/0044-stack-sizing-and-skid-inputs-through-the-equipment-list.md). It builds on
the [cell](electrochemical-cells.md), its [measured performance](electrochemical-measurements.md)
and the [duties](electrolysis-duties.md).

## The section

```yaml
stacks:
  - id: STK-1
    title: CO2-to-CO stacks on a 48 V DC bus
    cell: BPM-100                    # a cell id of the cells: section
    tags: [E-101A, E-101B]           # equipment-list tags, one per stack
    product:
      component: CO                  # a product of the cell's reaction
      rate: {value: 0.1, unit: kg/h, provenance: given, source: "..."}   # or mol/s, kmol/h, t/d
      purity: {value: 0.95, provenance: given, source: "..."}            # declared, reported
      pressure: {value: 1.2, unit: bar(a), provenance: given, source: "..."}
    electrical:
      max_stack_voltage: {value: 48, unit: V, provenance: given, source: "the DC bus"}
      max_stack_current: {value: 100, unit: A, provenance: given, source: "..."}   # optional
      rectifier_efficiency: {value: 0.95, provenance: assumed, source: "..."}      # optional
      rectifier_max_current: {value: 500, unit: A, provenance: assumed, source: "..."}  # optional
    envelope:                        # per cell, ASSUMED until the vendor's drawing
      cell_pitch: {value: 8, unit: mm, provenance: assumed, source: "..."}
      end_plates: {value: 120, unit: mm, provenance: assumed, source: "..."}
      frame_margin: {value: 40, unit: mm, provenance: assumed, source: "..."}
    access:                          # clearances around each stack
      end: {value: 1.0, unit: m, provenance: assumed, source: "..."}
      side: {value: 0.8, unit: m, provenance: assumed, source: "..."}
    replacement:
      interval: {value: 8000, unit: h, provenance: assumed, source: "membrane life"}
      operating_hours: {value: 8000, unit: h/a, provenance: assumed, source: "..."}
    equipment:
      duty: SKID-150                 # a duty id of process/duties.yaml: its horizon is the campaign
      reservoir: {tag: T-101, margin: {value: 0.25, ...}, aspect_ratio: {value: 1.5, ...}}
      recirculation_pump:
        tag: P-101
        flow_per_area: {value: 0.5, unit: mL/(min cm2), provenance: assumed, source: "..."}
        density: {value: 1050, unit: kg/m3, ...}
        viscosity: {value: 1.2, unit: mPa s, ...}
        reservoir_pressure: {value: 101.3, unit: kPa, ...}
        stack_pressure_drop: {value: 50, unit: kPa, ...}
      dosing_pump: {tag: P-102, margin: {value: 0.5, ...}}
      dosing_tank: {tag: T-102, margin: {value: 0.2, ...}, aspect_ratio: {value: 1.2, ...}}
      bleed_tank: {tag: T-103, margin: ..., aspect_ratio: ...}
```

Every field is optional except `id`, `cell`, `product` and `electrical.max_stack_voltage`; the
schema stays `cheme/electrochemical-cells/v1`. The stacks are not part of the cell's Faraday
balance (`cheme process cell` reads none of it).

## What is calculated

At the cell's operating point from `cheme process cell` (its current density `j = I /
A_cell`, voltage `U` and Faradaic efficiency `FE` of the product; a measured cell's looked up
at `j` in its series):

| value | how |
| --- | --- |
| total active area | `A = n F Ndot / (nu FE j)` for the product duty `Ndot` (mol/s) |
| cells required | `ceil(A / A_cell)` |
| cells per stack | at most `floor(U_max / U)` in series; the stacks `ceil(cells / that)`; the cells shared evenly, `ceil(cells / stacks)` per stack |
| stack voltage, current | cells x `U`; the cell's current (one current through a series stack) |
| bus current, DC power | stacks x `I`; `P = sum N U I`; AC power over the rectifier efficiency; rectifiers for the rectifier current |
| output, margin | the integer arrangement's product (never below the duty) and its margin over the duty |
| electricity, heat | kWh per kg of product (all the DC power); the cell's heat per cell times the cells |
| envelope | `L = cells x pitch + end plates`, `W = H = sqrt(A_cell) + 2 x frame margin`; the footprint with the clearances |
| replacements | cells and membrane area replaced per year from the interval and the operating hours |

From the duty named under `equipment:`, run at the sized arrangement (the cells per stack in
series, the stacks on the one reservoir) over its horizon:

| tag | gets | from |
| --- | --- | --- |
| reservoir | list `dimensions` (diameter, height, `head: flat`) | the largest volume over the duty times one plus the margin, a vertical cylinder of the stated H/D |
| dosing tank | list `dimensions` | the solution dosed over the campaign, with the margin |
| bleed tank | list `dimensions` | the bleed over the campaign, with the margin |
| recirculation pump | datasheet `type_specific`: `mass_flow_kg_h`, `density_kg_m3`, `viscosity_mpa_s`, `suction_pressure_kpa`, `discharge_pressure_kpa` | the anolyte flow per area (or per cell) times the cells at the density; the reservoir pressure and the stack's pressure drop |
| dosing pump | datasheet `mass_flow_kg_h`, `density_kg_m3` | the duty's dosing rate times one plus the margin |
| stack tags | list `dimensions` (length, width, height) | the envelope |

Every value carries its provenance (`given`, `assumed`, `calculated`, or `tbd` with the
reason) and its source; a value resting on an assumed input is marked ASSUMED.

## One design basis

The cell's operating point, the arrangement and the duty are stated once:

- the stack is sized at the cell's current density in the `cells:` section. A duty that runs
  the cell at another current density, or runs another cell, gives no reservoir, dosing or
  bleed inputs (`cheme.stack-duty`, error): the duty states the stack's operating point, or the
  stack is sized at the duty's;
- the arrangement comes from the sizing. `cheme process stack` runs the duty at it, and
  `cheme process duty` runs a duty a stack names at the same arrangement
  (`cheme.duty-arrangement`, info), so the two commands give one result for one duty id. A
  duty's own `cells_in_series` and `stacks` are then not used (`cheme.stack-duty`, info: drop
  them).

## Where the results go

Without `--write`, `cheme process stack` writes nothing and reports each target that differs
from the file (`cheme.stack-outdated`). `--write` edits the equipment list in place (comments
and the rest of the file kept; the edit must change only the named dimensions, or nothing is
written) and the pumps' datasheets, and only a value that is missing, TBD or written by
`cheme process stack` before. A value written by hand is kept and reported
(`cheme.stack-kept`).

The equipment list's `dimensions` take three optional fields for sizes a tool calculated:

| field | meaning |
| --- | --- |
| `source` | where the sizes come from (`cheme process stack: stack STK-1, duty SKID-150 at ...`); a source starting with `cheme process stack` marks them as the tool's, to rewrite |
| `assumed` | the sizes rest on an assumption (marked ASSUMED) |
| `fingerprint` | of the inputs the sizes were calculated from; `cheme process stack` compares it to report a stale size |

`cheme datasheets draft` and `fill` carry `source` and `assumed` onto the datasheet's main
dimensions (`derived_dimensions`); the fingerprint stays in the list. Then rerun:

1. `cheme layout build`: the 3D model's body of each tag from its list dimensions;
2. `cheme datasheets draft` / `cheme datasheets fill --tag TAG`: the tanks' volume, the pumps'
   head, NPSH and power along the routed lines.

The skill `skid-design` chains the whole sequence.

## Checks and refusals

| rule | level | when |
| --- | --- | --- |
| `cheme.stack-schema` | error | a unit a quantity does not take, a duplicate stack id, a value out of its range (not above 0: product rate, voltage and current limits, rectifier current, cell pitch, replacement interval, H/D, anolyte flow, density, viscosity, reservoir pressure; below 0: end plates, frame margin, clearances, operating hours, a margin, the stack's pressure drop; a rectifier efficiency not in (0, 1]): the value is not used |
| `cheme.stack-cell` | error | the cell is missing, refused by its Faraday balance (outside the measured range among others), has no active area, does not form the product, or a specified cell is outside its declared operating range: the stack is refused, never extrapolated |
| `cheme.stack-electrical` | error | the cell voltage above the stack voltage limit, or the cell current above the stack current limit |
| `cheme.stack-duty` | error / info | the duty is missing, runs another cell or another current density, is refused or not feasible at the sized arrangement (no tank and dosing inputs); info: the duty states another arrangement |
| `cheme.stack-envelope`, `stack-input-missing` | info | an envelope or equipment input is missing: that value stays TBD |
| `cheme.stack-unsourced` | info | an assumed input without a source |
| `cheme.stack-tags` | warning | fewer or more tags than stacks, or a tag not in the equipment list |
| `cheme.stack-outdated` | warning | a list dimension or datasheet input differs from the calculated one: `--write` |
| `cheme.stack-kept` | warning | a value written by hand differs: kept |
| `cheme.stack-target` | info | the item or datasheet a value goes to does not exist |

`cheme validate` reports the findings that need no duty run (the sizing, the cell, the tags
and the stacks' list dimensions). A `process/cells.yaml` that does not follow its schema makes
`cheme process stack` print its `cheme.cell-schema` findings and exit 1.

## Limitations

- The stack voltage counts the cells only (no busbar, contact or cable losses); the rectifier
  is an efficiency and a current rating, not a design. Stacks are in parallel on one bus;
  series strings of stacks are not sized.
- The envelope is a square active area with an assumed pitch and margins, not a vendor's
  drawing; a tank is its working volume's cylinder (heads, wall and supports not added).
- The anolyte flow per area or per cell is declared (the measured series states none); the
  pump head is the stack's declared pressure drop plus the routed lines of the pump sizing.
- No hazardous area, gas handling (H2, CO) or venting is sized.
- `cheme validate` does not yet check the duty-dependent list sizes (tanks) for staleness;
  rerun `cheme process stack` after a duty change.
