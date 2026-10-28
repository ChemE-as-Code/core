---
name: pid-design-isolation-vents-drains
description: What to consider for isolating, venting and draining equipment on a P&ID - which isolation type suits the hazard and whether people enter, the vent and drain branch, its size band and end, and battery limits. Use when adding block valves, drains, vents or blinds.
---

# Isolation, vents and drains

## Purpose and when to use

Equipment needing attention between turnarounds needs a way to be cut off, emptied and made safe
(Toghraei, *P&ID Development*, Wiley 2019, §8.7, §8.8).

## Required inputs and missing inputs

Fluid hazard, pressure, whether the equipment is entered, whether the connection is a process or
utility battery limit, and the project convention on hydrotest vents and drains.

## Workflow and tools

Engineering guidance only; core has no calculation for this.

**Isolation type** (Toghraei §8.7.2), as questions by case:
- Instrument or utility sub-header: a single root valve.
- Equipment nobody enters with benign fluid: block valve and blind.
- Where one seat passing is not tolerable (toxics, high pressure, steam, acids, live tie-ins):
  double block and bleed; utility and non-hazardous isolation is commonly a single block and a
  bleed, or block and check.
- Equipment a person enters: block valve, blind and removable spool. Valves alone are not entry
  isolation, since seats can pass, a bleed can plug and another party can reopen. Entry follows the
  site confined-space procedure; if a drawing leaves entered equipment with valves alone, raise it.

Block valves are line size (Toghraei §7.18); two in series need the bleed between them or one is
redundant (§7.11.1); a process line crossing a battery limit gets double block and bleed (CCPS,
*Guidelines for Engineering Design for Process Safety*, App. 6A), a utility connection a single
block and check, often with a blind; a blind is drawn in its open position. A ball or slab gate
valve that seals both ways can trap fluid in the body cavity and may need cavity relief or a
self-relieving seat, so seat direction matters (Sotoodeh, *A Practical Guide to Piping and Valves
for the Oil and Gas Industry*, Elsevier 2021, Ch 1, Ch 4).

**Vent or drain branch**: from a tee on the line or from the equipment nozzle, one block valve,
then a blind flange or a pipe to a closed drain header. Normally DN20 to DN50 (Toghraei §8.8.2.2);
larger for the bottom drain of a big vessel or for solids, wax or viscous liquid; report a size
outside the band as something to confirm. A flanged end allows a hose; an open-ended branch with
only a valve is a leak path. Vents are at the top, drains at the bottom; elevation is not on the
P&ID, so say which in the tag or description. Do not reuse a drain as a sample point without
saying so.

**Hydrotest vents and drains**: project conventions differ on whether they appear on the P&ID.
Ask which the project follows before reporting an absent high-point vent.

## Validation and failure handling

A drain branch ending in a blind is a dead leg by topology; that is expected and a review prompt,
not a defect.

## Outputs and provenance

Each branch with the equipment it serves and any location assumption.

## Required human judgment

Isolation type per hazard, entry isolation, closed-drain destination.

## References

Toghraei §7.11.1, §7.18, §8.7, §8.7.2, §8.8.2.2; CCPS App. 6A; Sotoodeh Ch 1, Ch 4. Needs review
before operational use: the DN20 to DN50 band, all section numbers (inherited), and the entry
isolation statement (safety-critical).
