---
name: structures-access
description: Decide what stands on a steel structure and how people reach it - frames in layout/structures.yaml (levels, bracing, stairs, ladders, enclosures such as a cold box casing or fire wall with their openings), equipment mounted on their levels, access platforms and ladders for manways, valves and instruments, escape (two ways down, travel to a stair), crane pads, lifting lanes and laydown, and maintenance envelopes. Use when an item is elevated, a platform is proposed (review_needed), a cold box or enclosure is modelled, or access, escape, operability, lifting or wall penetration findings appear.
---

# Structures and access

## Purpose and when to use

Put elevated equipment on structures that exist in the model, and give every place a person
must reach a platform, a ladder or a stair and a way out. `cheme layout build` generates the
steel from `layout/structures.yaml` (columns, beams, bracing, gratings, handrails, stairs,
ladders with cages, enclosure walls), the access platforms of vertical items from their
`access:` (or proposals), and the maintenance envelopes (bundle pull, motor removal, pump
access). Use this skill when an item stands above grade, when the build proposes platforms
(`review_needed`), when modelling a cold box, enclosure or fire wall, and before the layout
review.

## Required inputs and missing inputs

- The placement and the equipment list with dimensions (skill `layout-yaml`), the P&IDs (the
  nozzles, manways and in-line valves the model places).
- What must be reached and how often: operating valves, control valves, instruments, sample
  points, manways, relief valves, davits. The P&ID shows the items; the frequency and the
  operating philosophy are design information: ask, or write an assumption into `DESIGN.md`.
- Section sizes are defaults by span (HEB200 .. HEB500, L100x10 bracing, ASSUMED); they are
  placeholders for the structural design, not results.

## Workflow and tools

1. **When an item goes on a structure.** On a structure: items that must be elevated for the
   process (an overhead condenser draining by gravity to its drum, a reboiler under its column,
   NPSH for a pump below a vessel), items stacked with others, groups that share access. On a
   building level: items that need weather protection or a crane. At grade: pumps,
   compressors, heavy and vibrating machines, tanks. A column or tank stands on its own
   foundation or skirt, with platforms on its shell, not on a frame.
2. **A frame** (`layout/structures.yaml`, `cheme schema structures`): `origin` (south-west
   corner before rotation), `rotation_deg` (0/90/180/270), `spans_x`/`spans_y` (bays, typically
   6 to 8 m), `levels: [{id, elevation, kind: deck | platform, extent?}]` (a platform covers only
   its `extent` in frame coordinates), `bracing` (`x` or `k`, per side; leave a side open for
   access and bundle pulls), `stairs: [{id, from: grade, to, side}]`, `ladders: [{id, from, to,
   at, facing}]`, `enclosure: {walls, height, material}` for a cold box casing (`casing`) or a
   fire or blast wall (`fire_wall`). Items on it: `mount: {structure: S-1, level: L1}` with `z`
   at the level's elevation; `cheme validate` checks the level and the footprint, the build
   reports `layout-clash-equipment-steel` (an item through a member).
