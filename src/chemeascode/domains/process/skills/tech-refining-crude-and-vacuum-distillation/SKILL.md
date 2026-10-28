---
name: tech-refining-crude-and-vacuum-distillation
description: Reference for the refinery crude unit. Desalting, preflash, the atmospheric column with side strippers and pumparounds, overhead system, and the vacuum column with its ejector train. Use when crude or vacuum distillation is being discussed or reviewed.
---

# Crude and vacuum distillation

## Purpose and when to use

The first separation of the refinery: raw crude into light ends, naphtha, kerosene, diesel and
residue, then gas oil recovered from the residue under vacuum so the heavy end can be converted.
Reached from `tech-refining`.

## Required inputs and missing inputs

Crude assay and API gravity, salt content, light-ends content (decides a preflash), product cuts and
specifications (flash point), cooling water temperature, and the downstream limit on sodium if any.
Ask for any that is missing.

## Workflow and tools

Engineering guidance only; core has no calculation for this. A shortcut or rigorous column on
pseudocomponents is outside what core validates (`separation-method-selection` screens methods
for defined components; check `cheme process methods`).

Units in flow order: charge pumps with demulsifier and wash water, preheat train; one or two
desalters in series, each behind a mixing valve (wash water dissolves salt, an electrostatic grid
coalesces brine; make-up water enters the second stage; caustic downstream fixes residual chloride);
preflash tower or drum, only for crude rich in light ends; fired heater to transfer line temperature
(the master handle on flash-zone vaporisation); atmospheric column with steam stripping below the
flash zone; steam side strippers on kerosene and diesel draws to adjust flash point; pumparounds
returned above the draw, which exist because the overhead is too cold for heat recovery and
top-only reflux would swell vapour traffic; overhead system with air cooler and accumulator with a
water boot; fired vacuum heater and vacuum column with wash bed, heavy vacuum gas oil draw, bottom
quench; steam ejector train holding vacuum, non-condensables to a fired heater; foul water handling.

Heat limit: thermal cracking becomes measurable at around 650 degF, so what is limited is cracking
rate (temperature and time together), not temperature alone. Bottom and transfer-line temperatures
are held lower with short residence, and the rest of the separation is taken under vacuum. Reflux
drum pressure follows from the bubble point of the top product at the design cooling water
temperature, so the cooling medium sets the pressure profile.

Control reported: heater outlet temperature sets vaporisation and yield; top temperature on reflux;
each pumparound on duty; side strippers on steam; desalter interface level, mixing valve pressure
drop and wash water ratio; vacuum top pressure on ejector steam, bottom temperature on quench rate.

Variants: two-stage desalting where a downstream unit sets a tight sodium limit; very heavy crude
(below about 15 API) needs gas oil as diluent in the second stage; dry versus steam-stripped vacuum
operation changes ejector load and bottom arrangement; a second lighter vacuum draw may exist only
to recover heat at two levels.

## Validation and failure handling

Questions for a flowsheet or P&ID:

- Does every sidestream drawn as product have a stripper with vapour returned above the draw tray?
  (A heat-recovery-only vacuum draw and a dry vacuum column correctly show none.)
- Does each pumparound return above its draw with a cooler or exchanger?
- Does the accumulator have a water boot, and does the desalter show interface level control and a
  brine outlet?
- Are injection points for demulsifier, wash water, caustic, ammonia and corrosion inhibitor each
  from a named source?
- Do ejector discharge and sour water from accumulators and vacuum condensers have named destinations
  (heater or flare for vapour, stripper for water)?

Coking limits (coil residence time, minimum overflash keeping wash trays wet), overhead corrosion
(ammonia and filming inhibitor, caustic after the desalter) and the need for liquid-full oil phase at
the electrostatic grid are the reported failure drivers. Limits are cracking and coking limits, not
equipment ratings.

## Outputs and provenance

The line-up, cut and specification basis, and open points. Mark the figures below as a shape, not a
specification.

## Required human judgment

Cut points, desalting depth, heater and transfer line limits, corrosion control, and vent and flare
routing.

## References

- Parkash, *Refining Processes Handbook*, Elsevier 2003, Ch 1 (one worked 154,000 bpsd case:
  transfer line about 660 degF, flash zone vaporisation 50-60% of crude, overflash 3-6 LV%, vacuum
  heater outlet 730-770 degF). Indicative only; needs review before operational use.
- Retained as general method: the logic of pumparounds, strippers, overflash, cracking-rate limit.
- `tech-refining`, `tech-refining-residue-upgrading`.
