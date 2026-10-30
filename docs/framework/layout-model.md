# The generated 3D layout model

`cheme layout build` derives `layout/plant-model.yaml` (kind `layout_model`, schema
`cheme/layout_model/v1`) from what a plant repository already holds. `GET /api/layout`
serves it under `model`, so the viewer draws one engineered model instead of re-deriving
geometry. This page is the contract between core and the viewer. The JSON Schema is
`cheme schema layout_model` (pydantic, `domains/spatial/schemas.py`, `LayoutModelFile`).
`tests/data/api-layout-asu.json` is a frozen `/api/layout` of the ASU example (the
process-library repository, plant root `processes/asu-1`) to build against;
`scripts/build_layout_fixture.py <plant root>` regenerates it and `tests/test_layout_model.py`
checks it against the schema.

## Inputs and ownership

| input | what the model takes from it |
|---|---|
| `equipment/equipment-list.yaml` (equipment) | `type` (DEXPI class): the shape family and a machine's variant; `dimensions`: overall sizes, `orientation` and `variant` of a machine |
| `layout/equipment-placement.yaml` (spatial) | position, `rotation_deg`, `mount: {building\|structure, level}` or `plinth` (height of a concrete plinth), `nozzles` overrides, `shape` override, fallback `size` |
| `layout/site-plan.yaml`, `layout/building.yaml` (spatial) | site, areas, roads, racks (with generated bents and, where declared, `intermediate_supports`), buildings (with `walls`, `openings` and generated wall panels) |
| `layout/structures.yaml` (spatial, kind `structures`) | steel frames: members, gratings, handrails, bracing, stairs, ladders, enclosure walls; a valve access platform's `serves`; `pipe_supports` (posts and T-posts under pipes) |
| `layout/zones.yaml` (spatial geometry; safety classification, kind `zones`) | explicit zone volumes, and volumes around release points from the radius table |
| `pid/*.xml` (piping) | the nozzles of each placed item (`SubTagName`, DEXPI id, DN, lines and segments ending at it, the drawn side) and the piping network: segments, their ends (nozzles, tees, off-page connectors, components) and in-line items |
| `piping/line-list.yaml`, `piping/special-items.yaml` | DN, `pressure_class`, `insulation`, fluid; the ends of a line leaving the sheets (`from`/`to`, `from_area`/`to_area`) |
| `piping/pipe-specs.yaml` (piping, kind `pipe_specs`, optional) | pipe classes (`code`, `material`, `rating`, `colour`), insulation thickness by type and DN |
| `electrical/electrical-list.yaml` (control, kind `electrical`, optional), `electrical/tray-rules.yaml` (spatial, kind `trays`, optional), `control/instrument-list.yaml`, datasheets | rooms, motor list, junction boxes; tray rules; with them the model gets its cable trays and cables ([electrical.md](electrical.md)) |
| `layout/hvac.yaml` (spatial, kind `hvac`, optional) | air handling units, ventilated rooms (air changes, terminals), duct rules; with it the model gets its units, rooms, terminals and ducts (below) |
| `piping/routing.yaml` (spatial, kind `routing`, optional) | router rules (tiers by fluid or line prefix, `spacing_m`, headroom, `grid_m`, rack bent spacing, gravity fluids, `local_max_m`, `local_elevation_m`, `grade_max_m`, `rack_reach_m` (deprecated: `rack_reach` in the site plan), `rack_detour_factor`, `battery_limits`) and intent per line or segment (`rack`, `tier`, `via`, `elevation`, pinned `route`, `skip`, `gravity`, `buried` (below); a segment by DEXPI id, segment number or, where the line repeats the id on another sheet, `<sheet stem>/<DEXPI id>`); `operators` of valves and transmitters out of reach (below) |

Package data: `domains/piping/data/pipe-od.yaml` (OD by DN, ISO 4200 / ASME B36.10M, and
assumed insulation thicknesses by keyword), `domains/safety/data/release-radii.yaml` (indicative
zone radii by release point kind, release grade and substance class, every row ASSUMED with its
basis), `domains/spatial/data/duct-sizing.yaml` (air velocity limits per duct kind and for
louvres, standard duct sides, aspect ratio, terminal size, louvre free area; ASSUMED).

Code: `domains/spatial/shapes.py` (parametric families, pure geometry), `shape_details.py`
(machines and the level-2 detail of the other families, nozzle flanges, transmitters),
`pid_nozzles.py` (nozzles from a loaded DEXPI model), `pid_network.py` (piping segments),
`piping_detail.py` (valve bodies and operators, supports, jacketing),
`structures.py` (frames, walls, rack bents, platforms), `zones.py` (zone volumes), `trays.py`
(cable trays), `hvac.py` (HVAC units, terminals and ducts),
`routing.py` (the router), `geometry3d.py` (solids and distances), `access_rules.py` (headroom
over walking surfaces, standing space, landing width, egress, declared operators), `model.py`
(`build_model(workspace) -> Model`, `write_model`, `model_findings`), `model_rules.py` (rules
on the model), `drawing2d.py` (plans and sections), `pins.py`, `report.py`;
`domains/safety/area_classification.py`; `domains/piping/pipe_data.py`;
`interfaces/cli/layout.py` (the commands).

## Frame and units

Metres in the site frame: x east, y north, z up, origin at the site's south-west corner. Each
item has its own frame before `rotation_deg` (counterclockwise about z, seen from above): own x
is the axis of a horizontal drum or exchanger and a pump's shaft (suction end at -x, the
*front*; driver at +x, the *back*), z = 0 at the item's bottom. Every number is rounded to the
millimetre (3 decimals); a rebuild from the same inputs is byte-identical.

## Document

```yaml
schema: cheme/layout_model/v1
kind: layout_model
provenance:
  generator: cheme layout build
  generator_version: '2'
  generator_sha256: <hex>             # the generating modules (model.GENERATOR_MODULES)
  sources: {<path>: sha256:<hex>, ...} # each input file
  output_sha256: <hex>                # canonical JSON of everything but provenance
units: m
site: {id: site, refs, source, name, width, depth}
areas:      [{id, refs, source, title, box: [x0, y0, x1, y1], kind, wall_height?, parts?}]
roads:      [{id, refs, source, title, points: [[x, y], ...], width}]
racks:      [{id, refs, source, title, points, width, levels: [z, ...], parts: [Part],
              ladders: [Ladder]}]
buildings:  [{id, refs, source, title, origin, width, depth, rotation_deg, footprint,
              heights: [bottom, top], levels: [{id, title, elevation, height, clear_height,
              kind}], frame, walls, wall_material, openings, parts: [Part]}]
equipment:  [Equipment]
pipes:      [Pipe]       # one per routed DEXPI segment
structures: [Structure]  # steel frames (and proposed valve access platforms)
support_steel: [SupportSteel] # posts and T-posts under pipes (declared, proposed)
zones:      [Zone]
platforms:  [Platform]   # access platforms with their ladders (declared or proposed)
inline:     [Inline]     # valves and other components placed along the pipes
step_overs: [StepOver]   # proposed where a low pipe crosses a walkway
supports:   [Support]    # pipe shoes and guides on the steel
penetrations: [Penetration] # pipes through walls outside the declared openings
unrouted:   [{line, segment, segment_number?, sheet, reason}]
routing:    {segments, routed, unrouted, methods: {method: count},
             reasons: {reason: count}, battery_limits: {basis: count},
             rack_fill: [{rack, tier, used_m, width_m, fill}]}
# only with an electrical list (absent otherwise):
tray_tiers: [TrayTier]      # rack tray tiers on steel of their own
trays:      [Tray]          # cable trays
junction_boxes: [JunctionBox]
cables:     [Cable]         # the cable schedule
cabling:    {cables, power, instrument, motors, motors_skipped, instruments, junction_boxes,
             trays, tray_length_m, cable_length_m, rules: {separation_m, spacing_m,
             fill_max_power, fill_max_instrument, avoid_zones, support_span_m,
             support_reach_m}, missing: [{tag, kind, reason}]}
# only with layout/hvac.yaml (absent otherwise):
hvac_units: [HvacUnit]      # air handling units
hvac_rooms: [HvacRoom]      # ventilated rooms with their terminals
ducts:      [Duct]          # HVAC ducts
hvac:       {units, rooms, terminals, ducts, supply_m3h, extract_m3h, duct_length_m,
             duct_area_m2, louvres: [{building, opening, kind, flow_m3h, free_area_m2, units,
             velocity_m_s, velocity_max_m_s}], rules: {velocities: {kind: m/s},
             max_height_mm, max_aspect, terminal_max_m3h, spacing_m, louvre_free_area},
             missing: [{tag, kind, reason, level}]}
```

Every object has `id`, `refs` (any of `tag`, `dexpi`, `sheet`, `file`, `lines`, `segments`) and
`source`: `declared` (stated in an input file), `generated` (derived) or `pinned` (a generated
object copied into an input file to keep it; later steps).

**Equipment** `{id (the tag), refs, source: declared, tag, type, family, shape, size_from,
dimensions, position, rotation_deg, mount, plinth?, bbox, parts, nozzles, envelopes}`
(`plinth`: the height of a declared concrete plinth, placement `plinth:`; the item's bottom is
on it, the model draws it as a solid 0.1 m wider than the footprint and a tank's stair from
grade):

