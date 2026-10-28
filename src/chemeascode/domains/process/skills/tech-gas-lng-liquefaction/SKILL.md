---
name: tech-gas-lng-liquefaction
description: Reference for natural gas liquefaction. Pretreatment for freeze-out, heavies removal, mixed refrigerant, cascade and expander cycles, the main cryogenic exchanger and end flash handling. Use when an LNG train or its pretreatment is being discussed or reviewed.
---

# LNG liquefaction

## Purpose and when to use

A liquefaction train cools pretreated gas to LNG temperature and lets it down to near atmospheric
pressure. Everything upstream of the cold box exists so that nothing in the gas can freeze inside it.
Reached from `tech-gas-processing`.

## Required inputs and missing inputs

Feed composition including CO2, water, mercury, mercaptans, aromatics and nitrogen; feed pressure;
train size; site cooling medium; LNG specification; the project's pretreatment limits. Ask for any
that is missing.

## Workflow and tools

Engineering guidance only; core has no calculation for this. Refrigeration cycles and cooling curves
need a simulation with a property method valid at cryogenic temperature
(`thermodynamic-model-selection`).

Units in flow order: pretreatment (acid gas removal, dehydration, mercaptan and mercury removal,
each species either freezing out or attacking aluminium; the limits are absolute, not commercial);
heavies removal by a scrub column with refrigerated reflux or a full liquids recovery unit, keeping
aromatics and pentanes plus out of the cold end; refrigeration compression with condensers,
suction drums or economisers and accumulators; main cryogenic exchanger (spiral wound or parallel
brazed aluminium cores); letdown by valve, hydraulic turbine or flash; end flash handling (flash gas
rewarmed, compressed for fuel or partly reliquefied; feed nitrogen leaves here); LNG pumps to storage,
with boil-off returned to the flash gas compressor.

Cycle families: single mixed refrigerant (one loop of nitrogen and light hydrocarbons); dual mixed
refrigerant (precooling and cryogenic loops, balancing two drivers); cascade of pure refrigerants
(propane, ethylene, methane), suited to large base-load trains; expander cycles on nitrogen or
methane, which keep the refrigerant gaseous and are offered offshore and for peak shaving. Sources
disagree on which cycle is most efficient or most cost effective, so record the trade-off for the
project rather than ranking them here.

Control reported (Poe and Mokhatab, *Modeling, Control, and Optimization of Natural Gas Processing
Plants*, Elsevier 2017, Ch 3): chiller level with evaporator pressure control; liquid dump on each
compression stage; refrigerant composition as a manipulated variable on a mixed refrigerant cycle;
lower suction pressure buys colder refrigerant at the cost of compression ratio, so the set point is an
optimisation; every centrifugal machine needs a fast antisurge recycle. Beyond these loops the
literature describes cycle line-ups, not control schemes: start-up sequences and the trip matrix are
project information.

## Validation and failure handling

Questions for a flowsheet or P&ID:

- Are acid gas removal, dehydration, mercaptan and mercury removal all upstream of the cold box, with
  no bypass around any?
- Does heavies removal have a stated destination for its bottoms?
- Does flash gas go to fuel and partly to reliquefaction, and does boil-off return to the flash gas
  compressor?
- On a condensing-refrigerant cycle, are there economisers or suction scrubbers between stages? (An
  expander cycle needs neither.)
- Does each centrifugal machine have an antisurge recycle?

Freeze-out of CO2, water, heavy hydrocarbons or aromatics is the governing failure; clearing it means
shutdown and derime. Aluminium exchangers fail on thermal excursion, so cooldown rate and pass
temperature difference are limited by procedure and design. Inerts accumulate in an open-loop
refrigerant and must be bled. Flare and relief sizing should cover feed block-in as well as power and
cooling failure. This skill does not certify any of these protections.

## Outputs and provenance

Cycle choice with its trade-off recorded, pretreatment basis, and open points.

## Required human judgment

Cycle selection, pretreatment limits, antisurge and relief design, cooldown procedure.

## References

- Poe and Mokhatab, *Modeling, Control, and Optimization of Natural Gas Processing Plants*,
  Elsevier 2017, Ch 3 (refrigeration loop control). General method.
- Removed: all numeric pretreatment limits, temperatures, pressures and specific energy figures,
  because their only source was an edited trade compilation of process entries and they cannot be
  verified independently here. Needs review before operational use: cycle descriptions and hazards.
- `tech-gas-nitrogen-and-mercury`, `tech-gas-ngl-recovery`, `tech-gas-processing`.
