---
name: unit-ops-reactors
description: Reactors in their separation and recycle context - why design conversion is a system optimum, what the rate-limiting step implies, stirred tank, tubular, packed and fluidised bed geometries, and control and stopping the reaction. Use when a reactor is discussed as equipment; reaction models are reactions and reactor choice is cheme process reactor-choice.
---

# Reactors

## Purpose and when to use

A reactor is never alone: the reaction section is the reactor, the separation recovering product
and the recycle returning unconverted feed, and the design conversion minimises the cost of all
three together (Ray and Das, *Process Equipment and Plant Design*, Elsevier 2020, Ch 15). Higher
conversion buys a bigger reactor and a smaller separation and recycle; lower does the reverse; the
three must be capacity-matched. Use when a reactor is discussed as equipment.

## Required inputs and missing inputs

Reactions and conversion basis, phase, heat of reaction, catalyst, temperature and pressure range.
These live in `process/reactions.yaml` (skill `reactions`); ask for what is missing.

## Workflow and tools

Reaction models, extents and duties: skill `reactions` and `cheme process reactors`. Which ideal
reactor suits the reactions: `cheme process reactor-choice`. Hazards screening: `cheme process
reactor-hazards`. Catalyst mass and volume: `cheme datasheets fill`. Everything below is
engineering guidance only; core has no calculation for it.

What limits the rate selects the design: intrinsic kinetics (volume follows residence time); mass
transfer (design as mass-transfer equipment); mixing (very fast reactions); heat transfer (a
shell-and-tube reactor is a heat exchanger that reacts); feed addition rate (a control strategy).
Volume is often set by mixing, segregation or heat transfer, not by residence time.

Geometries and what each brings:

- Stirred tank: agitator and drive, baffles, jacket or coil, a vapour space for pressure control
  (typically a tenth of the vessel, often a quarter to two fifths; the basis is foaming, gas
  evolution, entrainment and venting, so ask before calling headspace adequate). Good temperature
  control, lowest conversion per volume; often in series.
- Tubular: high conversion per volume, good heat transfer, axial gradient, hot spots in exothermic
  service; L/D above about 20.
- Packed bed: highest conversion per catalyst mass, poor heat transfer, awkward catalyst
  replacement; support grid, inert layers, catalyst collector at the outlet; downflow preferred
  because upflow can fluidise the bed.
- Fluidised bed: uniform temperature, continuous regeneration through a loop; attrition, dust and
  bypassing; distribution grid, cyclones, transfer lines.

Each geometry adds its own services (quench connections, sparger and redistributor, foam breakers,
catalyst nozzles).

Control: temperature is almost always controlled, via coolant or feed rate. An exothermic reactor
needs a way to stop the reaction (quench, dump, feed cut, depressuring); name which one. The source
gives reactor design but no control scheme, so control detail comes from the project.

## Validation and failure handling

Questions for a design: no recycle path where the chemistry needs one; a packed bed with no support
or collector; a fluidised bed with no cyclone or regeneration loop; an exothermic reactor with no
means of stopping the reaction; a liquid-phase stirred tank drawn liquid-full. Whether means are
independent is a safety-study question, not answered here.

## Outputs and provenance

State the conversion basis, geometry and stopping means with sources. Record in `DESIGN.md`.

## Required human judgment

Reactor type, runaway protection and relief basis need a person; nothing here certifies safety.

## References

- Ray and Das, *Process Equipment and Plant Design*, Elsevier 2020, Ch 15.
- `reactions`, `process-design`, `datasheets`, `unit-ops-heat-transfer`.
- Retained as general method: system view of conversion, rate-limiting step table, geometry traits.
- Needs review before operational use: vapour space fractions, L/D above 20.
