# Spatial

**Scope.** The plant in 3D at layout level: the plot plan (site, areas, roads, pipe racks,
separations), buildings, steel structures, equipment placement, nozzle positions, access
platforms, zones, pipe routes and their in-line items; the rules on that geometry (clashes,
headroom, access, separations, rack reach and fill) and the drawings made from it (plot plan,
level plans, sections). Enough to arrange a plant, check it and review it; not a plant design
system.

**Artifact types.** The layout files of a plant repository (`layout/site-plan.yaml`,
`building.yaml`, `equipment-placement.yaml`, `structures.yaml`, `zones.yaml`,
`piping/routing.yaml`) and the generated model `layout/plant-model.yaml` (kind `layout_model`,
the contract with the viewer: [docs/framework/layout-model.md](../../../../docs/framework/layout-model.md)).

**Declared and generated.** What a person or an agent writes is *declared*: positions and
rotations, what an item is mounted on, nozzle overrides, declared platforms, structures and
their stairs and ladders, zones, routing rules and intent (tiers, battery limits, vias,
elevations, skips), separations. What `cheme layout build` derives is *generated*: every
item's parts from its DEXPI class and dimensions, nozzles from the P&ID side, maintenance
envelopes, rack bents, structure members, proposed platforms (`review_needed`), zone volumes
from release sources (the safety domain's ASSUMED radius table), one pipe route per P&ID
segment with its method and reason, in-line items along it, and the routing statistics. A
generated object copied into an input file with `cheme layout pin` becomes *pinned* and is
kept as it is. Every object of the model says which (`source`), and the model records the
hashes of its inputs and of the generating code (`provenance`), so validate reports it edited
or outdated.

**Code today.** `schemas.py` (every layout file and the model), `layout_validate.py` and
`layout_distances.py` (plot-plan rules, rack network, measured distances), `shapes.py`
(parametric equipment families), `pid_nozzles.py` and `pid_network.py` (nozzles and the piping
network from the P&IDs), `structures.py` (frames, rack bents, platforms), `zones.py`,
`routing.py` (the deterministic router), `geometry3d.py`, `model.py` (build, provenance),
`model_rules.py`, `drawing2d.py` (SVG plans and sections), `pins.py`, `report.py`, `gates.py`
(the `kind: layout-model` stage gate). Skills: `layout-yaml`, `pipe-routing`,
`structures-access` (and `area-classification` in the safety domain).

**Integration boundaries.** These are deliberately out of scope; the model is the input to
them, or takes their results back as declared data:

- **Pipe stress and flexibility**: no stress analysis, loads or expansion loops. Routes are
  orthogonal polylines between nozzles; a stress tool takes them (points, OD, class,
  insulation, fluid) and its results come back as vias or pinned routes.
- **Pipe supports**: no support design or placement; racks carry lines on generated bents
  only for geometry.
- **Isometrics and fabrication**: no isometric drawings, spools, cut lengths, weld counts or
  bills of material. Lengths and in-line items in the model are estimates for layout review.
- **Structural design**: frames, member sections and bents are geometry with default
  sections by span (ASSUMED); no loads, connections, foundations or code checks.
- **HVAC ducts and cable trays**: not routed; reserve their space with zones (`keep_clear`)
  or structures.
- **Dispersion and consequence modelling**: none. Zones come from an indicative radius table
  (safety domain) or as explicit volumes from a study done elsewhere.
- **CAD export**: the model is YAML and JSON (`/api/layout`); the viewer exports glTF. No
  other CAD or plant design system formats.

**Out of scope.** Deciding that a layout is good: the rules find intersections, missing access
and unkept distances; spacing criteria, access philosophy, tier allocation, area
classification and every proposal of the generator are decisions for the engineers who review
and sign the layout.

May import: `equipment`, `piping`, `safety`. See
[the architecture](../../../../docs/framework/architecture.md).
