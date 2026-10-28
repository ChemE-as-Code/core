# Layout

The 3D layout of the plant, as optional YAML files and a generated model. `cheme validate` checks them
against their schemas and each other; `cheme serve` shows them in 3D (Layout 3D in the
viewer). The skill `.claude/skills/layout-yaml` says how to edit them; `pipe-routing`,
`structures-access`, `area-classification` and `hvac-ducts` cover routes, steel and access,
zones, and ventilation.

| file | schema | holds |
|---|---|---|
| `site-plan.yaml` | `cheme schema site_plan` | site boundary, plot areas, roads, pipe racks |
| `building.yaml` | `cheme schema building` | buildings and structures, their levels and column grid |
| `equipment-placement.yaml` | `cheme schema placement` | where each equipment-list item stands, on which level, nozzle overrides |
| `structures.yaml` | `cheme schema structures` | steel frames: spans, levels (deck/platform), bracing, stairs, ladders, enclosure (cold box casing, fire wall) |
| `zones.yaml` | `cheme schema zones` | keep-clear, laydown, maintenance, escape, hazardous, oxygen-enriched/-deficient zones: a box/cylinder/sphere, or `sources` sized by cheme-as-code's radius table (ASSUMED) |
| `hvac.yaml` | `cheme schema hvac` | air handling units (in a building, `intake` and `exhaust` louvres), ventilated rooms (`air_changes_per_h` or `flow_m3h`, the unit, optional terminals), duct rules (velocity limits, sides, ceiling gap, spacing; defaults ASSUMED); optional, skill `hvac-ducts` |
| `../piping/routing.yaml` | `cheme schema routing` | router rules (rack tiers by fluid or line prefix, battery limits, pipe-way elevation, `local_max_m`, spacing, headroom, grid) and intent per line (`rack`, `tier`, `via`, `elevation`, pinned `route`, `skip`) |
| `../piping/pipe-specs.yaml` | `cheme schema pipe_specs` | pipe classes (material, colour) and insulation thickness by type and DN (optional) |
| `plant-model.yaml` (generated) | `cheme schema layout_model` | the 3D model `cheme layout build` derives: parts, nozzles, envelopes, steel, platforms, zones, pipe routes, in-line items |

Coordinates are metres in the site frame: **x east, y north, z up**, origin at the south-west
corner of the site. Rotations are degrees, counterclockwise seen from above.

- An **area** is a box `[x0, y0, x1, y1]`; kind `process`, `utilities`, `storage`, `road`,
  `reserved` or `building`. Areas should not overlap (roads may).
- A **road** or **rack** is a centreline `points: [[x, y], ...]` with a `width`; a rack has tier
  elevations `levels: [z, ...]`.
- A **building** is a rectangle `width` (along its x) by `depth` (along its y) from its
  south-west corner `origin: [x, y]`, turned by `rotation_deg` (0, 90, 180, 270) about that
  corner. `levels` are floors, platforms or roofs (`elevation`, `height`); `frame.grid_x` /
  `grid_y` are column lines as offsets from the origin.
- A **placement** puts an equipment tag at `position: [x, y, z]`: the centre of its footprint,
  `z` the bottom, turned by `rotation_deg` about the vertical (the item's own x: the axis of a
  horizontal drum or exchanger, the shaft of a pump from suction to driver). Its **shape and
  size come from the equipment list**: the DEXPI class in `type` picks the family (vessel,
  column, tank, shell-and-tube or plate exchanger, pump, compressor, filter, stack, ...) and
  `dimensions:` the overall size (`{diameter, height}` vertical, `{diameter, length}`
  horizontal, `{length, width, height}` box-like; optional `head`, `support`, `weight`).
  `shape: box | vertical_cylinder | horizontal_cylinder | sphere` overrides the shape; `size`
  (`[dx, dy, dz]` or `{diameter, height | length}`) is only a fallback for an item without
  dimensions (`layout-size-from-placement`, info) or of `piping/special-items.yaml`. An item
  on a building level gives `mount: {building: B-1, level: GF}` (`{structure, level}` for a steel
  structure); its `z` is then the level's elevation.
