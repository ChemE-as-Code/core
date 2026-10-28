# 0025. Solids as components and a bounded crystallizer adapter outside the simulation

- **Status:** Accepted
- **Date:** 2026-10-27

## Context

Process-library cases (salts, fertilizers, pigments, hydrates; ChemE-as-Code/process-library#114
and the issues listed in pre-release issue 365) need crystallization and solid-liquid separation. The
process model had no solid phase: `thermodynamics/methods.yml` declares solid equilibrium
unsupported in the property routes, the DWSIM translation has fluid outlet roles only, and
`separations/coverage.py` listed crystallization and solid-fluid separation as specified splits
with no solids model. The options were a solids phase on every stream (a new stream state
field, a second composition), a full solid-liquid equilibrium or population-balance model, or
treating a solid as its own component and adding a narrowly scoped crystallizer model.

## Decision

- A solid is a component of `process/materials.yaml` with `phase: solid` (schema
  `cheme/process/v1`, additive): a crystal, or a hydrate whose formula carries its water of
  crystallization (`MgSO4(H2O)7`). It is a separate component from the same substance
  dissolved. Stream compositions, mass balances and provenance need nothing new; a stream's dry
  solid is the sum of its solid components and the rest is its liquid (mother liquor or
  moisture), computed by `domains/process/solids.py`, never written twice. No particle size,
  porosity or population balance is part of the contract.
- A block or step may carry `crystallizer:` (one solute, one solvent, one crystal form; optional
  evaporation, a specified filter or centrifuge and a mother-liquor recycle; a lumped energy
  balance) or `solid_separation:` (a filter or centrifuge on its own), not both.
  `domains/process/crystallization.py` solves them inside `cheme process propagate`; they are not
  translated to DWSIM. A crystallizer node is balanced on mass and elements, like a reactor.
- The model basis keeps prediction and imposition apart: `solubility-equilibrium` (predictive
  within sourced solubility data: interpolated in temperature, never extrapolated; the mother
  liquor leaves saturated), `imposed-yield` and `solid-split` (specified). Because the solved
  crystallizer is not part of a converged simulation, it caps `predictive.model-basis` ("not in
  the simulation"); a sourced imposed yield or solid split supports `balanced`.
- Cases outside the model (impurities or a second solute in the inlet, a temperature outside
  the solubility data, a hydrate formula that is not the solute plus n solvent) are refused with
  `cheme.process-crystallizer-unsupported` or `-unsolved`, and `cheme.process-propagate-
  crystallizer` in propagate, each naming file, line and hint.
- `cheme process crystallizers [--case] [--json]` reports each unit: basis, sources,
  assumptions, limitations, crystals formed and at equilibrium, recovery, recycle iterations and
  residual, mass, solute, solvent and element balances, duty terms and the outlets as dry solid,
  liquid and moisture.

## Consequences

- Positive: salt and hydrate crystallization trains close mass and element balances in the
  flowsheet with traceable solubility and separation data; recovery and mother-liquor recycle
  are calculated, and specified yields stay possible at a lower declared basis.
- Positive: no change to stream state or the DWSIM translation; existing flowsheets (the ASU
  examples) are unaffected.
- Negative: the dissolved and solid forms are two components, so a plant must declare both;
  mixing, splitting or heating a slurry elsewhere uses the existing pass-through rules, which do
  not dissolve or crystallize anything.
- Known limitations: no supersaturation, kinetics, crystal size distribution, several solutes,
  impurities, common-ion effects, polymorph or hydrate transitions, washing, heats of dilution or
  filtration rates; the energy balance uses a constant heat capacity and a given heat of
  crystallization. Solid-liquid equilibrium from a thermodynamic model (activity coefficients,
  electrolytes) stays unsupported (`methods.yml` `regimes.solid_equilibrium`).

## Evidence

- pre-release issue 365; `src/chemeascode/domains/process/{solids,crystallization}.py`, `schema.py`
  (`Component.phase`, `Crystallizer`, `SolidSeparation`), `model_basis.solids_basis`,
  `propagate.py`, `interfaces/cli/process.py` (`process crystallizers`).
- `tests/test_crystallization.py`: Felder & Rousseau (3rd ed.) Example 4.5-2, Geankoplis
  (4th ed.) Examples 12.11-1 and 12.11-2, refusals and the report.
- `docs/framework/maturity.md` (model basis table), `separations/coverage.py`.
