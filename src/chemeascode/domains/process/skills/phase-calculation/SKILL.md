---
name: phase-calculation
description: Identify the phases of a pure component or mixture with a flash at given temperature, pressure and composition (vapour, liquid, liquid-liquid, vapour-liquid, vapour-liquid-liquid; no solids, electrolytes or pseudocomponents), through thermo with an equation of state or an activity-coefficient model, and report which binary interaction parameters are sourced, missing or accepted as zero. Use when phase identification or a flash is needed for a stream, or to check parameter coverage of a mixture.
---

# Phase calculation

## Purpose and when to use

Runs a flash through thermo and reports the number of phases, their fractions and
compositions, and per binary pair whether its interaction parameter is sourced, missing (zero
used) or accepted as zero. Use it to identify the phase of a stream or mixture. It is a
calculation with no application range claimed (no test benchmarks its values): stream properties
written to `process/flowsheet.yaml` come from `cheme process props` (see `process-design`), which
uses benchmarked property packages with validated ranges (`cheme process props --coverage`).

## Required inputs and missing inputs

- A thermodynamic model that has been recommended (`thermodynamic-model-selection`) or given.
  Do not pick one yourself. If the recommendation's `methods[...].phase` is not executable,
  use its `substitution` only with approval and report it as a substitution.
- Components (names or CAS numbers), the temperature and the absolute pressure with units, and
  the overall mole fractions for a mixture.
- `allow_two_liquids`: set it when liquid-liquid separation is expected, as a stated assumption.

If the temperature, pressure, composition or model is missing, ask for it.

## Workflow and tools

```python
from chemeascode.domains.process.thermodynamics.phase import phase_determination

result = phase_determination(
    components=["ethanol", "water"],
    overall_composition=[0.25, 0.75],
    temperature_value=70,
    temperature_unit="°C",
    pressure_value=1,
    pressure_unit="bar(a)",
    thermodynamic_model={"liquid_phase_model": "NRTL", "vapor_phase_model": "ideal_gas"},
    allow_two_liquids=False,
)
```

Models: `{"eos_model": "Peng-Robinson" | "Redlich-Kwong" | "Redlich-Kwong-Soave"}`, or
`{"liquid_phase_model": "NRTL" | "Wilson" | "UNIFAC", "vapor_phase_model": <an EOS> |
"ideal_gas"}`. The names are exact and case-sensitive. Needs the `props` extra
(`pip install 'cheme-as-code[props]'`). `accepted_zeros=[("A", "B")]` records pairs whose
missing parameter the engineer accepts as zero.

CLI: `cheme process phase ethanol water --liquid NRTL --vapor ideal_gas` prints the parameter
coverage per pair; add `--z 0.25,0.75 --temperature 343.15 --pressure 1` (units: 
`--temperature-unit`, `--pressure-unit`, default K and bar(a)) for the flash, `--accept-zero
A:B` for an accepted zero, `--check` to exit 1 on a missing pair, `--json` for the result.
Coverage alone in Python: `thermodynamics.coverage.interaction_parameter_coverage(components,
model, accepted_zeros)`.

Redlich-Kwong-Soave takes its `kij` from the ChemSep SRK file, which is not shipped (licence
unconfirmed). `cheme data status` shows whether it is installed; the user installs it
with `cheme data fetch chemsep-srk` (downloads ChemSep-LITE; `--zip lite.zip` for a copy
already downloaded). Ask before running the fetch: it downloads third-party data.

## Validation and failure handling

- `ValueError` "Invalid thermodynamic model input": compare the names with the values above and
  call again.
- The recommended model is not available: report it; use a similar one only with approval.
- A gauge pressure is refused, because no ambient pressure is known: give it as absolute.
- An ion (a component with a charge), or a salt, acid or base of `electrolytes.yml` together
  with water (sodium chloride, sulfuric acid, any compound of an alkali or alkaline-earth
  metal, ...), is refused: electrolytes are unsupported by
  this route. For aqueous NaCl inside its claimed range use `cheme process electrolyte`
  (activity and osmotic coefficients, water vapour pressure, heats of dilution); any other
  electrolyte is unsupported. A component
  thermo does not identify (a petroleum pseudocomponent) is refused. Solids are never formed:
  below a melting point the result is still fluid (`limitations` says so). Report these as
  unsupported; do not work around them.
- `interaction_parameters` with `missing` pairs: the flash used zero for them. Report the
  pairs; source the parameter, or have the engineer accept the zero (`accepted_zeros`), or
  choose another model where the interaction matters.
- Check `flash_convergence_error` before using the result.
- `notes` not empty (e.g. "ChemSep SRK interaction parameters are not installed; kij = 0"): the
  result used `kij = 0` for every pair. Report it with the result, and suggest
  `cheme data fetch chemsep-srk` or another model where the interaction matters.

## Outputs and provenance

`FlashCalculationResult`: `temperature_K`, `pressure_Pa`, `gas_count`, `liquid_count`, `betas`,
`gas_composition`, `liquid_compositions`, `component_cas_numbers`, the inputs
(`provided_facts`), `notes` (assumptions such as `kij = 0`), `source` (thermo), `method` (the
id in `methods.yml`), `interaction_parameters` (per pair: status, source, values),
`limitations` and `application_range` ("no range claimed"). Report the model and the assumptions with the result.

## Required human judgment

An engineer reviews the model choice and `allow_two_liquids`. A result near a phase boundary
needs confirmation from data. For a stream at its dew or bubble point that the flash puts a
fraction of a kelvin into the other phase, do not shift its temperature: state its phase, and
`cheme process props --fill` calculates it on that phase's EOS root, marked phase-constrained,
within a metastability tolerance (`process-design`).

## References

- `thermodynamic-model-selection`, `process-design`
- Interaction parameters: thermo's ChemSep databases (PR, NRTL, Wilson) and, for SRK, the
  ChemSep file installed by `cheme data fetch chemsep-srk` (origin and licence status:
  `src/chemeascode/domains/process/thermodynamics/data/chemsep/SOURCE.md`)
