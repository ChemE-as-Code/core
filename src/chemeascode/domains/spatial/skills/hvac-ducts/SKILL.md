---
name: hvac-ducts
description: Declare the air handling units and the ventilated rooms of the plant's buildings in layout/hvac.yaml, and let cheme layout build place the terminals, route the supply, extract, outdoor air and exhaust ducts inside the buildings and size them against the velocity limits. Use when the layout has clad buildings (compressor houses, substations, control rooms, analyser houses), before the detail-stage gate hvac, or when hvac-capacity, duct-unrouted, clash-duct or layout-hvac-ref findings appear.
---

# HVAC ducts

## Purpose and when to use

Ventilate every clad building of the layout: an air handling unit per building (or several),
the air changes of each room, and the ducts that carry the air, routed through the 3D model so
the layout reserves their space under the ceiling and the louvres in the walls. `cheme
layout build` places the terminals, joins them into a supply and an extract tree per unit,
ducts the outdoor air from the intake louvre and the exhaust to its opening, and sizes every
piece of duct by its air at the velocity limit. Use this skill once the buildings, their
openings and the equipment inside them are placed, at the latest before the detail stage
(gate `hvac`).

## Required inputs and missing inputs

- The buildings with their levels, walls and openings (`layout/building.yaml`): a louvre
  (`kind: louvre`, with an `id`) for the outdoor air and one for the exhaust. Skill
  `layout-yaml`.
- The equipment, pipes and cable trays inside the buildings: the ducts route around them.
- Why each room needs its air: heat load of the machines (kW over the allowed temperature
  rise), dilution of a gas that may leak, the code minimum for an occupied room, the
  overpressure of a control room or a substation. That is a process, safety or HVAC
  engineer's number: ask for it and write it in `basis:`. Never invent air changes; mark a
  screening value ASSUMED with its source.
- The unit's capacity (vendor data) where known.

## Workflow and tools

1. **Units.** In `layout/hvac.yaml` (`cheme schema hvac`) declare each unit under
   `units:` with its `building`, `position: [x, y]` (the centre, in the building, on a floor
   with room to service it), `rotation_deg`, `size` (default 4 x 2 x 2.2 m, ASSUMED),
   `capacity_m3h`, and the `intake` and `exhaust` opening ids of its building. The ports are
   on its top: outdoor air, exhaust, return and supply air along its length.
2. **Rooms.** Under `rooms:` each ventilated room: `building`, `level` (default the lowest
   floor), `extent: [x0, y0, x1, y1]` where it is part of the building, `air_changes_per_h` or
   `flow_m3h`, `extract_fraction` (below 1 to keep the room above ambient pressure, 0 where
   the air leaves by louvres), the serving `unit` and the `basis`.
3. **Terminals.** Without `supply:`/`extract:` points the build sets terminals of at most
   2500 m3/h (ASSUMED) in rows along the room, supply on one half and extract on the other.
   Declare them (`supply: [[x, y], ...]`, in duct order) where the air must go: over a
   machine's heat, at a gas's low or high point, away from the door.
4. **Rules** (optional `rules:`): `velocities` per kind (`main`, `header`, `intake`,
   `exhaust`, `louvre`; package defaults ASSUMED), `max_height_mm` (the ceiling space),
   `ceiling_gap_m`, `spacing_m`, `sides_mm`, `max_aspect`, `terminal_max_m3h`,
   `louvre_free_area`. A room's `duct_elevation_m` moves its ducts. Replace every default you
   rely on with the project's HVAC basis and cite it.
5. **Build and look.** `cheme layout build`, then a level plan and sections through the
   building (`cheme layout render --plan --z 0,12 --png`, `--section x=..`). Check: ducts
   clear of the crane hook path and of the maintenance envelopes, terminals over the heat or
   the leak, the unit reachable, the louvres away from the exhausts of other buildings and
   from hazardous zones.
6. **Findings.** `layout-hvac-ref` (validate: a building, level, unit or opening that does not
   exist, a unit or terminal outside its building, a room served from another building),
   `layout-hvac-capacity` (a duct above its velocity limit at the largest size, a louvre above
   its face velocity, a unit above its capacity, a unit without intake), `layout-duct-unrouted`
   (no clear way inside the building), `layout-clash-duct`. Fix the cause and rebuild.

## Validation and failure handling

- `cheme validate`: the schema, `layout-hvac-ref`, and the model findings above.
- Gate `hvac` (`kind: layout-model`, `require: [model-current, hvac]`): every clad building
  has `layout/hvac.yaml` and ducts in the model, no capacity or unrouted finding is left
  unaccepted. Clash findings count under the `clashes` requirement of the layout gates.
- A duct the router cannot fit inside the building is `direct` and `review_needed`: move the
  unit, declare the terminals, give the room another `duct_elevation_m` or deeper ducts.

## Outputs and provenance

`layout/hvac.yaml` and the rebuilt `layout/plant-model.yaml` (`hvac_units`, `hvac_rooms` with
their terminals, `ducts`, `hvac`: air flows, duct length and sheet area, louvre velocities,
the limits used). The model records `layout/hvac.yaml` as a source. Duct sizes come from a
package table of typical low-velocity limits (ASSUMED) and reserve space only.

## Required human judgment

The air changes and their basis (heat load, gas dilution, occupancy, overpressure), the
ventilation of rooms with a flammable, toxic or oxygen-enriched or -deficient atmosphere
(detection, emergency ventilation, where intakes may draw from), fire dampers and smoke
control, the fan and filter selection, noise and the duct pressure drop are decisions of a
competent HVAC and safety engineer. The build reserves space and checks velocities; it does
not design the ventilation.

## References

- `cheme schema hvac`, `layout/README.md`
- `docs/framework/layout-model.md` (HVAC sections, rules, drawings)
- skills `layout-yaml`, `structures-access`, `area-classification`, `review`
