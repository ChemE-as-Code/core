---
name: pipe-routing
description: Steer and review the generated pipe routes of the 3D model - routing intent in piping/routing.yaml (rack tiers per service, battery limits, the pipe-way elevation, vent riser heights, via points, pins, skips with a reason), iterate with cheme layout route, report and render --plan/--section, look at the PNGs, fix clashes, tier, wall penetration, vent outlet and span findings, and pin good routes. Use when lines are unrouted, run the wrong way, clash, or before a layout review or the layout-3d gate.
---

# Pipe routing

## Purpose and when to use

`cheme layout build` routes one pipe per P&ID segment (DN, insulation, class from the line
list and `piping/pipe-specs.yaml`). The router is deterministic and simple: it goes over the
racks for lines between areas, across roads or longer than `local_max_m`, and runs local lines
at the pipe-way elevation. It knows nothing of stress or drainage; the rules on the model then
screen what it produced (tiers, wall penetrations, vent outlets, spans between supports, valves
within reach), each against an ASSUMED criterion. This skill says how to give it the intent it lacks, how to check the
result, and when to stop iterating and pin. Use it when `cheme layout report` shows lines
unrouted or `direct`, when routes clash or look wrong in the drawings, and before the layout
review.

## Required inputs and missing inputs

- A built model: placement, site plan with racks, the P&IDs, the line list with DN, `fluid`,
  `insulation`, `from`/`to` (skill `layout-yaml`). A segment with no DN on the P&ID or in the
  line list is routed at DN 50, a line without `insulation` bare: fix the list first (skill
  `lists-sync`).
- `piping/routing.yaml` (`cheme schema routing`), optional. Without it the defaults apply,
  each ASSUMED: `local_max_m` 15, `local_elevation_m` 3.5 (bottom of pipe), `grade_max_m` 3,
  `rack_detour_factor` 2.5, `spacing_m` 0.1, `headroom_road_m` 6,
  `headroom_walkway_m` 2.2, `grid_m` 0.5. How far an end may be from a rack to use it is
  `rack_reach` in `layout/site-plan.yaml` (default: `max_unsupported_length`, 30 m), the same
  value `cheme validate` checks line routes with; do not set `rack_reach_m` here (deprecated).
- Where the utilities come from (cooling water plant, nitrogen header, flare) is design
  information: ask, or record an assumption in `DESIGN.md`, before declaring battery limits.

## Workflow and tools

1. **Read the result first.** `cheme layout report` lists each line (routed, partly routed,
   skipped, unrouted with the reason), the chains per method (`astar`, `astar_coarse`,
   `astar_fine`, `rack`, `rack+...`, `via`, `open`, `direct`, `pinned`) and per reason (`rack:
   across areas`, `rack: crosses a road`, `local: pipe-way`, `local: pump run at grade`, `local:
   rack run too short`, ...), the battery limit ends and the rack fill. `--json` gives the same
   per line. `direct` and `rack+direct` routes are fallbacks (`review_needed`): treat each as a
   finding; most come from crowded nozzles (give them room with nozzle overrides) or an end
   boxed in by steel and pipes.
