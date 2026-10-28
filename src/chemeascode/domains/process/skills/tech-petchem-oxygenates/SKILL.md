---
name: tech-petchem-oxygenates
description: Process knowledge for ethylene oxide and glycols by direct oxidation (ballasted recycle loop, CO2 removal, absorber and stripper, glycol reaction, evaporation, vacuum distillation) and the related oxidation and oxo products. Use when drafting or reviewing an ethylene oxide or glycol flowsheet.
---

# Oxygenates by partial oxidation

## Purpose and when to use

Reached from `tech-petrochemicals`. These plants add oxygen to an olefin or paraffin, most commonly ethylene to ethylene oxide and then to mono-, di- and triethylene
glycol. Oxidation over silver is exothermic with total combustion to CO2 and water as the competing reaction; the oxide hydrates, also exothermically, to glycols
(Speight 2002, Part 2).

## Required inputs and missing inputs

Oxidant (air or oxygen), glycol slate, capacity. Yield figures in the source sit on incompatible bases (per-pass selectivity versus overall yield) and temperature windows are
source dependent (225 to 325 degC at 55 to 70 % yield in Speight 2011, Ch 12, versus 270 to 290 degC): ask for the basis, do not average.

## Workflow and tools

Engineering guidance only; core has no calculation for this. Core's reaction library has `ethylene_oxide`, `maleic_anhydride`, `acrylonitrile`, `formaldehyde`
entries (stoichiometry only; see `reactions`). Units:

1. Fresh ethylene and oxygen mixed into recycle gas carrying a methane or nitrogen ballast.
2. Multitubular reactor with boiling water on the shell, then exchange against reactor feed.
3. Water-scrubbed absorber taking the oxide from the reactor gas.
4. Recycle gas compressor; a slipstream through CO2 removal and a purge for argon and inerts. Two absorber/stripper pairs (product and CO2) are the signature.
5. Oxide recovery: steam stripping, aqueous oxide to its own purification or to the glycol section; stripped water to the absorber.
6. Glycol reactor on aqueous oxide with recycle water.
7. Multi-effect evaporation (the last effect raising low pressure steam), then drying.
8. Vacuum distillation train for mono-, di- and triethylene glycol (boiling about 198, 246, 288 degC) with a heavy residue purge.

| Item | Source value |
|---|---|
| Oxidation reactor | 270 to 290 degC, about 8 to 21 bar (120 to 300 psi), about 1 s |
| Catalyst selectivity | 91 to 92 % fresh, 89 to 90 % averaged over three years |
| Glycol reaction | about 90 % yield at oxide:water 1:5 to 1:8 |

Control handles: reactor temperature via the boiling-water shell steam pressure; fresh ethylene and oxygen trimmed into the loop; excess water as selectivity handle in the glycol reactor.

Variants: air or oxygen oxidation; glycol via ethylene carbonate; ethanol dehydrated upstream. The oxo route (propylene, synthesis gas, catalyst in solution) is structurally different;
the source describes only the aldehyde step, and phthalic anhydride is absent.

## Validation and failure handling

Questions to put to the design:

- Does the recycle loop show a CO2 slipstream, a purge, a ballast source and a steam drum on the reactor shell?
- How does the loop keep gas composition outside the flammable region, and what prevents oxygen breakthrough into a hydrocarbon stream? Is concentrated oxide inventory minimised
  (stripped oxide reabsorbed promptly) and held only in dedicated product storage?
- Does stripped water return to the absorber, does the glycol train run under vacuum with a residue purge, does the last evaporator effect have a steam user, and do vents have a treatment destination?
- Neighbouring oxidations: acrylic acid dimerises (dedimeriser on finishing column bottoms); acrylonitrile makes hydrogen cyanide to recover or destroy; a near-stoichiometric maleic anhydride fluid bed makes
  heat removal a safety function.

## Outputs and provenance

Record oxidant, ballast, yield basis and sources in `DESIGN.md`.

## Required human judgment

Flammability management of the oxygen loop, ethylene oxide hazards (decomposition, toxicity), relief, vent treatment. This skill certifies none of them.

## References

- Speight, *Chemical Process and Design Handbook* (McGraw-Hill 2002), Part 2; Speight 2011, Ch 12.
- Independently verifiable general method: heat removal by boiling water, CO2 removal and purge logic.
- Needs review before operational use: yield and temperature figures, all safeguard statements (safety-critical).
