---
name: separation-method-selection
description: Screen and rank separation methods and sequences (conventional and intensified distillation, DWC/TCD, heat-pump and membrane-assisted options) for a binary or multicomponent mixture with the Li, Somoza-Tornos and Kiss (2025) decision matrix, from retrieved property data and the screening questions Q1-Q7. Use when separation methods or a distillation sequence have to be selected or justified.
---

# Separation method selection

## Purpose and when to use

Implements Li, Somoza-Tornos & Kiss (2025), "A systematic selection and decision matrix for
energy-efficient intensified distillation technologies", CPPM 20(2): 293-307: the high-level
screening, the PI matrix with a COP estimate for HPAD/HIDiC, the azeotrope-specific methods for
binaries, and for ternaries the distillation sequence efficiency (DSE), DWC/TCD scoring and the
PI matrix per adjacent pair. Use it to screen candidates for a separation block of the
flowsheet. The result is a ranking to discuss, not a design.

## Required inputs and missing inputs

Retrieved numeric values for every component, never estimates or the functions' defaults:
normal boiling points (K), melting points (for Q1), heats of vaporisation (kJ/mol),
viscosities (mPa s), the relative volatility of each adjacent pair (from vapour pressures and
activity coefficients, never from boiling points), feed mole fractions, the operating pressure
(bar, absolute), target recovery and purity (0-1), the minimum or operating reflux ratio, and
for a ternary the middle-key fraction. If one is missing, request it before calling, or
retrieve the numeric ones (step 2b).

## Workflow and tools

1. Answer Q1-Q7, each with a flag and a one-sentence justification backed by numbers:
   - Q1 solidification: `has_solidification_risk`;
   - Q2 non-condensables: `has_non_condensable`;
   - Q3 thermal sensitivity at the reboiler temperature: `has_thermosensitive`;
   - Q4 lightest component above 0.80 mole fraction: `large_light_fraction` (compare the
     number exactly: 69.81 mol% is 0.6981, false);
   - Q5 heaviest component above 0.80: `large_heavy_fraction`;
   - Q6 azeotrope, that is, the relative volatility crosses 1.0 (a positive deviation alone is
     not one: methanol/water and acetone/water are zeotropic, ethanol/water is azeotropic),
     and whether it is pressure-sensitive: `azeotrope`, `pressure_sensitive_azeotrope`;
   - Q7 the number of products: 2 for the binary function, 3 or more for the other.
2. Call the function:

```python
from chemeascode.domains.process.separations.selection import (
    select_binary_separation_methods,
    select_multicomponent_separation_methods,
)

r = select_binary_separation_methods(
    component_names=[...],
    molar_fractions=[...],
    boiling_points_K=[...],
    relative_volatility=...,
    heat_of_vaporization=[...],
    viscosity=[...],
    pressure=...,
    recovery=...,
    purity=...,
    reflux_ratio=...,
    azeotrope=False,
)
r.result.ranked_methods, r.result.high_level_assessment, r.assumptions, r.errors
```

2b. Or let the property sources fill the numeric inputs (NIST WebBook, the `thermo` package;
   GRAPPA and HANNA with their endpoints) and run the screening on them:

```python
from chemeascode.domains.process.separations.inputs import select_with_retrieved_properties

r = select_with_retrieved_properties(
    ["benzene", "toluene"],
    temperature_K=...,  # where viscosity and relative volatility are evaluated
    molar_fractions=[...],
    given={"relative_volatilities": [...]},  # your values win, entry by entry
    # your decisions, never retrieved: the flags, targets and reflux ratio
    azeotrope=False,
    recovery=...,
    purity=...,
    reflux_ratio=...,
)
r.input_provenance, r.missing_inputs, r.assumptions
```

   Every value carries its source (`caller`, `NIST`, `Thermo`, `GRAPPA`, `HANNA`, `Derived`);
   what no source gives stays missing (`missing_inputs` with the reason) and is passed as None,
   never as a default: the criterion it feeds is then not evaluated (`assumptions` says which).
   Without `temperature_K` viscosities and relative volatilities are not retrieved; diffusion
   coefficients have no source. An ideal relative volatility (no activity coefficients) is a
   warning: it cannot show an azeotrope; give alpha from VLE data for a non-ideal mixture. The
   components are reordered by normal boiling point; without all boiling points nothing runs.
   The Q1-Q7 flags stay yours (the melting points are retrieved to support Q1).

A YES to Q1, Q2, Q3, Q4, Q5 or (binary) Q6 resolves the selection in the pre-screen, and the PI
matrix is not evaluated. The binary function corrects Q4/Q5 from the mole fractions and warns
when `azeotrope` is set with a relative volatility well above 1. The multicomponent function
trusts the flags and has no azeotrope branch. There is no CLI command; the selection functions
need only the base dependencies (the `thermo` source of the retrieval needs the `props` extra).

## Validation and failure handling

- `r.errors` is set: an input was invalid; fix it and call again. Read `r.assumptions` (the
  guardrail corrections) before reporting.
- Never fabricate results or property values, and never leave the flags to the function.

## Outputs and provenance

Report the screening flags with their justification, the COP interpretation (3 or more
favourable, below 3 marginal), every method with a positive score in rank order, the excluded
methods with their reason, for a ternary the DSE result and each adjacent pair separately, and
the inputs used (with their provenance when retrieved). Record the selected method and its
basis in `DESIGN.md`; write the flowsheet block with `process-design`.

## Downstream representation (what core can model after the screening)

