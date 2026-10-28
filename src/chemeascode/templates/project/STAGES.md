# Stages

The stages are listed in `plant.yaml`; the gates of each are in `checks/checks.yaml`. A gate on
P&ID content is `kind: on-sheet` (tags and classes found in the model), never a `grep` over the
XML: DEXPI builds printed tags such as `AIA-3103` from several attributes, so grep finds ids,
not tags.

A stage is **reached** when its sign-off (`cheme check --stage <stage> --write`, an entry in
`checks/status.json`) is on the default branch. Stage work is done on a branch
`stage/<stage>-<topic>`; the sign-off is its last commit, and the branch is merged by a human or
the reviewer, not by its author (see `AGENTS.md`). A sign-off left on an unmerged branch has not
taken effect.

## concept: Concept and feasibility
Design basis agreed (assumed values marked `ASSUMED`), block flow (`process/flowsheet.yaml`, the
generated BFD, balances evaluable and clean), main equipment identified, the equipment, line and
instrument lists and `DESIGN.md` started (gates `design-basis`, `concept-lists`,
`assumptions-marked`, `process-concept`, `process-balances`; `process-links-concept` reports
unresolved links). The plot plan: the site, its areas, roads and pipe racks, every
equipment-list item placed and the spacing criteria declared as `separations:` (gate
`layout-plot-plan`, skill `layout-yaml`). Economics: the decision the next stage needs stated,
an AACE class 5 capital estimate, the prices of the main feeds and products with their sources,
and a screening TEA showing which premises dominate (`estimate/tea.yaml`, skill `tea`).

## basic: Basic engineering
PFD generated with no refinement pending and no stale calculated values (`process-basic`), every
flowsheet link resolved (`process-links`), P&IDs complete and valid, equipment and line lists
complete, design review done. The 3D layout (gate `layout-3d`): `layout/plant-model.yaml`
built from the current inputs and committed, every piped nozzle positioned (from the P&ID side
or an override), every elevated item mounted on a building or structure level, every process
line of DN 25 and above routed or skipped with a reason (utilities follow at detail), no clash
or headroom finding left unaccepted, zones declared (`layout/zones.yaml`, skill
`area-classification`), and a layout review (topic `layout`, gate `layout-review`) that cites
the rendered plot plan and at least two sections (skills `pipe-routing`, `structures-access`,
`review`). The material take-off (`estimate/mto.csv`, skill `mto-estimate`) is rewritten from
the committed model (gate `mto`). Economics: a class 4 capital estimate (equipment costed from
datasheet sizes, OSBL and owner's cost stated), every flow priced or listed free, the TEA's
uncertainty and break-even values reviewed against the decision (gate `tea`, skill `tea`).

## detail: Detail engineering
Datasheets (one `equipment/datasheets/<TAG>.yaml` per equipment-list item, format in
`equipment/datasheets/README.md`, `cheme schema datasheet`; gate `datasheets`), instrument
list, HAZOP actions closed. Every line routed, utilities and small bore included, still
without clashes (gate `layout-detail`). Every motor and instrument has a cable routed in trays
from its room, no tray over its fill, power and instrument trays kept apart
(`electrical/electrical-list.yaml`, skill `electrical-cabling`; gate `electrical`). Every
clad building is ventilated: air handling units, rooms with their air changes, ducts routed
inside the building within their velocity limits, louvres large enough (`layout/hvac.yaml`,
skill `hvac-ducts`; gate `hvac`). Where the plant documents its control: every loop and
sequence complete and every control reference resolved (`control/loops.yaml`,
`control/sequences.yaml`, `process/narrative.md`, `control/philosophy.md`; skills
`control-loops`, `control-sequences`, `control-narrative`; gate `control-complete`).
Economics: a class 3 estimate from quotations and the take-off, the TEA current with it, ready
for the investment decision.
