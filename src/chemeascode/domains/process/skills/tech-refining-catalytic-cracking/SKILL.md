---
name: tech-refining-catalytic-cracking
description: Reference for fluid catalytic cracking. Riser and reactor, catalyst stripper, regenerator and flue gas train, main fractionator and gas concentration unit, with the heat balance logic and variants. Use when an FCC unit is being discussed or reviewed.
---

# Catalytic cracking

## Purpose and when to use

Turns heavy gas oil into gasoline, olefinic LPG and cycle oils without hydrogen. Coke laid on the
catalyst is burned in the regenerator, and that heat vaporises the feed and drives the endothermic
cracking, so the unit is a closed heat loop between two vessels. Reached from `tech-refining`.

## Required inputs and missing inputs

Feed properties (carbon residue, metals, nitrogen), desired mode (gasoline or distillate), feed
rate, catalyst type, and air and flue gas constraints. Ask for any that is missing.

## Workflow and tools

Engineering guidance only; core has no calculation for this. The heat balance and catalyst
circulation are not computed by core.

Units in flow order: feed surge, charge pump and preheat against fractionator pumparounds; riser
where feed meets hot regenerated catalyst and cracks in seconds; reactor cyclones; catalyst stripper
with steam (unstripped hydrocarbon burns in the regenerator and appears as regenerator heat); spent
catalyst standpipe and slide valve; regenerator with air blower, cyclones, and a flue gas train
(power recovery turbine, particulate control, heat recovery); fresh and equilibrium catalyst hoppers;
main fractionator fed at the bottom with pumparounds, side strippers and a slurry circuit in the
bottom, built like a crude column; heat recovery as steam; gas concentration unit (wet gas compressor,
primary and sponge absorbers, stripper, debutaniser), whose gas goes to amine treating.

Control reported: riser outlet temperature on the regenerated catalyst slide valve (sets catalyst to
oil ratio, the conversion handle); regenerator temperature on air rate and catalyst cooling for
resid feed; reactor-regenerator differential pressure to keep catalyst moving in the intended
direction; dispersion and stripping steam on their own controllers; catalyst make-up on equilibrium
activity.

Variants: gasoline mode versus distillate mode (lower severity roughly reduces gas make and raises
distillate yield); resid feed brings catalyst cooling, higher make-up and tighter metals limits;
zeolite to matrix balance is the yield-tuning variable.

## Validation and failure handling

Questions for a flowsheet or P&ID:

- Does the catalyst circuit close (riser, cyclones, stripper, spent line, regenerator, regenerated
  line), with slide valves in both transfer lines and the differential pressure measurement that
  governs them?
- Are dispersion steam and stripping steam separate services, and do catalyst hoppers connect to the
  regenerator?
- Does the fractionator bottom show a slurry circuit and the overhead receiver a sour water draw?
- Does the gas plant show primary and sponge absorbers, with sponge bottoms back to the main
  fractionator, and gas reaching amine treating before the fuel header?

Reported limits and hazards: the regenerator metallurgical temperature limit forces catalyst cooling
as coke rises, and a resid feed is limited by the steam a cooler can raise; slide valve and standpipe
integrity guard against reverse flow of hydrocarbon into the regenerator or air into the reactor, a
question to put to the designer; nickel and vanadium damage catalyst; the power recovery turbine
needs its own protection and bypass. FCC light gasoline carries mercaptans and the distillate has a
low cetane index, so treating is a flowsheet consequence. This skill does not certify protection.

## Outputs and provenance

Line-up, mode, and open points; figures stated as a worked case.

## Required human judgment

Severity and mode, regenerator temperature limit, feed metals acceptance, trips and reverse-flow
protection.

## References

- Parkash, *Refining Processes Handbook*, Elsevier 2003, Ch 4 (a 40,000 bpsd worked case: riser
  outlet about 991 degF, regenerator bed about 1341 degF, catalyst to oil ratio about 5.4). Indicative
  only. Speight, *Handbook of Industrial Hydrocarbon Processes*, Elsevier 2011, Ch 11 quotes
  1230-1400 degF, which is a regenerator-side figure rather than a riser outlet; the two are not one
  range. Needs review before operational use.
- `tech-refining`, `tech-refining-treating-and-blending`.
