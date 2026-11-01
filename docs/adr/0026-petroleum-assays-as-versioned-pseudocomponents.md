# 0026. Petroleum assays characterised into versioned pseudocomponents, claimed only where benchmarked

- **Status:** Accepted
- **Date:** 2026-10-27

## Context

Naphtha and heavier petroleum fractions are mixtures no database identifies compound by
compound. Both execution routes of cheme-as-code, the thermo flash of `cheme process phase` and
the DWSIM simulation, need identified compounds and refuse a petroleum fraction
(`thermodynamics/methods.yml`, regime `petroleum_pseudocomponents`). Process-library
case studies on naphtha and heavy fractions (process-library#176, #181) need at least a
characterisation of the fraction with known provenance, and a flash whose accuracy is known.

Characterising an assay into pseudocomponents is established practice, with published
correlations (Riazi-Daubert, Kesler-Lee, Twu) and conversions between distillation methods
(API Technical Data Book procedure 3A1.1). None of them is in `thermo` or `chemicals`, which
provide the building blocks (the Lee-Kesler acentric factor, the Lastovka-Shaw ideal-gas heat
capacity from a similarity variable, cubic equations of state). The options were: hand the
assay to DWSIM's own characterisation (a second, uninspected method on the simulation route
only, with no pseudocomponent input in `simulation.yaml` yet), or characterise in
cheme-as-code with named correlations and flash through thermo.

## Decision

- An assay is a file in the plant repository: `process/assays.yaml`, schema `cheme/assay/v1`
  (`cheme schema process-assays`). Each assay names its `source` and gives either a TBP or
  ASTM D86 curve from 0 to 100 % distilled with the fraction's density (or Watson K), or its
  cuts with volume, normal boiling point and specific gravity each. A measured molar mass is a
  check, not an input.
- `domains/process/thermodynamics/assay.py` characterises it deterministically: D86 to TBP by
  API 3A1.1, cuts of equal liquid volume, one Watson K per curve, Riazi-Daubert (1987) molar
  mass, critical constants and C/H ratio, Lee-Kesler acentric factor, Lastovka-Shaw ideal-gas
  heat capacity through thermo. Every correlation is named with its citation
  (`assay.CORRELATIONS`) and every pseudocomponent property carries the id of the correlation
  that gave it.
- Nothing is extrapolated. An insufficient assay is refused with `cheme.assay-insufficient`; a
  pseudocomponent outside the range the correlations were fitted for
  (`assay.RANGES`) refuses the assay with `cheme.assay-extrapolation`. No pseudocomponent is
  produced from a refused assay.
- A characterisation carries `METHOD_VERSION` and the 16-hex fingerprint of the method version
  and the assay's inputs (not its id, title or source). A pseudocomponent's identity is
  `pseudo:<fingerprint>:<n>`. `cheme process assay --fill` records the characterisations in
  `process/assay-characterization.json` (schema `cheme/assay-characterization/v1`); `cheme
  validate` and `--check` report a record made from other inputs or by another method version
  (`cheme.assay-record-stale`). `assay.comparability` names what differs between two
  characterisations; a flash result carries the fingerprint it was made from.
- The flash of the pseudocomponents is Peng-Robinson through thermo with kij = 0. It is claimed
  only inside `assay.FLASH_CLAIM` (temperature, pressure, pseudocomponent boiling points and
  gravities, properties and tolerances), which a test benchmarks against CoolProp's reference
  multi-fluid models of defined naphtha surrogates. A state outside is computed and reported
  outside the claim. `methods.yml` records the regime as `limited` for the assay route; the
  phase and simulation routes stay `unsupported`.
- The pure-component routes do not import the assay module and keep refusing
  pseudocomponents, so the ethane-cracker and gas routes do not depend on it.

## Consequences

- Positive: an agent can write a sourced assay, get pseudocomponents with traceable
  properties, and see at once when the assay is insufficient, extrapolated or changed since a
  result was made.
- Positive: the flash claim is as narrow as its benchmark: a reader knows which properties hold
  within which tolerances, and what is not claimed (Peng-Robinson liquid density, states inside
  the two-phase region, light ends, heavy fractions).
- Negative: the flash benchmark compares with defined surrogates, not with a measured naphtha
  assay with phase-behaviour data; no openly accessible assay with measured molar mass and
  flash data was found. A published assay (TotalEnergies' Oman crude, 2020) checks the mass
  basis and density behaviour of a real heavy naphtha only. Naphthenes and aromatics are represented by one compound each.
- Negative: changing a correlation or coefficient changes every pseudocomponent identity:
  `METHOD_VERSION` must be raised, and recorded results become stale.
- Open: pseudocomponents in `simulation.yaml` (DWSIM), light ends (C5 and lighter, below the
  Riazi-Daubert range) and heavy fractions (above 650 °F, which need Riazi's or Twu's heavy-end
  correlations and their own benchmark).

## Evidence

- `src/chemeascode/domains/process/thermodynamics/assay.py`, `methods.yml` (regime
  `petroleum_pseudocomponents`), `interfaces/cli/process.py` (`cheme process assay`),
  `project/validate.py`.
- `tests/test_assay.py`, `docs/framework/assay.md`.
