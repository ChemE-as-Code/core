# Equipment sizing: `cheme datasheets fill`

`cheme datasheets fill` calculates the sizes the draft datasheets leave `TBD` and writes
each value with its basis. The calculations are typed functions in the owning domains; the
command only parses options and prints the result.

| Module | Holds |
|---|---|
| `domains/process/hydraulics.py` | Reynolds number, Colebrook and Swamee-Jain friction factors, Darcy-Weisbach line losses; package data `data/hydraulics.yaml` (pipe roughness, fitting K, wall thickness by schedule) |
| `domains/process/separations/shortcut.py` | Fenske, Underwood, Gilliland (Molokanov) |
| `domains/process/props.py` | the one property adapter: besides `flash`, `entropy`, `heat_capacity_ratio`, `flash_ps`, `flash_ph`, `bubble_pressure`, `k_values` (each refused outside the validated range) and `liquid_viscosity` (thermo correlations, outside the validated method: callers mark it ASSUMED) |
| `domains/equipment/sizing.py` | LMTD and F (1-2), exchanger area, typical U (`data/overall-coefficients.yaml`), pump head, power and NPSH available, compressor stages and ideal-gas stage work, cylinder volume, residence time |
| `domains/equipment/pumps.py` | the public pump sizing from explicit inputs: `size_pump(model, pump, suction_from=, discharge_to=, mass_flow_kg_s=, density_kg_m3=, viscosity_pa_s=, suction_pressure_kpa=, discharge_pressure_kpa=, vapour_pressure_kpa=None, efficiency=None, allowance_kpa=0, ...) -> PumpDuty`, `route_line(...) -> Line`, `network(model) -> PipeNetwork` (see below) |
| `domains/equipment/fill.py` | `fill_datasheets(root, tags, write, parameters, case) -> FillResult`: applies them to the drafts, reading the flowsheet (process), the layout model as a file and the design basis (requirements) |
| `interfaces/cli/datasheets.py` | `cheme datasheets fill [--tag] [--param] [--case] [--dimensions] [--dry-run] [--list]` |

Every draft also gets the main dimensions and the empty weight the equipment list and the
layout model state; `--dimensions` fills only those, final datasheets included
([datasheet-drawings.md](datasheet-drawings.md)).

## Rules

- **Only drafts, never a value it did not write.** A key is written when it is missing, `TBD`
  or was written by an earlier fill (its source starts with `cheme datasheets fill`). A
  value someone gave (a supplier's, a hand calculation) stays and is used as an input where it
  applies (a given `duty_kw` for the area, a given head for the power).
- **Every value carries its basis**: the formula with its inputs, the stream ids and case, the
  nozzles and pipes, the cited table with edition and page. `assumed: true` when any input is
  an assumption (a typical U, an efficiency, a default schedule, a viscosity from correlations
  outside the validated method, an ideal-gas route).
- **TBD with the reason** when an input is missing, a state lies outside the property method's
  validated range (also a finding), or no cleanly sourced method exists (column diameter from
  flooding). A TBD is added only for the size fields of the item's class (`TYPE_FIELDS`: a
  pump's flow, head, NPSHa, power; an exchanger's duty and area; ...), the column's flooding
  diameter and the fields of the aspects core does not calculate (see Coverage); a field outside them (LMTD and F of an exchanger it cannot size, the shortcut's
  stages of a column it does not run on) is written only when calculated. A TBD reason written
  by hand (any source but the draft's placeholder and the fill's own) is kept.
- **Markers.** A field holding `value: supplier` (waiting for the supplier's data; `source` or
  `reason` says what is awaited) or `value: not_applicable` (with a `reason`) is never written
  and never read as an input. A sheet whose only open fields are such markers can be final
  (`draft: false`); a final sheet with a `TBD` left anywhere (a value section at any depth,
  `nozzles[].dn`, `sizing_basis[].value`) is `cheme.datasheet-open` (warning) and
  fails the `datasheets` gate; a marker without its source or reason is
  `cheme.datasheet-marker` (error).
- **Stale values.** A calculated value carries `fingerprint:` over its inputs: the states of
  every stream at the item's linked nodes (once the fill read them), and the inputs it names in
  `inputs:` (the catalyst record behind a bed, `catalyst:<id>`; the routed pipes and the nozzles
  behind a pump's head and NPSH, `pipe:<id>`, `nozzle:<TAG>/<N>`; the design basis' residence
  time rule, `residence_time:<TAG>`; a column step's condenser type in
  `process/simulation.yaml`, `condenser:<step>`; the sheet's own values it read, such as the
  dimensions behind a vessel's volume, `datasheet:<section>.<key>`; the declared parameters the
  calculation read, `param:<name>`, found or not, as the fill reads them: the sheet's
  `type_specific` value, else the `--param` value recorded in `sizing_basis`; and the rows of
  the shipped tables it used, `table:overall-coefficients/<row>`, `table:roughness/<row>`,
  `table:fittings/<row>`, `table:pipe-sizes/<schedule>/DN<dn>`, as the table states them, its
  `check` notes left out). A value names only what its own calculation read: a pump's NPSH
  not the efficiency, its power not the vapour pressure, an exchanger's LMTD not the U. A
  vessel volume from the dimensions alone does not cover the streams. When an input changes,
  `cheme validate` reports the value as `cheme.datasheet-stale` (warning). A refill rewrites it
  with the new fingerprint; a final sheet is not refilled, so check each value there. A value
  without a fingerprint (filled by an earlier release, or given) is never reported stale; a
  value is compared on the inputs it names, so one filled before parameters and tables were
  covered stays current until those inputs change, and a refill names the rest.
