---
name: datasheets
description: Draft and size equipment datasheets - cheme datasheets draft (a draft per listed item from the equipment list, the P&ID nozzles and the linked flowsheet streams) and cheme datasheets fill (exchanger duty, LMTD and area; pump head, NPSH available and power along the routed lines; compressor and expander stages, power and intercooler duties; Fenske-Underwood-Gilliland stages; vessel volume and residence time; reactor catalyst mass and volume, pressure drop and duty from its bed or the catalyst's space velocity), every value with its basis, ASSUMED or TBD with the reason. Use when datasheets are asked for, when sizes for the equipment estimate are missing, when the datasheets gate fails, or after the flowsheet, the layout or a sizing assumption changed.
---

# Equipment datasheets and sizing

## Purpose and when to use

A datasheet (`equipment/datasheets/<TAG>.yaml`, `cheme schema datasheet`) is what goes to a
supplier: operating and design conditions, materials, nozzles and the sizes. `cheme
datasheets draft` writes a draft for every listed item without one; `cheme datasheets fill`
calculates the sizes a draft leaves `TBD` from the flowsheet, the layout model and the
assumptions the project declares, and writes each value with its basis. Use it when datasheets
are asked for, when `cheme assess equipment` reports items without a size, when the
`datasheets` gate fails, and again after the flowsheet, the layout model or an assumption
changed (a fill rewrites only what an earlier fill wrote).

## Required inputs and missing inputs

- The equipment list, and the flowsheet nodes linked to each item
  (`links: [{target: equipment, ref: <TAG>}]` on the block or step, skill `process-design`).
  An item no node links gets nothing: its sizes stay `TBD: no flowsheet node links <TAG>`.
  Exchangers, pumps and machines need a linked node with one material inlet and one outlet;
  a column one feed and two products.
- Stream states (pressure, temperature, flow, composition) of the case (`--case`, default the
  flowsheet's). Enthalpies, densities, vapour pressures and volatilities come from the property
  adapter (`cheme process props`, extra `props`), which is claimed only inside its validated
  range: a state outside it is a finding and the value stays `TBD`. Give such a value yourself
  with its source (`density_kg_m3`, `vapour_pressure_kpa`, `heat_capacity_ratio`, ...).
- For pump line losses: `layout/plant-model.yaml` (`cheme layout build`) with the suction
  and discharge lines routed between the pump and the items linked to the other ends of its
  streams. Without it the head is the pressure difference only, marked ASSUMED.
- A pump no flowsheet stream links (it draws from a battery limit): declare its end points
  `suction_from` / `discharge_to` (`TAG`, `TAG/N2`, or a routed pipe's end
  `pipe:<pipe id>:start|end`: a free end at the battery limit or a tie-in on another pipe) and `mass_flow_kg_h`, `density_kg_m3`, `viscosity_mpa_s`,
  `suction_pressure_kpa`, `discharge_pressure_kpa` (pressures at those end points), each with
  its source; `vapour_pressure_kpa` and `pump_efficiency` for NPSHa and power. On a linked pump
  `suction_from` / `discharge_to` replace the flowsheet's source or destination. In a script use
  `chemeascode.domains.equipment.pumps` (`size_pump`, `route_line`), never the private
  `fill._route` / `_Network`.
- **Declared parameters** (`cheme datasheets fill --list`): in the datasheet's
  `type_specific` with their source, or for every item with `--param name=value` (then written
  ASSUMED with that basis and recorded in `sizing_basis`). Efficiencies, the maximum pressure
  ratio per stage, the exchanger arrangement, the typical-U row (`u_service`), margins, reflux
  ratio factor and tray efficiency are design decisions: take them from DESIGN.md or a supplier,
  never from memory. Without them the dependent values stay `TBD` with the parameter to declare.

## Workflow and tools

1. `cheme datasheets draft [--tag T]` for the items without a datasheet.
2. Declare what the calculations need in each draft's `type_specific` (with `source`), or decide
   project-wide assumptions and pass them as `--param`.
3. `cheme datasheets fill [--tag T] [--param name=value ...] --dry-run`, read the findings
   and the TBD reasons, then run it without `--dry-run`.
4. Check every filled value against its `source`: the streams, nozzles, pipes and tables it
   names. A value computed from an ASSUMED input is `assumed: true`.
5. `cheme assess equipment` picks up the filled `area_m2`, `shaft_power_kw`,
   `fluid_power_kw`, `duty_kw` and `volume_m3` with their source (ASSUMED and draft marked).
6. When a supplier confirms a value, write it with its source (the fill never touches it),
   complete the datasheet and remove `draft: true`.
7. Main dimensions and weights: `cheme datasheets fill --dimensions [--tag T] --dry-run`
   adds what the equipment list and the layout model state (the model's tangent length and
   support height are its proportions: ASSUMED until the vessel design gives them); write the
   designed values (ID, T-T, tubes, plates, baseplate, sections, weights) with their source.
   Give each nozzle its `face`, `orientation_deg`, `elevation_m` (and `axial_m` on a
   horizontal item), DN, rating and facing.
8. `cheme datasheets drawing --write` regenerates `equipment/datasheets/<TAG>.svg`; commit it
   with the datasheet. Never edit the SVG.
9. A field waiting for the supplier: `{value: supplier, unit, source: <the enquiry or data
   awaited>}`; a field that does not apply to this item (stages of a packed contact cooler):
   `{value: not_applicable, reason: <why>}`. The fill never writes either. A sheet whose only
   open fields are these markers can be final (no `draft: true`); a `TBD` left on a final sheet
   is `cheme.datasheet-open` and fails the `datasheets` gate. Never mark a field `supplier` to
   hide a value you can calculate, nor `not_applicable` without a real reason.

What `fill` calculates:

- **Exchangers**: duty `Q = n (h_out - h_in)` of a linked side (adapter enthalpies), or the
  datasheet's own `duty_kw`; LMTD for `counter-current`, `co-current` or `1-2` (with the
  Bowman-Mueller-Nagle F); `A = Q / (U F LMTD) (1 + area_margin)` with `overall_u_w_m2k` or
  the middle of a row of the typical coefficients (Sinnott, C&R Vol. 6, 4th ed., Table 12.1;
  rows checked against public reproductions, not the print: `check` in the data file),
  always ASSUMED. The other side's temperatures come from a second linked node or from
  `utility_inlet/outlet_temperature_degc`.
- **Pumps**: `H = (p_out - p_in)/(rho g) + (z_dest - z_source) + h_suction + h_discharge`
  (+ `control_valve_dp_kpa`): static head between the nozzles of the source and destination
  items, Darcy-Weisbach with Colebrook along the routed pipes (roughness: Moody 1944; fittings
  K: Perry's 7th ed. Table 6-4; inside diameter: ASME B36.10M/B36.19M OD less twice the wall,
  `pipe_schedule` default 40 ASSUMED); `NPSHa = (p_in - p_vap)/(rho g) + static - h_suction`;
  `P = m g H / pump_efficiency`. Liquid levels above the nozzles are not counted
  (conservative); fittings without a K are named, not counted. The stream pressures are taken
  at the source and destination items (`stream_pressures_at: ends`, the default); when the
  flowsheet carries the pump's own suction and discharge pressures declare
  `stream_pressures_at: pump`, or the static head and line losses count twice.
- **Compressors, expanders**: stages from `max_stage_pressure_ratio`, the power for
  `isentropic_efficiency` or `polytropic_efficiency`, real gas through the adapter where it is
  claimed, else ideal gas with the suction Cp/Cv (or `heat_capacity_ratio`), intercooled to
  `intercooler_outlet_temperature_degc` (default the suction temperature, ASSUMED), no
  intercooler or aftercooler pressure drop (ASSUMED); the stream pressures are at the machine's
  flanges. Polytropic: the gas work `cp T1 (r^((k-1)/(k eta_p)) - 1)`, not the polytropic head;
  `shaft_power_kw` only with `mechanical_efficiency`.
- **Columns**: Fenske, Underwood, Gilliland (Molokanov) with volatilities from the adapter at the
  top dew and bottom bubble points; keys `light_key`/`heavy_key` (a binary needs none);
  `reflux_ratio` or `reflux_ratio_factor`; trays `ceil((N - 1) / tray_efficiency)` (the
  reboiler is a stage, not a tray), `ceil((N - 2) / tray_efficiency)` with a partial
  condenser (a stage too). The condenser type is `condenser_type` (`total`, `partial`, `none`),
  else the linked step's `condenser` in `process/simulation.yaml`; without either a total
  condenser is ASSUMED and the source says so. A component absent
  from a product (a sharp split) takes its infinite-dilution K (fugacity coefficients). The diameter stays
  `TBD`: no flooding correlation is in the package.
- **Vessels**: volume `pi/4 D^2 L` from the sheet's `dimensions`: the inside diameter, else
  the outside; the tangent length, else the overall length (horizontal) or height. Over the
  tangent length it is the cylindrical shell, heads not included; over an overall length or
  height (or the older `type_specific` `diameter_m` with `length_m`/`height_m`) an upper
  bound. The source names the fields used. A draft's volume (from the list's dimensions) and an
  earlier fill's follow changed dimensions; a volume given by hand is kept. Residence time
  against `residence_times` in `process/design-basis.yaml`.