- `family`: `vessel`, `column`, `tank`, `horizontal_vessel`, `shell_tube`, `plate_exchanger`,
  `air_cooler`, `pump`, `compressor`, `turbine`, `filter`, `silencer`, `stack`, `generic`. A
  machine is drawn as a variant: a pump `end_suction` (default), `vertical_inline` (with
  `dimensions.orientation: vertical`) or `cryogenic`; a compressor `integrally_geared`
  (default), `blower` (DEXPI `Blower`, `...Fan`) or `machine` (axial, reciprocating, rotary:
  the plain casing and motor); a turbine `compander` (default), `expander` or `machine` (steam,
  gas). `dimensions.variant` overrides the choice. Items at grade (no `mount`, bottom at 0)
  stand on concrete: a machine on a plinth inside its envelope, the others on a foundation
  (detail) under their supports;
- `shape`: `box`, `vertical_cylinder`, `horizontal_cylinder`, `sphere` (what `bbox` and the
  layout rules use); `size_from`: `list`, `placement` or `default` (assumed family size);
- `dimensions`: the sizes used (`diameter`, `height`, `length`, `width`, `head`, `support`),
  and the equipment list's `weight` (t) where it gives one (the lifting rule uses it);
- `bbox`: `[x0, y0, z0, x1, y1, z1]` after rotation.

**Part** `{id: <tag>/<part>, refs, source: generated, kind, material, ...}`, site frame:

| kind | fields |
|---|---|
| `cylinder` | `start`, `end` (axis end points), `radius` |
| `cone` | `start`, `end`, `radius` (at start), `radius_end` |
| `cap` | half ellipsoid of revolution: `centre` (of its base), `axis` (unit, outward), `radius`, `depth` (`depth = radius`: hemisphere) |
| `box` | `centre`, `size` [dx, dy, dz] in the item's frame, `rotation_deg` about z |
| `sphere` | `centre`, `radius` |
| `member` | a steel section from `start` to `end`: `profile` [b, h] (m), `section` (e.g. `HEB300`); a horizontal member has its web vertical (h up), a column its flanges along the frame's x |
| `annulus` | a ring or ring sector (a platform): `centre` = centre of its **top** face, `radius` (inner), `radius_end` (outer), `depth` (thickness, downward from `centre`), `arc_deg` [from, to] ccw from east in the site frame (absent: all round; `to` < `from` wraps through east) |
| `torus` | a ring of round section (a volute, a fan ring, an elbow): `centre`, `axis` (unit, normal to its plane), `radius` (to the tube's centre line), `tube` (the tube's radius); a sector when `arc_deg` [from, to] is given: from the unit `ref` (perpendicular to `axis`), counterclockwise about `axis` (right hand) |
| `frustum` | an upright rectangular frustum (a fan plenum, a hipped roof): `centre` of its **bottom** face, `size` [dx, dy, height] (bottom face and height), `size_end` [dx, dy] of the top face, `rotation_deg` about z |

`material` is a rendering hint: `shell`, `steel`, `casing`, `motor`, `plates`, `fan`, `grating`,
`handrail`, `cage` (a ladder cage: draw as wire), `cladding`, `fire_wall`, `concrete`
(plinths, foundations, ring walls, bund walls), `guard` (coupling guards: safety yellow),
`flange` (flanges, blind covers), `insulation` (an insulated cold end), `opening` (a dark
hole: a skirt's access opening), `instrument` (transmitter heads), `ahu` (an air handling
unit's casing), `duct_supply`, `duct_extract`, `duct_outdoor`, `duct_exhaust` (ducts by
system), `grille_supply`, `grille_extract` (terminals).

**Level of detail.** Every part may carry `lod`:

| `lod` | drawn | a solid for clash checks and the router |
|---|---|---|
| absent | at every distance | yes |
| `1` | from afar only (the envelope: a few cylinders and boxes) | yes |
| `2` | close up only (detail) | no |

The detail of an item stays within (or, for foundations and nozzle flanges, just outside) its
envelope, so the rules on the model see the same item whatever detail it has. What stands well
outside the item's box and people or pipes must keep clear of is a part in its own right (`lod`
absent, like a structure's stair): a tank's spiral stair (`stair-tread-<k>`, `stair-landing`,
`stair-stringer-in|out-<k>`, `stair-handrail-<k>`; up to about 1 m outside the shell) or caged
ladder (`ladder-rail-<n>`, `ladder-cage`), and a column's top-head davit (`davit-post`,
`davit-arm`, about 1.8 m above the head, on the side free of nozzles with its arm stowed along
the shell edge). The router routes around them and the clash checks see them. A
viewer shows `lod` absent + `1` from afar and absent + `2` close up; the 2D drawings draw the
envelope plus the detail that shows in a plan (gratings and stair treads, handrails, flanges).
Detail parts of equipment (ids `<tag>/<part>`): pumps and machines (volutes, flanges, bearing
housing, coupling, motor frame, ribs, fan cowl, feet, drip rim, intercoolers, lube oil
console), vessels and columns (base ring, anchor chairs, skirt opening, lifting lugs,
stiffening rings, `manway-<k>-neck|flange|davit-post|davit-arm`), exchangers (body
flanges, tie bolts, plenums, fan rings and blades), tanks (ring wall, anchor chairs,
the stair's `stair-midrail-<k>` and `stair-post-<k>`, roof handrail ring, mid rail, toe
plate, roof platform), foundations; nozzles (`<tag>/<nozzle>/neck|flange`) and instrument
tappings (`<tag>/<nozzle>/impulse-1|impulse-2|transmitter|transmitter-cap|stand|stand-base|bracket`).

**Nozzle** `{id: <tag>/<name>, refs: {tag, dexpi, sheet, lines, segments}, source, name, dn,
point, direction, base?, basis, side}`: `point` is where the pipe connects, the face of the
nozzle's flange; `base` where its neck leaves the shell (absent when the point is a machine's
own flange or the flange sits on a machine's envelope with its neck reaching back into the
body); `direction` the outward unit vector, `dn` from the DEXPI node (an instrument tapping
without one: DN 25); `operator?` a declared remote mount of its transmitter (see Inline). The neck stands out of the shell by about 150 mm + OD/2 (at most 400 mm);
the flange is about EN 1092-1 PN 16 (ASSUMED). A machine's own round flange (a pump's
`suction-flange`, `discharge-flange`, a stage's `stage-<k>-inlet|outlet-flange`) is sized the
same way from the DN of the nozzle on it, so one DN gives one flange and the pipe never hides
it. An unconnected tapping without a DN (an
instrument connection) gets a transmitter on a stand (at 1.2 m above the item's base, or on a
bracket at the tapping when that is more than 3 m up). `basis`:

- `pid`: placed from the side of the symbol the P&ID draws it on (`side`: `top`, `bottom`,
  `left`, `right`): top and bottom go to the heads (vertical items; on a flat bottom standing
  on its foundation, the shell just above it) or the top and bottom of
  the shell along the axis (horizontal items), left and right to the shell at the drawn height
  (vertical) or the axis ends (horizontal); a machine's left nozzles go on its inlet flanges
  (a pump's axial suction, a compressor's first stage inlet, then the next), its right or top
  nozzles on its outlet flanges (a pump's top discharge, a compressor's last stage outlet,
  then the others), a bottom nozzle on its casing drain. Nozzles drawn at the same spot are
  spread;
- `default`: no drawn position (typically an instrument tapping): spread over the shell;
- `override`: from the placement's `nozzles:` (`source: declared`).

**Envelope** `{id: <tag>/<kind>, refs, source: generated, kind, centre, size, rotation_deg}`: a
box to keep free. `bundle_pull` (in front of a shell-and-tube exchanger's channel, as long as
the DEXPI `TubeLength` or 85 % of the exchanger), `motor_removal` (behind a pump's or
machine's driver), `access` (1 m around a pump).

**Area** of `kind: bund` (a containment inside a storage area): `wall_height` (from the site
plan, default 1 m, ASSUMED) and `parts`: four `box` walls `<area>/wall-<side>` of material
`concrete`, 0.3 m thick, along the inside of its box. The router treats them as obstacles that
pipes pass over; `-clash-pipe-steel` reports a pipe through one.

**Rack** `ladders`: caged ladders from grade to the top tier just beyond an end bent (ids
`<rack>/<ladder id>`, `end: start|end`): the rack's declared `ladders` (`[{id, end}]` in the
site plan; `[]`: none), else one proposed at each end that is no joint with another rack
(`<rack>/ladder-start|end`, `source: generated`, `review_needed`, `reason`).

