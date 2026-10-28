---
name: tech-gas-dehydration
description: Reference for natural gas dehydration. Glycol contactor and regenerator, enhanced regeneration, molecular sieve bed cycles, how deep each route dries, and the main hazards. Use when gas drying for pipeline or cryogenic duty is being discussed or reviewed.
---

# Gas dehydration

## Purpose and when to use

Sits downstream of acid gas removal and takes water out so it cannot condense or form hydrates.
Reached from `tech-gas-processing`. How deep to dry is set by the coldest step downstream, not by
the pipeline specification.

## Required inputs and missing inputs

Required dryness (water content or dew point at pressure), the coldest downstream temperature,
inlet gas temperature, pressure and water content, whether mercaptans must also be removed, and
what is available for regeneration. Ask for any that is missing.

## Workflow and tools

Engineering guidance only; core has no calculation for this. Water content and hydrate
conditions need a property basis suited to water-hydrocarbon systems (see
`thermodynamic-model-selection`).

Glycol absorption, in flow order: inlet filter separator (carryover of free water or liquid
hydrocarbon fouls everything after it); contactor with a scrubber section and structured packing or
bubble-cap trays; demister; rich glycol through the regenerator overhead condenser coil, a
glycol/glycol exchanger and a flash tank whose gas is recovered as fuel; mechanical and carbon
filters; regenerator with reboiler and still column, its overhead (water vapour and aromatics) to
an incinerator; surge tank and pump back to the contactor. Glycol takes up a share of the aromatics
in the gas, so the regenerator overhead is an emission point (Mokhatab, Poe and Mak, *Handbook of
Natural Gas Transmission and Processing*, 3rd ed., Elsevier 2015, Ch 7).

Route selection:

- Glycol absorption is the economic choice for pipeline dryness. Enhanced regeneration (stripping
  gas, vacuum, internal condensation, or a hydrocarbon solvent) dries deeper by lowering the water
  partial pressure over the lean glycol. The reboiler temperature is capped by glycol degradation,
  which caps lean glycol purity.
- Molecular sieve is needed for cryogenic drying and also removes mercaptans, at the cost of a
  regeneration gas that recycles them upstream. It is a cycle of parallel adsorbers (adsorbing,
  regenerating, cooling, standby) with a regeneration loop of compressor, heater, cooler and a
  separator that draws off water and hydrocarbon on level.
- Chilling with inhibitor injection meets water and hydrocarbon dew point together.

Control reported for glycol units: a moisture analyser on dry gas corrects lean glycol flow
(ratioed to gas) and reboiler heat; if drier than needed, cut circulation first, if wetter add
heat first, because dryness depends mainly on lean glycol purity. On a sieve unit the control is
the timed cycle itself.

## Validation and failure handling

Questions for a flowsheet or P&ID:

- Is there an inlet filter separator ahead of every contactor or bed?
- Does the glycol flash gas go to fuel and the regenerator overhead to an incinerator or recycle,
  not to vent?
- Does a sieve regeneration loop show compressor, heater, cooler and separator, and where do
  mercaptans in the regeneration gas go?

Hazards: free water destroys molecular sieve, so the feed knockout is a protection of the bed;
rapid depressuring can lift and crush a bed, so depressuring rate and pressure equalisation before
switching are questions for the designer; desorbed water condensing on a cool top head and rinsing
back onto hot adsorbent (bed refluxing) is avoided by a gradual heating ramp; glycol degrades with
oxygen ingress and local overheating; dirty glycol foams. Spent sieve may be pyrophoric and retain
H2S, so change-out needs a controlled procedure. Whether a given measure suffices is not something
this skill can certify.

## Outputs and provenance

Route chosen with the dew point target and its basis, open points, and a note on which statements
below need review.

## Required human judgment

Dryness target, glycol versus sieve, regeneration scheme, bed change-out and depressuring
procedures, and the handling of regenerator emissions.

## References

- Mokhatab, Poe and Mak, *Handbook of Natural Gas Transmission and Processing*, 3rd ed.,
  Elsevier 2015, Ch 7 (aromatic uptake and emissions). General method.
- Needs review before operational use: reboiler and circulation figures, sieve cycle times and
  regeneration temperatures were not carried over (no section-level citation). Line-up, route
  selection and hazards are retained as general descriptions.
- `tech-gas-processing`, `tech-gas-ngl-recovery`.