- **Case and streams.** A fill that calculated values from the streams writes `operating.case`
  (the case it filled from) and `operating.streams` (the streams at the linked nodes, those
  the fingerprint covers); a refill replaces them. `cheme validate` reports a case or stream
  the flowsheet does not have as `cheme.contract-ref` (warning).
- **Declared parameters** come from the datasheet's `type_specific` (with their source) or from
  `--param name=value` (ASSUMED, recorded in `sizing_basis`); `--list` names them.
- Deterministic: the same files and parameters give the same text; rounding to four
  significant digits.

## Coverage: preliminary sizing, not equipment engineering

What the fill writes is **preliminary process sizing**: short-cut methods (typical
coefficients, declared efficiencies, Fenske-Underwood-Gilliland) with their basis, good for
screening, the equipment estimate and an enquiry. It is not a rating, a design to a code, a
material selection or a relief study, and a filled datasheet or a drawn outline is not detailed
engineering. The machine-readable declaration is
`chemeascode.domains.equipment.coverage` (`SIZING_COVERAGE`, `coverage_table()`), per class of
`TYPE_FIELDS` and aspect; this table is the same (a test keeps them equal):

| Class | process sizing | rating | mechanical code | materials corrosion | relief | dynamics controls |
|---|---|---|---|---|---|---|
| pump | preliminary | unsupported | unsupported | unsupported | unsupported | unsupported |
| compressor | preliminary | unsupported | unsupported | unsupported | unsupported | unsupported |
| turbine | preliminary | unsupported | unsupported | unsupported | unsupported | unsupported |
| fan | unsupported | unsupported | unsupported | unsupported | unsupported | unsupported |
| exchanger | preliminary | unsupported | unsupported | unsupported | unsupported | unsupported |
| heater | preliminary | unsupported | unsupported | unsupported | unsupported | unsupported |
| column | preliminary | unsupported | unsupported | unsupported | unsupported | unsupported |
| reactor | preliminary | unsupported | unsupported | unsupported | unsupported | unsupported |
| vessel | preliminary | unsupported | unsupported | unsupported | unsupported | unsupported |

- **supported** (no cell today): calculated to the standard the aspect needs;
  **preliminary**: a short-cut calculation with its basis; **unsupported**: not calculated:
  a supplier, a specialist calculation or a recorded decision gives it.
- **rating**: exchanger thermal-hydraulic rating (tubes, film coefficients, fouling, pressure
  drop, vibration), pump curve and NPSH required, compressor and turbine maps, tray or packing
  hydraulics (the column diameter), separator droplet settling, reactor internals.
- **mechanical code**: wall thickness, MAWP, nozzle loads (ASME VIII, EN 13445, API
  610/617/650/660, TEMA). The design pressure and temperature on a sheet are the equipment
  list's, given.
- **materials corrosion**: the material is the equipment list's, given; core selects none and
  sets no corrosion allowance.
- **relief**: relief scenarios and device sizing (API 520/521, ISO 4126); the piping-items list
  holds a device's set pressure and relief case as given data.
- **dynamics controls**: the process model is steady state; `domains/control` holds the
  interlocks and the cause-and-effect matrix, not dynamics or controller design.

**On the datasheets.** Every draft a fill processes gets the line
`sizing_basis: [{parameter: sizing_scope, value: preliminary, reference: "cheme datasheets
fill: ..."}]`, naming the class's unsupported aspects; every value it writes keeps its `source`
starting with `cheme datasheets fill` (and `origin: correlation` when calculated from the
streams), which is how `coverage.status_of(entry)` reads it as preliminary. For the unsupported
aspects with a datasheet home the fill adds the field as `TBD` with the reason
(`unsupported in cheme-as-code: ...`), so a draft never looks complete there:

| Field (`type_specific`) | Classes | Aspect |
|---|---|---|
| `rating` | every class but pump and column | rating |
| `npsh_required_m` | pump | rating |
| `flooding_diameter_m` | column | rating |
| `mechanical_design` | all | mechanical code |
| `corrosion_allowance_mm` | all | materials corrosion |
| `relief_protection` | all | relief |

