---
name: tech-refining-hydroprocessing
description: Reference for refinery hydrotreating and hydrocracking. Feed surge, fired heater, multi-bed reactor with quench, recycle gas loop, separator cascade, amine wash and fractionation, with variants and hazards. Use when a hydroprocessing unit is being discussed or reviewed.
---

# Hydroprocessing

## Purpose and when to use

Reacts a liquid cut with hydrogen over a fixed-bed catalyst, either to remove sulfur, nitrogen,
oxygen, olefins and metals (hydrotreating) or to also break it into lighter products
(hydrocracking). Reached from `tech-refining`.

## Required inputs and missing inputs

Feed cut and properties (sulfur, nitrogen, metals, boiling range), required conversion and product
specifications, hydrogen availability and purity, and operating pressure. Ask for any that is missing.

## Workflow and tools

Engineering guidance only; core has no calculation for this. Reaction heat and bed temperature rise
for petroleum cuts are outside what core computes; if a defined-component reaction is modelled, see
`reactions` and `cheme process reactors`, which do not cover catalyst kinetics for these cuts.

The common skeleton: feed filters and inert-blanketed surge drum (dissolved oxygen fouls exchangers);
charge pump; feed joined with recycle hydrogen and heated against reactor effluent, with an oil bypass
so the fired heater retains control authority; fired heater (or a separate gas heater); downflow
reactor of one to four beds with distributors and an interbed quench, beds sized unequally so each
takes a similar temperature rise; effluent cooling with wash water injected upstream of the air cooler;
separator cascade (hot, optionally warm for asphaltenes on resid, cold, then low-pressure
separators, sometimes with a power recovery turbine); recycle gas loop (knockout, amine absorber,
knockout, compressor, part to interbed quench, rest to feed; make-up hydrogen ahead of the
compressor; a purge holding purity); fractionation with a stripper, second amine contactor and
product fractionator.

Quench is sized on reaction heat per unit of hydrogen consumed, which differs by reaction type, so a
cracked feed needs much more (Parkash, *Refining Processes Handbook*, Elsevier 2003, Ch 2 and 3).

Variants: light cuts can run once-through with no recycle compressor. Hydrocracking is single-stage
once-through at partial conversion, single-stage with recycle of bottoms, or two-stage, where a
clean second stage gives the best product qualities. Recycle to extinction is avoided because
refractory material concentrates. Ebullated-bed resid hydrocracking is near isothermal with no quench
system. For mild hydrocracking the source gives conditions but not topology; treat its line-up as
project information.

Control reported: reactor inlet temperature on heater fuel (in an operating hydrocracker bed temperature
is the only conversion handle, raised through the run); interbed quench on each bed inlet temperature;
cold separator temperature held steady; make-up hydrogen on loop pressure; purge on recycle purity;
amine on treated gas H2S; wash water set so it does not fully vaporise at the injection point.

## Validation and failure handling

Questions for a flowsheet or P&ID:

- On a unit with a recycle loop, does the loop close through knockout, amine absorber, compressor,
  quench headers and feed? On a once-through light-cut unit, where does separator vapour go?
- Does the loop have a purge with a destination and make-up hydrogen with a named source?
- Is wash water injected upstream of the air cooler, and does the separator have a water draw?
- On a multi-bed fixed-bed reactor, are quench connections between beds? (A single-bed reactor or an
  ebullated bed has none.)
- Do stripper and flash drum overheads reach an amine contactor before the fuel header, and does sour
  water reach stripping?

Thermal runaway is bounded by the interbed quench and a per-bed temperature rise limit which is
service specific, tighter for hydrocracking; take it from the reactor datasheet (`cheme datasheets`
for the datasheet workflow), not from this skill. Channelling and plugging are watched through
temperatures at several circumferential positions and bed pressure drop. Shutdown hazards to be
answered by the design: metal carbonyl formation if beds cool with CO present, pyrophoric material and
hydrogen on opening, and exceeding exchanger design temperature on fast feed cut. Wash water and
polysulfide address ammonium bisulfide and cyanide attack. This skill does not certify any protection.

## Outputs and provenance

Line-up, hydrogen balance basis, and open points; state that conditions are from worked cases.

## Required human judgment

Conversion severity, quench and temperature limits, shutdown and catalyst handling procedures,
hydrogen purity.

## References

- Parkash, *Refining Processes Handbook*, Elsevier 2003, Ch 2 and 3 (worked hydrotreating and
  hydrocracking cases; quench sizing basis). Indicative figures from the cases (reactor pressure
  classes from about 300 psia for naphtha up to about 2600 psig for hydrocracking) are not
  specifications; needs review before operational use.
- `tech-refining`, `tech-refining-hydrogen-and-sulfur`.
