---
name: tech-gas-ngl-recovery
description: Reference for hydrocarbon dew point control and NGL recovery. Joule-Thomson and refrigeration chilling, turboexpander schemes, demethaniser and fractionation train, and their hazards. Use when liquids recovery from natural gas is being discussed or reviewed.
---

# NGL recovery

## Purpose and when to use

Makes the gas cold, drops heavy hydrocarbons out as liquid, then splits the liquid into products.
Whether to build a dew point unit or a deep recovery plant is a commercial decision about the value
of the liquid against the gas. Reached from `tech-gas-processing`.

## Required inputs and missing inputs

Feed composition, pressure and temperature, target recovery (ethane or propane and heavier),
residue gas pressure, product slate, and the dryness and CO2 level available from upstream. Ask for
any that is missing.

## Workflow and tools

Engineering guidance only; core has no calculation for this. Phase behaviour near the critical
region needs a suitable property method (`thermodynamic-model-selection`, `phase-calculation`).

Dew point unit: dehydration first (everything after it runs below the hydrate point); gas/gas
exchanger; a Joule-Thomson valve or kettle chiller; cold separator with vapour back through the
exchanger to the residue compressor; reboiled stabiliser on the liquid.

Deep recovery plant: sieve dryers; brazed aluminium exchanger cooling feed against residue gas and
column streams; cold separator with vapour split between subcooled column reflux and a
turboexpander (whose shaft drives a booster compressor on the residue gas); demethaniser or
absorber with side and bottom reboilers; residue compressor; fractionation train (deethaniser,
depropaniser, debutaniser, optionally a butane splitter), each with condenser, reflux drum, pump and
reboiler; treating of the liquids, since sulfur not removed upstream arrives there.

Variants: Joule-Thomson expansion is simple and tolerant of swings, so it suits small and remote
plants; refrigeration suits a feed with no pressure to spare; turboexpander schemes differ in how
reflux is made (subcooled separator vapour, recycled residue gas, or a second column).

The demethaniser pressure ceiling is a phase-behaviour limit rather than a mechanical one: the
bottom is the hottest point and nearest the critical region, so raising pressure collapses the
methane-ethane split (Poe and Mokhatab, *Modeling, Control, and Optimization of Natural Gas
Processing Plants*, Elsevier 2017, Ch 1).

Control reported: the expander through inlet guide vanes (which variable it holds is a project
choice); a Joule-Thomson valve in parallel on split range; a recycle valve on the booster compressor
against surge; demethaniser bottom temperature on reboiler heat; for each fractionation column,
reboil against a temperature below the feed, reflux against one above, pressure as low as flooding
allows; chiller level cascaded to refrigerant flow.

## Validation and failure handling

Questions for a flowsheet or P&ID:

- Does a turboexpander plant show a Joule-Thomson path in parallel and an antisurge recycle on the
  booster? (A pure Joule-Thomson or refrigeration unit has neither.)
- Is there dehydration ahead of every sub-ambient step, and a mercury bed ahead of brazed aluminium
  where the feed carries mercury?
- Is each fractionation column complete, and does each overhead go where the product slate says
  (propane and butane columns give products, not sales gas)?
- Is product treating present where the feed carried sulfur?

CO2 freezing limits column temperature and is dealt with upstream. Hydrate inhibition with methanol
is not overpressure protection: a plugged or blocked-in cryogenic exchanger needs its own relief or
depressuring route. Aluminium exchangers are limited by thermal stress between passes. Lube oil in
a propane circuit is a recognised cause of lost refrigeration duty.

## Outputs and provenance

The scheme chosen with recovery target and basis, and the open points. Control and temperature
limits as project information.

## Required human judgment

Dew point versus deep recovery, expander control objective, relief and depressuring of cold
equipment, hydrate management.

## References

- Poe and Mokhatab, *Modeling, Control, and Optimization of Natural Gas Processing Plants*,
  Elsevier 2017, Ch 1 (pressure ceiling). General method.
- Needs review before operational use: all pressure and temperature figures were dropped
  (no section-level citation); scheme descriptions, control and hazards retained as general
  descriptions.
- `tech-gas-dehydration`, `tech-gas-nitrogen-and-mercury`, `tech-gas-processing`.
