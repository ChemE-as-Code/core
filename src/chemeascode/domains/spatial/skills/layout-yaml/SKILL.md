---
name: layout-yaml
description: Edit the 3D layout in layout/ - site plan (areas, roads, pipe racks, separations), buildings, steel structures, zones and equipment placement (mount, nozzles, access) - keeping tags consistent with the equipment list and clear of clashes, then build the 3D model with cheme layout build and check it. Use when placing, moving or resizing equipment, adding a building, structure, zone, area, road or rack, or when cheme validate reports cheme.layout-* findings.
---

# Editing the 3D layout

## Purpose and when to use

Edit the 3D layout in `layout/` and keep it consistent with the equipment list and clear of
clashes, then build the generated 3D model (`layout/plant-model.yaml`) and look at it. Use it
when placing, moving or resizing equipment, or adding a building, structure, zone, area, road
or rack. Pipe routes: skill `pipe-routing`; steel, platforms and access: `structures-access`;
hazardous and oxygen zones: `area-classification`.

## Required inputs and missing inputs

The optional files explained in `layout/README.md` (`site-plan.yaml`, `building.yaml`,
`equipment-placement.yaml`, `structures.yaml`, `zones.yaml`, and `piping/routing.yaml`), and
the sizes in the equipment list; the schemas are `cheme schema site_plan`, `building`,
`placement`, `structures`, `zones` and `routing`.
Coordinates are metres, x east, y north, z up, origin at the site's south-west corner.

1. **Read first**: `layout/site-plan.yaml` for the site box and what is already taken (areas,
   roads, racks), `layout/building.yaml` for building outlines and level elevations, and
   `equipment/equipment-list.yaml` for the tags and types.

A dimension not known yet may be estimated: mark it `notes: ASSUMED ...` (step 2).

## Workflow and tools

2. **Sizes live in the equipment list**, not in the placement: give each item
   `dimensions:` in `equipment/equipment-list.yaml` -- overall `{diameter, height}` (vertical:
   from the bottom of the skirt or legs to the top of the head), `{diameter, length}`
   (horizontal: over both heads or channels; optional `height`, the top of the shell, when it
   sits on saddles), or `{length, width, height}` (pumps, skids, plate exchangers, packages),
   with `head` and `support` where you know them. The DEXPI class in `type` picks the shape
   family (column with skirt and heads, tank with roof and spiral stair, shell-and-tube
   exchanger with channel and bundle-pull space, end-suction pump with volute, coupling guard
   and motor on a baseplate, integrally geared compressor, ...). For a machine,
   `orientation: vertical` draws a vertical inline pump, and `variant` picks another drawing
   (`cryogenic` for a pump with an insulated cold end, `blower`, `compander`, `expander`,
   `machine` for a plain casing and motor); the model puts the machine's nozzles on its real
   flanges, and items at grade on concrete plinths or foundations. Unknown sizes are fine to
   estimate: say so (`notes: ASSUMED ...`) and record the basis in `DESIGN.md`. Give heavy
   items their empty `weight` (t): the lifting rule needs a crane for 5 t and more. Where the P&ID
   states a size (capacity, cylinder or tube length, shell diameter) the two must agree
   (`cheme.equipment-dimension-mismatch`).
   **Placing equipment** (`layout/equipment-placement.yaml`):
   - one entry per equipment-list tag, spelled exactly as in the list (`cheme.layout-unknown-tag`
     otherwise); every listed item should get one (`layout-not-placed` is reported as info).
     An internal of another item (a condenser-reboiler in a column sump) has no placement of
     its own: accept its `layout-not-placed` finding in `checks/checks.yaml` with the reason,
     and skip its internal lines in `piping/routing.yaml`;
     Silencers, vent stacks' relief valves and other items of `piping/special-items.yaml` may be
     placed too, by their tag (they are not reported as not placed); they have no
     dimensions, so they take `size` in the placement;
   - `position` is the centre of the footprint and the **bottom** elevation: `[x, y, 0]` at
     grade; `rotation_deg` turns the item's own x (the axis of a horizontal drum or exchanger,
     a pump's shaft from suction to motor) away from east. On a building level give
     `mount: {building: B-1, level: GF}` and set `z` to that level's `elevation` (`layout-level`,
     0.05 m tolerance), keep the whole footprint inside the building and the item's height
     within the level's clear height;
   - a containment around tanks is an area of `kind: bund` in the site plan with its
     `wall_height` (inside the storage area); a building that has an overhead crane declares
     `crane: {capacity_t, rail_elevation?}` in `layout/building.yaml` (the model adds the
     runway, bridge and hook, and the roof, doors and louvres of a clad building);
   - `shape` only overrides what the dimensions give (`box`, `vertical_cylinder`,
     `horizontal_cylinder`, `sphere`); `size` is a stop-gap for an item without dimensions
     (`layout-size-from-placement`, info) and is ignored next to them (`layout-size-ignored`);
   - nozzles are taken from the P&ID with their DN and lines and put on the side the P&ID draws
     them on. Where that is wrong -- a nozzle that must face the rack, a manway at a platform --
     override it: `nozzles: [{id: N1, angle_deg: 90, elevation: 2.5}]` or
     `[{id: N2, face: top, offset: [0.5, 0]}]` (see `layout/README.md`). An override must name a
     nozzle of the P&ID (`layout-nozzle-unknown`).
