# 0028. Composition limits in property package claims

- **Status:** Accepted
- **Date:** 2026-10-27

## Context

A property package (`domains/process/property_packages.py`) claims components, binary pairs and
per-component temperature-pressure boxes, each benchmarked against an authoritative reference.
For the ammonia synthesis loop, `syngas-pr-vapor` must claim ammonia in mixtures with H2, N2, Ar
and CH4. Peng-Robinson (thermo, ChemSep kij) agrees with the reference mixture models (Neumann et
al. 2020) and with measured data only for dilute ammonia:

- the pure-ammonia boxes stop at 15 MPa below 500 K and at 20 MPa below 600 K (dense fluid,
  where Peng-Robinson drifts), but 3-25 % ammonia in hydrogen and nitrogen stays within 3 %
  from 375 K at 10 MPa and from 500 K at 20 MPa;
- Ar-NH3 misses by more than 3 % above about 5 MPa unless argon is minor;
- methane-rich ammonia gas misses the enthalpy tolerance.

Methane above its reference equation's 625 K is backed by measured densities only for a gas with
about 20 % methane (Cheng et al. 2019, 673.1 K). A temperature-pressure box per component and a
list of pairs cannot say "only while dilute", so the choice was between refusing loop gas,
claiming states that fail the benchmark, or making the claim depend on composition.

## Decision

A package claim may limit composition in two ways, both optional and additive in the schema:

- `Region.max_mole_fraction`: a component's box holds only while its mole fraction is at most
  this. A box without it holds at any mole fraction (pure-fluid boxes).
- `ApplicationRange.pair_limits`: pair -> component -> the largest mole fraction of that
  component in a mixture holding both at which the pair is claimed.

`props.range_problems` refuses a state outside them (`property-out-of-range`) and names the
limit exceeded; `--coverage`, `--fill`, `--check` and the maturity regime checks go through it.
Each limit is the composition the benchmark test covers: the test evaluates every claimed box
at the compositions it limits, and a failing point narrows a box or a limit, never the
tolerance. Unset, neither field enters the method fingerprint, so methods recorded before this
keep their fingerprints.

A reference mixture model that CoolProp lacks may be loaded into CoolProp in the test from its
published parameters (in `tests/data/`, with the publication, table and page), provided the test
checks the loaded model against the published equation and against measured data. The model is
test evidence only; it is never a runtime method.

## Consequences

- Positive: ammonia converter and loop gas (dilute NH3 with H2, N2, CH4 and Ar) is calculated
  and benchmarked instead of refused; hot methane is claimed exactly as far as measured.
- Positive: a refusal tells the agent which limit a stream exceeds.
- Negative: a claim is no longer a set of boxes alone; readers of `application_range` (the
  maturity checks, `--coverage`) must pass the mole fractions, which they do through
  `range_problems`.
- Known limitations: carbon monoxide above 500 K stays unclaimed (no reference equation or
  measured densities found), as does methane above 673.1 K, so the methanol reactor outlet and
  the hottest ammonia converter gas are refused; pre-release issue 315.

## Evidence

- Part of pre-release issue 315 (part C), extending pre-release PR 154.
- `src/chemeascode/domains/process/schema.py` (`Region`, `ApplicationRange`),
  `property_packages.py` (`limit_gaps`, `region_gaps`, `SYNGAS`), `props.py`
  (`range_problems`, `method_fingerprint`).
- `tests/test_property_packages.py`, `tests/data/syngas_references.yaml`.
