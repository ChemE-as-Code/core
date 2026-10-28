---
name: unit-ops-refrigeration
description: Refrigeration loops - how the evaporator temperature picks the system (steam jet, absorption, mechanical, cascade), the mechanical cycle and its easily omitted items, multistage arrangements, and low-side pressure. Use when a refrigeration or chilling loop is designed or reviewed.
---

# Refrigeration

## Purpose and when to use

A refrigeration rating means nothing without the temperature it is delivered at; ask for both
(Ludwig, *Applied Process Design for Chemical and Petrochemical Plants* v3, Elsevier 2001, Ch 11).

## Required inputs and missing inputs

Duty, delivery temperature, cooling-water or ambient temperature, refrigerant constraints, and
whether the loop is opened routinely. Ask for what is missing.

## Workflow and tools

Engineering guidance only; core has no calculation for this. Compressor power and exchanger duties
from `cheme datasheets fill` and `cheme process energy` apply once the loop is in the flowsheet.

Temperature level picks the system:

| Evaporator temperature | System |
|---|---|
| Above about 0 C | Steam jet, or lithium bromide absorption |
| About 0 to -40 C | Ammonia-water absorption, or mechanical compression |
| About -40 to -60 C | Mechanical compression, single refrigerant |
| Below about -60 C | Mechanical, low-boiling refrigerant, usually cascaded once compression ratio or freezing point makes one loop impractical |

The refrigerant evaporates a few degrees colder than the process; a wider gap shrinks the evaporator
but raises compressor power, a cost trade.

Mechanical cycle: compressor, condenser, receiver, expansion valve, evaporator. Items easily left off:
the receiver (sized for inventory, and for the whole charge only if the loop is to be pumped out into
it); the expansion valve as close to the evaporator inlet as practical, to keep the two-phase run
short (a distributor between valve and bundle is normal); a purge for non-condensables, standing on
a low-pressure machine whose low side runs below atmospheric or on a system opened routinely, often
absent on a sealed loop held above atmospheric; a suction knockout ahead of a centrifugal compressor,
and a few degrees of suction superheat on reciprocating machines. The evaporator is normally
refrigerant on the shell side; a wet evaporator needs disengaging space and a level, and oil and
water collect and need draining.

Multistage: an economiser flashes condensed liquid at an intermediate pressure and sends the vapour
to an intermediate stage (one is usual, two enough for almost anything); compound compression keeps
one refrigerant with a liquid intercooler; cascade uses two loops with different refrigerants, each
with its own compressor, condenser and controls: say which loop is meant.

Further points (Ludwig Ch 11): a vapour-compression low side is usually kept at or above
atmospheric because air ingress brings moisture and with some refrigerants a flammable mixture;
it is a preference, since steam-jet and absorption chillers run under vacuum by design and handle
ingress by purging. Discharge pressure follows the available condensing temperature. Compressor
discharge temperature is generally held below roughly 140 C. Direct expansion against the process is
preferred to a brine loop, which adds a heat-transfer step, corrosion, and its own pump, expansion
and inhibitor control. A large system holds a large refrigerant inventory, so toxicity and
flammability drive the choice of refrigerant and the relief and detection.

## Validation and failure handling

Identify the system before naming anything missing: steam-jet and absorption machines have no
compressor, receiver or expansion valve. Mechanical loop questions: expansion valve far from the
evaporator; receiver absent or small (ask whether pump-out is intended); no purge where the low side
can go sub-atmospheric; no suction knockout on a centrifugal machine. Steam-jet or absorption:
no motive steam or heat supply, non-condensable removal or solution circulation. A cascade drawn as
one loop. A sub-atmospheric low side: ask how air ingress is managed, do not call it a defect.

## Outputs and provenance

State the system, delivery temperature and the source of each rule. Record in `DESIGN.md`.

## Required human judgment

Refrigerant choice, inventory and every detection and relief provision need a person.

## References

- Ludwig v3 Ch 11.
- `datasheets`, `unit-ops-heat-transfer`.
- Retained as general method: system selection by level, cycle components, cascade/economiser logic.
- Needs review before operational use: temperature bands, 140 C discharge limit, economiser count.