What `fill` does **not** calculate (docs/framework/sizing.md, "Coverage";
`chemeascode.domains.equipment.coverage`): equipment-specific rating, mechanical design to a
code, material selection and corrosion allowance, relief sizing, dynamics and controls. Every
filled draft records `sizing_basis: sizing_scope = preliminary`, and the fill adds `rating`
(pumps: `npsh_required_m`; columns: `flooding_diameter_m`), `mechanical_design`,
`corrosion_allowance_mm` and `relief_protection` as `TBD: unsupported in cheme-as-code ...`.
Resolve them with the supplier's or specialist's value and source, `supplier`, or
`not_applicable` with the reason; never fill them from memory. Report filled sizes as
preliminary, not as a rated or code-checked design.

## Validation and failure handling

- `cheme.datasheet-fill-property-unsupported` / `-out-of-range`: a state outside the
  validated property method. Do not widen the claim; give the value with its source.
- `cheme.datasheet-fill-temperatures`: a temperature cross or an F that no 1-2 exchanger
  reaches: check the temperatures and the arrangement (more shells, counter-current).
- `cheme.datasheet-fill-correction-factor`: F of one 1-2 shell below 0.75 (the usual design
  limit, Sinnott Section 12.6; Kern): the area is written, but more shells in series are the
  sound design.
