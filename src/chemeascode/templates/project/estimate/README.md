# Estimate

The material take-off of the 3D model and its estimate (skill `mto-estimate`).

| file | what | written by |
|---|---|---|
| `rates.yaml` | the project's unit rates and estimate factors, each with status, source and year (`cheme schema rates`) | people; the file `cheme init` writes is an **example** (`example: true`) and prices nothing |
| `mto.csv`, `mto.md` | the take-off of `layout/plant-model.yaml`: pipe by DN, class and insulation, fittings, flanges, valves, steel tonnage, grating, insulation, concrete | `cheme assess mto --write` |
| `estimate.csv`, `estimate.md` | the take-off priced with `rates.yaml`, then the factors (direct, indirect, contingency) | `cheme assess estimate --write` |
| `cost-basis.yaml` | the cost index (CEPCI value, year, source), the estimate class, and per item a size, factors, an own cost or an exclusion the lists do not give (`cheme schema cost_basis`) | people (none until the project has a cost index) |
| `equipment-cost.csv`, `equipment-cost.md` | the equipment list costed by the published correlations of Turton et al. (purchased and bare module cost), escalated by the cost index | `cheme assess equipment --write` |
| `tea.yaml` | the premises of the techno-economic analysis: the decision it supports, the basis (product specification, battery limits, scale, location, cost year), the capital build-up (ISBL from the equipment or take-off estimate, OSBL, owner's cost, contingency), the prices of the flowsheet's feeds and products, fixed operating cost, finance, uncertainty and scenarios, each value with status, source and year (`cheme schema tea`, skill `tea`) | people (none until the project prices its plant) |
| `tea.md`, `tea-cashflow.csv`, `tea-sensitivity.csv`, `tea-uncertainty.csv` | the analysis: capital cost, cash flow, NPV, IRR, LCOP, payback, scenarios, tornado, break-even values, P10/P50/P90 | `cheme assess tea --write` |

Never edit `mto.*` or `estimate.*` by hand: rebuild the model (`cheme layout build`), then
rewrite them. The gate `kind: mto` (`checks/checks.yaml`) checks they are current; the gate
`kind: tea` checks the analysis (prices, estimate class against the stage, decision, current).