2. **Rules, in `piping/routing.yaml` `rules:`**:
   - `tiers`: which service runs on which tier, by `fluids` or line-number prefix (`lines`),
     optionally per `rack`. Typical: large process lines low, utilities and small lines high,
     cold and oxygen lines on their own tier or edge. Without a rule DN 300 and above take the
     lowest tier, the rest the top tier;
   - `battery_limits`: where lines that leave the plot end (`BL`, `CW`, `CWR`, ... ends in the
     line list): `{id, lines: [CW-*, CWR-*], point: [x, y, z]}` or `{id, fluids: [Steam], rack:
     PR1, rack_end: start | end | nearest}`. Without a rule: the line's `from_area`/`to_area`,
     else the free end of the nearest rack, else the site edge;
   - `local_elevation_m` (the pipe-way of an area), `local_max_m` (longer goes to the rack),
     `grade_max_m`, `spacing_m`, headroom, `gravity_fluids`;
   - `vent_rise_m` (default 1 m): how far an open vent or relief end rises above its stub;
     `vents: [{lines: [VNT-*], fluids?, rise_m?, radius_m?, max_rise_m: 20}]` raises the
     outlets of the lines it matches until a sphere of `radius_m` around the outlet (default:
     the line's zone radius from `layout/zones.yaml`, when the line is a zone source) clears
     every walking level (grade, structure floors and stair landings, item platforms, a
     tank's spiral stair, landing and roof platform, step-overs, building levels; not the
     levels inside a casing) up to the walkway headroom.
     Use it for oxygen, inert and flammable vents that must discharge above where people
     stand; the criterion (radius, headroom) is ASSUMED until the vent study gives it.
3. **Intent per line or segment** (`lines:`, `{line, segment?}`; a segment by DEXPI id or
   segment number; where a line drawn on two sheets repeats a segment id, by its pipe id
   `<sheet stem>/<DEXPI id>`, e.g. `P-03/Line_A_S1`, which `layout pin` then writes):
   - `rack: PR2` or `tier: 8` to force the rack (and the tier);
   - `via: [[x, y, z], ...]` points the route must pass, in order; `elevation: z` runs it at
     that height;
   - `skip: <reason>` for what is not routed at this stage (field-run small bore, a package's
     internal piping, an item not placed yet). The reason is shown in the report and counts for
     the `layout-3d` gate; "later" is not a reason;
   - `gravity: true` (or the fluid in `gravity_fluids`) checks a continuous fall.
   Vent and relief lines end in a riser where the P&ID ends them (`vent_rise_m`, or a `vents`
   rule); a silencer or safety valve that discharges elsewhere (a vent stack area) is listed in
   `piping/special-items.yaml` and placed in `layout/equipment-placement.yaml` by its tag:
   the line is then routed to it.
4. **Iterate on the lines you changed only**: `cheme layout route --line L [--line M]`
   reroutes those and keeps every other route of the committed model; `cheme layout build`
   reroutes all (needed after a placement change). Lines route in order of DN, largest first:
   a small line that clashes may need a via, a large one moves everything after it.
5. **Look at it.** `cheme layout render --plan --png` (plot plan), `--z 2,6` (a band of
   elevations), `--section y=68 --depth 8 --png` (across a rack), `--section x=.. --crop
   X0,Y0,X1,Y1 --png` (around one item). Read the PNGs in `build/`: lines through items, lines
   at grade across walkways, lines in front of manways, bundle-pull or motor-removal space,
   lines over a road below the headroom, too many bends, dead legs, a lane jumping across the
   rack. `cheme serve` (Layout 3D) shows the same in 3D with the findings.
6. **Fix clashes** (`cheme.layout-clash-pipe`, `-clash-pipe-equipment`, `-clash-pipe-steel`,
   `-headroom`, `-access-blocked`, `-zone-crossing`): each finding names both objects and a
   `box`. Prefer, in this order: move the item or turn the nozzle (skill `layout-yaml`), give a
   tier rule, add a via, change the pipe-way elevation. Rebuild after each step. A clash that is
   real but intended (a line resting on its own support steel) is accepted in the `layout-3d`
   gate with a reason, never silently left.
6a. **The engineering findings on the routes** (each names the pipe, a `box`, the criterion and
   a hint; the criteria are ASSUMED package values a plant overrides under `criteria:` in
   `layout/site-plan.yaml`):
   - `layout-tier`: a line runs along a rack on another tier than its `tiers` rule (or between
     the tiers): its lane was taken or crossed. Free the tier (widen the rack, move other lines
     with their own rule), give it `tier:`/`via:` intent, or change the rule; never leave a
     line off its tier without saying why;
   - `layout-wall-penetration`: a pipe through a building's cladding, its roof or a fire wall
     outside the declared openings, passing through a building or enclosure it has no end in,
     or running in a wall's plane (warning); into a casing outside a declared opening (info,
     for the casing penetration schedule). The model's `penetrations` hold the opening each
     would need: `cheme layout pin OWNER/LINE` declares it in `layout/building.yaml`
     (`openings`) or `layout/structures.yaml` (`enclosure: openings`), and the next build cuts
     the wall around it. A roof penetration (`side: roof`, its opening in the building's plan
     frame: offset and width along its x, sill and height along its y) cannot be declared and
     the pin refuses it: give the line `via` points that bring it in through a wall (a rack
     drop into a low building), then pin that wall opening. Prefer fewer, grouped openings (route lines through one declared opening with `via`
     points) and keep pipes out of fire walls where you can: a fire-rated penetration is a
     design decision to record;
   - `layout-vent-outlet`: the zone sphere around a vent or relief outlet reaches a walking
     level (grade, a platform, a roof walkway, a tank's stair, landing or roof platform); the
     message gives the outlet height it needs. Also an open end directly under a walking
     surface (within `vent_plan_clearance_m`, 1.5 m, in plan and `vent_overhead_m`, 6 m,
     below it: a relief tailpipe under a stair landing discharges into the only way onto the
     roof), and an open end beside one (within `vent_side_clearance_m`, 1.5 m, of its edge in
     plan, between its floor and the walkway headroom above it: a vent at head height next to
     a platform). Add a `vents` rule for the line (or raise the placed silencer or valve), turn the
     tailpipe to the far side of the roof, or move the stair or platform;
   - `layout-operability` on in-line items inside a casing: a valve, relief valve or
     instrument inside a cold box cannot be operated or tested from outside. Route the line so
     the item stands outside the casing (pin the route), or bring it to the casing face with a
     declared `hatch` opening within 1 m and a platform outside (skill `structures-access`);
   - `layout-free-span` (warning) and `layout-support-missing` (info): a level run spans
     farther between supports than the DN's span (`pipe-spans.yaml`, after ASME B31.1, liquid
     or gas by the fluid's name), or has no support in the model at all (a local pipe-way
     without steel). Small lines on a rack with bents 6 m apart usually need intermediate
     steel: declare `intermediate_supports: {spacing_m: 3}` on the rack in
     `layout/site-plan.yaml` (a stringer along each tier's edges and a beam across every
     3 m, optionally only on `levels`), or let them ride on a larger line; record which. Off
     the racks the build proposes support steel under each run that spans too far
     (`support_steel`, `<pipe>/SP-<arc>`, the arc its nominal place in m along the pipe, so
     the id stays the same from build to build and never moves to another post: a T-post from
     grade, or a stub on the steel below when that is at most `support_stub_max_m` (1.5 m)
     below and not another line's support steel; dashed in the plans, named in the finding;
     the finding lists those to place by hand apart, never as `pin` candidates). A post
     keeps `support_pipe_clearance_m` (0.1 m, ASSUMED) from the pipes it does not carry: it
     moves along its pipe to the first clear place and its `reason` says so, or says "place it
     by hand" when none in the span is clear. Check where it stands (roads, walkways,
     foundations) and `cheme layout pin <pipe>/SP-<arc>` it into `pipe_supports` of
     `layout/structures.yaml`, or declare your own posts there. Posts pinned under the older
     `<pipe>/post-<k>` ids keep them (a declared id is the plant's); nothing to migrate.
     `layout-support-stub` (warning): a declared stub taller than `support_stub_max_m`, or one
     standing on another line's T-post: carry the pipe from steel close below (a bracket off a
     column), or give it a post from grade or a frame of its own. The supports themselves (shoes,
     guides) are generated where a pipe rests on a beam or a declared crossbar;
   - `layout-operability`: a manual valve's handwheel or lever more than 1.8 m above the floor
     below it (a transmitter more than 2 m), with no floor within 0.6 m in plan, or no free
     standing space there (a stair flight or steel in front of it). Move the valve on the route
     (a pinned route with the valve near a floor), add a platform (the build proposes a
     valve access platform `VP-<valve tag>` and names it in the finding; skill `structures-access`),
     or declare its operator under `operators:` in this file: a
     `chainwheel` (a handwheel valve of `use: infrequent`, at most 6 m up), an
     `extension_spindle` or `remote_operator` (at most 6 m long), a transmitter's
     `remote_mount` (`via: impulse`, 6 m, or `capillary`, 10 m), each with its `basis`;
   - `layout-headroom` over walking surfaces: a pipe lower than 2.1 m (`access_headroom_m`)
     over a structure floor, a platform, a stair or landing, a tank's stair or roof platform.
     Route it above the headroom or under the steel; a line leaving a casing face must clear
     the stair tower and the platforms on that face. A pinned route is taken as it is: check
     it against them before pinning;
   - a pinned vent or relief route keeps its open end, so the zones derived from the line
     (`layout/zones.yaml` sources) stay; `layout-zone-source` (also in `validate`, and failing
     the `zones` requirement of gate `layout-3d`) means a source the model cannot place.