3. **Avoiding clashes** (`cheme.layout-clash`): cheme-as-code compares each item's outline in
   plan (a circle for a vertical vessel or tank, else its rectangle turned with it) over its
   height, and the solid parts standing out of it (a tank's stair, a base plate, a plinth).
   Leave maintenance and access space - about 1 m around pumps, a
   tube-bundle pull length in front of a shell-and-tube exchanger - even though cheme-as-code only
   flags real intersections. Keep equipment off roads and out of buildings it is not placed
   in. Pumps may stand at grade **under** a pipe rack, the usual arrangement in a rack-type plot
   plan, as long as their top stays at least 0.5 m below the lowest tier; anything taller goes
   beside the rack. Put a pump close to its suction source (a tank or vessel it draws from):
   a long suction line costs NPSH, and for a reciprocating pump also brings pulsation.
   Buildings must not stand on roads or overlap each other, and a rack may cross a building
   only with its lowest tier above the building's top. `cheme layout build` writes the
   maintenance envelopes (bundle pull, motor removal, pump access) into `layout/plant-model.yaml`,
   where the viewer shows them: keep them free.
4. **Site plan**: give every area a road: trucks must reach loading areas, and the process
   area needs fire-fighting access, ideally from more than one side. Areas are `[x0, y0, x1, y1]` with x0 < x1, y0 < y1 and should not overlap
   (`layout-area-overlap`); split a plot into adjacent areas instead of nesting them. Everything
   stays inside `site.width` x `site.depth` (`layout-outside-site`).
5. **Racks and lines**: lines between areas, or longer than 30 m, need a rack route
   (`cheme.layout-line-route`): extend or add a rack so both ends are within `rack_reach`
   (default: the 30 m unsupported length) of it and the racks touch. Vent and relief lines count: place the silencers and
   relief valves (from `piping/special-items.yaml`) or give the line `to_area: <vent area>`.
   Use the `layout-line-length` estimates for line lengths, never guess them.
6. **Spacing criteria** (toppling radius, distances to tanks, roads, the boundary) go into
   `separations:` of `site-plan.yaml` (see `layout/README.md`), so validate measures them
   (`cheme.layout-separation`). Between equipment items the build also applies a package
   spacing table by family or DEXPI class (fired equipment 15 m, pumps 1 m, machines 3 m,
   columns 3 m, ..., every row ASSUMED: `cheme.layout-spacing`); a separation naming both
   items replaces the table for that pair, `criteria: {spacing_table: false}` switches it off.
   The other layout criteria of the rules (operator height, escape travel, heavy lift, crane
   reach) are overridden under the same `criteria:` key with the site standard's values. Model a cold box or fire wall as a building with its height,
   or a tagged box. Quote **measured** distances in `DESIGN.md`: `cheme show <tag> --layout`
   prints them; never write a distance you have not measured.
7. **Buildings** turn only in steps of 90 degrees, about their `origin` corner. Column grid
   offsets are along the building's own x and y and must lie within its width and depth.

7a. **What an item stands on** (`mount:`): at grade, nothing (`z = 0`); on a building level
   `mount: {building, level}`; on a steel frame of `layout/structures.yaml` `mount: {structure,
   level}` with `z` at the level's elevation (skill `structures-access` says when an item
   belongs on a structure). An item stacked on another (an LP column on its HP column) stands
   on it: its `z` is the other's top. An item raised on a concrete foundation block (a tank
   whose bottom outlet must stand above its pumps' suctions) takes `plinth: <height>` with
   `z` equal to it: the model draws the plinth and a tank's stair from grade. Every item above
   grade must be mounted, stacked or on a plinth (gate `layout-3d`, requirement `mounted`).
7b. **Nozzles** come from the P&ID side; override the ones that must face elsewhere
   (`nozzles:` of the placement, step 2). A piped nozzle placed `basis: default` (no drawn
   position: `cheme.layout-nozzle-defaulted`) needs an override before the basic gate
   (`nozzles`).
