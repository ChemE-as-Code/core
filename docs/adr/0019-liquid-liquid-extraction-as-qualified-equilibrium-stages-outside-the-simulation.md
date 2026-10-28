# 0019. Liquid-liquid extraction as qualified equilibrium stages, solved by core outside the simulation

- **Status:** Accepted
- **Date:** 2026-10-27

## Context

Liquid-liquid extraction was covered only as a `component_separator` with given recoveries (a
specified split): the flash and the columns of `process/simulation.yaml` take vapour and liquid
roles only, and nothing in core solved a liquid-liquid stage (pre-release issue 369, from pre-release issue 137 and
process-library#114). thermo's multiphase flash (`thermodynamics.phase`) can find two liquids,
but it also searches for a vapour, needs vapour-pressure and volume correlations for every
component, reads interaction parameters only from its own databases, and has no stage or
cascade.

Options considered: (a) an extraction unit in the DWSIM translation (DWSIM's liquid-liquid
extractor needs an LLE-capable package with parameters for every pair, and its result would have
to be benchmarked per system again); (b) a core calculation on thermo's NRTL with the
parameters stated in a file, solved stage by stage; (c) keeping the specified split and asking
for recoveries from the literature.

## Decision

- cheme-as-code solves liquid-liquid extraction itself, in `separations.extraction`
  (`cheme process extract`): a unit of `process/extraction.yaml` (schema
  `cheme/extraction/v1`) is a feed and a solvent feed through countercurrent equilibrium stages
  at one temperature. Each stage is a liquid-liquid equilibrium (`separations.lle`: a
  tangent-plane stability test and a split) on thermo's NRTL
  (`integrations.thermo.nrtl_ln_gammas`), with the interaction parameters of an LLE system:
  bundled in `domains/process/data/lle-systems.yaml` or given in the unit (`model:`) with its
  source.
- A missing binary pair is refused, never taken as zero; a temperature outside the parameters'
  range is refused; a feed and solvent without a two-phase region are refused
  (`cheme.extraction-one-liquid`); a stage that ends with one liquid fails. Every refusal is a
  finding with file, line, rule id and hint.
- A result is `qualified` only for a bundled system whose `qualification` names a core test
  that benchmarks it against measured tie lines, inside the benchmarked temperatures and solute
  fractions of both phases; otherwise it is `unqualified` with the reasons. Parameters from a
  plant file are a predictive calculation, never qualified.
- The extraction unit boundary is the stages only: solvent regeneration is a separate unit, and
  the solvent feed is an input. No energy balance is evaluated (`energy: not-evaluated`): NRTL
  parameters fitted to tie lines do not qualify heats of mixing.
- The result does not enter `process/simulation.yaml` and does not change the maturity report:
  the flowsheet keeps a component separator (`component-split`, specified) whose
  `basis_source` cites the unit's `split_to_extract`. `separations.coverage` lists
  liquid-liquid extraction as `predictive` through the `extraction` calculation, tested.
- The first bundled system is water + 1-propanol + n-butyl acetate, with the NRTL parameters of
  Hajjar and Enders (Fluid Phase Equilib. 582 (2024) 114104, CC BY), benchmarked at 323.15 K
  against the tie lines of Costa et al. (J. Chem. Eng. Data 54 (2009) 2845, from its NIST
  ThermoML file) in `tests/test_extraction.py`.

## Consequences

- Positive: an agent can predict an extractor's raffinate, extract, recovery, solvent loss,
  distribution and selectivity from sourced parameters, with the boundary of the claim stated;
  a system without a two-phase region fails loudly instead of returning an invented split.
- Positive: adding a qualified system is data plus a benchmark test; no solver change.
- Negative: two places hold separator results (the simulation and the extraction file); the
  link between the extractor and its flowsheet separator is the `basis_source` citation and the
  informative `represents`, not checked by `cheme maturity`.
- Known limitations: isothermal, liquid only (the pressure is not used), no stage efficiency or
  hydrodynamics, NRTL only; one qualified system, whose benchmark data are among those its
  1-propanol pairs were fitted to (it qualifies the correlation as core evaluates it, not an
  unseen prediction); the solvent in the aqueous phase is over-predicted (qualified to 0.003
  mole fraction).

## Evidence

- pre-release issue 369; `src/chemeascode/domains/process/separations/extraction.py`, `lle.py`,
  `domains/process/data/lle-systems.yaml`, `integrations/thermo.py` (`nrtl_ln_gammas`),
  `interfaces/cli/process.py` (`process extract`).
- `tests/test_extraction.py`, `tests/test_extraction_lle.py`.
- `docs/framework/maturity.md` (liquid-liquid extractor), `separations/coverage.py`.
