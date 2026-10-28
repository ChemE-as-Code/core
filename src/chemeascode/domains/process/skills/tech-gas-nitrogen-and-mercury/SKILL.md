---
name: tech-gas-nitrogen-and-mercury
description: Reference for cryogenic nitrogen rejection and fixed-bed mercury removal in a gas plant, where each belongs, what the placement costs, and the hazards. Use when inert removal or protection of aluminium cold-end exchangers from mercury is being discussed or reviewed.
---

# Nitrogen rejection and mercury removal

## Purpose and when to use

Two small units that protect the cold end. Nitrogen rejection brings an inert down to pipeline
quality; mercury removal keeps a metal that attacks aluminium out of the cryogenic exchangers.
Reached from `tech-gas-processing`.

## Required inputs and missing inputs

Feed nitrogen content and flow, CO2 and heavy hydrocarbon content, helium value if any, the
mercury analysis, the product nitrogen limit, and the lowest temperature the cold section sees.
Ask for the mercury analysis before reporting a bed missing.

## Workflow and tools

Engineering guidance only; core has no calculation for this. Cryogenic distillation needs a
property method valid at low temperature (`thermodynamic-model-selection`).

Nitrogen rejection, in flow order: pretreatment (CO2 removal, dehydration, sieve reaching the lowest
temperature seen, mercury removal; a rich feed also needs hydrocarbon dew point control so aromatics
cannot freeze); brazed aluminium feed exchanger; cold separator removing heavy hydrocarbons, then
Joule-Thomson letdown to the high pressure column; the column set (single column with a heat pump or
the pipeline compressor providing reflux and reboil, stacked double column in which the high pressure
condenser is the low pressure reboiler, or two unlinked columns with a preseparator); nitrogen vent to
a safe location; methane product warmed against the feed and compressed. Cryogenic distillation is the
only route at scale; pressure swing adsorption and membranes are bulk separations for small flows and
leave enough hydrocarbon in the reject to be an emissions question.

The nitrogen content at which a two-column design is chosen over a single column is reported
differently by different sources (Mokhatab, Poe and Mak, *Handbook of Natural Gas Transmission and
Processing*, 3rd ed., Elsevier 2015, Ch 10): treat the crossover as project specific.

Mercury removal is a fixed bed, normally a lead-lag pair so one can be changed on line. Non-
regenerative sorbents react the mercury with sulfur or a metal and are discarded; a regenerative
silver-loaded sieve recovers it into the regeneration water. Placement trades bed size against
protection: at the inlet the bed is large but protects everything; after the solvent unit it is
smaller but exposes the solvent; inside the sieve beds one vessel does several duties but its water
carries mercury; after the sieve it is cheapest and protects least. The sources give no control
loops for mercury beds; they run on breakthrough and elapsed service.

## Validation and failure handling

Questions for a flowsheet or P&ID:

- Are dehydration and mercury removal upstream of any cryogenic column?
- Is there a feed strainer ahead of the aluminium exchanger, and a removal route?
- Is the nitrogen vent routed to a safe location, not to a nearby stack or a confined space?
- Where mercury removal is a dedicated bed, is it a lead-lag pair? Where it sits inside the sieve
  dryers, where does the regeneration water go?

Hazards: CO2 freezing in the low pressure column usually decides the configuration, and clearing it
means shutting down to derime; hydrates can form at start-up before the system is dry;
aluminium exchangers fail from temperature excursions, especially during cooldown, so rate of
change is what is monitored, under the manufacturer's procedures; a cold box is kept under dry inert
gas and watched for hydrocarbon accumulation; cold nitrogen vent gas is an asphyxiant; spent mercury
sorbent carries aromatics as well as mercury and needs a written change-out procedure.

## Outputs and provenance

The route and placement chosen with their basis and the project-specific thresholds left open.

## Required human judgment

Single versus double column, mercury bed placement and sorbent, cooldown and derime procedures,
vent location.

## References

- Mokhatab, Poe and Mak, *Handbook of Natural Gas Transmission and Processing*, 3rd ed.,
  Elsevier 2015, Ch 10 (nitrogen rejection configuration thresholds). Sources disagree; no
  threshold is given here.
- Needs review before operational use: all pressure, temperature, purity and mercury limits were
  dropped (no section-level citation); placement trade-offs and hazards retained as general
  descriptions.
- `tech-gas-ngl-recovery`, `tech-gas-lng-liquefaction`, `tech-gas-processing`.