- `cheme.datasheet-fill-phase`: a pump suction that is not liquid.
- `cheme.datasheet-fill-balance`: two linked sides whose duties differ by more than 1 %.
- `cheme.datasheet-residence-time`: less hold-up than the design basis asks for.
- `cheme.datasheet-fill-param` / `-tag`: an unknown `--param` or a tag without a datasheet.
- `cheme.datasheet-marker` (error): `not_applicable` without a `reason`, or `supplier` without
  a `source` or `reason`.
- `cheme.datasheet-open` (warning): a final datasheet with a field still `TBD`, at any depth
  (nested `type_specific` tables, `nozzles[].dn`, `sizing_basis[].value` count too).
- `cheme.datasheet-dimension-mismatch` / `-dimension-layout`: a main dimension or the empty
  weight against the equipment list or the layout model: change them together.
- `cheme.datasheet-nozzle-pid` / `-nozzle-line`: the schedule against the P&ID nozzles (count,
  DN, lines) and the line list.
- `cheme.datasheet-drawing-stale`: rerun `cheme datasheets drawing --write`.
- `cheme.datasheet-stale` (warning): a filled value whose streams or named `inputs` changed
  since (its `fingerprint`); rerun `cheme datasheets fill --tag T` on the draft.
- `cheme validate` checks the datasheets afterwards (schema, list agreement).

## Outputs and provenance

Each filled value is `{value, unit, source: "cheme datasheets fill: <calculation, inputs,
tables>", assumed}`; a value that cannot be calculated is `TBD` with the reason. A `TBD` is
added only for the size fields of the item's class (and a column's flooding diameter); a TBD
reason written by hand is kept. The `--param`
assumptions are in `sizing_basis`. The fill rewrites only the values whose source starts with
`cheme datasheets fill` (or `TBD`), never a value someone else wrote, and only draft
datasheets; a non-draft datasheet is reported as kept. The file is rewritten as YAML (the header
comment kept). The output is deterministic for the same inputs.

## Required human judgment

The typical U, the efficiencies and the staging are preliminary: an exchanger or machine is
sized by its supplier. Decide whether a calculated head includes everything the line holds
(control valves, strainers, flow meters, filters: give `control_valve_dp_kpa`). Check that the
linked nodes are the right sides and the right source and destination of a pump. A filled
datasheet is still a draft until an engineer has checked its values.

## References

Skills `process-design` (links, stream states), `phase-calculation`, `mto-estimate`
(equipment estimate), `pipe-routing` (routed lines); `equipment/datasheets/README.md`;
`cheme schema datasheet`; `cheme datasheets fill --list`. Sources of the methods:
Sinnott, Coulson & Richardson's Chemical Engineering Vol. 6, 4th ed. (2005), Table 12.1;
Bowman, Mueller and Nagle, Trans. ASME 62 (1940) 283; Moody, Trans. ASME 66 (1944) 671;
Colebrook, J. Inst. Civil Eng. 11 (1939) 133; Swamee and Jain, J. Hydraulics Div. ASCE 102
(1976) 657; Perry's Chemical Engineers' Handbook, 7th ed. (1997), Table 6-4; ASME B36.10M and
B36.19M; Fenske, Ind. Eng. Chem. 24 (1932) 482; Underwood, Chem. Eng. Prog. 44 (1948) 603;
Gilliland, Ind. Eng. Chem. 32 (1940) 1220; Molokanov et al., Int. Chem. Eng. 12 (1972) 209.