- **Nozzles** come from the P&ID (name, DN, connected lines) and are placed on the item from
  the side the P&ID draws them on. Override one with `nozzles: [{id: N1, angle_deg: 90,
  elevation: 2.5}]` (vertical items: degrees ccw from the item's x, height above its bottom;
  horizontal items: `along` the axis from the front end, `angle_deg` about it, 0 = top) or
  `{id: N2, face: top, offset: [0.5, 0]}` (faces `top`, `bottom`, `north`, `south`, `east`,
  `west`, `front` (= -x end), `back`, in the item's own frame; `offset` from the face centre).

- A **structure** (`structures.yaml`) is an open frame from `origin` with bays `spans_x` x
  `spans_y`, `levels: [{id, elevation, kind: deck | platform, extent?}]`, `bracing` (`none`,
  `x`, `k`, one for all sides or per side), `stairs: [{id, from, to, side}]` (`from: grade` at
  grade), `ladders: [{id, from, to, at: [x, y]}]` and an `enclosure: {walls, height, material}`.
  Items on it give `mount: {structure: S-1, level: L1}` with `z` at the level's elevation.
- **Access**: a vertical item's `access: {platforms: [{elevation, arc_deg?, width?}],
  ladder_side}` declares its platforms; without it `layout build` proposes platforms for
  nozzles and valves more than 2.5 m up (`review_needed`); `cheme layout pin TAG/platform-1`
  copies a proposal here.

**The generated model.** `cheme layout build` derives `layout/plant-model.yaml` (kind
`layout_model`) from these files, the equipment list, the line list and the P&IDs: the parts of
every item, its nozzles with point, direction and DN, maintenance envelopes (bundle pull, motor
removal, pump access), steel, platforms, zones, a pipe route for every P&ID segment (with
in-line valves) and the site geometry. Never edit it; change the inputs and rebuild.
`cheme layout report` lists routed and unrouted lines with the reasons and how and why each
was routed, `cheme layout route --line L` reroutes one line, `cheme layout pin L` keeps a route, and `cheme layout
render --plan | --level ID | --section x=..` draws plans and sections into `build/`.
`cheme validate` says when it is outdated (`layout-model-outdated`), edited by hand
(`layout-model-edited`) or missing (`layout-model-missing`).

Rules (`cheme.layout-*`): `outside-site`, `clash` (two items intersect: their plan outlines,
a circle for a vertical vessel, or the parts standing out of them such as a tank's stair, base
plate or plinth; equipment in a building it is not placed in, equipment on a road, equipment reaching up into a rack's tiers,
buildings on roads, under racks or overlapping each other), `unknown-tag`, `not-placed` (info),
`level` (also items taller than their level), `area-overlap` (warning), `duplicate` (warning),
`line-route` (warning), `line-length` and `line-unrouted` (info), `separation` (warning),
`size-from-placement` (info: sizes that belong in the equipment list), `size-ignored` (warning:
a placement size next to dimensions), `size-missing` (warning: neither, drawn at an assumed
size), `nozzle-unknown` (error: an override naming a nozzle the P&ID does not have).
A level without `height` reaches up to the next level (a top floor: 4 m); a building without
levels counts as 6 m high. Numbers must be finite and ids not empty.

Example (uncomment into the files):

```yaml
# layout/site-plan.yaml
# site: {name: Plot 1, width: 60, depth: 40}
# areas:
#   - {id: A-100, title: Process area, box: [10, 18, 46, 38], kind: process}
# roads:
#   - {id: R-1, title: Main road, points: [[0, 13], [60, 13]], width: 6}
# racks:
#   - {id: PR-1, title: Main pipe rack, points: [[10, 20], [46, 20]], width: 4, levels: [5, 7]}
# notes: ASSUMED - plot dimensions not yet confirmed.

# layout/building.yaml
# buildings:
#   - id: B-1
#     title: Process building
#     origin: [26, 26]
#     width: 14
#     depth: 10
#     levels:
#       - {id: GF, title: Ground floor, elevation: 0, height: 5, kind: floor}
#       - {id: PF, title: Platform, elevation: 5, height: 4, kind: platform}
#     frame: {grid_x: [0, 7, 14], grid_y: [0, 5, 10]}

# layout/equipment-placement.yaml
# equipment:
#   - {tag: P-101, position: [16, 24.5, 0]}
#   - {tag: E-101, position: [34, 31, 5], mount: {building: B-1, level: PF},
#      nozzles: [{id: N1, face: top, offset: [-1.5, 0]}]}

# equipment/equipment-list.yaml (the sizes)
#   - {tag: P-101, type: CentrifugalPump, dimensions: {length: 2.0, width: 0.8, height: 1.0}}
#   - {tag: E-101, type: TubularHeatExchanger, dimensions: {diameter: 0.8, length: 5}}
```

**Lines and racks.** Each line of `piping/line-list.yaml` whose ends (`from`, `to`: placed
tags, area ids or other line numbers; or `from_area` / `to_area` for an end that is not placed,
such as a vent area) lie in different areas or more than `max_unsupported_length` (default 30 m)
apart must be carried by racks: each end within `rack_reach` of a rack centreline (default:
`max_unsupported_length`, since the run from an end to the rack is unsupported pipe), the racks
connected (`layout-line-route`). Carried lines get a length estimate along the racks
(`layout-line-length`, info). The router of `layout build` takes such lines over the racks too,
with the same `rack_reach`,
and also lines whose straight run would cross a road or another area or that are longer than
`local_max_m` (`piping/routing.yaml`, default 15 m); local lines run at the pipe-way elevation
(`local_elevation_m`, default 3.5 m). Ends at the battery limit (`BL`, `CW`, `CWR`, ... in the
line list) go to a `battery_limits:` point or rack end of `routing.yaml`, else the nearest free
rack end, else the site edge:

```yaml
# piping/routing.yaml
# rules:
#   tiers:
#     - {rack: PR-1, elevation: 7, fluids: [Cooling water, Cooling water return]}
#   battery_limits:
#     - {id: CW-plant, lines: ["CW-*", "CWR-*"], rack: PR-1, rack_end: start}
#   local_elevation_m: 3.5        # ASSUMED pipe-way height in the areas
# lines:
#   - {line: 50-N-101, skip: field-run small bore at basic engineering}
```

**Separations and keep-clear radii.** State spacing criteria as data, not only in `DESIGN.md`
prose, and they are measured (`layout-separation`):

```yaml
# separations:                     # in layout/site-plan.yaml
#   - {from: CB-3101, to: K-4101, min_factor_of_height: 1, reason: toppling, basis: D-026}
#   - {from: T-4101, to: site-boundary, min_m: 8, basis: D-026}
#   - {from: T-4101, to: R-1, min_m: 8, measure: footprint}
```

`from`/`to` are placed tags, area, building, road or rack ids, or `site-boundary`;
`min_factor_of_height` multiplies the height of the taller of the two (`height_of: from|to`
to choose). Distances are between footprints (`measure: centre` between centres).
`cheme show <tag> --layout` prints measured distances to quote in `DESIGN.md`. Model an
enclosure you measure from -- a cold box, a fire or blast wall -- as a building with a level of
its height (and place the items inside it with `building:`), or as a tagged box placement.
