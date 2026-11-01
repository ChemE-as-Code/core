# 0024. Adsorber performance basis: an equilibrium TSA cycle and external results, outside the simulation

- **Status:** Accepted
- **Date:** 2026-10-27

## Context

An adsorber (PSA, TSA) in `process/simulation.yaml` is a `component_separator`: the engineer
states its recoveries and DWSIM closes the balances around them. A converged flowsheet then says
nothing about whether the split is attainable, and the model basis reports it as
`component-split` (specified). Process-library work (the ASU front-end purification, hydrogen
PSA, gas dehydration) needs a basis that is calculated or at least checked, without making such
a model a prerequisite for a concept, a BFD or a sourced inventory.

Options considered: a dynamic PSA/TSA bed model (PDEs for breakthrough and cycles), which needs
kinetics and heat-transfer data that a design rarely has and a solver core does not ship; a
DWSIM unit operation, which DWSIM does not provide; coupling an external model as a unit inside
the DWSIM solve, as the fixed bed is coupled, which needs an outer loop; or a
calculation beside the simulation whose recoveries the `component_separator` carries.

## Decision

- A plant repository may hold `process/adsorption.yaml` (schema `cheme/adsorption/v1`,
  `chemeascode.domains.process.separations.schema`, `cheme schema process-adsorption`). It is
  optional; without it a sourced `component_separator` split stays the representation, labelled
  as specified.
- An entry with `technique: tsa`, `performance: calculated` is evaluated by core's equilibrium
  TSA cycle (`chemeascode.domains.process.separations.adsorption`, `cheme process adsorption`):
  local equilibrium from sourced isotherms (Langmuir, dual- and multi-site Langmuir, Sips, Toth,
  extended Langmuir or Sips within a layer), breakthrough at the stoichiometric time less half a
  measured mass transfer zone, the cyclic-steady-state balance for recoveries and product
  impurity, regeneration heat carried by the hot purge with an ideal thermal front, the purge
  needed to carry the desorbed components, and adsorbent replacement. Every isotherm states the
  temperature and partial-pressure range it was measured over; core evaluates it nowhere else
  and refuses the calculation instead (`cheme.adsorption-isotherm-range`).
- An entry with `performance: external` holds an external model's recoveries, utilities and
  operating range. Core checks the range, the balance and the specification; the performance
  stays the external model's. A calculated PSA is refused (`cheme.adsorption-unsupported`):
  core has no PSA cycle model.
- The simulation keeps the `component_separator`. When an entry qualifies (every case inside
  the ranges, the specification met, the regeneration feasible, every input sourced) and the
  simulator's recoveries agree with it within `split_tolerance`, the model basis reports
  `adsorption-equilibrium` (predictive, not simulated) or `external-performance` (specified);
  otherwise the basis stays as it was and the reason is a limitation. `predictive.model-basis`
  therefore still fails for an adsorber ("not in the simulation"): a calculated split is not a
  simulated one.

## Consequences

- Positive: a TSA's recoveries, regeneration duty and replacement rate follow from data with
  provenance; the report keeps prescribed and calculated performance apart; nothing new is
  required for conceptual work.
- Negative: a second place (the adsorption record) has to agree with the simulation spec; core
  reports a difference but does not write the spec.
- Known limitations: no thermal front, breakthrough dynamics, heat losses or PSA cycle; a
  component without an isotherm is treated as not adsorbed. The reference case (CO2 on 13X,
  NASA/TM-2017-219847 isotherm, US 6,506,236 mass transfer zone) is qualified for its
  equilibrium inputs and the cycle relations, not against a measured TSA cycle.
  Coupling the calculation into the DWSIM solve, as for the fixed bed, is a possible follow-up.

## Evidence

- `src/chemeascode/domains/process/separations/{schema,adsorption}.py`,
  `src/chemeascode/domains/process/model_basis.py` (`apply_adsorption`),
  `src/chemeascode/project/maturity.py`, `tests/test_adsorption.py`,
  `tests/test_adsorption_reference.py`, `docs/framework/maturity.md`.
