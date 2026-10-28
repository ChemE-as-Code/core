---
name: tech-petchem-polymers
description: Process knowledge for polyolefin, polystyrene and polyester plants - catalyst preparation, reactor types, monomer recovery, degassing and catalyst deactivation, drying, extrusion and pelletising, and what replaces a distillation train. Use when drafting or reviewing a polymer plant flowsheet.
---

# Polymer plants and their finishing end

## Purpose and when to use

Reached from `tech-petrochemicals`. A polymer plant converts a monomer almost quantitatively into a solid, so it has catalyst preparation, a reactor train, degassing, extrusion and pelletising where other plants
have a distillation train, and most equipment is at the finishing end. Chain-growth polymerisation is strongly exothermic, so reactor choice is a heat removal decision; polyester is step-growth condensation whose
equilibrium is driven by removing diol under vacuum.

## Required inputs and missing inputs

Polymer and grade slate (bimodal grades may need a second reactor; sources disagree), route (slurry, gas phase, solution, high pressure), capacity. The source has no polycarbonate polymerisation entry and only index lines for
vinyl chloride polymers: do not answer for them from this skill.

## Workflow and tools

Engineering guidance only; core has no calculation for this. Units:

1. Catalyst preparation and metering (cocatalyst; external donor for polypropylene).
2. Purified monomer, comonomer, hydrogen and diluent feed (the catalyst is poisoned by feed impurities).
3. Reactor train: slurry loop, stirred tanks in series, gas-phase fluidised bed with external cooler, solution reactor, or high pressure autoclave or tubular reactor. These are different flowsheets; do not merge them.
4. Monomer recovery: flash, condense and return, vent recovery by compression and cooling; a high pressure plant has two loops at different pressures; a distillation slipstream holds diluent composition and is the loop purge.
5. Degassing and catalyst deactivation by nitrogen, moist nitrogen or steam in a purge bin or column.
6. Drying, often a closed nitrogen circuit with regeneration.
7. Additive dosing, extrusion, pelletising, silos, blending and packaging.

| Item | Source value |
|---|---|
| Slurry loop | 25 to 40 bar, 75 to 110 degC, about 98 % ethylene polymerised |
| Gas phase | below 20 to 25 bar, about 70 to 110 degC |
| High pressure route | tubular to about 3,000 bar, autoclaves below 2,000 bar |
| Monomer consumption | 1.005 to 1.015 t per t polyethylene |
| Electricity | 315 to 450 kWh/t slurry, about 410 gas phase, 700 to 1,300 high pressure |

Control handles: gas composition and temperature are the product property handles in catalytic reactors; production split sets molecular weight distribution; hydrogen sets melt flow, donor isotacticity; heat is removed with the
monomer itself (evaporative cooling or jackets); high pressure route has initiator, pressure, temperature profile and comonomer; in polyester the cascade profile and finisher vacuum set viscosity.

## Validation and failure handling

Questions to put to the design:

- Does the initiating system have its own metering paths matched to the route?
- Does flashed monomer return by condensation (with diluent and a distillation slipstream on slurry or solution plants; no diluent circuit on gas phase)? Do recovered monomer streams have named return points rather than vents?
- On a chain-growth plant, does a degassing or purge bin with nitrogen or steam sit between the last reactor and any silo? On polyester the duty is done by finisher vacuum and, where fitted, solid state postcondensation.
- Is a nitrogen dryer circuit closed with regeneration, and does an air dryer vent have a named destination?
- Does a high pressure line show two recycle loops, and what manages ethylene decomposition (the hazard of that route, answered in the source by temperature profile control and staged letdown)?
- Is residual catalyst killed before powder meets air? Do cyclones on a gas-phase recycle protect the compressor?

## Outputs and provenance

Record route, grade basis, loop and degassing arrangement and sources in `DESIGN.md`.

## Required human judgment

Ethylene decomposition and runaway protection, dust and flammable-atmosphere hazards, relief, route and grade decisions. This skill certifies none of them.

## References

- Speight, *Handbook of Industrial Hydrocarbon Processes* (Elsevier 2011), Ch 14.
- Independently verifiable general method: monomer recovery and recycle logic, degassing before storage.
- Needs review before operational use: pressures, energy and consumption figures, the decomposition-hazard statement.
