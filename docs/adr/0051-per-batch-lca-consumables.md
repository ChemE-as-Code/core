# 0051. Per-batch LCA exchanges are consumables per batch of the recipe

- **Status:** Proposed
- **Date:** 2026-11-05

## Context

A batch plant uses things per batch that its flowsheet does not carry: cleaning solvent, rinse
water, nitrogen purges, the make-up of an off-spec or rework share (core#158 package 5). The
LCA (`lca/lca.yaml`) has consumables per year or per replacement, and the TEA has variable opex
`per: batch`. A per-batch amount written as a year figure hides the batch count it rests on,
and when the cycle changes, nothing tells you the figure is stale.
The process library's ADR 0035 asked for per-batch flows as year-average streams until core
had this.

Options considered:

1. A `per: batch` key on every LCA exchange kind (flows, emissions, consumables). Only
   consumables are amounts the flowsheet does not already carry; flows and emissions follow the
   flowsheet.
2. Year-average streams in the flowsheet. They work today, but the per-batch amount and the
   batch count sit only in a `source` text.
3. `consumables: [{per_batch: ...}]`, converted with the recipe's batches per year.

## Decision

- An `lca.yaml` consumable may give `per_batch` (an amount in its `unit`) instead of
  `per_year` or `per_replacement`, alone or with an `initial_charge`. The name follows the
  consumable's own `per_year`; it means what the TEA's `per: batch` means.
- Per hour of the flowsheet's year averages it is `per_batch x batches per year / hours`, taken
  from `process/recipe.yaml` (`cheme process recipe`, ADR 0049). That is the same basis as the
  flowsheet, so the LCI per kg does not depend on `operation.hours_per_year` of the study. The
  exchange's source records the arithmetic ("500 kg per batch x 1000 batches in 8000 h
  (process/recipe.yaml, bottleneck ...)").
- Without a recipe, or with one that gives no cycle, the consumable is left out and the error
  `cheme.lca-per-batch` says why. It never silently counts as zero.
- Disposal, uncertainty, background and cut-off work as for any consumable.

## Consequences

- Positive: a change of the cycle (dosing time, a heat-up from the jacket, parallel units)
  changes the per-batch exchanges with it. The batch count is visible in the dataset.
- Negative: the per-batch amounts are not scaled with the batch size. A larger batch with the
  same rinse is the same `per_batch`, which is usually right for a rinse and wrong for a wash
  proportional to the cake (give it per kg as a flowsheet stream then).
- Follow-up: a library entry that wrote per-batch flows as year-average streams (process-library
  ADR 0035) may move them to `per_batch` consumables once this is released.

## Evidence

- core#158 package 5; this ADR's PR (stacked on ADR 0050's).
- `src/chemeascode/domains/assessment/lca/schemas.py` (`Consumable.per_batch`),
  `inventory.py` (`_batches`, `_supplies`).
- `tests/test_lca_inventory.py::test_a_consumable_per_batch_follows_the_recipe`.