`r.result.downstream_representation` gives, for every method the result names (ranked methods
first), how core can represent it afterwards. The machine-readable table is
`chemeascode.domains.process.separations.coverage` (`SEPARATION_COVERAGE`, `coverage_table()`,
with units, fallback, notes and the test that solves each arrangement):

- **predictive**: the split follows from the property package (a `flash` or a rigorous
  `distillation_column` in `process/simulation.yaml`); only as good as the package (an
  azeotrope the package misses is predicted wrong: check with `phase-calculation`), or, for
  crystallization, a `crystallizer:` with `basis: solubility` on the flowsheet step (sourced
  solubility data, one solute in one solvent; `cheme process propagate` fills its outlets and
  `cheme process crystallizers` reports yield, recovery, balances and duty);
- **shortcut**: Fenske-Underwood-Gilliland (`shortcut_column`, `separations.shortcut`);
- **specified split**: a `component_separator` with given recoveries (`basis: specified`, a
  `basis_source` and an `operating_basis`); its convergence closes balances, it predicts
  nothing;
- **none**: no core model; keep it conceptual with sourced approximations, or use the
  `fallback` and state what it leaves out.

Each entry also has an **evidence** status: `tested` (a core test solves the arrangement) or
`untested` (the model form exists, no core test solves the arrangement), and `status` combines
both (`predictive (untested arrangement)`). An untested predictive arrangement (DWC, Kaibel,
E-/A-DWC, HiGee, HPAD, PSD, ED/AD, strippers and absorbers) is a model form, not an
established capability: say so when reporting it, and do not claim it as validated.

| Technique | Representation | Evidence | Units | Heat integration | Left out |
|---|---|---|---|---|---|
| ConvDist | predictive | tested | `distillation_column`, `shortcut_column` |  |  |
| Distillation sequences | predictive | tested | `distillation_column`, `shortcut_column` |  |  |
| Vacuum distillation | predictive | tested | `distillation_column` |  | thermal degradation |
| High pressure distillation column | predictive | tested | `distillation_column` |  | freezing (no solid phase) |
| Preconcentration column | predictive | tested | `distillation_column` |  |  |
| Two columns with second distillate recycled back | predictive | untested | `distillation_column` |  |  |
| Partial condenser | predictive | tested | `distillation_column`, `flash` |  |  |
| PSD | predictive | untested | `distillation_column` |  | azeotrope only if the package has it |
| ED/AD | predictive | untested | `distillation_column` |  | entrainer selection; azeotrope as PSD |
| DWC | predictive | untested | `distillation_column` |  | as the thermally coupled equivalent; no wall unit |
| TCD | predictive | tested | `distillation_column` | modelled |  |
| Kaibel column | predictive | untested | `distillation_column` |  | as DWC |
| E-DWC | predictive | untested | `distillation_column` |  | as DWC and ED/AD |
| A-DWC | predictive | untested | `distillation_column` |  | as DWC and ED/AD |
| HPAD | predictive | untested | `distillation_column`, `compressor` | screening only (COP) | column predictive (untested arrangement); heat pump: screening estimate only |
| HIDiC | none | not applicable |  | screening only (COP) | internal heat transfer (fallback: a plain column) |
| CyDist | none | not applicable |  |  | cyclic operation (fallback: a steady-state column) |
| HiGee | predictive | untested | `distillation_column` |  | rotating bed mass transfer and sizing |
| MAD | specified split | untested | `distillation_column`, `component_separator` |  | membrane permeance and area |
| Flash | predictive | tested | `flash` |  |  |
| Evaporation | predictive | tested | `heater`, `flash` |  | evaporator rating |
| (Steam) stripping | predictive | untested | `distillation_column` |  |  |
| Absorption | predictive | untested | `distillation_column` |  | rate-based and reactive absorption |
| Liquid-liquid extraction | predictive | tested | `extraction` (`cheme process extract`) |  | solvent regeneration (a separate unit); in the flowsheet still a `component_separator` (specified split) citing the extraction result; qualified only for a benchmarked LLE system (`--systems`) |
| Membrane separation | specified split | untested | `component_separator` |  | permeance, selectivity, area |
| Adsorption | specified split | tested | `component_separator` |  | isotherms, breakthrough, PSA/TSA cycle |
| Crystallization | predictive | tested | `crystallizer` (flowsheet) |  | population balance, kinetics, several solutes or impurities |
| Drying | specified split | untested | `component_separator` |  | dryer, solids |
| Solid-fluid separation | specified split | tested | `solid_separation` (flowsheet) |  | filtration, centrifuge, cyclone and settling models |

Report the representation of the selected method beside the ranking; when it is a specified
split or none, say so in `DESIGN.md` and name the source of the split.

For liquid-liquid extraction, write the extractor into `process/extraction.yaml` and run
`cheme process extract` (feed, solvent feed, stages, temperature, carrier/solute/solvent, a
bundled LLE system or `model:` with sourced NRTL parameters for every pair). Report its
`qualification`: `qualified` only for a bundled system inside its benchmarked range; with
your own parameters it is a predictive calculation, not a validated one. A refusal for one
liquid means the feed and solvent have no two-phase region: change the solvent or ratio, do
not fall back to an invented split. Model the solvent regeneration as its own unit.

## Required human judgment

Ask a person when Q3 is ambiguous, when the pressure sensitivity of an azeotrope cannot be
determined from data, or when a required input is missing. The choice of method is an
engineering decision.

## References

- `src/chemeascode/domains/process/separations/selection.py`: the matrices and the scoring
- `src/chemeascode/domains/process/separations/inputs.py`: property retrieval for the screening
- `src/chemeascode/domains/process/separations/coverage.py`: the downstream representation table
- `phase-calculation` (phase and azeotrope checks), `process-design`
