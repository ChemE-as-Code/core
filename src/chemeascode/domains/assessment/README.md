# Assessment

**Scope.** Economic evaluation and costing, summaries of utility consumption, interfaces to
environmental assessment and LCA, and the comparison of design alternatives.

**Artifact types.** A material take-off (`estimate/mto.csv`), a cost estimate with its basis
and year (`estimate/rates.yaml`, `estimate/estimate.csv`), a utilities summary, a comparison of
alternatives (each alternative a branch or a set of files at a revision).

**Related code today.** The material take-off of the generated 3D layout model and its
estimate by the factor method, and the equipment estimate from the published Turton et al.
correlations (`equipment_cost.py`, package data `data/turton-capcost.yaml`) (`mto.py`,
`estimate.py`, `schemas.py` for `estimate/rates.yaml` and `estimate/cost-basis.yaml`,
`gates.py` for `kind: mto`, `data/steel-sections.yaml`, skill `mto-estimate`;
[mto.md](../../../../docs/framework/mto.md)). The LCA of the operation (`lca/`: schemas of
`lca/lca.yaml` and `lca/factors.yaml`, the foreground inventory from the flowsheet's terminals,
allocation, characterisation with the project's factors, `kind: lca` gate;
[lca.md](../../../../docs/framework/lca.md)). The techno-economic analysis (`tea/`: schema of
`estimate/tea.yaml`, the capital build-up from the equipment or take-off estimate, the
discounted cash flow with NPV, IRR, LCOP and payback in `model.py`, break-even, tornado and Monte
Carlo, the comparison of two analyses' basis, `kind: tea` gate, skill `tea`;
[tea.md](../../../../docs/framework/tea.md)). The feed and product rates of the flowsheet both
read are in `flows.py`. The take-off reads `layout/plant-model.yaml` as a
file (the contract in `docs/framework/layout-model.md`), so this domain imports no `spatial`
code. Other inputs exist: the equipment list and datasheets (`equipment`), and stream tables and
balances (`process`).

**What will live here.** Cost correlations that take explicit, unit-bearing inputs and return
the estimate with its correlation, year and assumptions; summaries that read the balances
`process` computes.

**Out of scope.** Recomputing balances or utility duties: those come from `process`. Market
forecasts, project financing structures (gearing, debt schedules) and company-specific cost
data: the TEA takes prices and rates as the project's premises. An LCA engine itself; only an adapter to one
in `integrations/`.

May import: `requirements`, `process`, `equipment`. See
[the architecture](../../../../docs/framework/architecture.md).
