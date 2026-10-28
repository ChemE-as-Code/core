# Datasheet dimensions and outline drawings

A datasheet (`equipment/datasheets/<TAG>.yaml`, `cheme schema datasheet`) states the item's
main dimensions, weights, materials per part and nozzle schedule in typed, optional fields, and
comes with a generated outline drawing `equipment/datasheets/<TAG>.svg`. Every field is
optional: a datasheet written before them validates unchanged.

| Module | Holds |
|---|---|
| `domains/equipment/schemas/datasheet.py` | `DatasheetDimensions` (with `Support`, `ColumnSection`, `Tubes`, `Plates`, `Baseplate`), `Weights`, `Material` and its `MaterialClass`, the nozzle schedule fields of `DatasheetNozzle` |
| `domains/equipment/outline.py` | `outline(sheet) -> Outline` (the main sizes in metres, the drawing family), `derived_dimensions(item, model) -> (dimensions, weights)` (what the equipment list and the layout model state), `kind_of`, `head_depth` |
| `domains/equipment/drawing.py` | `render_outline(sheet, meta, source) -> str` (the SVG), `title_meta(config)` |
| `domains/equipment/datasheets.py` | the checks (`dimension_findings`, `nozzle_findings`, `drawing_findings`), `drawing_states`, `datasheet_gate`, `field_counts` |
| `domains/equipment/dimensions.py` | the tolerances, shared with the equipment-list check against the P&ID sizing attributes (`size_problems`) |
| `project/datasheets.py` | `drawings(root, tags, write)`, `datasheet_report(root)` (the viewer's index and entries), `nozzles_of(models)` |
| `interfaces/cli/datasheets.py` | `cheme datasheets drawing [--tag] [--write \| --check \| --print]`, `cheme datasheets fill --dimensions` |

## The fields

Every value is a number, text or `{value, unit, assumed, source}` (and may be `TBD`,
`supplier` or `not_applicable` like any other datasheet value). Lengths are in m unless the
unit says `mm` or `cm`, weights in t (`kg` is read too); another unit is
`cheme.datasheet-unit` (warning) and left out of the checks and the drawing.

```yaml
dimensions:
  orientation: vertical                 # of a round item's axis
  outside_diameter: {value: 4.0, unit: m, source: equipment/equipment-list.yaml dimensions.diameter}
  inside_diameter: {value: 3960, unit: mm, source: DESIGN.md D-061, assumed: true}
  tangent_length: {value: 20.0, unit: m, source: DESIGN.md D-061}
  head: {value: ellipsoidal_2_1, source: equipment/equipment-list.yaml dimensions.head}
  support: {type: skirt, height: {value: 4.0, unit: m, source: D-061}}  # base to bottom tangent
  # an item above grade: support: {type: none, elevation: 20.0, stands_on: C-3101} (an LP column
  #   on the HP column); an internal of another item with no sizes of its own: housed_in: C-3102
  sections:                             # a column: from the bottom tangent line up
    - {id: lower bed, internals: structured packing 250Y, bottom: 1.5, height: 6.0}
  overall_height: {value: 25.0, unit: m, source: equipment/equipment-list.yaml dimensions.height}
  # shell and tube: inside_diameter (shell ID), shell_passes, tubes: {count, outside_diameter,
  #   length, passes, pitch}; plate exchanger: plates: {height, width, count}; machine:
  #   baseplate: {length, width}, shaft_height; a horizontal item or a machine: axis_deg
weights: {empty: 38.0, operating: {value: supplier, unit: t, source: enquiry E-12}, test: TBD}
materials:
  shell: {value: SA-516-70, material_class: carbon_steel, standard: ASME II A}
  packing: SS 304                       # a plain value is still accepted
nozzles:
  - {name: N1, mark: N1, service: Air inlet, dn: 600, rating: PN16, facing: RF, face: side,
     orientation_deg: 180, elevation_m: 7.333, projection_m: 2.6, lines: [AIR-1002]}
```

`material_class` is one of `carbon_steel`, `low_temperature_carbon_steel`, `low_alloy_steel`,
`stainless_steel`, `duplex_stainless_steel`, `nickel_alloy`, `aluminium`, `copper_alloy`,
`titanium`, `cast_iron`, `plastic`, `fibre_reinforced_plastic`, `lined_steel`, `concrete`,
`other`: the key the take-off, the LCA and the cost factor can match a part by.

Nozzle locations keep the convention of the layout (`orientation_deg` from site east,
counter-clockwise; `elevation_m` above the item's base). `projection_m` is the flange face from
the axis (a side nozzle of a vertical item) or from the surface it leaves; `axial_m` places a
nozzle of a horizontal item or a machine along the item's own axis. `mark` is the drawing's
mark when it differs from `name`.

## Draft and fill: only what the files state

`cheme datasheets draft` writes `dimensions` and `weights` from the equipment list's
`dimensions` (outside diameter, overall height or length, head and support types, the empty
`weight`) and, where `layout/plant-model.yaml` exists, the tangent length and support height of
its generated shell and a horizontal item's axis direction (`axis_deg`, the placement's angle).
An item placed above grade gets its base elevation (`support.elevation`, the placement's z) and,
when the top of exactly one other model item is at its base under its centre, that item
(`support.stands_on`). `housed_in` is written by hand (the files do not state it).
The model's tangent length and support height are the 3D model's proportions, not a vessel
design: they are written `assumed: true` with a source that says so. Only the empty weight the list
gives is written; the gate's `require: [weights]` asks for the rest.

`cheme datasheets fill` adds the same to every draft; `cheme datasheets fill --dimensions`
does only that, into final datasheets too. A field is added when the sheet does not have it or
rewritten when an earlier fill wrote it (source `cheme datasheets fill: ...`); a value written
by hand, a `TBD` and a marker are kept, and a final sheet gets no `TBD`.

## The outline drawing

`cheme datasheets drawing --write` writes `equipment/datasheets/<TAG>.svg` for every valid
datasheet whose drawing is not current; `--check` exits 1 when one is missing or stale; without
an option it lists each drawing's state; `--print --tag T` prints one. The drawing is
generated from the datasheet alone (plus the title block fields of `plant.yaml`): never edit it.

- A3 sheet, SVG in sheet millimetres; an elevation and a nozzle orientation (plan) view.
- Vertical vessels, columns and tanks: shell, heads by type, skirt, legs or lugs, tangent lines,
  column sections; side nozzles at their angle and elevation, top and bottom nozzles at their
  offset. Horizontal vessels and shell-and-tube exchangers: side view on saddles and plan in the
  item's frame (north arrow from `axis_deg`). Machines, plate exchangers and anything else: the
  overall box, baseplate, shaft centre line.
- The base line is labelled with what the item stands on (`base on C-3101 (+20 m)`), its base
  elevation (`base +7.5 m`) or `base / grade`. The schematic saddles (or legs) of a horizontal
  item move, the least distance, clear of its bottom nozzles.
- An item that cannot be drawn says which `dimensions.` fields are missing, or, with
  `housed_in`, that it is housed in that item and has no main dimensions of its own.
- The schedule shows the connected `lines` as the service where a nozzle gives none.
- Nozzles at one angle or at one point share a label (`N3, N4 270°`); a label that would
  overlap an earlier one steps down, in the order the nozzles are listed.
- Dimension lines for the stated dimensions only (`*` marks an assumed one). A nozzle without a
  location is in the schedule (marked) but not drawn; an unknown head is drawn flat with a note;
  saddle positions and nozzle stubs without `projection_m` are schematic, which the notes say.
- The title block names the tag, service, class, plant, project, revision and the datasheet's
  fingerprint (`sha256:` of the YAML), not the commit: the drawing stays current across commits
  that do not change its datasheet. A draft carries a `DRAFT` marker.
- Deterministic: the same datasheet gives the same bytes.

`cheme validate` reports a drawing that is no longer what its datasheet gives
(`cheme.datasheet-drawing-stale`, warning). A datasheet without a drawing is not reported
unless a gate requires it.

## Checks

All warnings, each naming the datasheet, the line and the item's tag:

- `cheme.datasheet-dimension-mismatch`: a main dimension against the equipment list's
  `dimensions`, with the tolerances of `domains/equipment/dimensions.py`: a size stated twice
  (outside diameter, an overall size, the empty weight) within `SAME` (5 %); an inside
  diameter within `DIAMETER` (15 %) and not above the outside one; a tangent or tube length
  between `SHORT` (50 %) and `FIT` (105 %) of the overall size; plates not beyond it; head and
  support types the same.
- `cheme.datasheet-dimension-layout`: against `layout/plant-model.yaml`: the outside diameter
  against the model's shell, the overall sizes against the item's box, a tangent or tube
  length not longer than the model's extent.
- `cheme.datasheet-nozzle-pid`: a datasheet nozzle the P&IDs do not draw on the item, a drawn one
  the datasheet does not list (once it lists any), a different DN or different lines (only when every P&ID loads).
- `cheme.datasheet-nozzle-line`: a line of a nozzle that the line list does not have (one the
  P&ID draws there is the lines cross-check's finding).
- `cheme.datasheet-nozzle-duplicate`, `cheme.datasheet-unit`: a nozzle listed twice, a unit
  that is not read.
- `cheme.datasheet-nozzle-layout` (as before): nozzle locations against the layout model.

## The gate

`kind: datasheets` keeps its meaning (one final, valid datasheet per listed item) and can
require more at a stage with `require:`:

```yaml
- id: datasheets
  title: Datasheets with dimensions, weights and current drawings
  stage: detail
  kind: datasheets
  require: [dimensions, weights, nozzle-schedule, drawing-current]
```

- `dimensions`: the main dimensions of each item's family: a diameter, the tangent length, head
  and support type (and the sections of a column); a shell-and-tube's shell ID and tube length,
  count, OD and passes; a plate exchanger's plate height, width and count; a machine's
  baseplate and shaft height; anything else an overall height or length. A `supplier` or
  `not_applicable` marker counts as given, a `TBD` does not.
- `weights`: empty and operating, and the test weight of a vessel, column, tank or
  shell-and-tube exchanger.
- `nozzle-schedule`: every nozzle with a DN and a face, a side nozzle with its orientation and
  elevation.
- `drawing-current`: every outline drawing what `cheme datasheets drawing` writes.

## In the viewer API

- `GET /api/datasheets?rev=`: `{rev, directory, datasheets: [{tag, file, valid, type, service,
  draft, counts: {assumed, tbd, supplier, not_applicable}, nozzles, has_dimensions,
  has_weights, drawing, has_drawing, drawing_current, findings: {error, warning, info}}],
  missing: [tags], source}`; 404 without datasheets. `GET /api/repo` says `has_datasheets`.
- `GET /api/datasheets/{tag}?rev=`: `{rev, tag, file, summary, datasheet (parsed, null when it
  does not validate), data (the file as JSON), drawing: {file, state, current}, findings,
  source}`.
- `GET /api/datasheets/{tag}.svg?rev=`: the committed drawing (`X-Cheme-Drawing: committed`,
  `X-Cheme-Drawing-Current: true|false`), or the generated one when none is committed or with
  `generated=true` (`X-Cheme-Drawing: generated`); 422 for a datasheet that does not validate.

The findings are computed on a private copy of the revision's inputs (`plant.yaml`, the
equipment and line lists, the layout model, the P&IDs, the datasheets and their drawings) and
cached by their blob ids. `cheme export-static` exports all three for every datasheet; a
datasheet whose YAML or drawing an `--exclude` glob matches is left out, of the index too.
