---
name: electrical-cabling
description: Declare the electrical rooms, the motor list and the junction boxes in electrical/electrical-list.yaml, set the cable tray rules, and let cheme layout build route the power and instrument trays and write the cable schedule. Use when the plant has motors or instruments to cable, before the detail-stage gate electrical, or when tray-fill, tray-separation, tray-voltage, clash-tray, tray-zone, tray-span, cable-missing or electrical-* findings appear.
---

# Electrical cabling

## Purpose and when to use

Give every motor, electric consumer and instrument a cable from its room, routed in cable trays
through the 3D model, so the layout reserves the space and the cable schedule has its lengths.
`cheme layout build` derives the motor list from the driven equipment, places the
instruments where the P&IDs say they measure, groups them into junction boxes, routes the trays
(rooms to racks, along their own rack tier, branches to the loads) and sizes them by their
cables. Use this skill when the layout has its racks and buildings, at the latest before the
detail stage (gate `electrical`).

## Required inputs and missing inputs

- The 3D layout with its racks (`layout/site-plan.yaml`) and the building of each electrical
  room (`layout/building.yaml`): skills `layout-yaml`, `pipe-routing`.
- The equipment list (the DEXPI class decides which items have a motor: pumps, compressors,
  blowers, fans, agitators, air coolers; not turbines or expanders) and the motor powers: a
  datasheet's `type_specific: {driver_kw: ...}`, or `power_kw` in the electrical list. A power
  nobody gave is a question to the process or mechanical engineer (or the vendor), never a
  guess: mark an estimate `assumed: true` with its `source`.
- The P&IDs: each instrument function measures something (`SensingLocation`); a function
  located `Field` is a local gauge without a cable. Actuated valves are known by their tag
  letters (FV, LV, PV, XV, SDV, ...).
- The electrical philosophy: which room feeds what (MCC for LV, switchgear for MV), the voltage
  levels and the MV threshold, junction box sizes and spare pairs, the tray standard
  (widths, fill, separation). Ask, or write the assumption into `DESIGN.md`.

## Workflow and tools

1. **Rooms.** In `electrical/electrical-list.yaml` (`cheme schema electrical`) declare the
   substation and its transformers, and the rooms with their `kind` (`mcc`, `switchgear`,
   `control`, `rack_room`) and `building`. A room's cables leave its building on the side that
   faces the nearest rack; give `point: [x, y, z]` where the cable entry is elsewhere.
2. **Motors.** Run `cheme validate`: `electrical-motor-power` names every motor without a
   power, `electrical-motor-room` every one fed from no room. Give the power in the item's
   datasheet or under `motors: [{driven: P-101A, power_kw: 15, source: ...}]`; `voltage_v`,
   `room` and the motor `tag` only where the defaults (`defaults: {lv_room, mv_room,
   mv_above_kw, ...}`) do not fit. `skip: <reason>` for a motor cabled by its vendor package.
   `cable_entry` where its cable leaves the tray beside the machine (the terminal box side):
   `{side: north|south|east|west, offset_m, clearance_m}` of the item's plan footprint, or
   `{point: [x, y]}`, with `elevation_m` optional; the tray ends there and the cable drops to
   the terminal box (in its length). Give it for every heavy machine with a crane lane over it.
   Other consumers (an electric heater, a package panel) go under `feeders:`, with a
   `power_factor` for a package with motors (default 1.0, a resistive load, ASSUMED).
3. **Instruments and junction boxes.** Without `junction_boxes` the build proposes one per area
   at the middle of its instruments (`review_needed`). Declare the boxes you want (`tag`,
   `point` or `area`, `instruments` patterns, `capacity`), an instrument's own `jb`, its
   `point` where the P&ID does not place it, or `skip` (wireless, local).
4. **Tray rules** (optional, `electrical/tray-rules.yaml`, `cheme schema trays`): standard
   widths, depth, fill per system, the separation between power and instrument trays, the tray
   tier per rack (`tiers: [{rack, elevation}]`; default 1.5 m above the top pipe tier on steel
   of its own), more power trays on a rack whose cables one tray cannot hold (`power_trays:
   [{rack: PR-1, trays: 2}]`, or one voltage class per tray, `trays: [hv, hv, lv]`, HV above
   `lv_max_v`, 1000 V; side by side, the build shares the cables out and names each cable's
   tray in the schedule), the branch elevation, the zone kinds a tray may not run in (`avoid_zones`,
   default `[oxygen_enriched, hazardous]`; add `oxygen_deficient` where the cables must stay
   out of inert vent plumes), the longest tray run between supports (`support_span_m`, 6 m)
   and how close steel must be to carry it (`support_reach_m`, 1 m). Every default is
   ASSUMED: replace it by the project's electrical standard and cite it.
