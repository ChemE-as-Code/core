# plant.yaml

`plant.yaml` is the root of a plant repository: `cheme` finds the repository by looking for it
from the current directory upwards. It names the plant, the oldest cheme-as-code it works with,
the current stage and the list of stages, the title-block data and the sheets (P&IDs, and the
generated BFD and PFD by `kind`).

The template writes this file (`{{plant_name}}` and `{{cheme_minor}}` are filled in by
`cheme init`):

<!-- include-code: src/chemeascode/templates/project/plant.yaml yaml -->

The fields, their types and defaults are in the [schema reference](../reference/schemas.md#plant)
(`cheme schema plant`). How sheets are checked against `plant.yaml` (planned sheets, title-block
sheet numbers, generated sheets) is part of [P&IDs and DEXPI](../guides/pids.md) and
[Editing and generating sheets](../guides/editing.md).