**Rack** `parts`: a bent every `rack_bent_spacing_m` (default 6 m, ASSUMED), or the rack's own
`bent_spacing_m` (site plan, kept on the rack; evenly along it, so a rack crossing a road can
span it with no bent in it): two `member`
columns just outside the rack width (ids `<rack>/bent-<k>/col-<0|1>`) up to the top tier and a
`member` beam per tier (`<rack>/bent-<k>/beam-<z>`), top of steel at the tier elevation. A
rack's end bent that would stand inside another rack (a branch rack's first bent at its joint,
both end bents at a corner) is left out: the other rack carries the joint; a bent along the
rack where a branch joins it stays. A rack's `intermediate_supports` (`{spacing_m: 3, levels?,
section?}` in the site plan, kept on the rack; absent: none, ASSUMED default off) adds steel
between the bents on its tiers (`levels`, default all): a `member` stringer along each edge
(`<rack>/bay-<k>/stringer-<z>-<0|1>-<n>`, where the columns stand) and a `member` beam across
every `spacing_m` (`<rack>/bay-<k>/mid-<j>/beam-<z>`), top of steel at the tier; the pipes rest
on them as on the bents' beams (shoes, shorter spans), and risers keep off them. Where
another rack joins with a tier at or up to 1 m below one of these tiers (`JOINT_DROP`), that
tier's stringer pieces and beams through the other rack's strip are left out: the branch's
lanes cross there.

**Building** `parts`: `box` wall panels (`<building>/wall-<side>-<k>`, material
`wall_material`) on the clad sides (`walls: all | none | [north, south, east, west]`, own
frame), cut around the `openings` (`{id?, side, offset, width, height, sill, kind}`). A clad
building also has a `box` roof slab `<building>/roof` (0.2 m on top, material `roof`) with a
low ridge `roof-ridge` (`frustum`, detail), and as detail in its openings (ids
`<building>/<opening id or opening-k>/...`): a door `leaf`, a roller door's `shutter` and
`drum` (material `door`), a window's `glass` (`glass`), louvre `blade-<k>` every 0.15 m
(`louvre`). `crane` (`{capacity_t, rail_elevation?, notes}` from `layout/building.yaml`, kept
on the building) adds an overhead crane: two `member` runway girders `crane/runway-1|2` along
the longer side, 0.5 m inside the walls, top of rail 1.5 m below the roof (or at
`rail_elevation`; HEB600 above 20 t, else HEB400, ASSUMED), and as detail the `crane/bridge`
across them, `end-carriage-1|2`, the `crab`, `rope` and `hook-block` (material `crane`).
`use` (optional, from `layout/building.yaml`: control, substation, office, process,
compressor, ...) is the key of the building spacing table.

A declared steel section (a structure's `column_section` and `beam_section`, a rack's
`intermediate_supports.section`, a pipe support's `section`) names a section of the material
take-off's `steel-sections.yaml` (HEB 100 to 1000, HEA, IPE and UPN or `C` of EN 10365, equal
angles `L100x10`, square hollow sections `RHS50x50`, flat bars `FL100x10`), blanks and case
ignored (`HEB 300`); its members take that section's real b x h. Any other name is a schema error (`yaml.schema`), not a guessed size.

**Structure** `{id, refs, source: declared, title, origin, rotation_deg, width, depth,
footprint, height, grid_x, grid_y, levels: [{id, title, elevation, kind: deck|platform,
extent?, use, source?, review_needed?, reason?, serves?}], sections: {column, beam, brace,
assumed: true}, parts, stairs, ladders, walls}`. A level's `extent` may reach up to 3 m outside
the frame (a cantilevered platform, e.g. outside a casing wall):

- `parts`: `member` columns (`<id>/col-<i>-<j>`, at every grid point up to the top level),
  beams per level (`<id>/<level>/beam-x<k>|beam-y<k>`, only over a platform's `extent`), bracing
  (`<id>/brace-<side>-<storey>-<bay>a|b`, `x` or `k`), handrails (`<id>/<level>/handrail-<k>`,
  1.1 m above the level, `handrail-<k>-<j>` for the pieces of an edge left open where a
  stair's landing or a ladder's head arrives or another level of the floor joins; as detail,
  `lod: 2`: a mid rail `-mid` at 0.55 m, a toe plate `-toe` and posts `-post-<k>` at most 1.8 m
  apart), and a `box` grating per level
  (`<id>/<level>/grating`, 30 mm, top at the elevation). Section sizes are defaults by span
  (HEB200 .. HEB500, L100x10 bracing), ASSUMED. `levels[].use`: `regular` (a deck's default)
  or `occasional` (a platform's);
- `stairs`: `[{id, refs, source, from, to, side, offset, width, flights, out?, box: [x0, y0,
  z0, x1, y1, z1], parts, review_needed?, reason?}]`: switchback flights (at most 3 m rise
  each, risers at most 0.19 m, going g + 2h = 0.63 m: ISO 14122-3, ASSUMED) outside the
  side, `member` stringers, `box` treads
  (`<stair>/flight-<k>/tread-<n>`) and landings (`<stair>/landing-base` at the foot,
  `<stair>/landing-<k>` at the top of flight k: the last one is where it meets the level),
  and as detail handrails, mid rails and posts on both sides of each flight. `out` (absent at
  0): how far the stair's inner edge stands out from the side, declared, else the enclosure
  wall's thickness on a walled side (a stair stands outside the wall);
- `ladders`: `[{id, refs, source, base, top, cage, parts, from, to, at, facing, review_needed?,
  reason?}]`: `member` rails to 1.1 m above the top, a `cylinder` part of material `cage` above
  2.3 m when the rise exceeds 3 m; a climb over 10 m in staggered flights of at most 6 m
  (`flight-<k>/rail-<n>`, `flight-<k>/cage`) with rest landings (`rest-<k>`, a grating box)
  between them (ISO 14122-4, ASSUMED);
- **access proposals** (`source: generated`, `review_needed: true`, `reason` says why): a stair
  `<id>/stair-to-<level>` for a level at 6 m or higher, or in regular use, that has no
  connected stair down (a stair is connected when its top landing is within 0.3 m in plan of
  the level's grating and its foot landing on the floor below, or grade): stacked on the
  frame's declared stair where that reaches the level, else on a side the level's extent
  reaches, from the highest floor below its foot lands on; a caged ladder
  `<id>/ladder-to-<level>` at the corner of its extent farthest from its other ways down while
  a floor has fewer than two connected ways (a ladder's top within 0.8 m of the floor), from
  the highest floor below under it. Levels at one elevation within 0.3 m of each other are one
  floor, unless a casing wall is between them. In a structure closed by a casing (enclosure
  walls on every side, no fire wall), a level below the casing height whose extent lies in the
  frame is inside the casing: it gets no stairs or ladders, but a **platform outside the
  casing** `<level>-out` (a level with `source: generated`, `serves: <level>`, 1.5 m wide
  along the side the level runs longest on, outside the wall, ASSUMED), and the casing roof's
  floor a landing `<roof level>-out` on that side joining it across the wall's top; the
  proposed stairs and ladders reach those. `cheme layout pin <id>` declares a proposal in
  `layout/structures.yaml` (a platform first, then the stairs and ladders that reach it;
  ASSUMED rules: check them against the site's standard);
- `walls`: `box` parts of the enclosure (`<id>/wall-<side>`), material from the file; a side
  with declared `enclosure.openings` (`{id?, side, offset, width, height, sill, kind}`, as a
  building's, `sill` above grade; `kind: hatch` is an access opening an item inside the casing
  is worked through) is cut around them into `<id>/wall-<side>-<k>`;
- `openings`: the enclosure's declared openings as written (absent without any);
- **valve access platforms** (proposed: `source: generated`, `review_needed`, `reason`;
  `serves`: the in-line item ids of the valves): a structure `VP-<valve tag>` of one bay with one
  platform level `P1` (`use: occasional`), built for the manual valves whose handwheel or lever
  no walking level reaches (`-operability`) and that have no declared operator, outside the
  casings. Valves along one pipe direction (or on vertical pipes) whose handwheels lie within
  `valve_platform_group_m` (3 m) of one another in plan, and within
  `valve_platform_operating_m` (1.2 m) in height, share one: beside the pipes (their
  insulation plus 0.1 m off; for a vertical pipe in front of the handwheel), 1 m past the
  outer handwheels, `valve_platform_depth_m` (1.2 m) wide, its floor 1.2 m below the highest
  handwheel; a caged ladder on its far edge at the end away from the valves, or from 6 m the
  stair the access proposals give it (all ASSUMED criteria; a stair of an odd number of
  flights on a platform shorter than its run starts back by one run and a landing, so its top
  landing meets the platform). The id is the first valve it serves in sorted order
  (`VP-<tag>`, other characters than letters, digits, `-`, `_`, `.` as `_`; `-2`, `-3` when a
  declared structure has it already), so it is the same from build to build and never passes
  to another platform (the earlier `VP-<n>` numbering filled gaps left by pinned ones). The `reason` names what stands in its volume (items, pipes, steel, racks), and
  what its corner columns would meet from grade up to the floor (`its columns from grade stand
  in: ...`, the served valve's own pipe included); of the two sides of a pipe the one with the
  fewer is proposed. A declared structure with `serves` needs one way
  down while its far end is within `dead_end_m` of it. The rules on the model leave proposed
  structures out (no floor, steel or way down) until they are pinned; `cheme layout pin
  VP-<tag>` declares it in `layout/structures.yaml` with its ladder or stair and pins the routes
  of the pipes its valves sit on. The take-off counts it once pinned.

**Support** `{id: <pipe id>/support-<k>, refs: {lines, segments}, source: generated, kind:
shoe|guide, pipe, on (the member's part id), point (on the member's top under the pipe),
parts}`: where a horizontal pipe crosses a horizontal steel member (a rack beam, a structure
beam) with its bottom at most 0.15 m above the top of steel (plus its insulation): a `shoe`
box, and on every third support of a pipe on a rack a `guide` (the shoe and two stops on the
beam). Detail parts only.

**SupportSteel** `{id, refs, source: declared|generated, kind: t_post|post|stub, at: [x, y],
top (top of steel), base (its foot: 0 at grade), width, rotation_deg, serves?, review_needed?,
reason?, parts}`: support steel under a pipe where no frame or rack carries it. Declared in
`layout/structures.yaml` as `pipe_supports: [{id, kind, at, top, from: grade|steel, base?,
width (t_post crossbar, default 1 m), rotation_deg (of the crossbar, ccw from east), section?,
serves?, notes}]` (`from: steel` stands on `base`, else on the highest horizontal member under
it, else grade). Parts: a `member` column `<id>/column` (HEB200, ASSUMED) up to the crossbar
`<id>/crossbar` (a t_post) or a 0.3 m cap `<id>/cap` (a post or stub), top of steel at `top`,
and at grade a concrete footing `<id>/footing` (detail). A declared crossbar or cap carries
shoes like a beam (`supports`), so the span rules count it, and the clash rules see it; the
router does not route around support steel. **Proposed** (`source: generated`,
`review_needed`, ids `<pipe>/SP-<arc>` with the arc the post's nominal place along the pipe in
m to 0.1 m, the same from build to build while the route stays; a declared id is never
proposed again): where a level run that is not on a rack tier spans
farther between its supports (or from them to its ends) than its DN's span, posts at even
spacing under it, top of steel a 0.1 m shoe below the pipe's insulation, a `stub` on the
highest member under it when that is at most `support_stub_max_m` (1.5 m, ASSUMED) below and is
not the support steel of another line, else a `t_post` from grade, crossbar across the pipe;
`reason` gives the span. A post keeps `support_pipe_clearance_m` (0.1 m, ASSUMED) from every pipe it does not carry
(its column and crossbar, insulation included; a pipe resting on the crossbar's top is carried):
it moves along its pipe by up to 1.5 m within its span to the first clear place (`reason`:
`moved ... m`), else it stays and `reason` names the pipe (`place it by hand`; the findings
then do not offer it for `cheme layout pin`). Proposals carry no shoes (the `-free-span` and `-support-missing` findings name them),
nor count in the take-off ([mto.md](mto.md)), until `cheme layout pin <pipe>/SP-<arc>` declares them in `pipe_supports`.

**Migrating pinned ids.** Pinned support steel and valve access platforms keep the id they were
pinned with: `<pipe>/post-<k>` and `VP-<n>` in `layout/structures.yaml` stay valid declared ids
and nothing needs renaming. Only the proposals of the next build carry the new ids, so a
`cheme layout pin` of an old proposal id written down before the upgrade is refused (no such
proposal): look up the new id in the build's findings or `support_steel` / `structures`.

**Penetration** `{id: <owner>/<line>[-<n>], refs: {lines, segments}, source: generated, owner,
wall (the panel's part id), pipe, point (where the axis meets the wall), material, end_inside,
length, opening: {side, offset, width, height, sill, kind: opening}, review_needed: true,
reason}`: where a pipe passes a building's wall panel or a structure's enclosure wall (both
already cut around the declared openings), or a building's roof slab (`wall: <building>/roof`,
`side: roof`, where the pipe's axis meets the slab), one per run of consecutive pipe runs
meeting one side (`length`: how far the axis runs in the wall's or roof's plane). `opening` is
the opening that would take it, in the owner's frame (`offset` from the side's left end seen
from outside, `sill` above grade; on `side: roof` the owner's plan frame: `offset` and `width`
along its own x from its origin corner, `sill` and `height` along its own y): the pipe's OD with
its insulation plus 0.05 m all round (ASSUMED), rounded out to 0.05 m. `end_inside`: the pipe
has an end inside the owner (a penetration), else it passes through. `cheme layout pin <id>`
declares a wall opening; a roof opening cannot be declared (the pin refuses it): route the
line in through a wall. From
`domains/spatial/penetrations.py`; no parts (a viewer may draw a sleeve at `point`).

**StepOver** `{id: step-over-<n>, refs: {lines, segments, sheet?}, source: generated, pipe,
walkway, point, height, box, review_needed: true, parts}`: where a horizontal pipe whose top is
at most 0.75 m (ASSUMED) above a walkway (an `escape` zone's box, a structure's grating)
crosses it, at the middle of the crossing: a grating deck (`<id>/deck`) `height` above the
floor over the pipe, treads on both sides and handrails (detail). They follow the route (not
pinned): a rebuild moves them with the pipe.

**Platform** `{id: <tag>/platform-<n>, refs, source, tag, kind: circular|rectangular,
elevation (floor, m above grade), item_elevation (above the item's bottom), width, arc_deg?,
review_needed?, serves?, parts, ladder}`: `circular` around a vertical cylinder (`annulus`
grating and handrail parts), `rectangular` around a box (four `box` gratings). `ladder` is a
Ladder (above) from the platform below (or the item's base). `source: declared` from the
placement's `access:`; `generated` proposals have `review_needed: true` and `serves` (the
nozzle and valve ids more than 2.5 m above the item's base the platform reaches). Detail
(`lod: 2`): a circular platform's mid rail and toe plate (`annulus`) and posts; a rectangular
one has guard rails (`<pid>/handrail-<k>` with mid rail, toe plate and posts). A declared
`access: {platforms: [], notes}` means the item has no platforms of its own (a column inside a
cold box, reached from the structure's platforms): nothing is proposed.

**Pipe** `{id: <sheet stem>/<segment id>, refs: {lines, segments, sheet}, source:
generated|pinned, line, segment (DEXPI id), segment_number?, dn, od (m), insulation_mm, class?:
{code, material?, colour?}, fluid?, points: [[x, y, z], ...] (axis polyline, orthogonal except
pinned and rack runs along a skewed rack), length, method, racks?, tier?, open_ends?:
[start|end], ends?: [{kind, ref?}, {kind, ref?}], review_needed?, reason?, jacket?, buried?:
{cover_m?, basis?}}`. `ends`
(absent in older models) says what the start and the end connect to: `nozzle` (`ref`: its id),
`junction` (a tee, an off-page connector pair or a component two segments share; `ref`: the
router's key, `<sheet>:<tee id>` or `opc:<line>:<k>`), `open` (a vent or relief outlet),
`item` (a placed component; `ref`: its tag), `battery_limit`, `line` (`ref`: the line it
ends on). `jacket` (rendering hint) is the cladding of
an insulated pipe from the line list's insulation text: `cold` (cold, cryogenic, vacuum
jacketed, PUR, ...: vapour-tight cladding), `personnel` (personnel protection) or `hot`.
`buried` (absent: above grade) is the line's or segment's `buried` of `piping/routing.yaml`:
the runs whose top (axis plus OD / 2 and insulation) is at or below grade (z = 0) are in the
ground (see the rules below and the take-off's `buried` rows); its runs above grade (the risers
at the users) are pipes like any other. `method`: `astar`, `astar_coarse`, `astar_fine` (a
leg found only on the half grid with the larger search), `rack` (or `rack+...` when a
leg fell back), `via`, `open` (a vent or relief end: a riser of 1 m above the stub), `direct`
(over the obstacles at a clear elevation, `review_needed`), `pinned`. An `open` riser is
`vent_rise_m` (default 1 m) high, or what a `vents` rule of `routing.yaml` makes it (see the
router). Pipes of one chain (through
tees, off-page connector pairs, shared components) meet exactly at their end points; a branch
starts on its run's polyline. `reason` (added in step 3, absent in older models) says why the
router took that way, one of `rack: battery limit at a rack end | intent | across areas |
crosses a road | crosses another area | longer than local_max_m`, `local: pipe-way | short run |
pump run at grade | above the pipe-way | no rack in reach | rack run too short | rack detour too
long`, `open end`,
`intent: via | elevation`, `pinned` (the viewer may show it; it must not depend on the
wording). `routing.reasons` counts the chains per reason (as `methods` per method);
`routing.battery_limits` counts the battery limit ends by `battery limit rule`, `area`, `rack
end` or `site edge`; `rack_fill.used_m` is the most crowded cross-section along the rack.

**Inline** `{id: <sheet stem>/<DEXPI id>, refs: {dexpi, sheet, lines, segments, tag?}, source:
generated, kind (valve, check_valve, safety_valve, reducer, silencer, filter, instrument, item),
dexpi_class, tag?, point, direction (unit, along the pipe), line, segment, pipe, parts?,
operator?}`. `operator` (`{kind, use?, via?, length_m?, basis?}`) is the operator declared for
it in `piping/routing.yaml` `operators:` (by its tag or id): `chainwheel`, `extension_spindle`,
`remote_operator` or, for an instrument, `remote_mount`; a nozzle carries a transmitter's
`operator` the same way (`TAG/NOZZLE`). The rules check it (below); the model draws no
chain or spindle.
`parts` (detail, `lod: 2`, ids `<inline id>/<part>`, from `domains/spatial/piping_detail.py`):
a valve's `flange-1|2` and `body` (sphere for ball, globe and safety valves, a wafer for a
butterfly valve, a cylinder otherwise) and its operator on a stem up (vertical on a horizontal
pipe, else across it): `stem` + `lever` (quarter-turn up to DN 150), `gearbox` + `handwheel`
(quarter-turn above), `handwheel` (`torus`) + `spoke-1|2` (gate, globe), `yoke` +
`actuator-lower|upper` (a control valve: `Control` in its class), `actuator` + `motor`
(`Motor`/`Operated`); a check valve's `cover`; a safety valve's `bonnet`, `cap`, `outlet`,
`outlet-flange`; an in-line instrument's transmitter on its stand. Materials `valve`,
`flange`, `handwheel`, `actuator`, `steel`, `motor`, `instrument`. Ids are
unique: a component two segments share (a valve between them, a safety valve with its outlet
segment) is one item, placed on the first segment routed (`segment`, `pipe`), with every
segment and line in `refs.segments` and `refs.lines`. A placed silencer or safety valve a line
ends at sits at that end of its pipe.

**Zone** `{id, refs, source: declared, title, kind, zone?, basis?, volumes: [{shape:
box|cylinder|sphere, source: declared|generated, box? | centre + radius (+ height), zone?,
item?, source_kind?, release_grade?, substance_class?, basis?, status?}]}`. A cylinder's
`centre` is the centre of its base. Generated volumes come from the radius table (`status:
ASSUMED`, `basis` the row's text). A `crane_pad` zone (where a mobile crane stands; kept clear
by the router like a laydown zone) may give `reach_m`, the crane's working radius.

**Tray** `{id, refs: {file, tag?}, source: generated, system: power|instrument, kind:
trunk|room|link|branch, points (the tray's bottom centreline, orthogonal off the racks), drop_to?
(a branch ending at its motor's `cable_entry`: the terminal box the cable drops to), width,
depth (m), length, cables (tags), fill, fill_max, rack?, method?, review_needed?, parts}`:
`parts` one `box` per straight run (`<id>/run-<k>`, material `tray_power` or `tray_instrument`;
a horizontal run's box stands on the centreline, `size` [length, width, depth] turned by
`rotation_deg`; a vertical run's box is centred on it, `size` [width, depth, length]). ids
`PT-...` power, `IT-...` instrument; a branch's `refs.tag` is the item it feeds.

**TrayTier** `{id: <rack>/tray-tier, refs, source: generated, rack, elevation, parts}`: `member`
column extensions (`<rack>/tray-tier/bent-<k>/col-0|1`) from the top pipe tier and a beam
(`.../beam`, top of steel at `elevation`) at each bent along the trunks' span.

**JunctionBox** `{id (its tag), refs, source: declared|generated, tag, point (centre), area?,
instruments, room?, review_needed?, parts}`: a `box` (`<tag>/box`, 0.6 x 0.25 x 0.8 m,
material `junction_box`) on a `stand` (detail).

**Cable** `{id (its tag), refs: {tag, file}, source: generated, tag, system, kind:
motor|feeder|field|multipair, from, to, from_point, to_point, size, od_mm, count, voltage_v?,
power_kw?, current_a?, pairs?, trays (in order from its room), route_length, length, basis?,
review_needed?, reason?}`. Tags: `C-<motor or feeder>`, `IC-<instrument>` (to its junction box,
no trays), `MC-<junction box>` (from the control room). How the ends, sizes, trays and lengths
come about: [electrical.md](electrical.md).

**HvacUnit** `{id, refs: {tag, file}, source: declared, title, building, level?, position
(centre of its base), size [length, width, height], rotation_deg, capacity_m3h?, supply_m3h,
extract_m3h (of the rooms it serves), intake?, exhaust? (opening ids of its building), ports:
{outdoor, exhaust, return, supply} (top of each port), parts}`: a `box` casing (`<id>/casing`,
material `ahu`, its length along x at `rotation_deg` 0) and as detail a base frame
(`<id>/base`) and the casing's section joints (`<id>/joint-1..3`). The ports stand on its top
along its length at -3/8, -1/8, +1/8, +3/8 of it.

**HvacRoom** `{id, refs: {file}, source: declared, title, building, level?, unit, extent [x0,
y0, x1, y1], floor, height, volume_m3, air_changes_per_h, supply_m3h, extract_m3h, basis?,
terminals: [{id: <room>/<supply|extract>-<k>, system: supply|extract, point (on its header's
centreline), flow_m3h, source: declared|generated, parts}]}`: a terminal's part is a grille
(`<terminal id>/grille`, `box` 0.6 x 0.6 x 0.1 m under the header, material
`grille_supply|grille_extract`, detail). `air_changes_per_h` is computed from `flow_m3h` where
the room gives that.

**Duct** `{id, refs: {tag (the unit), file}, source: generated, system:
supply|extract|outdoor|exhaust, kind: main|header|intake|exhaust, unit, room?, serves?
(the rooms whose air it carries), points (centreline, orthogonal), width (across, horizontal),
height (m), flow_m3h, velocity_m_s, velocity_max_m_s (of its kind), length, method?,
review_needed?, reason?, parts}`: one piece of constant air flow; `parts` one `box` per
straight run centred on the centreline (`<id>/run-<k>`, material `duct_<system>`; a level
run's `size` [length, width, height] turned by `rotation_deg`, a vertical run's [width,
height, length]). Ids: `SA-<room>-<row>-<k>` (supply mains, cut where another main tees off),
`SA-<room>-<row>-H<k>` (supply headers between terminals), `EA-...` (extract), `OA-<unit>`
(intake: from the louvre's inner face to the outdoor air port), `XA-<unit>` (exhaust: from the
exhaust port to its opening). A main starts at its unit's port (the riser straight up) or on
another main of its system (a tee). How the terminals, trees and sizes come about: the module
text of `domains/spatial/hvac.py` and the skill `hvac-ducts`. Routing and clash checks use a
round envelope as wide as the duct's larger side (LOD 1).

## The router (C2)

See `domains/spatial/routing.py`. In short: segments are chained through off-page connector
pairs (by line number, across sheets), components two segments share and each tee's run; tee
branches start from the run's route. A pinned segment ends its chain: where it is one of a tee's
run segments, the other run segment and the branch both start at its pinned end. Chains go by largest DN, then id. A nozzle end leaves along
its direction for 2 x OD (at least 0.3 m) and every connected nozzle's stub is kept free for its
own pipe; a stub ending under or inside its own item (a bottom nozzle under a horizontal drum
or in a skirt) continues sideways out of the item's outline. Every leg is an orthogonal A*
route on a `grid_m` grid (bend cost 1 m; obstacles grown by the pipe radius, `spacing_m` and half
a grid step; within a bubble around each end the fixed obstacles only block where the pipe
itself would cut them and the pipes by `spacing_m`, each move there checked as a whole, and the
run a branch leaves does not block), retried on a grid twice as coarse and on a half grid with a
larger search; the last run onto the end is moved onto the end's exact position where that keeps
the spacing (another arrival is tried where it does not). Only a leg none of these finds becomes
a `direct` route. Rack beams, columns, structure members and stairs are obstacles; enclosure
walls (a cold box casing, a fire wall) and building walls are obstacles for a line passing by
and passable for a line with an end inside (its penetration).

A chain goes over the racks when an end is a battery limit at a rack end, the line asks for a
`rack` or `tier`, its ends are in different areas, the straight line between them crosses a road
or another area, or they are more than `local_max_m` (default 15 m) apart (for the length alone
only while the rack route is at most `rack_detour_factor`, default 2.5, times the plan
distance). The racks are chosen by twice the orthogonal distance to and from them (an
unsupported run off the rack counts double) plus the run along them, 5 m for each change of rack and 100 m for a way to or from a rack that crosses a road
(another rack carries a line over a road); ends whose rack points lie closer than the rack is wide
stay local (`local: rack run too short`), and a piece shorter than its rack is wide (a line
touching a rack only at a joint) is no run on it. It rises (or drops) near each end to the
tier's passing elevation (above the top tier, under the others' steel), between the bents, and
by A* onto the rack point nearest the end (straight down or up onto the lane from the passing
point above or below it where that point is free, so it does not cross the tier's other lanes
at their height), runs in a lane of its own on its tier (a `tiers`
rule, else the lowest tier for DN 300 and above and the top tier otherwise; lanes from the
rack's edge on the side the line comes from inward, shared along the rack by runs that do not
overlap, and clear of every pipe routed before, such as another line's riser through the tier:
else the next lane, then the next tier), hops (by A*) over or under the lanes from one rack
onto the next and comes off near the other end. A chain takes the lane of its largest pipe; a
smaller segment of it is lowered onto the tier where it runs in the lane (bottom of pipe on the
beams, as an eccentric flat-bottom reducer keeps it), with a step at the junction. A local chain
runs at the pipe-way: up near each end to `local_elevation_m` (bottom of pipe, default 3.5 m),
across and down, except short runs (`grade_max_m`, default 3 m), pump suction and discharge
runs and lines whose ends are both above the pipe-way. Ends within the rack reach of a rack may use it:
`rack_reach` in `layout/site-plan.yaml` (default: `max_unsupported_length`, 30 m), the same
value the `cheme.layout-line-route` check uses (`routing.yaml` `rack_reach_m` is deprecated and
only read when the site plan sets no `rack_reach`). A route that doubles back under (or over) itself (a run, a riser and
a run straight back: a lane run past the point where the line drops off the rack, then back
below it) is cut to the riser where the two runs overlap, wherever that riser keeps
`spacing_m` from the obstacles and the pipes routed before; `via` and pinned routes are taken
as they are.

A pinned route keeps the open end of its segment (`open_ends`), so the zones `layout/zones.yaml`
derives from the line still apply to its outlet. Pinning a route does not move the others: a
pinned pipe becomes an obstacle (and takes its lane on the rack) only when the routing reaches
the chains that would have been routed after it were nothing pinned (the order by DN and id,
with the waits for tees and lines), or when a chain routed before it would come within
`spacing_m` of it (less 10 mm; then that chain is routed again with the pin in the way, one pin
at a time). The run next to an end a route shares with a pinned pipe (a branch off a pinned
run) is not compared as far as their clearance reaches; a chain whose tee already has a pinned
branch start is cut there. Rack lanes are taken with their centre on the millimetre (rounded
away from the edge or lane they are placed against), as the route is written, so a route pinned
as generated takes back exactly its lane, and a junction is cut where the run passes nearest
its branch's target by an orthogonal run, found exactly (not on 0.5 m samples, which a route a
hair longer shifted): the other lines keep their routes to the millimetre. A pinned pipe
carries `racks` and `tier` where it runs at least 1 m along a rack with its bottom on a tier,
as a routed one does. The other segments of its own chain are routed from the pinned end, and
can move.

Line ends leaving the sheets: `ATM`/vent: an open end (a riser of `vent_rise_m`, default 1 m,
stepped sideways where it would cut a pipe routed before or steel; for a line a `vents` rule
`{lines?: [patterns], fluids?, rise_m?, radius_m?, max_rise_m: 20}` matches, at least its
`rise_m` and high enough that a sphere of `radius_m` (default: the largest zone radius
`layout/zones.yaml` derives from the line as a source) around the outlet clears every walking
level up to `headroom_walkway_m` above it: grade (not inside a closed casing), structure
floors, building levels; at most `max_rise_m`), unless a silencer or safety valve on that segment is
placed in the layout (by its tag of `piping/special-items.yaml`; a component's tag is its
`PipingComponentNumber`, tag name or `PositionNumber`): then the line ends at that item; a
placed relief valve between an inlet and an outlet segment (on a cold box roof) ends the inlet
there and starts the outlet's riser there; `BL` and other text (`CW`, `CWR`, ...): a
battery limit, from the first `battery_limits` rule matching the line (`{id?, lines: [CW-*,
CWR-*], fluids?, point: [x, y, z]}` or `{..., rack: PR1, rack_end: start|end|nearest}`), else the
`from_area`/`to_area` edge, else the free rack end nearest the other end (the line stops at the
end of its lane), else the nearest site edge at the road headroom; a placed tag: its nozzle on
that line; another line: its nearest point. On the ASU (218 segments, 124 chains) routing takes
about 3 s and a build about 6 s.

## Rules on the model (C4)

`model_rules.py`, run by `layout build`, `layout report`, `validate` (on the committed model)
and `/api/layout` (`model_findings`). Findings name `layout/plant-model.yaml`, the object ids
and `box: [x0, y0, z0, x1, y1, z1]` (site m) to highlight: `layout-clash-pipe`,
`-clash-pipe-equipment` (not for the runs that leave the outline of the item a pipe starts or
ends at from a nozzle under or inside it: a bottom outlet passes its skirt's opening; nor for
the legs onto and along the closed outline of that item where the pipe ends on it: the
approach to a placed relief valve or silencer along its face),
`-clash-pipe-steel` (warnings), `-clash-equipment-steel` (error), `-pipe-disconnected` (error:
a pipe end more than 10 mm from what its `ends` say it connects to: its nozzle's face, another
pipe of its tee, connector pair or shared component, its placed item, the line it ends on; a
pinned or `via` route that no longer meets its connection above all; key `<pipe>+start|end`),
`-headroom`, `-buried-cover` (below), `-access-blocked`, `-zone-crossing`, `-rack-fill`,
`-separation` (a site plan separation naming a zone) (warnings), `-nozzle-unconnected`, `-gravity-fall` (info). With
cables: `-tray-fill`, `-tray-separation`, `-clash-tray`, `-tray-zone` (a tray inside a zone of
a kind in the tray rules' `avoid_zones`, default oxygen-enriched and hazardous; info with a hint
to add `oxygen_deficient` to `avoid_zones` for a tray in an oxygen-deficient zone), `-tray-span`
(a tray off the racks running level more than `support_span_m`, 6 m, with no steel, wall or
tray tier within `support_reach_m`, 1 m), `-cable-missing`, `-cable-unrouted` (warnings,
[electrical.md](electrical.md)). With `layout/hvac.yaml` (`hvac.py`,
`hvac_findings`):

| rule | level | finding |
|---|---|---|
| `-hvac-capacity` | warning | a duct above the velocity limit of its kind at the largest standard size (key: the duct id; names the rooms that cannot get their air changes), a louvre whose free area passes its air above the louvre limit (key `<building>/<opening>`), a unit supplying more than its `capacity_m3h` (key: the unit), a room or unit without its air path (`hvac.missing`: a unit in another building, no intake; no exhaust opening is `info`) |
| `-duct-unrouted` | warning | a duct the router could not fit inside its building (`method: direct`) |
| `-clash-duct` | warning | a duct through an item, steel, a pipe, a tray, a unit or another system's duct (LOD 1 envelopes; its own unit at its port ends excepted), or a unit standing in an item, steel, a pipe or a tray (key `<duct or unit>+<other>`) |

**Buried lines.** A line or segment declared `buried` in `piping/routing.yaml` (`buried: true`,
or `buried: {cover_m: 1.0, basis: D-012}`) is laid in the ground where its route lies below
grade: a run whose top (axis plus OD / 2 and insulation) is at or below z = 0. Such a run is
not under the road headroom (`headroom_road_m`) nor an escape route's headroom, meets no steel
member, equipment part, envelope or zone volume that stands wholly above grade (a column on
grade, an item on its plinth; a footing or pit below grade still clashes), is no
`-ladder-clearance` finding and needs no supports (`-free-span`, `-support-missing`). Its
cover is checked instead: `-buried-cover` (warning) where the soil over its top is less than
its `cover_m`, or under a road less than `max(cover_m, road_cover_m)`; `road_cover_m` is a
routing rule, 1.2 m ASSUMED (secondary sources cite 1.2 m (4 ft) under the road surface for
uncased pipeline crossings after API RP 1102; not verified against the standard: the site's or
road authority's rule replaces it). The worst point is reported per pipe and road (key
`<pipe>+<road>`) and off the roads (key `<pipe>`), with the cover as `measured`; vertical runs
(risers through grade) are left out. Its runs above grade, and a run of it at or above grade
over a road, have every rule of a pipe above grade. The gates' `clashes` requirement counts
`-buried-cover` with the clashes and `-headroom`. Without `buried` nothing changes: a pipe below
grade is checked as any other.

The engineering rules (`engineering_rules.py`; criteria from package tables, every value
ASSUMED with its basis, overridden per plant under `criteria:` in `layout/site-plan.yaml`:
`operator_max_height_m` 1.8, `operator_reach_m` 0.6, `instrument_max_height_m` 2.0,
`stair_travel_m` 25, `dead_end_m` 7.5, `heavy_lift_t` 5, `crane_reach_m` 30,
`lane_margin_m` 1.0, `lift_clearance_m` 0.5, `vent_plan_clearance_m` 1.5, `vent_overhead_m`
6.0, `vent_side_clearance_m` 1.5, `support_pipe_clearance_m` 0.1, `support_stub_max_m` 1.5, `casing_reach_m` 1.0, `access_headroom_m` 2.1, `ladder_clearance_m` 0.2, `walkway_clear_m` 0.6, `standing_space_m` 0.6,
`chainwheel_max_height_m` 6.0, `extension_max_m` 6.0, `impulse_max_m` 6.0, `capillary_max_m`
10.0, `valve_platform_group_m` 3.0, `valve_platform_operating_m` 1.2, `valve_platform_depth_m`
1.2, `lift_dynamic_factor` 1.1, `lift_rigging_fraction` 0.05, `lift_rigging_height_m` 3.0,
`lift_chart_utilisation` 0.75, `spacing_table: true`):

| rule | level | finding |
|---|---|---|
| `-wall-penetration` | warning | a pipe through a building's cladding, its roof or a fire wall outside its declared openings, through any wall (or roof) of an owner it has no end in, or running in a wall's plane; the key is the penetration id, the hint the proposed opening (for a roof penetration: via points that enter through a wall) |
| `-wall-penetration` | info | a pipe into a casing (a structure's enclosure that is no fire wall) outside a declared opening |
| `-tier` | warning | a pipe running along a rack (level runs of 1 m or more in its strip along its centreline, 2.5 m or more in all) on another tier than its `tiers` rule for that rack (or its `tier` intent) assigns, or between the tiers |
| `-vent-outlet` | warning | a generated zone sphere around a `vent` or `psv_outlet` reaches a walking level up to the walkway headroom; the message gives the outlet height needed (key `<zone>+<item>+<k>`); or a pipe's open end lies under a walking surface, within `vent_plan_clearance_m` of it in plan and up to `vent_overhead_m` below it (key `<pipe>+<end>+below`), or beside one, within `vent_side_clearance_m` of its edge in plan and at most the walkway headroom above its floor (key `<pipe>+<end>+beside`) |
| `-free-span` | warning | a level run with steel supports (`supports`) spans farther between them, or from the outer ones to the ends of the run, than the DN's span (`domains/piping/data/pipe-spans.yaml`, after ASME B31.1 Table 121.5; liquid or gas column by the fluid's name); the message names the support steel proposed under it (to pin), and apart those with no place clear of other pipes (to place by hand) |
| `-support-missing` | info | a level run longer than that span with no support in the model (names the proposals too) |
| `-operability` | warning | a manual valve's handwheel or lever (not actuated) or a transmitter head with no walking level at most 1.8 m (2.0 m) below it within 0.6 m in plan (a stair flight is no operating position; its landings are), or with no free standing space there: a `standing_space_m` square, `access_headroom_m` high, on such a floor within reach, free of stair parts, ladders, steel members and items; an in-line item (not a reducer) inside a casing volume with no declared `hatch` of the enclosure within `casing_reach_m`, or whose hatch no walking level outside reaches, or whose standing space in front of the hatch is blocked (a stair flight across it). A declared `operator` answers it when it fits: a `chainwheel` on a handwheel valve of `use: infrequent` at most `chainwheel_max_height_m` above a floor within reach; an `extension_spindle` or `remote_operator` at most `extension_max_m` long (declared `length_m`, else from the handwheel to a pedestal 1 m above the nearest floor); a transmitter's `remote_mount` on `impulse` lines or a `capillary` within `impulse_max_m` or `capillary_max_m` (to a stand 1.2 m above the nearest floor); else the finding says why it does not (key: the item id) |
| `-operator-unknown` | warning | an `operators:` entry of `piping/routing.yaml` naming no valve, in-line instrument or nozzle of the model (key `operator:<item>`) |
| `-headroom` | warning | a pipe lower than `access_headroom_m` over a structure floor, an item platform, a stair tread or landing, an item's stair or roof platform: its top above the surface, its bottom less than the headroom above it, over the surface in plan (a vertical run on stairs and landings only; not the run at the nozzle of the item the pipe connects to, nor a crossing with a proposed step-over; key `<pipe>+<surface>`, a stair or an item's stair as a whole) |
| `-ladder-clearance` | warning | a pipe less than `ladder_clearance_m` from a ladder's rails (up to the top of its handhold extension) or through its cage: a structure's, a rack's, an item platform's or an item's own ladder (key `<pipe>+<ladder>`) |
| `-walkway-riser` | warning | a vertical run rising through an item's ring platform that cuts its outer edge (the handrail) or leaves less than `walkway_clear_m` of walkway on its wider side (not the run at the nozzle of the item it connects to; key `<pipe>+<platform>`) |
| `-landing-width` | warning | stacked stairs (one arrives at a floor, the next leaves from it): the free width of the walk between the two landings beside the next stair's flights (below the headroom) is less than the narrower stair's width (key `<stair>+<next stair>`) |
| `-egress-zone` | warning | a ladder's head (a structure's, a platform's or a rack's ladder, up to the headroom above its top) or a stair's top landing inside an `oxygen_deficient`, `oxygen_enriched` or `hazardous` zone volume (key `<way>+<zone>`) |
| `-access-enclosed` | warning | a structure floor, an item platform, a ladder or a stair inside a casing volume (key `<structure>/<level>`, the platform's or the way's id) |
| `-access-unconnected` | warning | a declared stair whose top (foot) landing is more than 0.3 m in plan from the level it climbs to (from), or a ladder whose top (foot) is more than 0.8 m from it, or whose level is inside a casing (key: the way's id) |
| `-escape-ways` | warning | a structure floor with fewer than two connected ways down to grade (declared stairs and ladders, not enclosed, reaching the floor and standing on a floor that has its own connected way down; proposals count once pinned; floors of generated levels only are left out), or a floor with a dead end longer than `dead_end_m` (with one way down, as on a valve access platform, the walk to it from the floor's far end; with more, the walk in plan from a point of the floor to the nearest point where two of its ways lie 45 degrees or more apart, Approved Document B Vol. 2 Diagrams 2.1 and 2.2; checked on every floor and platform that has the ways it needs, and the access proposals add caged ladders until none is left), or an item's platform whose far end is more than `dead_end_m` along it from its only ladder |
| `-escape-travel` | warning | a structure floor at 6 m or more, or in regular use, with no connected declared stair, or a point of it more than `stair_travel_m` in plan from its nearest one |
| `-lifting` | warning | an item of `weight` at or above `heavy_lift_t`: in a building with no overhead crane, or one whose `capacity_t` is below the gross load (weight x `lift_dynamic_factor` x (1 + `lift_rigging_fraction`)); outside, no `crane_pad` zone within its reach, or the crane lane blocked (the nearest pad within reach whose lane is clear, else the nearest; from the pad's nearest point over the item to its far side, as wide as the item across the direction of travel (the load keeps its orientation) plus `lane_margin_m` each side, above its top plus `lift_clearance_m`: pipes not ending at the item, cable trays (an item's own branch but its last drop onto it; all of a branch that ends at a `cable_entry` beside it, whose cable drop is not counted), ducts, steel, walls, roofs, other items) |
| `-laydown` | warning | no `laydown` zone within the crane's reach whose plan holds the heavy item's footprint |
| `-pad-overlap` | warning | a `crane_pad` or `laydown` zone's box overlapping a rack's strip, a structure's or a building's footprint by more than 0.05 m in plan (key `<zone>+<other>+<k>`) |
| `-steel-in-way` | warning | declared steel (a rack's bents, a structure with its stairs and ladders, a support post) in a road's strip below `headroom_road_m`; a declared support post (column or crossbar) in a `crane_pad`, `laydown`, `escape`, `keep_clear` or `maintenance` zone volume, in an item's outline (a vertical cylinder's circle, else its box) over its height, through a ladder's cage or less than `ladder_clearance_m` from its rails (key `<steel>+<road, zone, tag or ladder>`) |
| `-support-stub` | warning | a declared support `stub` taller than `support_stub_max_m` (1.5 m, ASSUMED; key `<stub>+height`, `measured` the height), or standing on the support steel of another line (a T-post crossbar laid out for that line; a segment of its own line's steel is fine; key `<stub>+<that support>`) |
| `-spacing` | warning | two items closer in plan than the equipment spacing table (`domains/spatial/data/equipment-spacing.yaml`: fired equipment 15 m, pumps 1 m, machines 3 m, ...) says for their families or DEXPI classes; not between stacked items or items in a closed casing, nor a pair a site plan separation names |
| `-building-spacing` | warning | two buildings closer in plan (footprint to footprint) than the building spacing table (`domains/spatial/data/building-spacing.yaml`, by `use`: 6 m any two, 15 m an occupied or electrical building to a process or machine building, ASSUMED) says, unless a site plan separation names both (key `<a>+<b>`) |

Walking levels (`floors.py`): grade (everywhere but inside a structure walled on every side by
walls that are no fire walls: a casing), each structure level's grating, the treads (kind
`stair`) and landings of the structures' stairs, each item platform's grating, every grating
part of an item (a tank's spiral stair treads, its landing and roof platform), of a step-over
and of a rack, each building level above grade over its footprint. A grating inside a casing
volume (in its footprint, below the top of its walls) is none (left out when wholly inside,
else the casing's footprint is a hole in it); a casing's roof is one. The router's vent
risers clear the same levels.

## The lifting study

`cheme layout lifting [--csv | --json] [--write | --check]` (`domains/spatial/lifting.py`,
`lifting_study(root) -> LiftingStudy`) takes the cases of the `-lifting` rule (every item of
`heavy_lift_t` or more outside a closed casing, by its list `dimensions.weight`, or by
`dimensions.lift_weight` where the list gives the heaviest single maintenance lift of the item,
a machine's motor or rotor: the study marks that row `(heaviest part)`: its building crane or nearest crane pad within
reach, what blocks the lane, the laydowns that hold it) and gives per lift: the working radius
(in plan from the pad's centre, where the crane is ASSUMED to slew, to the item's centre), the
gross load (weight x `lift_dynamic_factor` x (1 + `lift_rigging_fraction`)), the load moment
(gross x radius, t m), the chart capacity needed (gross / `lift_chart_utilisation`), the lift
height (the highest top in the lane from grade, plus `lift_clearance_m`, at least the set
elevation) and the hook height (+ the item's height + `lift_rigging_height_m`), and the nearest
laydown. A building's overhead crane is checked on the gross load (the chart utilisation of a
mobile crane does not apply: the capacity needed is the gross load), its `capacity_t` in the
capacity column with the utilisation: `building crane <t> t carries it`, or `... short`; a
building without a crane is `no crane`. `--write` writes `layout/lifting-study.md` and `.csv` (columns `tag, weight_t, crane,
pad, radius_m, gross_t, moment_tm, required_t, lift_height_m, hook_height_m, lane, laydown,
chart, chart_radius_m, chart_capacity_t, utilisation, status`).

Choosing the crane stays a human judgement unless the plant gives load charts in
`layout/crane-chart.yaml` (kind `crane_chart`, `cheme schema crane_chart`):

```yaml
cranes:
  - id: MC-1
    title: mobile crane, 50 m main boom
    source: "<supplier> load chart <document, page>"
    status: QUOTED              # or ASSUMED (a typical chart)
    configuration: "50 m boom, 100 t counterweight, outriggers 8.5 x 8.5 m"
    pads: [Z-PAD-A4]            # empty: every pad
    max_hook_height_m: 48
    chart: [{radius_m: 10, capacity_t: 120}, {radius_m: 14, capacity_t: 80}, ...]
```

Each lift from a pad is then checked against the charts for that pad: the capacity at the
smallest tabulated radius at or beyond the lift's (no interpolation) must be at least the
capacity needed, and the hook height at most `max_hook_height_m`; else
`cheme.layout-lifting-capacity` (warning, `layout/crane-chart.yaml`), which `validate`
reports too. The gate requirement `lifting` (`kind: layout-model`) fails on unaccepted
`-lifting`, `-laydown` and `-lifting-capacity` findings, `lifting-current` on a written study
that is not current; the template's gate `lifting-study` (stage basic) requires both. `validate`
reports a written study (`.csv` or `.md`) that is not what `cheme layout lifting` gives for the
committed model now as `cheme.layout-lifting-study-outdated` (warning), so a rebuilt model with
a study left behind is seen without the gate. The `.md` names the model's `output_sha256`: a
regeneration that changes nothing else keeps a review of it current (the review gate does not
count a change of digests alone). Ground
bearing, rigging design, slewing clearances and wind stay with the lifting plan.

## 2D drawings (C5)

`cheme layout render --plan [--level ID | --z A,B] | --section x=..|y=.. [--depth D]
[--crop X0,Y0,X1,Y1] [--png]` writes `build/layout-plan.svg`, `layout-level-<id>`,
`layout-plan-z<a>-<b>`, `layout-section-x<v>|y<v>` (`_crop-...` with a crop). A1 sheet at a
standard scale, SVG units sheet mm. Parts are drawn by their envelope (`lod` absent or 1)
plus the detail that shows in a plan (gratings and stair treads, handrails, flanges); a level
plan draws the cut level's top rails dashed; proposed stairs, ladders and step-overs are
dashed. Ids for scripting: `north-arrow`, `scale-bar`,
`title-block`, `grade`, `equipment-<tag>`, `pipe-<pipe id>` (with `data-line`),
`tray-<tray id>` (with `data-system`; outlines as wide as the tray in plans, width x depth where
a section cuts it), `jb-<tag>`, `duct-<duct id>` (with `data-system`; outlines as wide as the
duct in plans, a crossed width x height rectangle where a section cuts it), `ahu-<unit id>`,
`terminal-<terminal id>`,
`zone-<id>-<k>`, `road-<id>-<k>`, `rack-<id>`, `stair-<id>`, `ladder-<id>`,
`step-over-<id>`, `inline-<id>`.

## Intent commands

`cheme layout route [--line L]...` rebuilds routing only those lines (the others are kept
from the committed model); `cheme layout pin LINE|PIPE_ID|TAG/platform-N|S/stair-to-L|S/ladder-to-L|RACK/ladder-start|end|OWNER/LINE`
copies a route into `piping/routing.yaml` (`{line, segment, route}`), a platform into the
item's `access:`, a platform proposed outside a casing (`S/L-out`) into its structure's
`levels`, a proposed stair or ladder into its structure's `stairs` or `ladders`, a
proposed rack ladder into the rack's `ladders`, or a penetration's proposed opening into its
building's `openings` (`layout/building.yaml`) or its structure's `enclosure: openings`
(`layout/structures.yaml`), with the line as the opening's id (a roof penetration is refused:
a roof opening cannot be declared); proposed support steel
(`PIPE/SP-<arc>`) into `pipe_supports` and a proposed valve access platform (`VP-<tag>`) into
`structures` of `layout/structures.yaml` (with its ladder or stair; the routes of its valves'
pipes are pinned with it). The files are edited as text, so comments stay (except inside a
replaced route entry or `access:`); a pin is refused (exit 1, nothing written) when the result
would not validate against the file's schema, when the entry cannot be placed so the data is
the old data plus the pinned entry, or when the structure already declares the id. A replaced
route entry keeps its `gravity`, `buried` and `notes`; an item with several pinned platforms gets no
`ladder_side` (each ladder stands where the build puts it);
`cheme layout report [--json]` lists every line routed, partly routed, skipped or unrouted
with the reasons, lengths, how and why each was routed, the chain counts per method and per
reason, how the battery limit ends were placed, rack fill, rule counts and object sources.

## Validation

`cheme validate` checks the model file against its recorded provenance:

| rule | level | when |
|---|---|---|
| `cheme.layout-model-edited` | error | its content no longer matches `output_sha256`, or it has no provenance |
| `cheme.layout-model-version` | warning | built by another generator version, schema or generator code |
| `cheme.layout-model-outdated` | warning | an input changed (or a new input file appeared) since it was built |
| `cheme.layout-model-missing` | info | layout files but no model |
| `cheme.layout-lifting-study-outdated` | warning | a written `layout/lifting-study.csv` or `.md` is not what `cheme layout lifting` gives for the committed model |

The layout files themselves are checked by `validate` before the build: with
`layout/hvac.yaml`, `cheme.layout-hvac-ref` (error) names a unit or room in a building
`layout/building.yaml` lacks, a level its building lacks, a room's unit that `units:` lacks or
that stands in another building, an `intake`/`exhaust` that is no opening of the unit's
building, a unit, room extent or terminal outside its building or room, and a duplicate id.

`validate`, `layout report` and `/api/layout` also report `cheme.layout-zone-source`
(warning, `layout/zones.yaml`) for a zone source the committed model cannot place (an
unplaced tag, a nozzle the item lacks, a line without an open end), as the build does; the
`zones` requirement of a `layout-model` gate fails on it until it is fixed or accepted.

`cheme impact` reports the outdated model as `cheme.review-needed`.

A finding that measures a length carries it as `measured` (m): `-free-span` (the worst span),
`-support-missing` (the bare run), `-tray-span` (the worst run), `-spacing` and
`-building-spacing` (the distance), `-ladder-clearance` (the gap). `validate` reports
`cheme.accept-stale` (warning, `checks/checks.yaml`) for an `accept:` entry whose reason
quotes lengths (`<number> m`) none of which is within 0.1 m or 2 % (ASSUMED) of the finding's
current `measured` value: the acceptance still applies, its reason is out of date. A wildcard
entry gives one finding per finding it matches, named in the message and in `ids`, with the
key `<gate>:<entry id>@<finding id>` (`<entry id>@<finding id>` for a top-level entry).
`cheme layout build` refuses while a layout file is invalid and over an edited model unless
`--force`; `--check` writes nothing and exits 1 when the file is not current. It prints
`cheme.layout-nozzle-defaulted` (info) per item with nozzles placed by default, and
`cheme.layout-nozzle-unknown` (error) for an override naming a nozzle the P&ID lacks.

## `GET /api/layout` and the drawings

Unchanged keys (`site`, `areas`, `roads`, `racks`, `buildings`, `equipment`, `lines`, `notes`,
`files`, `rev`, `findings`), and:

- `equipment[]` entries add `family`, `size_from` (`list`, `placement`, `default`) and `mount`; their
  `shape`, `size` and `bbox` are the derived ones;
- `separations`: the site plan's `separations` as written (`from`, `to`, `min_m` or
  `min_factor_of_height`, `height_of`, `measure`, `reason`, `basis`);
- `model`: the committed `layout/plant-model.yaml` of that revision as data, `null` when there
  is none. The API never builds it: it is read-only;
- `zones`: `model.zones` (empty without a model);
- `model_findings`: the rules on the model (above), as findings (`box` 3D; `measured` where the
  finding measures a length).

`GET /api/mto?rev=` takes off the committed model's bulk materials (pipe, fittings, flanges,
valves, steel, grating, insulation, concrete) from the parts and pipes above, and prices them
with `estimate/rates.yaml`: [mto.md](mto.md). A change to a part's `material`, a member's
`section` or the pipe fields changes the take-off; keep them as documented here.

`GET /api/layout/plan.svg?rev=&level=ID|z=a,b` (the plot plan without either) and
`GET /api/layout/section.svg?rev=&x=..|y=..&depth=` (default 6 m) draw the committed model of
that revision (404 without one, 400 for bad arguments).
