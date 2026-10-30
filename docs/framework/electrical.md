# Cable trays and the cable schedule

`cheme layout build` cables the plant when the repository has an electrical list
(`electrical/electrical-list.yaml`, kind `electrical`). It derives the motor list, places the
instruments and junction boxes, routes power and instrument cable trays through the 3D model and
writes the cable schedule into `layout/plant-model.yaml` (`tray_tiers`, `trays`,
`junction_boxes`, `cables`, `cabling`: [layout-model.md](layout-model.md)). Skill
`electrical-cabling`; gate requirements `cables` and `trays`.

Code: `domains/control/schemas.py` (`ElectricalList`), `domains/control/electrical.py` (motor
list, cable sizes, instrument functions, actuated valves, the validate cross-checks),
`domains/control/data/cables.yaml` (package table), `domains/spatial/trays.py` (ends, junction
boxes, trays, schedule, rules), `domains/spatial/schemas.py` (`TrayRules`, the model sections).
`control` declares, `spatial` places: spatial may import control (architecture.md).

## Inputs

| file | kind | what |
|---|---|---|
| `electrical/electrical-list.yaml` | `electrical` (control) | `substations` (`id`, `building`, `incoming_kv`), `transformers` (`tag`, `substation`, `rating_kva`, `primary_kv`, `secondary_v`, `feeds`), `rooms` (`id`, `kind: mcc \| switchgear \| control \| rack_room`, `building` or `point`, `voltage_v`), `defaults` (`lv_room`, `mv_room`, `control_room`, `lv_voltage_v` 400, `mv_voltage_v` 6600, `mv_above_kw` 200, `jb_capacity` 24, `spare_pairs` 0.2), `motors` (`driven`, `tag`, `power_kw`, `voltage_v`, `room`, `assumed`, `source`, `skip`, `cable_entry`: see [Motor cable entry](#motor-cable-entry)), `feeders` (`tag`, `item` or `point`, `power_kw`, ...), `junction_boxes` (`tag`, `point` or `area`, `instruments` patterns, `capacity`, `room`), `instruments` (`tag`, `jb`, `point`, `skip`) |
| `electrical/tray-rules.yaml` (optional) | `trays` (spatial) | `rules`: `widths_mm` (100 .. 900), `depth_mm` 100, `fill_max_power` 0.3, `fill_max_instrument` 0.4, `separation_m` 0.3, `spacing_m` 0.15, `tier_gap_m` 1.5, `tiers: [{rack, elevation}]`, `lane_fraction` 0.25, `entry_elevation_m` 3, `branch_elevation_m` 3, `rack_reach_m` 50, `jb_elevation_m` 1.2, `jb_reach_m` 30, `termination_m` 1.5, `slack` 0.05, `grid_m` 0.5, `avoid_zones` [oxygen_enriched, hazardous], `support_span_m` 6, `support_reach_m` 1. Every default ASSUMED |
| `equipment/equipment-list.yaml`, `equipment/datasheets/<TAG>.yaml` | | the driven items; their power (`type_specific` or `operating`: `motor_kw`, `motor_power_kw`, `driver_kw`, `driver_power_kw`, `rated_power_kw`, `power_kw`) |
| `control/instrument-list.yaml`, `pid/*.xml` | | the instruments; what each P&ID function measures (`SensingLocation`) and where it sits (`Location`: `Field` is a local gauge) |

With an electrical list the model records it, the instrument list and the datasheets it took a
power from as sources: a change outdates the model (`layout-model-outdated`).

## Motors

Every equipment-list item whose DEXPI class ends in `Pump`, `Compressor`, `Blower`, `Fan`,
`Agitator`, `Mixer`, `Stirrer`, `Centrifuge`, `Conveyor`, `Crusher`, `Mill`, `Extruder`,
`Kneader`, `AirCooledHeatExchanger`, `AirCooler` or `CoolingTower` has a motor (`M-<tag>`
unless `motors` names it), not a turbine, expander or engine, nor a machine of `variant:
compander | expander`. Power: the `motors` entry, else the datasheet, else missing
(`electrical-motor-power`, warning; the cable gets the smallest size and `review_needed`).
Voltage: the entry's, else `mv_voltage_v` above `mv_above_kw`, else `lv_voltage_v`. Room: the
entry's, else `defaults.mv_room`/`lv_room`, else the first `switchgear` (MV) or `mcc` (LV) room.

## Cable sizes (package table, ASSUMED)

`data/cables.yaml`: a motor's full-load current `P / (sqrt(3) U cos(phi) eta)` with `cos(phi)`
0.85 and `eta` 0.92; a feeder's (heater, package) `P / (sqrt(3) U cos(phi))` with its own
`power_factor` (default 1.0, a resistive load, marked ASSUMED in the cable's basis; give it for
a package with motors) and no efficiency. Both are three-phase: a single-phase load (a 230 V
socket outlet) draws more for its power. The smallest size whose rating times the derating 0.8
carries it (LV 4-core 2.5 .. 300 mm2, MV 3-core 35 .. 300 mm2), else parallel cables of the
largest; overall diameters typical of catalogues. A field instrument cable is 1 pair (transmitter, control valve) or 3 pairs (on/off
valve), a junction box's home run the smallest multipair (2 .. 48 pairs) that holds its pairs
plus `spare_pairs`. The table sizes the trays; it is no cable sizing.

## Instruments and junction boxes

Cabled: every P&ID instrument function with a sensor that is not located `Field`, every
instrument-list tag (drawn on no P&ID: needs a `point`), every in-line valve that is actuated
(tag letters ending in V, not `H..`, `..SV`, `..RV`, `..CV`; `X`, `U`, `K`, `Z`, `SD`, `BD`,
`ES`, `HS` letters are on/off valves; or a DEXPI class with `Control`, `Motor`, `Operated`),
and every `instruments` entry with a `point`; not those with `skip`. Position: the entry's
`point`, else what the function measures (a nozzle's face, the middle of a routed segment, an
in-line item, an item's centre up to 1.5 m), the valve's point. A device the model cannot place
is listed under `cabling.missing`.

Junction box: the entry's `jb`, else the first box whose `instruments` patterns match, else the
nearest declared box with a point within `jb_reach_m` and room left, else one proposed per site
plan area (`JB-<area>-<k>`, the area's devices ordered by x, y and cut by `jb_capacity`) at
their middle, `jb_elevation_m` up, moved to the nearest free spot (a 1 m ring search clear of
items, steel, pipes): `source: generated`, `review_needed`. A field cable runs the orthogonal
distance from the device to its box (not in trays).

## Trays

Power cables (motors, feeders) and junction box home runs run in trays from their room:

- **Room exit**: the room's `point`, else the middle of its building's side facing the nearest
  rack, 0.5 m out, at `entry_elevation_m` (rooms of one building 1.5 m apart along the side).
- **Rack path**: the nearest rack within `rack_reach_m` of each end, the shortest way along the
  racks between them (racks join where their strips touch, as for the pipes). A cable whose ends
  reach no rack is fed directly (`no rack in reach`).
- **Trunk** (`kind: trunk`, id `PT|IT-<rack>-<k>`): along the rack on its tray tier (a `tiers`
  rule, else `tier_gap_m` above the top pipe tier, carried by a generated `tray_tiers` entry:
  column extensions and a beam at each bent along the trunks' span), power trays
  `lane_fraction` x the rack width left of the centreline seen along the rack, instrument trays
  as far right. A trunk is cut wherever its set of cables changes.
- **Room** (`PT|IT-<room>`), **link** (`PT|IT-<rack>-<rack>`, from one rack's lane onto the
  next at their joint) and **branch** (`PT|IT-<load>`): A* legs of the pipe router, clear of
  items, steel, walls, pipes and the trays before them by `spacing_m`; a branch runs at least
  `branch_elevation_m` high to above its load and drops onto it (0.6 m above the terminal box);
  a motor with a `cable_entry` ends its branch beside the item instead (below).
  Power trays and both trunks are routed first; instrument legs keep `separation_m` from every
  power tray. A leg the router cannot find is `method: direct`, `review_needed`.
- **Width**: the smallest of `widths_mm` whose `width x depth x fill_max` holds the cables'
  cross-section; `fill` is cables' cross-section over the tray's.

**Length** of a cable: along its trays plus the drop to its terminal (`route_length`; the drop
is orthogonal, from the tray's end to the terminal box), times `1 + slack`, plus
`termination_m` at each end, rounded up to the metre.

## Motor cable entry

Without it a motor's branch runs to above the terminal box and drops onto the machine, so the
tray crosses the machine's footprint: a crane lane over the machine (`cheme layout lifting`)
counts that tray as a blocker. A motor's `cable_entry` says where its cable leaves the tray
beside the item; the branch ends there and the rest of the way to the terminal box is a cable
drop (a conduit or a flexible cable, not tray), counted in the cable's length:

```yaml
motors:
  - {driven: K-101, power_kw: 8567.9, cable_entry: {side: east, offset_m: 1.5}}
  - {driven: K-102, power_kw: 260, cable_entry: {point: [131.0, 152.0], elevation_m: 4.0}}
```

| field | meaning |
|---|---|
| `side` | `north` (+y), `south` (-y), `east` (+x) or `west` (-x) side of the driven item's footprint in plan (the placed item's axis-aligned box in site axes) |
| `offset_m` | along that side from its middle, m: toward +x on north and south, toward +y on east and west (default 0); at most half the side's length |
| `clearance_m` | from the side out to the tray's centreline, m (default: the layout criteria's `lane_margin_m` + half the tray's width + `spacing_m`: just outside a crane lane that runs along that side or ends at it) |
| `point` | instead of `side`: the tray's end [x, y], site m, outside the footprint |
| `elevation_m` | the tray's end above grade, m (default 0.6 m above the terminal box); the branch runs at `branch_elevation_m` to above the entry and drops to it as tray |

The branch's tray entry records the terminal box it drops to (`drop_to`); its last run is no
longer the item's own drop, so the lifting lane and `clash-tray` count every run of it. Pick a
side the lane runs along or the side away from the crane pad: an entry between the pad and the machine is
still in the lane. A crane lane that runs diagonally to the footprint is wider than the
footprint's sides: check with `cheme layout lifting`. The branch's way from the rack to the
entry is the router's; it may still cross the lane higher up (the study names it).

`cheme validate` and `cheme layout build`: `cheme.electrical-cable-entry` (error, on the entry's
line) when the placed item makes it impossible (a `point` inside the footprint, an `offset_m`
beyond the side); the build then gives that motor no cable (`cable-missing`) rather than end the
tray over the machine. The schema refuses an entry with neither or both of `side` and `point`,
or with `offset_m`/`clearance_m` beside a `point`.

## Rules (on the model)

| rule | level | when |
|---|---|---|
| `cheme.layout-tray-fill` | warning | a tray's fill over its `fill_max` (only at the largest width) |
| `cheme.layout-tray-separation` | warning | a power and an instrument tray closer than `separation_m` (`cabling.rules`) |
| `cheme.layout-clash-tray` | warning | a tray through an item part (not the branch's drop onto its own item, unless the branch ends at a `cable_entry`), a pipe or a steel member |
| `cheme.layout-tray-zone` | warning | a tray inside a zone (`layout/zones.yaml`) of a kind in `avoid_zones` (`cabling.rules`; default oxygen-enriched and hazardous areas): move the lane, or record the cable sheath and glands for the zone and accept it |
| `cheme.layout-tray-span` | warning | a tray off the racks (no `rack`) with a level run longer than `support_span_m` between points where steel (rack, tray tier and structure members, enclosure walls, building wall panels and roofs) comes within `support_reach_m` of it |
| `cheme.layout-cable-missing` | warning | a motor, feeder, instrument or junction box without a cable (`cabling.missing`, with the reason) |
| `cheme.layout-cable-unrouted` | warning | a cable with a `direct` tray |

`cheme validate` on the list: `electrical-duplicate`, `-unknown-room`,
`-unknown-substation`, `-unknown-tag` (a motor's `driven`), `-unknown-jb`, `-cable-entry` (with
the committed model; errors),
`-motor-power`, `-motor-room` (warnings); `layout-tray-rack` (error) for a tray tier on a rack
the site plan lacks.

## Commands and gate

`cheme layout cables [--csv | --json] [--write | --check]`: the schedule of the committed
model (Markdown: the cables, totals by size, the trays with width and fill, what has no cable);
`--write` into `electrical/cable-schedule.csv` and `.md`, `--check` exits 1 when they are not
current.

Gate `kind: layout-model` requirements: `cables` (an electrical list, a model with `cables`, no
`layout-cable-missing` or `-unrouted` finding unaccepted) and `trays` (no `layout-tray-fill` or
`-separation` finding unaccepted). The template's detail-stage gate `electrical` requires
`[model-current, cables, trays]`.

## Not modelled

Cable sizing (voltage drop, short circuit, protection, grouping), load flow, hazardous-area
glands, earthing, lighting and small power, conduits and the field cables' own trays, tray
supports other than the rack tray tiers, and the trays in the material take-off.
