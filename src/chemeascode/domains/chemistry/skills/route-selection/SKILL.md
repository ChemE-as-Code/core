---
name: route-selection
description: Compare the candidate reaction routes recorded in process/reaction-evidence.yaml (cheme chemistry evidence), select one explicitly with its rationale, and hand over to the engineering model. Write model_basis (route, reactions of process/reactions.yaml, catalyst, the observations used, the assumptions beyond them and how they will be validated), then write or update reactions.yaml and catalysts.yaml with each value citing its observation, never overwriting reviewed inputs silently. Use after reaction-evidence-search, before the first reactor model, and when the selected route or its basis changes.
---

# Route selection and model handoff

## Purpose and when to use

Evidence and model are kept apart. `process/reaction-evidence.yaml` (skill
`reaction-evidence-search`) records what the sources report. `process/reactions.yaml` and
`process/catalysts.yaml` (skill `reactions`) hold what the model uses. This skill is the step
between them. It compares the routes, selects one with its reasons, records the
`model_basis` (which reactions, which observations, which assumptions), and writes the
model's inputs so that each one cites the evidence it comes from.

Use it once the evidence for the candidate routes has been gathered, before the first
reactor is modelled, and again whenever the selected route, its catalyst or its basis changes.

## Required inputs and missing inputs

- `process/reaction-evidence.yaml` with at least the candidate routes and their observations,
  without `cheme.evidence-*` errors.
- The selection criteria: ask the user if they are not stated (feedstock availability,
  selectivity and separation load, operating pressure, catalyst maturity, safety, scale,
  evidence quality).
- The components in `process/materials.yaml` (skill `materials`).

If the evidence cannot support a choice (no route has observations at relevant conditions, or
the deciding sources were unavailable), say so and stop. Do not pick a route the evidence does
not support, and do not fill the gap with assumed values to make one look better.

## Workflow and tools

1. **Compare.** Run `cheme chemistry evidence` (or `--json`). Per route it shows the sources
   and observations, the scales, the reported temperature and pressure ranges, conversion,
   selectivity and yield (each kept apart, a yield with its type), kinetics, by-products,
   conflicts, sources not read in full and gaps. Present the comparison to the user against
   the criteria. Point out where the evidence is only patent examples, only one source, or in
   conflict, and where yield and conversion bases differ between sources (they are not
   comparable).
2. **Select.** Set the chosen route's `status: selected` and its `rationale`. Mark the
   others `rejected` (with the reason) or leave them `candidate`. Only one route is selected
   at a time. Record the decision in `DESIGN.md` (`## D-NNN ...`) when it is a project
   decision, and cite it in `model_basis.decision`.
3. **Write the model basis.**

   ```yaml
   model_basis:
     route: DEHYD
     reactions: [EtOAc_DEHYD, AcH_SIDE]          # ids in process/reactions.yaml
     catalyst: CU_ZN                             # id in process/catalysts.yaml
     evidence: [O1, O2]                          # observations of this route
     assumptions:
       - "per-pass conversion 0.6 from O1 at 250 °C, 2 MPa; not verified at the plant WHSV"
     validation: "pilot test at design WHSV before the basic stage"
     decision: D-004
     decided_by: process lead
     date: 2026-10-24
   ```

   - Use the selected route's own observations. Evidence borrowed from another route, or
     pooled from observations on different catalysts, gets a warning until an assumption
     says why it transfers.
   - Every value the model uses that the evidence does not give is an assumption, written
     out with how it will be checked. Do not fit kinetic parameters to too few points, and
     do not take a rate law outside the range it was fitted in, unless an assumption names
     the gap and `validation` says how it will be tested.
4. **Hand over to the model.** A reported per-pass conversion with its selectivities goes
   onto the reactor step as `selectivity: {key, conversion, products}` (molar, relative to
   the key converted, the observation in `source`): no per-reaction conversions need to be
   invented for the side reactions. Write or extend `process/reactions.yaml` and
   `process/catalysts.yaml` (skill `reactions`). Each `conversion`, `heat_of_reaction` and
   `rate` taken from the evidence gets `provenance: given` and a `source` naming the
   observation and the source (`source: "reaction-evidence O1 (S2, Table 2)"`). A working
   value chosen beyond the evidence is `provenance: assumed`, and its source names the
   assumption. Convert units deliberately: a conversion of 61 % becomes `value: 0.61`. A
   kinetic law goes into `rate:` with its `temperature_range` and `catalyst`. Use
   `cheme experiments fit-rate` to fit one only from enough data points, with the fit's
   intervals.
   - **Do not overwrite reviewed inputs silently.** If `reactions.yaml` already has a value
     covered by a current review record, or a `given` value from another source, do not
     replace it. Show the user the existing value and the new evidence. Change it only when
     they agree, and record the change in `DESIGN.md`.