7. **Pin what is good.** `cheme layout pin LINE` (or a pipe id) copies the route into
   `piping/routing.yaml` (`route:`, `source: pinned`): later builds take it as it is, so a
   reviewed route stays reviewed. Pinning a route as it was generated does not move the other
   lines: a pinned pipe becomes an obstacle where its chain would have been routed, and takes
   back its rack lane on the millimetre, so the other lines keep their lanes and tiers. It
   keeps its racks and tier too (intermediate rack steel carries it; no post is proposed under
   it). The other segments of its own line can move: one segment pinned out of a chain (a
   branch's tee to a nozzle) leaves the rest of the chain to be routed from the pinned end, so
   pin a line's segments together (`layout pin LINE`). Pin a route only after looking at it;
   re-pin or delete the pin when
   its ends move (`layout build` keeps a pinned route even when it no longer fits, and
   `layout-pipe-disconnected` (error) then names every pipe end more than 10 mm from its
   nozzle, its tee or connector partner, its placed item or its line).

## Validation and failure handling

- `cheme validate` checks `piping/routing.yaml` against its schema and the model rules on
  the committed model; `cheme layout build --check` says whether the model is current.
- Unrouted reasons and what to do: `<tag> is not placed` (place it, or skip the line with the
  reason); `both ends are open` (a vent between two open ends: check the P&ID); `it starts or
  ends at <tee/line>, which no route reaches` (route the run first, or fix the topology);
  `connector ...: line ... is not in the line list` (add the line).
- The `layout-3d` gate (`cheme check --stage basic`) fails while a process line of DN 25
  and above is neither routed nor skipped, or a clash or headroom finding is not accepted; the
  `layout-detail` gate requires every line, utilities included. A gate's `rules:` may add the
  engineering rules (`cheme.layout-tier`, `-wall-penetration`, `-vent-outlet`, ...); a
  finding left as it is gets an acceptance with its reason.

## Outputs and provenance

`piping/routing.yaml` (rules, intent, pins) and the rebuilt `layout/plant-model.yaml`, both
committed. Every pipe records its `method`, `reason` and `source` (`generated` or `pinned`);
assumed rules (tier allocation, battery limit points, pipe-way elevation) are marked ASSUMED in
`routing.yaml` `notes:` with their basis in `DESIGN.md`.

## Required human judgment

The router does not decide, and you must not pretend it did:

- tier allocation, rack width and spare space, which lines may share a support;
- pipe stress and flexibility (expansion loops, hot and cold lines), supports and anchors (the
  span rule is a screening value, not a support design);
- drainage and venting (low-point drains, pockets in two-phase and gravity lines), slug flow;
- operability and maintenance: valve and instrument access, spectacle blinds, removal spools;
- safety: oxygen-line velocity and material rules, cryogenic lines and their insulation, relief
  and vent outlets, lines over escape routes.

A route without a clash finding is only geometrically free. The layout review (skill `review`)
records which routes were checked by whom.

## References

- `cheme schema routing`, `layout/README.md`, `docs/framework/layout-model.md` (the router)
- `cheme layout build | route | pin | report | render`, `cheme serve` (Layout 3D)
- skills `layout-yaml`, `structures-access`, `review`
