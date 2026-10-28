---
name: tech-petchem-ammonia-and-urea
description: Process knowledge for ammonia from hydrocarbons (desulfurisation, reforming, shift, CO2 removal, methanation, synthesis loop and purge) and urea (synthesis loop, decomposition, evaporation, finishing) - units, conditions, control handles and what to question. Use when drafting or reviewing an ammonia or urea flowsheet.
---

# Ammonia and urea

## Purpose and when to use

Reached from `tech-petrochemicals`. An ammonia plant makes hydrogen from a hydrocarbon and nitrogen from air,
combines them in a recycle loop, and commonly feeds a urea plant with ammonia and its own carbon dioxide.
Reforming is endothermic, shift exothermic, ammonia synthesis exothermic and equilibrium limited, so the converter
is cooled and most gas recycles. In urea, carbamate forms exothermically and dehydrates endothermically under
equilibrium control, so unconverted carbamate is decomposed and returned.

## Required inputs and missing inputs

Feedstock, capacity, urea or ammonia product, steam to carbon ratio, catalyst choice (loop pressure follows it).
Quoted ammonia energy totals differ by roughly 10 % on non-uniform bases: do not compare them without a common basis.

## Workflow and tools

Engineering guidance only; core has no calculation for this. Core's reaction library has `ammonia`, `steam_reforming`,
`ht_shift`, `lt_shift` and `methanation` entries (equilibrium basis, see `reactions`). For property coverage see
`process-design`: the syngas vapour package covers H2, N2, Ar, CH4, CO, CO2 and mixtures within boxes, NH3 pure and
in loop gas with H2, N2, Ar, CH4 up to mole fraction 0.25 (Ar then up to 0.10, CH4 up to 0.20), and CH4 in mixtures
to 673.1 K. Richer ammonia, hotter converter gas with CH4, liquid ammonia and separator VLE are refused, so give them
with a source.

Units in flow order:

1. Feed compression and hydrodesulfurisation, steam addition at a set steam to carbon ratio, prereformer on heavier feeds.
2. Fired primary reformer, then an air-fed secondary reformer (air supplies nitrogen; its oxygen burns feed).
3. Waste heat boiler raising high pressure steam on each reformer outlet.
4. High and low temperature shift, then wet CO2 removal; that CO2 is the urea feed.
5. Methanation as the final guard on carbon oxides (which poison the synthesis catalyst), drying, syngas compressor.
6. Multi-bed converter with interbed exchange or quench, heat recovery, chilling, product separator; unconverted gas
   recycles to compressor suction with an inert purge.
7. Urea synthesis loop: high pressure ammonia pump and CO2 compressor, reactor, steam-heated stripper at reactor
   pressure, carbamate condenser, scrubber.
8. Medium and low pressure decomposition, returning carbamate upward.
9. Vacuum evaporation to melt, prilling or granulation, process condensate to desorber and hydrolyser.

| Item | Source value |
|---|---|
| Primary reformer | about 40 to 42 bar, 800 to 850 degC exit |
| Steam ratio, shift | steam ratio about 2.7, shift inlet about 250 degC |
| Synthesis loop | pressure depends on catalyst; the source quotes up to 140 to 220 kg/cm2g on iron |
| Ammonia storage | chilled to about -33 degC, or warm liquid to urea |
| Urea synthesis | 140 to 155 bar, 182 to 190 degC, N:C about 3.7 |
| Urea decomposition | 17 to 20 bar medium, 2.5 to 4.5 bar low pressure |
| Urea consumption | 564 to 567 kg NH3 and 730 to 735 kg CO2 per t |

The urea consumption is consistent with stoichiometry (2 NH3 + CO2 giving urea and water: about 567 kg NH3 and 733 kg CO2
per tonne); that part is independently checkable. Licensor-specific loop and reformer variants are not covered; the
generic fork on the urea side is CO2 or ammonia stripping.

Control handles named by the source: process air to the secondary reformer trims the H2:N2 ratio; steam to carbon is set on
the feed; converter bed temperatures by interbed exchange or quench; refrigeration duty sets condensation temperature;
purge rate holds inert level; methanator outlet analysis gates the loop; in urea the feed ratio and stripper steam rate set conversion.

## Validation and failure handling

Questions to put to the design:

- Does the synthesis recycle run from the separator to compressor suction with an inert purge that has a fuel or recovery
  destination? A purge-free design needs feed purification that explains why.
- Is a desulfuriser upstream of the reformer (hydrogenation plus zinc oxide is normally enough on natural gas, Speight 2011 Ch 8)
  and a methanator between CO2 removal and the converter?
- Does each reformer outlet and the converter outlet go to a heat sink without an uncooled run? Has the CO2 from removal a destination?
- Does each urea decomposition stage return carbamate upward, process condensate reach a hydrolyser, and flash gas get a water scrub before any burner?
- Urea is a corrosion-governed plant: temperature and feed ratio are justified by corrosion as much as conversion.

## Outputs and provenance

Record the front end, loop pressure basis, purge treatment and sources in `DESIGN.md`.

## Required human judgment

Synthesis loop and reformer safeguarding, ammonia release and storage hazards, catalyst choice, materials for urea service, relief
and isolation. This skill certifies none of them.

## References

- Speight, *Handbook of Industrial Hydrocarbon Processes* (Elsevier 2011), Ch 8.
- Independently verifiable general method: urea stoichiometry, the reaction-sequence logic.
- Needs review before operational use: all table conditions, the uncited statements on water scrubbing of flash and purge gas and on cooled
  tubesheets, loop pressure ranges.