7c. **Access** (`access: {platforms: [{elevation, arc_deg?, width?}], ladder_side}` of a
   vertical item): without it `layout build` proposes platforms for nozzles and valves more
   than 2.5 m up (`review_needed`). Review each proposal (skill `structures-access`), then pin
   it (`cheme layout pin TAG/platform-1`) or declare your own.
7d. **Structures** (`layout/structures.yaml`: `origin`, `spans_x`/`spans_y`, `levels` deck or
   platform with `extent`, `bracing`, `stairs`, `ladders`, `enclosure` for a cold box casing or
   fire wall) and **zones** (`layout/zones.yaml`: keep-clear, laydown, maintenance, escape as
   explicit volumes; hazardous, oxygen-enriched and oxygen-deficient zones explicit or from
   `sources`, skill `area-classification`; `crane_pad` where a mobile crane stands, with its
   `reach_m`). Forbidden zones (keep clear, laydown, maintenance, escape, crane pad) are
   obstacles for the router. An enclosure takes `openings` like a building; the build lists the
   pipes through walls outside them as `penetrations` (`cheme layout pin OWNER/LINE`).
7e. **Pipe routes** (`piping/routing.yaml`): rules (rack tiers per fluid, battery limits, the
   pipe-way elevation, vent riser heights) and intent per line (`rack`, `tier`, `via`,
   `elevation`, `skip: reason`, pinned `route`): skill `pipe-routing`. `operators:` declares
   how a valve or transmitter out of reach is worked (chain wheel, extension spindle, remote
   operator, remote mount): skill `structures-access`.
7f. **Crane charts** (`layout/crane-chart.yaml`, kind `crane_chart`, optional): the load chart
   of a crane the project has chosen (radius against capacity, with its source), so
   `cheme layout lifting` checks each heavy lift's capacity; skill `structures-access`. Once
   the study is written (`--write`, commit it), `cheme validate` reports
   `layout-lifting-study-outdated` until it is rewritten after a rebuild. A
   machine train whose heaviest maintenance lift is one part (the motor that sets a building
   crane) gives it as `dimensions.lift_weight` in the equipment list (ASSUMED with its basis
   until the vendor's).

## Validation and failure handling

8. **The build loop.** After every change to the layout, the lists or a P&ID:
   1. `cheme validate`: fix every `cheme.layout-*` error first (a `yaml.schema` error
      names the line; `layout build` refuses while a layout file is invalid);
   2. `cheme layout build` writes `layout/plant-model.yaml`, the generated 3D model (never
      edit it: `layout-model-edited`); it prints the clash, headroom, access and nozzle
      findings. `--check` only says whether the committed model is current;
   3. `cheme layout report`: every line routed, skipped or unrouted with the reason, how
      and why it was routed (rack or local), the rack fill and the finding counts;
   4. look at it: `cheme layout render --plan --png`, `--level ID`, `--section x=..|y=..
      --png` (files in `build/`; read the PNGs), and `cheme serve` (**Layout 3D**), where
      clashing items show red and the findings are listed beside the model;
   5. fix the cause (move an item, change a nozzle, add a via, declare a zone) and go back to
      1. Move equipment before bending pipes around it.
   Commit the model with its inputs; `cheme validate` reports `layout-model-outdated` until
   it is rebuilt. The gates `layout-plot-plan` (concept), `layout-3d` (basic) and
   `layout-detail` (detail) of `checks/checks.yaml` say what each stage needs (`cheme
   check`).

## Outputs and provenance

The edited `layout/*.yaml` files and `dimensions` in the equipment list; the rebuilt
`layout/plant-model.yaml` (commit it with its inputs: `cheme validate` reports
`layout-model-outdated` until it is rebuilt); the layout basis, assumed dimensions and measured
distances go into `DESIGN.md`.

9. When a tag changes in the equipment list or on a P&ID, change it here too, in the same
   commit.

## Required human judgment

Maintenance and access space, pump positions, what stands on a structure, spacing criteria
and zone extents are design choices: cheme-as-code only flags real intersections and measures the
`separations:` you give it. A clean build is not a good layout: look at the plan and sections,
and have the layout reviewed (skill `review`, topic `layout`).

## References

- `layout/README.md`; `cheme schema site_plan`, `building`, `placement`, `structures`,
  `zones`, `routing`, `equipment`, `layout_model`
- skills `pipe-routing`, `structures-access`, `area-classification`, `review`
- `cheme show <tag> --layout`, `cheme serve` (**Layout 3D**)