3. **Cold boxes and enclosures.** Model a cold box as a structure with an `enclosure` (casing
   walls all round, the casing's height) and the columns, exchangers and separators inside it
   mounted or standing at grade inside its footprint; stacked columns stand on each other. Keep
   the casing's purge, breather and manholes on the P&ID and their access on the frame. The
   walls are obstacles for lines passing by and passable for a line with an end inside; every
   pipe that meets a wall outside a declared opening is a model `penetration` with the opening
   it would need (finding `layout-wall-penetration`: info for a casing penetration, a warning
   for a fire wall, a building's cladding or roof, a line passing through or one running in the
   wall; a roof penetration cannot be pinned: bring the line in through a wall).
   Declare the openings you accept (`enclosure: {..., openings: [{id, side, offset, width,
   height, sill, kind: opening}]}`, offset along the side from its left end seen from outside,
   sill above grade; or `cheme layout pin OWNER/LINE`): the walls are cut around them. A
   fire wall's separation distances go in `separations:` of the site plan.
   **Nobody stands inside a casing.** A perlite-filled, purged cold box has no walkable level
   below the top of its walls: a level whose extent lies inside the frame and below the casing
   height is no walking level and is finding `layout-access-enclosed` (so are ladders, stairs
   and item platforms inside it); it does not count as a way down, and nothing is operable
   from it. Put the access platforms outside the casing: a level's `extent` may reach up to
   3 m outside the frame (a cantilevered platform, e.g. `[0, 9.2, 15, 10.7]` along the north
   face of a 9 m deep casing with 0.2 m walls). The build proposes such a platform for every
   level inside the casing (`S/<level>-out`, along the side the level runs longest on, outside
   the wall, `review_needed`) and a landing at the casing roof on that side, with the stairs
   and ladders to them outside the platforms: pin the platforms first (`cheme layout pin
   CB-1/P10-out`), then the stairs and ladders. Valves and instruments inside the casing are
   not operable from outside (`layout-operability`): route them to the casing face and
   declare an access `hatch` (`openings: [{..., kind: hatch}]`) within `casing_reach_m`
   (1 m) of the item, with a platform outside within reach of the hatch, or bring the item
   out of the casing.
4. **Platforms and ladders of vertical items.** The build proposes a platform for every nozzle
   and in-line valve more than 2.5 m above the item's base (`review_needed: true`, `serves:`
   lists them). For each proposal decide: needed (operating or maintenance access), reachable
   otherwise (a structure next to it, a mobile platform for rare tasks), or wrong (a nozzle
   placed by default: give its real position first). Then `cheme layout pin TAG/platform-1`
   or declare `access: {platforms: [{elevation, arc_deg, width}], ladder_side}` in the
   placement. An item reached from a structure (a column inside a cold box, whose valves and
   instruments are brought out to the casing platforms) declares `access: {platforms: [],
   notes: <how it is reached>}`: no platforms of its own, nothing proposed. Rules of thumb (check them against the site's standard and the local
   regulations, ASSUMED until then):
   - manways, operating valves, control valves, instruments read in the field and sample points
     above about 2.5 m get a platform; rarely used items may be reached by a mobile platform;
   - a ladder over 3 m has a cage (drawn) or a fall-arrest system; long climbs are broken by
     rest platforms (often every 6 to 9 m); offset ladders between platforms;
   - a stair, not a ladder, where people carry tools or work often, and as the main access to a
     structure's working levels;
   - every platform and deck has two ways out where the travel distance or the hazard (oxygen,
     inert vents, flammables) requires it; escape routes are declared as `escape` zones in
     `layout/zones.yaml` (kept clear of pipes up to the walkway headroom). The rules check it:
     `layout-escape-ways` (a structure floor with fewer than two **connected declared** ways
     down to grade: a stair or ladder counts only when it is outside any casing, its top
     landing reaches the floor (within 0.3 m in plan; a ladder's top within 0.8 m), its foot
     stands on the floor below, and that floor has its own connected way down; proposals count
     once pinned; two ways count only when they arrive at least `escape_remote_fraction`, half
     the floor's diagonal, apart, so two ladders side by side are one; a dead end longer than
     `dead_end_m`, 7.5 m, on any floor or platform: the walk in plan from a point of it in one
     direction only, to its only way down or to where two of its ways lie 45 degrees or more
     apart, so a long platform with both ways at one end fails until a way stands at its far
     end; an item's platform whose far end is more than `dead_end_m` along it from its only
     ladder),
     `layout-access-unconnected` (a declared stair or ladder that does
     not reach the levels it names: a stair tower beside the platforms serves none of them; an
     item platform's ladder whose foot stands on no floor or whose top misses its platform),
     `layout-escape-travel` (a floor at 6 m or more, or in regular use, without a connected
     declared stair, or a point of it more than `stair_travel_m`, 25 m, from its nearest
     stair). Where the stair's top landing lands depends on its flights (an odd number ends at
     the far end of its run, an even number at its start): check it in a section;
   - valves and instruments within reach: `layout-operability` flags a manual handwheel or lever
     more than 1.8 m (a transmitter more than 2 m) above the nearest floor below it within
     0.6 m in plan (stair landings, a tank's landing and roof platform count as floors; stair
     flights do not: nobody operates a valve from the treads), and every in-line item inside a
     casing (above). The operator also needs room to stand: a free 0.6 m square
     (`standing_space_m`), as high as the access headroom, on that floor within reach; a stair
     flight, a ladder, a column or another item in it blocks it, and the same holds in front
     of a casing hatch (a stair flight rising across the hatch). Give it a platform, move the
     valve or the stair, or declare its operator in `piping/routing.yaml` (below);
   - **valve access platforms** (`VP-<valve tag>`, proposed; named after the first valve it
     serves in sorted order, so the id is the same from build to build and never passes to
     another platform; pinned ones keep the id they were pinned with, `VP-<n>` included): for the manual valves no floor reaches
     and no declared operator serves, the build proposes a small platform of its own beside
     the pipes (`valve_platform_depth_m` 1.2 m wide, its floor `valve_platform_operating_m`
     1.2 m below the highest handwheel), shared by valves within `valve_platform_group_m`
     (3 m) of each other at one operating height, with a caged ladder on its far edge, or a
     stair from 6 m (all ASSUMED; override under `criteria:` in the site plan). Its `reason`
     names what stands in its way: over the floor, and under it where its columns from grade
     would meet a pipe (the served valve's own pipe too), an item, steel or a rack; the side
     with the fewest is proposed. Decide first whether a chain wheel, a spindle, moving the
     valve or a larger platform is the better answer; then `cheme layout pin VP-<valve tag>`
     declares it (a structure with `serves: [valves]`, which needs one way down while its far
     end is within `dead_end_m`) and pins the routes of the valves' pipes. Until pinned the
     rules do not count it (the `layout-operability` finding names it);
   - **operators for what stays out of reach** (`operators:` in `piping/routing.yaml`, each
     with its `basis`): `{item: <valve tag>, kind: chainwheel, use: infrequent}` for a
     handwheel valve operated rarely (isolation for maintenance, not control or emergency
     duty), handwheel at most `chainwheel_max_height_m` (6 m) above a floor; `{item, kind:
     extension_spindle | remote_operator, length_m?}` to a pedestal at a floor, at most
     `extension_max_m` (6 m); `{item: <transmitter tag> or TAG/NOZZLE, kind: remote_mount, via:
     impulse | capillary, length_m?}` to a stand at a floor, at most `impulse_max_m` (6 m) or
     `capillary_max_m` (10 m). The rule accepts what fits and says why the rest does not
     (`layout-operability`); `layout-operator-unknown` names an entry that matches nothing. A
     chain wheel on a valve used often, in emergency duty or on a lever is no answer: give it
     a platform. The limits are ASSUMED: confirm them with the owner's standard and the valve
     and instrument suppliers;
   - headroom over every walking surface above grade at least `access_headroom_m` (2.1 m,
     ASSUMED): `layout-headroom` flags a pipe lower than that over a structure floor, an item
     platform, a stair tread or landing, a tank's stair or roof platform (escape routes at
     grade keep `headroom_walkway_m`, 2.2 m). Look at the stair towers in a section: a line
     leaving a casing face often crosses the stair beside it;
   - stacked stairs (one per storey, each from the platform the last arrives at):
     `layout-landing-width` flags a walk between the arriving stair's top landing and the next
     stair's foot that is narrower beside the next flight than the stair width; widen the
     platform over the stair bay or turn the stairs;
   - ladders and ring platforms: `layout-ladder-clearance` flags a pipe through a ladder's
     cage or closer than `ladder_clearance_m` (0.2 m, ASSUMED) to its rails, the climb, the
     toe space or the step-off at its head; `layout-walkway-riser` flags a riser through an
     item's ring platform that cuts the handrail or leaves less than `walkway_clear_m` (0.6 m)
     of walkway. Take risers outside the handrail or into the gap of the arc;
   - ways off a roof or platform: `layout-egress-zone` flags a ladder head or a stair's top
     landing inside an oxygen-deficient, oxygen-enriched or hazardous zone (a breather or vent
     next to the roof ladder). Move the vent or the ladder.
5. **Access proposals on structures and racks.** The build proposes (`source: generated`,
   `review_needed: true`, with a `reason`) a stair for every structure level at 6 m or higher,
   or in regular use (`use: regular`; a deck's default), that has no connected stair down:
   stacked on the frame's declared stair where that reaches the level, else on a side the
   level reaches, from the highest floor below its foot lands on; a caged ladder while a floor
   (levels at one elevation within 0.3 m of each other, not across a casing wall) has fewer
   than two connected ways down remote from each other (outside the casing; a casing roof's
   just outside the wall); no stair where no position reaches the level (the finding then
   says to place one by hand); a caged ladder at each free end of a rack, to its top tier;
   and a step-over where a low pipe (top within 0.75 m) crosses an escape route or a grating.
   Decide each one like a platform: pin it (`cheme layout pin S-1/stair-to-L2`,
   `S-1/ladder-to-L2`, `RACK/ladder-start`), declare something else (a stair on another side,
   `ladders: []` on a rack reached from a structure), or move the pipe. Step-overs follow the
   route: raise or reroute the pipe rather than accept many of them. Guard rails are drawn with
   a top rail, a mid rail, a toe plate and posts. The rules are ASSUMED defaults: check them
   against the site's standard and the local regulations.
6. **Maintenance envelopes.** Keep the generated `bundle_pull` (in front of an exchanger's
   channel), `motor_removal` and pump `access` boxes free of steel, pipes and other items
   (`layout-access-blocked`); add `maintenance` and `laydown` zones for crane access, removal
   routes and laydown areas. Look at them in a plan (`cheme layout render --plan --png`) and
   a section through the structure (`--section x=.. --png`).
7. **Lifting.** Give heavy items their `weight` (t) in the equipment list's `dimensions`. An
   item of `heavy_lift_t` (5 t) or more needs a crane: inside a building its overhead crane
   (`crane: {capacity_t}` at least the item's weight), outside a `crane_pad` zone (`kind:
   crane_pad`, a box where the mobile crane stands, with its `reach_m`) within reach (the
   nearest pad whose lane is clear is taken), with the lane from the pad over the item (the
   item's width across the direction of travel plus the margins) clear above the item's top (no pipes, cable trays, ducts,
   racks, steel or roofs: `layout-lifting`; a tray over the item, even its own feed, blocks the
   lift: bring the cable in from the side or at grade), and a `laydown` zone within reach that
   holds the item's footprint (`layout-laydown`). Crane pads and laydown zones stand on open
   ground: one overlapping a rack, a structure or a building is `layout-pad-overlap`. Items
   inside a closed casing are left out.
   Steel keeps out of the ways: a rack bent, a platform, a stair, a ladder or a support post
   in a road below its headroom, and a declared support post in a crane pad, laydown, escape,
   keep-clear or maintenance zone, in an item or at a ladder, is `layout-steel-in-way`. A rack
   crossing a road gets its own `bent_spacing_m` so its bents stand either side of it.
8. **Criteria.** The values above (operator height and reach, dead end, stair travel, heavy
   lift, crane reach, lane margin and clearance) are package defaults, ASSUMED. Where the site's
   standard says otherwise, put its values under `criteria:` in `layout/site-plan.yaml` and
   cite the standard in `DESIGN.md`.

## Validation and failure handling

- `cheme validate` (schemas, levels, footprints); `cheme layout build` (clashes with
  steel, blocked access, headroom); `cheme layout report` (platforms `review_needed`,
  objects generated, pinned or declared).
- Gate `layout-3d` requirement `mounted`: every item above grade on a building or structure
  level, or stacked on another item.
- `layout-escape-*`, `-access-enclosed`, `-access-unconnected`, `-operability`, `-headroom`,
  `-ladder-clearance`, `-walkway-riser`, `-landing-width`, `-egress-zone`, `-operator-unknown`, `-lifting`, `-laydown`,
  `-pad-overlap`, `-steel-in-way`, `-wall-penetration` findings: fix
  the cause, or accept the finding with the reason (an operating philosophy, a mobile crane
  plan) and record it in the layout review.
- A frame that fails its schema (spans, levels, a stair to an unknown level) names the line;
  fix it before building (the build refuses invalid layout files).

## Outputs and provenance

`layout/structures.yaml`, the `mount:` and `access:` of the placements, rack `ladders` in the
site plan, zones for escape and maintenance; the rebuilt `layout/plant-model.yaml`. Structures,
stairs and ladders are `source: declared`; generated platforms, stairs, ladders and step-overs
stay `generated` with `review_needed` until pinned or declared. Record the access philosophy and the assumed sections in `DESIGN.md`.

## Required human judgment

Structural design (loads, member sizes, connections, foundations, vibration of machine
supports), the access and escape philosophy, and compliance with the local regulations on
ladders, platforms, handrails and escape routes are engineering decisions for a competent
person; the model only places the geometry and flags clashes. Every proposed platform is a
question, not an answer: decide it and record the decision.

## References

- `cheme schema structures`, `cheme schema placement` (`mount`, `access`),
  `layout/README.md`, `docs/framework/layout-model.md` (structures, platforms, envelopes)
- skills `layout-yaml`, `pipe-routing`, `area-classification`, `review`
