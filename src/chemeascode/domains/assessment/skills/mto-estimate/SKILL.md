---
name: mto-estimate
description: Take off the bulk materials of the 3D layout model and price them - cheme assess mto (pipe length by DN, class and insulation; elbows, tees, reducers, flanges and gaskets; valves by type and DN; steel tonnage by section; grating, insulation and concrete), cheme assess estimate (unit rates from estimate/rates.yaml, then direct, indirect and contingency factors) and cheme assess equipment (purchased and bare module equipment costs from the published Turton et al. CAPCOST correlations, escalated by the project's CEPCI). Use when an equipment cost estimate is asked for, when a material take-off, a bill of quantities, a bulk-material or factor estimate is asked for, when the gate mto fails, or after the layout model changed.
---

# Material take-off and estimate

## Purpose and when to use

Turn the committed 3D model (`layout/plant-model.yaml`) into quantities, and the quantities into
an estimate whose every number has a source. `cheme assess mto` counts what the model shows;
`cheme assess estimate` prices those quantities with the project's own unit rates and
applies the factor method. `cheme assess equipment` costs the equipment list from the
published correlations of Turton et al. (CAPCOST, 5th ed. 2018, Appendix A; package data with
the table and a cross-check per row): purchased cost, bare module cost, escalated by the cost
index the project gives. Use it for a material take-off or bill of quantities, a factor
estimate of the bulk materials, a comparison of two layouts by their quantities, when the gate
`mto` fails, and after every rebuild of the model that will be reported.

## Required inputs and missing inputs

- A current model: `cheme layout build` without `layout-model-outdated`, and the lines
  routed that the take-off should cover (`cheme layout report`). An unrouted line has no
  length, fittings or flanges in the take-off.
- `estimate/rates.yaml` (`cheme schema rates`) for an estimate: the currency, the cost year,
  one rate per take-off category (more where size, class or group change the price), and the
  factors. Every rate and factor needs `status` (`ASSUMED`, or `QUOTED` when a quotation backs
  it), `source` and `year`. The file `cheme init` writes is an **example** (`example: true`,
  currency `XXX`): its numbers price nothing.
- `estimate/cost-basis.yaml` (`cheme schema cost_basis`) for the equipment estimate:
  `cost_index: {value, year, source}` (the CEPCI of the estimate's year, as published: the
  package holds only the correlations' base, CEPCI 397 of 2001), `estimate_class` (AACE 18R-97,
  default 5), and per item where the lists cannot say it: `correlation`, `size` with
  `size_source`, `fm`/`fp`/`fbm` with `factor_source`, an own `cost` (a quotation, with
  currency, year, status, source) or `exclude: <reason>`. The size comes from the datasheet
  (`type_specific.area_m2`, `volume_m3`, `shaft_power_kw`, `fluid_power_kw`,
  `gas_flow_m3_s`, `duty_kw`; drafts from the lists: `cheme datasheets draft`, calculated
  sizes in them: `cheme datasheets fill`, skill `datasheets`), a vessel's
  volume else from its list dimensions (an upper bound, marked ASSUMED).
- **Never invent a price.** When the project has no rate for a category, leave the rows unpriced
  (the estimate reports them) and ask for a source: a quotation, the company's cost database, a
  published cost index or estimating handbook named with its edition and year. A number from
  memory is not a source.

## Workflow and tools

1. **Take off.** `cheme assess mto` (Markdown), `--csv`, `--json`. Read the totals first, then
   the findings: `mto-section-unknown` (members whose section has no mass per metre: their steel
   is not in the tonnage), `mto-no-pipes`.
2. **Check the counts against the model.** Look at the largest rows and at anything surprising:
   a DN with a long length but few pipes (a long rack run), many `bend <deg>` rows (pinned or
   skewed routes), a reducing tee whose branch is larger than its run (two lines meeting the
   wrong way), flanges much more than twice the valves plus the piped nozzles. Open the item in
   the viewer or `cheme layout render` before trusting it.
3. **What the take-off does not count.** It counts the model: pipe as routed (no allowance for
   field routing, small bore or vents and drains not on the P&ID), fittings at the bends and
   junctions it draws (no olets, couplings, spectacle blinds, weldolets for instruments),
   flanges at valves and piped nozzles (not at spool breaks), steel members with a section (not
   shoes, chairs, base plates, connections, tank and platform handrails drawn as rings), grating
   plan area, insulation of pipes (not of valves, flanges or equipment shells beyond the
   insulated cylinders the model draws), concrete of plinths, foundations, ring walls and bund
   walls (not paving, piles or sumps). Add allowances as factors or explicit rates, with the
   reason, not by editing the take-off.
4. **Rates.** In `estimate/rates.yaml`: the first rate of a category whose `where:` matches a
   row prices it, so order specific before general (`{item: "*Control*"}` before all valves,
   `{dn_max: 50}` before all pipe). Filters: `item`, `dn_min`, `dn_max`, `class`, `spec`,
   `group`. Units are fixed per category (pipe m; fittings, flanges, gaskets, valves, inline ea;
   steel t; grating and insulation m2; concrete m3). Record the cost year and escalate rates of
   other years yourself (the estimate reports them as `estimate-rate-year`, unescalated).
5. **Factors.** `kind: direct` with `applies_to: [categories]` (erection, testing, painting, on the
   materials of those categories), `indirect` (engineering, construction management, on the
   direct cost), `contingency` (on direct plus indirect). State the estimate's class and
   accuracy in `basis:`; the factors must fit it.
6. **Estimate.** `cheme assess estimate` (Markdown), `--csv`, `--json`. Resolve
   `estimate-unpriced` (add a rate, or say why the rows stay unpriced), read
   `estimate-rate-unused` (a rate shadowed by an earlier one).
6a. **Equipment.** `cheme assess equipment` (Markdown), `--csv`, `--json`. Each item
   says which correlation it takes and why (the DEXPI class; a shell and tube exchanger is a
   fixed tube sheet one unless its class says U-tube or floating head), where its size comes
   from, Fp, Fm, FBM, the purchased and bare module cost. Resolve the findings, never by a
   guess: `estimate-equipment-uncovered` (no correlation for the class, no size: give the size
   from the datasheet or the process, an own cost, or exclude with a reason),
   `estimate-equipment-range` (outside the correlation's range: not extrapolated; split into
   units within it and say so, or a quotation), `estimate-equipment-partial` (purchased cost
   only: the package data has no material or bare module factor for it, e.g. aluminium, a
   CS/SS combination, a tank: give `fm`, `fp` or `fbm` from the printed source with its page),
   `estimate-no-index` (no CEPCI: costs stay in 2001 dollars). The bare module cost includes
   the item's installation materials (piping, instruments, steel, insulation, ...) and labour
   and its indirects: do not add the bulk factor estimate on top for the same scope; use the
   take-off to check the bulk quantities, or to price them instead of the bare module factors
   in a later, detailed estimate. State the class: AACE 18R-97 class 5 (an equipment-factored
   estimate on a concept or basic design: -20 % to -50 % low, +30 % to +100 % high) unless the
   definition supports a better one.
7. **Write and gate.** `cheme assess mto --write` and `cheme assess estimate --write`
   write `estimate/mto.csv|md` and `estimate/estimate.csv|md`; commit them with the model. The
   gate `kind: mto` (`checks/checks.yaml`) requires `mto-current` (the CSV is what the current
   model gives), and once the project prices its plant `rates` (not an example, every row
   priced) and `estimate-current`. `cheme assess equipment --write` writes
   `estimate/equipment-cost.csv|md`; the gate requirements `equipment-current` and
   `equipment-covered` (every item costed, its own cost, or excluded with a reason, and a cost
   index given) belong to `kind: mto` as well.

## Validation and failure handling

- `cheme validate` checks `estimate/rates.yaml` against its schema (a rate's unit must be
  its category's; ids unique).
- `cheme assess mto --check` and `cheme assess estimate --check` exit 1 when the
  written files are not what the current model and rates give: rewrite them, never edit them.
- No model (`mto-model-missing`): build and commit the model first. No rates
  (`estimate-no-rates`): write them; the take-off alone still works.
- A finding you cannot resolve (an unknown section, an unpriced row) goes into the estimate's
  basis in `DESIGN.md` with its effect on the total, not into a silent allowance.

## Outputs and provenance

- `estimate/mto.csv` (columns category, item, dn, dn2, class, spec, group, count, quantity,
  unit, length_m) and `estimate/mto.md` (with the model's `output_sha256`).
- `estimate/estimate.csv` and `estimate/estimate.md`: every priced row with its rate id,
  status, source and year; every factor with its base; the totals; the findings.
- `estimate/equipment-cost.csv` (columns tag, type, correlation, size, unit, size_source,
  cp0_base, fp, fm, fbm, cbm_base, index_ratio, purchased, bare_module, status, notes) and
  `estimate/equipment-cost.md` (the class and its accuracy range, the source, the escalation,
  the items covered and not covered).
- `--json` adds the git commit and the fingerprints of the files it read (`source`).
  `GET /api/mto` serves the take-off (and the estimate when rates exist) of a committed revision.

## Required human judgment

Quantities from a layout model at concept or basic stage are incomplete by nature; the
allowances for what it does not count, the unit rates, their sources and escalation, the
factors, the estimate's class and accuracy, and the contingency are a cost engineer's
decisions. An agent may assemble and check the numbers and propose rates **only** from a source
the project gives it; it never presents an assumed price as a quotation, and never signs off
an estimate. Record who decided each rate and factor (their `source`) and review the estimate
like any other deliverable (skill `review`).

## References

- `cheme schema rates`, `cheme schema cost_basis`, `estimate/README.md`,
  `docs/framework/mto.md` (rows, rules, the API, the equipment estimate)
- R. Turton, J. A. Shaeiwitz, D. Bhattacharyya, W. B. Whiting, Analysis, Synthesis, and Design
  of Chemical Processes, 5th ed., 2018, Appendix A (the package data
  `domains/assessment/data/turton-capcost.yaml` cites the table of each row)
- AACE International Recommended Practice No. 18R-97, Cost Estimate Classification System
- `docs/framework/layout-model.md` (what the model holds)
- skills `pipe-routing`, `structures-access`, `layout-yaml`, `review`
