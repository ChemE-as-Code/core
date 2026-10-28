---
name: flowsheet-process-model-vocabulary
description: Vocabulary of the DEXPI process model behind the BFD and PFD - process steps, hierarchy grain, the step taxonomy, streams, ports and compositions - for naming flowsheet steps precisely. Use when describing what a process does rather than what the P&ID draws.
---

# Flowsheet process-model vocabulary

## Purpose and when to use

DEXPI describes a plant twice. The plant model is the P&ID (tagged equipment, piping,
instrumentation). The process model is the flowsheet behind it: what happens, in what order, to
what material. An engineering model holds one conceptual model, a plant model or a process model,
not both. `cheme process build` writes the BFD and PFD as DEXPI 2.0.1 process models from
`process/flowsheet.yaml` (skill `process-design`); use this vocabulary to name the steps and
blocks in that YAML.

## Required inputs and missing inputs

The step or block being described and the grain it is drawn at. Without them, name the process
action and ask for the grain.

## Workflow and tools

Engineering guidance only; core has no calculation for this. In `flowsheet.yaml` a block or step
takes a DEXPI `class`; the table is the classification to choose it from (class names present in
pyDEXPI, which core uses).

| What happens | Class |
|---|---|
| Material enters or leaves the drawing | `Source`, `Sink` |
| Streams join or divide | `Mixing`, `Splitting` |
| Flow is generated | `Pumping`, `Compressing` (under `GeneratingFlow`) |
| Flow is steered or stopped | `SteeringFlow` and its members |
| Heat is added or removed | `ExchangingThermalEnergy`, `RemovingThermalEnergy`, `SupplyingThermalEnergy` |
| Phases or components are separated | `Separating` and its members, among them `SeparatingByPhaseSeparation`, `SeparatingByFlash`, `SeparatingMechanically` (`Filtering`), `SeparatingByPhysicalProcess` (`Absorbing`, `Adsorbing`), `SeparatingByThermalProcess` (`Distilling`, `Evaporating`, `Drying`) |
| A reaction occurs | `ReactingChemicals` |
| Material is stored | `StoringMaterial`, `StoringFluids`, `StoringInTank` |
| Particle size changes | `ReducingParticleSize`, `IncreasingParticleSize` (`Crystallizing`) |
| Material is burned off | `Flaring`, `Emitting` |

The classes name what is done, so one class covers many machines. Several carry a method
enumeration (pumping, compression, heat exchange, reaction process type) for how.

Hierarchy grain: process, process section, process train, unit operation, elementary function,
plus control, safety and support functions. A block on a BFD is usually a process or process
section, a column on a PFD a unit operation. Core nests steps in blocks and blocks in parent
blocks, which is how the grain is expressed in the YAML.

Connections are streams (material, with flows, pressure, temperature and a material state),
energy flows (thermal, mechanical, electrical, carrying duty or shaft work) and information flows.
They attach to ports with a nominal direction. In core a stream names a template, and its
composition may only use that template's components; a composition read without its template is
a list of numbers.

"A `Distilling` unit operation with an `ExchangingThermalEnergy` step as its condenser" says what
the process does; "a column with a condenser" says what the P&ID draws. Make clear which is meant.

## Validation and failure handling

`cheme validate` reports `cheme.process-*` findings on the YAML (template, component, balance,
delegation). It does not judge whether the class chosen is the right one.

## Outputs and provenance

Name the step class and grain, and say when a step is the description of a process rather than an
item with a tag on a drawing.

## Required human judgment

Choice of step class, method and grain.

## References

- DEXPI process model (DEXPI 2.0.1) and pyDEXPI class names, verified to exist in the version
  core installs. The grouping in the table is a summary; check exact class membership against the
  specification before relying on a parent-child relationship (needs review).
