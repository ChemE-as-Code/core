---
name: thermodynamic-model-selection
description: Recommend a thermodynamic model (equation of state or activity-coefficient model) for a mixture from facts about pressure, polarity, electrolytes, interaction parameters, liquid-liquid split, pseudocomponents and vapour association, with Carlson's decision tree. Use before a phase or flash calculation and before choosing the property method in process/materials.yaml.
---

# Thermodynamic model selection

## Purpose and when to use

Recommends thermodynamic models with a rule engine that implements E. C. Carlson's decision tree
(Chem. Eng. Prog. 92, 1996, 35-46). Use it when a model has to be chosen or justified, before a
phase calculation (`phase-calculation`) and before recording a property method in
`process/materials.yaml`. The recommendation is not a validated choice.

## Required inputs and missing inputs

`ThermoModelSelectionInput`, every field optional: `pressure_value` with `pressure_unit`
(absolute: `bar(a)`, `atm`, `Pa`, ...), `is_polar`, `is_electrolyte`,
`interaction_parameters_available`, `vapor_association_expected`, `liquid_liquid_expected`,
`has_pseudocomponents`, `polymerization_degree` (`dimer`, `hexamer`).

Fill in only what the information given or well-established chemistry supports (classify each
compound as polar or nonpolar); leave the rest unset. The function raises
`InsufficientFactsError` naming the facts the tree still needs (`missing_facts`, with a
question for each): ask for exactly those and call again.

## Workflow and tools

```python
from chemeascode.domains.process.thermodynamics.model_selection import select_thermo_model

result = select_thermo_model(
    {"pressure_value": 5, "pressure_unit": "bar(a)", "is_polar": True, "is_electrolyte": False}
)
result.models, result.reasoning, result.triggered_rules, result.provided_facts, result.source
result.methods  # per model: .phase / .simulation executable, else .substitution or .reason
result.executable  # {'phase': [...], 'simulation': [...]}: models each route runs as recommended
result.notes  # a route that runs none of them: its substitutions, or 'unsupported'
```

Every recommended model is resolved against the supported-method contract
(`src/chemeascode/domains/process/thermodynamics/methods.yml`; `cheme process methods` prints
it): whether `phase-calculation` (thermo) and `process-simulation` (DWSIM) run it, and where a
route does not, the nearest model it runs as a `substitution` with what it `loses`, or no
substitution (electrolytes, petroleum pseudocomponents: unsupported on both routes; a sourced
petroleum assay has its own limited Peng-Robinson flash, `cheme process assay`). For
Pitzer, `methods[].electrolyte` names the qualified systems the electrolyte route runs
(`cheme process electrolyte`: aqueous NaCl only, liquid properties in the range of
`electrolytes.yml`); the result's `notes` say so.

There is no CLI command for the selection itself. Units go through
`chemeascode.foundation.units`; units other than K, °C, Pa, kPa, MPa, bar and the `(a)`/`(g)`
pressures need the `units` extra.

## Validation and failure handling

- An unknown input, a value outside a fact's possible values, or a pressure without its unit
  raises `ValueError`.
- No outcome: explain why from the reasoning trace; do not pick a model yourself.
- A recommended model a route does not run: say so, and offer only the table's substitution,
  named as a substitution with what it loses; use it only with the engineer's approval. With
  no substitution (electrolytes, pseudocomponents) the regime is unsupported: say that, do
  not fall back to another model. The one exception is a system the electrolyte route
  qualifies (aqueous NaCl): use `cheme process electrolyte` for its liquid properties, inside
  its range only.

## Outputs and provenance

Report the recommended models with the reasoning, the rules that fired, the facts used
(`pressure_band` is derived from the pressure) and `source`, the literature of the knowledge
base, and per model whether each route runs it or the substitution. Use the exact model names
in the next step. When the choice becomes the plant's property method, record it and its
reason in `DESIGN.md`; for the simulation record the facts in `process/simulation.yaml`
`method_selection.facts` (and, for an approved substitution, `method_selection.substitution`
with the reason), so the translation checks the property package against them.

## Required human judgment

Polarity, an expected liquid-liquid split and association are judgments: state each as an
assumption so it can be reviewed. An engineer accepts or overrides the recommendation.

## References

- `src/chemeascode/domains/process/thermodynamics/model_selection_rules.yml`, the decision tree
- `src/chemeascode/domains/process/thermodynamics/methods.yml`, the supported-method contract
- `phase-calculation`, `process-design`
