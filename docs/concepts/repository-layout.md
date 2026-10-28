# Repository layout

A plant repository holds the whole design as text files: P&IDs as DEXPI 2.0.1 XML, everything
else as YAML with a schema, decisions and reviews as Markdown. There is no database and no
server-side state; git is the history, branches are design alternatives, and pull requests are
design reviews.

The table below is the template's own map of the repository, as `cheme init` writes it:

<!-- include: src/chemeascode/templates/project/README.md :: # {{plant_name}} | body | intro -->

Optional files join as the design advances: the 3D layout (`layout/site-plan.yaml`,
`layout/building.yaml`, `layout/equipment-placement.yaml`, ...; see [3D layout](../guides/layout.md)),
equipment datasheets in `equipment/datasheets/`, the estimate inputs in `estimate/`, the LCA in
`lca/` and the electrical list in `electrical/`. Every YAML kind, the file it lives in and its
fields are listed in the [schema reference](../reference/schemas.md); `cheme schema` prints the
same list.

Generated files are committed with their inputs (the BFD and PFD in `process/`,
`layout/plant-model.yaml`, `estimate/mto.csv`), so a diff shows what changed and `cheme impact`
can tell when they are out of date. Scratch output (`cheme render`, `cheme diff`) goes to
`build/`.