5. **Build and look.** `cheme layout build`, then `cheme layout cables` (the schedule:
   from, to, size, trays, length, tray widths and fill) and a plan and sections through the
   rack (`cheme layout render --plan --png`, `--section x=..`). Check: trays on their own
   tier, branches clear of walkways and access, junction boxes where people can reach them,
   rooms where the cables leave.
6. **Findings.** `layout-cable-missing` (a motor not placed, a room without building, an
   instrument the model cannot place), `layout-cable-unrouted` (a tray with no clear way),
   `layout-tray-fill` (more cables than the largest width holds: the hint names the number of
   power trays the rack needs, declare them in `power_trays`; or another room),
   `layout-tray-voltage` (a cable in a power tray of the other voltage class: give the rack a
   tray of its class or an `any` tray), `layout-tray-rack` (a `power_trays` rack the site plan
   lacks, or more trays than fit on the power half of the rack),
   `layout-tray-separation` (power and instrument trays too close: move one, or a metal divider
   with an accepted finding), `layout-clash-tray`, `layout-tray-zone` (a tray inside an
   oxygen-enriched or hazardous zone: move the lane or the release, or record the cable sheath
   and glands chosen for the zone and accept it), `layout-tray-span` (a branch or room tray
   running more than `support_span_m` with no steel near it: run it along a rack or a
   structure, declare support steel, or bring the cable in at grade or in a trench). A tray
   over a heavy item blocks its crane lift (`layout-lifting`, skill `structures-access`):
   give its motor a `cable_entry` on a side the lane runs along or on the side away from the
   crane pad (not between pad and machine), so the tray ends beside the machine; its default
   clearance keeps it outside a lane running along that side or ending at it;
   `electrical-cable-entry` (error) is an entry the placed item makes impossible (a point
   inside its footprint, an offset beyond the side).
   Rerun `cheme layout lifting`: a tray still in the lane is still named. Fix the cause and
   rebuild.
7. **Schedule.** `cheme layout cables --write` writes `electrical/cable-schedule.csv` and
   `.md`; commit them with the model.

## Validation and failure handling

- `cheme validate`: the schema, `electrical-unknown-room|-substation|-tag|-jb`,
  `electrical-duplicate`, `electrical-motor-power`, `electrical-motor-room`; the model findings
  above.
- Gate `electrical` (`kind: layout-model`, `require: [model-current, cables, trays]`): the
  model is current, every motor and instrument has a cable routed in trays, no tray fill,
  separation or voltage finding is left unaccepted.
- A build that cannot route a tray marks it `direct` and `review_needed`: give the room a
  `point`, a rack nearer the load, or move what blocks it.

## Outputs and provenance

`electrical/electrical-list.yaml`, `electrical/tray-rules.yaml`, the rebuilt
`layout/plant-model.yaml` (`tray_tiers`, `trays`, `junction_boxes`, `cables`, `cabling`) and
`electrical/cable-schedule.*`. The model records the electrical list, the instrument list and
the datasheets it took powers from as its sources. Cable sizes come from a package table of
typical catalogue values (ASSUMED) and size the trays only.

## Required human judgment

Cable sizing (load flow, voltage drop, short circuit, protection, grouping derating), the
voltage levels and the switchgear arrangement, the hazardous-area cable glands and routing
through classified zones, the separation and segregation standard and every motor power are
decisions of a competent electrical engineer. The build places geometry and counts lengths; it
does not design the electrical system. Every proposed junction box is a question: decide it.

## References

- `cheme schema electrical`, `cheme schema trays`, `electrical/README.md`
- `docs/framework/electrical.md`, `docs/framework/layout-model.md` (trays, cables)
- skills `layout-yaml`, `pipe-routing`, `structures-access`, `mto-estimate`, `review`
