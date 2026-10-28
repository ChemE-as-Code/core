# MTO and estimate

`cheme assess` derives the assessment from committed files: the material take-off of the 3D
model, its factor estimate, the equipment cost estimate and the [LCA](../framework/lca.md).
cheme-as-code ships no prices and no factors: every rate, cost index and factor is the
project's, with its status, source and year.

```sh
cheme assess mto [--write]         # take-off of layout/plant-model.yaml: pipe, fittings, valves, steel, ...
cheme assess estimate [--write]    # the take-off priced with estimate/rates.yaml, then its factors
cheme assess equipment [--write]   # equipment costs from published correlations (Turton et al.)
```

`--write` puts the results into `estimate/`; the gate `kind: mto` checks that they are current.
The inputs are the kinds [`rates`](../reference/schemas.md#rates) (`estimate/rates.yaml`) and
[`cost_basis`](../reference/schemas.md#cost-basis) (`estimate/cost-basis.yaml`); the options are
in the [CLI reference](../reference/cli.md#cheme-assess).

The rows, rules and `GET /api/mto` are described in [MTO](../framework/mto.md); equipment sizes
that the estimate needs come from the datasheets, see [Sizing](../framework/sizing.md).