5. **Check.** Run `cheme validate`. `cheme.evidence-model-basis` and `-reaction` must be
   clean. Review `cheme.evidence-handoff` (info: a given model value that cites none of the
   basis's observations). Then continue with the reactor (skill `reactions`: `cheme process
   propagate --fill`, `cheme process reactors`). The reactor calculations remain the existing
   tools'.
6. **What `cheme maturity` reads from it.** A conversion reactor's specified value (a
   reaction's `conversion`, or the step's `selectivity:` conversion and each selectivity)
   counts as sourced at the `balanced` level when the selected route's `model_basis` names
   its reactions and the basis's cited observations cover it at the reactor's outlet
   temperature and pressure (only these: residence time, space velocity, feed ratios,
   catalyst loading, phase and solvent are not compared, and are listed so). No
   `cheme.evidence-*` error may be on the basis or a route (one route selected). An
   observation counts when its source was read in `full-text` and is declared once, no
   error names it or its source, it states its catalyst (`catalyst`, else
   `catalyst_formulation`; "none (thermal)" for a non-catalytic one) and is the basis's
   `catalyst` (same id, or a formulation equal to its id or its name in
   `process/catalysts.yaml`; the basis's catalyst must be the one the reactor step declares
   in `catalyst:`, and with no basis catalyst the observations must be on the step's), its
   value is reported or
   derived (not assumed) and labelled: `basis: per-pass` for a conversion, `basis: molar`
   and `relative_to` the key for a selectivity. It must report a temperature (a range, or a
   single value with its `uncertainty`) holding the reactor's outlet temperature, and a
   pressure holding the outlet pressure where both give one. The value must lie inside the
   range those observations span, one catalyst's observations at a time (never pooled). The
   step's `selectivity:` (kmol product per kmol key) is compared as a fraction: divided by
   the product's coefficient per key in its reactions. So label every observation, record
   its temperature and catalyst, and give the reactor's outlet temperature in every case of
   the flowsheet: a case without it leaves nothing sourced. A value outside the range,
   evidence only from unread or erroneous observations, a conflict on a cited observation
   (whatever its `resolution`), or a route that is not selected leaves it unsourced, with
   the reason in the detail and as a limitation. A value's own `given` source (a reaction's
   conversion, the step's `selectivity:`) stands where the evidence cannot compare it (a
   route not selected, a conflict, an unknown outlet temperature, ...), but not where usable
   observations, compared at a known outlet temperature, contradict it. A reaction whose key another reaction of
   the step also consumes is not compared with a total conversion: give the step a
   `selectivity:`. It stays a specified basis: never `predictive`.

## Validation and failure handling

- `cheme.evidence-model-basis`: a selected route without a model basis, two selected
  routes, a basis on a route that is not selected or with no evidence (errors). Evidence from
  another route, or pooled across catalysts without an assumption (warnings).
- `cheme.evidence-reaction`: a model reaction that `process/reactions.yaml` does not declare
  (error). A route's reaction that it does not declare (warning).
- `cheme.evidence-catalyst` (warning): a catalyst that `process/catalysts.yaml` does not
  declare.
- `cheme.evidence-handoff` (info): a given conversion, heat of reaction or rate of a model
  reaction whose source names no observation or source of the basis. Cite it, or mark it
  assumed.
- The reaction and catalyst checks of the `reactions` skill apply to the written model as
  usual (element balance, catalyst window, rate validity).

## Expected outputs and provenance

The selected route with its rationale and the `model_basis` in
`process/reaction-evidence.yaml`. The model's reactions and catalysts in
`process/reactions.yaml` and `process/catalysts.yaml`, each value citing its observation.
A `DESIGN.md` entry for the decision. Competing routes and every individual observation stay
in the evidence file, unchanged by the selection.

## Required human judgments

- The selection criteria and the choice of route. The agent presents the evidence; a person
  decides.
- Whether observations are comparable enough to support the model (catalyst, scale, reactor
  type, analysis), and how a conflict between sources is resolved.
- Which assumptions beyond the evidence are acceptable at the current stage, and the
  validation plan for them.
- Whether a reviewed value in `reactions.yaml` should change.

## References

- `reaction-evidence-search` (the evidence), `reactions` (the model and the reactor
  calculations), `process-design`, `review`.
- `cheme chemistry evidence`, `cheme schema reaction-evidence`, `cheme schema
  process-reactions`.
