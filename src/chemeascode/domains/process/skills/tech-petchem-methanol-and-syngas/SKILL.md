---
name: tech-petchem-methanol-and-syngas
description: Process knowledge for synthesis gas generation (steam reforming, autothermal, partial oxidation, gasification) and methanol (compression, synthesis loop with purge, distillation) and near derivatives - units, conditions, control handles and what to question. Use when drafting or reviewing a syngas or methanol flowsheet.
---

# Methanol and synthesis gas

## Purpose and when to use

Reached from `tech-petrochemicals`. A methanol plant makes synthesis gas from natural gas, naphtha, coal or biomass, converts it over a
copper catalyst in a recycle loop and distils the crude product. Reforming is strongly endothermic; methanol formation from CO and CO2 is
exothermic and equilibrium limited, so the converter is cooled and the loop carries a large recycle (Speight 2011, Ch 8).

## Required inputs and missing inputs

Feedstock, capacity, steam to carbon ratio, reforming route, converter cooling concept. Energy figures (6.7 to 8 Gcal/t, about 30 GJ/t
including oxygen production) are not on a common basis: some include the oxygen plant. Ask for the basis before comparing.

## Workflow and tools

Engineering guidance only; core has no calculation for this. Core's reaction library has `methanol`, `steam_reforming`, `ht_shift`,
`lt_shift`, `methanation`, `formaldehyde` entries (see `reactions`). Methanol in mixtures and liquid synthesis products are outside the
validated property package (see `process-design`); give such values with a source. Units in flow order:

1. Feed compression and desulfurisation (hydrogenation plus zinc oxide ahead of everything; sulfur poisons the reforming catalyst).
2. Steam addition at a set steam to carbon ratio, optional prereformer on heavier feeds.
3. Reforming: fired tubular, oxygen-blown autothermal with an air separation unit, gas-heated reforming exchanger with autothermal, or gasification.
4. Waste heat recovery on the reformer outlet (steam for compressors and column reboilers), cooling, condensate separation.
5. Stoichiometry trim (CO2 or hydrogen addition) and syngas compression.
6. Synthesis loop: circulator, converter with reaction heat recovered as steam, cooling and condensation of crude methanol, separator; recycle to
   circulator suction with a purge burned as reformer fuel, preventing accumulation of nitrogen, methane and hydrogen.
7. Distillation: two or three columns; light ends first, then water and higher alcohols.

| Item | Source value |
|---|---|
| Steam reforming | about 815 degC over nickel, window 730 to 845 degC at about 28 bar (400 psi) |
| Steam to carbon | 2.5 to 3 molar, autothermal and secondary reforming |
| Synthesis loop | 30 to 100 bar (quoted variously) |
| Converter | 200 to 280 degC |

Control handles: steam drum pressure on the converter shell sets reaction temperature; purge rate sets loop composition (destination fuel, not
atmosphere); steam to carbon on the feed protects against carbon laydown. Beyond these the source gives heat integration, not loops.

Variants: converter cooling (boiling water tubes, plate, water-cooled then gas-cooled, adiabatic beds with interbed exchange, radial flow).
Partial oxidation suits heavy, high-sulfur feeds because temperature replaces a catalyst. Near derivatives: dimethyl ether by methanol dehydration,
formaldehyde by methanol oxidation over silver, substitute natural gas by staged methanation.

## Validation and failure handling

Questions to put to the design:

- Does every path reaching a nickel bed pass a desulfurisation or guard bed?
- Does heat recovery sit directly on the reformer and converter outlets?
- Does the loop show a circulator, separator and recycle with a purge that has a fuel or recovery destination?
- Is condensate recovered where a saturator exists, and does the steam drum carry pressure control?
- Does distillation make at least a light ends cut and a water cut?
- On heavier feeds carbon laydown accumulates, which caps the feed range; was a prereformer or alkali-promoted catalyst considered?

Column control, drum levels and antisurge schemes are project information.

## Outputs and provenance

Record reforming route, loop pressure, purge destination and the basis of any energy figure in `DESIGN.md`.

## Required human judgment

Reformer tube and converter safeguarding, loop relief, flammable inventory and fire protection, catalyst choice. This skill certifies none of them.

## References

- Speight, *Handbook of Industrial Hydrocarbon Processes* (Elsevier 2011), Ch 8.
- Independently verifiable general method: reaction thermodynamic character, the role of the purge, steam to carbon and laydown.
- Needs review before operational use: temperature and pressure ranges, the energy figures, the variant list.