Resolve each before the sheet goes final: the value with its source (the supplier's rating, the
mechanical calculation, the relief study), `value: supplier` with what is awaited, or
`value: not_applicable` with the reason (a centrifugal pump's relief). A final sheet with one of
them left `TBD` is `cheme.datasheet-open` like any other.

## Cited data

| Table | Source | Use |
|---|---|---|
| typical overall coefficients | R. K. Sinnott, Coulson & Richardson's Chemical Engineering Vol. 6, 4th ed. (2005), Table 12.1, p. 637 | U = middle of the row's range, ASSUMED |
| pipe roughness | L. F. Moody, Trans. ASME 66 (1944) 671-684, Fig. 2 (relative roughness) | Colebrook |
| fitting resistance K | Perry's Chemical Engineers' Handbook, 7th ed. (1997), Table 6-4, p. 6-18 | bends, tees, valves of the routed path |
| outside diameter, wall thickness | ASME B36.10M (schedule 40), ASME B36.19M (schedule 10S) | inside diameter = ASME OD - 2 wall (the layout model's ISO 4200 ODs differ at DN 20, 25, 32, 65 and 125; the result names them) |

**Verification.** None of the tables has been checked against the printed source
(`print_checked: false` in each file). Each row's `check` names the independent public
reproductions of the same table that agree with it (the file's `checks`: a reproduction is not
the print):

- typical U: 25 of 28 rows agree with two reproductions (P & I Design MNL 032A Appendix VI, in
  Btu/(h ft2 F); an unattributed SI table); `exchanger/heavy-oils` with one;
  `cooler/light-oils-water` 350-900 agrees with MNL 032A (62-158 Btu/(h ft2 F)) and not with the
  SI table (350-700): kept; `exchanger/gases-gases` stays unverified;
- roughness: all five rows agree with LMNO Engineering's table (ft values);
- fitting K: all nine rows agree with Neutrium's K table, six of them also with
  PowderProcess.net (which cites Perry's 8th ed., p. 6-18);
- walls and ODs: Wikipedia's NPS tables agree with every schedule 10S wall and every value to
  DN 300; schedule 40 DN 350, 500, 600 and the ODs of DN 450 and 600 differ in the last digit
  (rounding of the inch values) and stay unverified against the standard.

No value disagreed with the reproductions in a way that called for a correction. Check the rows
against the printed tables before a contractual use.

## Pumps the flowsheet does not link

A pump that draws from a battery limit (a utility pump) has no linked flowsheet streams. Size it
with `chemeascode.domains.equipment.pumps` (in a script: `cheme run scripts/x.py`) or let the
fill do it from declared fields in `type_specific`:

| field | what |
|---|---|
| `suction_from`, `discharge_to` | end points: an item `TAG`, a nozzle `TAG/N2`, or a routed pipe's end `pipe:<pipe id>:start` / `:end`: a free end (the battery limit) or a tie-in where it meets another pipe. The line stops there; it marks nothing in the network, so other lines still run through that point. An end on a nozzle is that nozzle |
| `mass_flow_kg_h`, `density_kg_m3`, `viscosity_mpa_s` | the fluid and flow |
| `suction_pressure_kpa`, `discharge_pressure_kpa` | the pressures at the two end points, kPa(a) |
| `vapour_pressure_kpa`, `pump_efficiency`, `control_valve_dp_kpa` | optional: NPSHa, power, an allowance in the head |

On a linked pump, `suction_from` / `discharge_to` replace the flowsheet's source or destination
item. The head is the pressure difference plus the static head between the two end points plus
the routed line losses (plus the allowance); NPSHa takes the suction end point's height over the
pump's suction nozzle. The private network (`fill._Network`, `_route`) stays private: scripts use
`pumps.network`, `pumps.route_line` and `pumps.size_pump`.

## Pump paths in the layout model

The routed pipes of `layout/plant-model.yaml` become a graph: nodes are pipe ends and the points
where a pipe ends on another's run (tees), edges the stretches between them with their length,
bends (from the polyline, 90 and 45 degrees) and in-line items (by DEXPI class). The suction
path is the shortest path from a pump nozzle to a nozzle of the item linked to the other end of
the inlet stream, not passing through another item; the discharge path likewise to the item at
the end of the outlet stream. A tee passed straight on counts as `tee_run`, turning as
`tee_branch`. Static heads use the nozzle elevations; a liquid level above a nozzle is not
counted (conservative for NPSH). A tee's K is charged to the stretch that ends at it (at that
stretch's velocity); a plain joint of two pipes is no tee.

## Where a stream's pressure applies

- **Pumps** (`stream_pressures_at`, default `ends`): the inlet stream's pressure is at the
  source item and the outlet stream's at the destination item, so the static head between
  their nozzles and the routed suction and discharge losses are added. With
  `stream_pressures_at: pump` the streams carry the pump's own suction and discharge pressures:
  nothing is added (adding them would count them twice) and NPSHa takes the inlet pressure at
  the suction nozzle.
- **Compressors, expanders**: the stream pressures are at the machine's flanges; no line losses
  are added. Between stages no intercooler or aftercooler pressure drop is taken (ASSUMED, said
  in the basis): the stages split the outlet stream's pressure.
- **Columns**: a component absent from a product (a sharp split) gets its infinite-dilution K
  from the fugacity coefficients of the same Peng-Robinson phases.
  The trays are the theoretical stages less the reboiler, and less a partial condenser (both
  equilibrium stages), over the tray efficiency. The condenser type is the sheet's
  `type_specific.condenser_type`, else the linked step's `condenser` in
  `process/simulation.yaml`; without either a total condenser is ASSUMED (said in the source).
