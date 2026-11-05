# 0051. A batch recipe in process/recipe.yaml derives the cycle time; the flowsheet holds year averages

- **Status:** Proposed
- **Date:** 2026-11-05

## Context

A batch plant's TEA took `operation.batch.cycle_time` by hand, and nothing in cheme-as-code
derived it (core#158). The flowsheet's rates had no stated relation to a batch. The TEA read
them as "one batch over `basis_hours`", and the semi-batch model (ADR 0050) reads them as "per
hour of charge". The balance, the LCI per kg and the TEA could therefore rest on different
bases without any check saying so. The process library's batch entries (fine chemicals, NBS
first) need a declared batch size, a recipe and a cycle time from it.

Options considered:

1. The recipe inside `process/flowsheet.yaml`. That mixes a time-ordered recipe into the
   steady-state flowsheet, and every flowsheet consumer would have to skip it.
2. A full ISA-88 model (procedures, unit procedures, operations, phases, equipment modules,
   control recipes). This is far more than a concept or basic design needs, and it belongs to
   control (`domains/control`, sequences) when it is needed.
3. A separate `process/recipe.yaml` with the batch size, the operating hours and the unit
   procedures with their ordered operations. Only the ISA-88 names are borrowed. The
   flowsheet's rates become the year averages of the recipe.

## Decision

cheme-as-code takes option 3 (`domains/process/recipe.py`, schema `cheme/recipe/v1`).

- **File**: `batch_size: {value, unit: kg | t | m3, stream, provenance, source}` (the amount of
  one stream per batch), `hours_per_year: {value, provenance, source}`, and `unit_procedures`.
  Each unit procedure is `{id, unit, parallel, start, operations}`. `unit` is a flowsheet block
  or step, and `parallel` is the number of units that take batches in turn. Each operation is
  `{id, kind, duration | from}`, where the kind is one of charge, heat, dose, react, cool,
  transfer, filter, dry, clean, hold or other. `from: STEP` gives a dose's or a reaction's time
  from that batch or semi-batch step's model: the dosing time, or the reaction time (the
  post-reaction of a semi-batch; solved when the batch ends at a target). A heat-up or
  cool-down time from the jacket comes with package 3 of core#158. Until then those durations
  are given.
- **Basis**: the flowsheet's rates are the year averages of the recipe: a stream's kg/h is the
  amount one batch makes of it times the batches per year over the hours. The semi-batch's
  "per hour of charge" is that same basis, since its model is intensive in the composition.
- **Derived** (`cheme process recipe`): each unit's occupancy per batch (the sum of its
  durations), its cycle (occupancy / parallel), the cycle time (the largest cycle: the
  bottleneck), the batches per year (hours / cycle time), each unit's utilisation, and one
  batch's timeline. A unit procedure starts when the previous one starts its `transfer` (else
  when it ends), or at its `start: {after, operation}`. The command also gives the batch-size
  stream's year-average rate and a Gantt chart of one batch (`--svg`, light and dark, like the
  other figures).
- **Findings** (`cheme.recipe-*`, through `cheme validate` with the process rules): `-schema`;
  `-reference` (an unknown unit, stream, `from:` or `start.after`, a `from:` that is no batch, a
  dose from a batch, a duplicate id); `-duration` (the model does not solve); and `-basis`. The
  `-basis` finding is a warning when the flowsheet's flow of the batch-size stream differs from
  batch size x batches / hours by more than 1 %, and info when there is no flow to compare. An
  m3 batch size is compared on the liquid volume from the components' molar volumes.
- **TEA**: `operation.batch: {recipe: true, source}` (no `cycle_time`, `basis_hours` or
  `batches_per_year`) takes the cycle time and batches per year from the recipe, with
  `basis_hours = hours / batches` and `trains = 1`, since the parallel units are already in the
  recipe's cycle. Their source names `process/recipe.yaml`. The hand-entered form stays valid.
  `cheme.tea-batch-recipe` is an error when the recipe gives no cycle, and a warning when it
  runs on other hours than `operation.hours_per_year`.

## Consequences

- Positive: the cycle time and the batches per year are derived, and the dosing time comes
  from the reactor model, so changing the dosing changes the cycle. One basis is checked
  between the flowsheet, LCI and TEA.
- Positive: the recipe is small and declarative. An agent writes it from a patent's or a
  textbook's procedure.
- Negative: every unit procedure runs once per batch, with no recycling of the same vessel for
  several operations of one batch at different points (a vessel used twice is two unit
  procedures on one unit, and their occupancies are not added).
- Limitations: no campaign scheduling of several products on one train (core#158 package 6);
  no shared equipment across products; no batch-to-batch variation; the batches per year are
  not rounded down to whole batches.
- Follow-ups: heat-up and cool-down durations from the jacket (package 3); per-batch LCA
  exchanges converted with the batch size (package 5).

## Evidence

- core#158 (plan), this ADR's PR (stacked on ADR 0050's).
- `src/chemeascode/domains/process/recipe.py`, `interfaces/cli/process.py` (`process recipe`),
  `domains/process/model.py` (rules), `domains/assessment/tea/build.py` (`_recipe_batch`),
  `domains/assessment/tea/schemas.py` (`Batch.recipe`).
- `tests/test_recipe.py`; `examples/process-semibatch/process/recipe.yaml`.
