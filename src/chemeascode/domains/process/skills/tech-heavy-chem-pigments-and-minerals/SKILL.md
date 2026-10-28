---
name: tech-heavy-chem-pigments-and-minerals
description: Process knowledge for titanium dioxide (sulfate and chloride routes), alumina (Bayer), soda ash (ammonia-soda) and carbon black - units, recycles and purges, conditions and materials breaks. Use when drafting or reviewing a pigment or mineral processing flowsheet.
---

# Pigments and minerals

## Purpose and when to use

Reached from `tech-heavy-chemicals`. These are plants where the reaction is cheap and the solids handling
is not: titanium dioxide from ilmenite or rutile, alumina from bauxite, soda ash from salt and limestone,
carbon black from aromatic oil.

## Required inputs and missing inputs

Feed (ilmenite or rutile, bauxite assay, brine and limestone, oil), route, product grade or crystal form.
The source's trona figure lost its labels in extraction and is not used.

## Workflow and tools

Engineering guidance only; core has no calculation for this. Routes (Speight, Part 2):

- TiO2 sulfate route: ilmenite, sulfuric acid and scrap iron to digestion (the violent exothermic attack),
  then separation, crystalliser and settler dropping iron sulfate heptahydrate, hydrolyser, filter,
  calciner; spent acid and unreacted ilmenite drawn off. Scrap iron keeps iron ferrous so it crystallises
  out. Seeds choose the crystal form, so seed preparation is a process unit.
- TiO2 chloride route: rutile or slag with coke and chlorine to the chlorinator, separator, still
  distilling titanium tetrachloride, oxidation reactor on oxygen, chlorine recovery closing the loop.
- Alumina (Bayer): bauxite, lime, soda ash and hot water with steam to the digester, washing thickener,
  filters taking out red mud, calciner. Cooling drives precipitation; spent caustic returns to digestion
  (the defining recycle) and red mud is its purge.
- Soda ash: brine and ammonia to the absorber, two carbonating towers, vacuum filter, dryer; limestone to
  kiln and slaker for the carbon dioxide; filtrate to an ammonia still. Ammonia and carbon dioxide recycle;
  calcium chloride is the purge. Dense ash is made from light ash by rehydrating and redrying.
- Carbon black: oil preheated, reaction chamber, quench, precipitators, cyclones, bag filter, pulverising
  and pelletising. Feed is atomised into hot gas with too little air to burn it.

| Item | Source value |
|---|---|
| Sulfate route, continuous variant | 25 to 60 % acid |
| Seeding | anatase seeds 6 h boiling, rutile seeds 3 h |
| Anatase to rutile | 700 to 950 degC |
| Titanium tetrachloride | boils 136 degC; oxidised in a flame near 1500 degC |
| Bauxite assay | 35 to 60 % alumina, 1 to 15 % silica, 5 to 40 % ferric oxide |
| Calcination | alumina 980 degC (99 to 99.5 %); bicarbonate 175 degC (light ash) |
| Carbon black | 1400 to 1650 degC, microsecond residence, quench to about 200 degC |

## Validation and failure handling

Questions to put to the design:

- Does the Bayer plant return spent caustic to the digester with red mud leaving on a washed filter? Does the
  soda ash plant show both recycles?
- Chloride route: chlorine recovery to the chlorinator, still ahead of the oxidation reactor. Sulfate route:
  iron sulfate dropped before hydrolysis and spent acid given a destination.
- After a rapid-cooling reaction (carbon black) is there a quench zone; otherwise heat recovery or a cooler?
  Wet solid trains end in solid-liquid separation and drying or calcination, with mother liquors returned;
  dry trains end in gas-solid separation.
- Hydrolysis needs controlled pH and heating ramp as well as seeding to make the specified crystal form.
- Materials: sulfate digestion is the worst service (concentrated acid, entrained sulfur oxides). Sulfuric
  acid to 50 % in graphite exchangers with non-metallic piping (Ray and Das, Ch 6). Bayer digestion is hot
  caustic under pressure (caustic below 40 % in stress-relieved carbon steel, stronger in nickel). Dry
  chlorine and tetrachloride permit metals that wet chlorine does not. Slurries are abrasive; the carbon
  black bag filter is kept above the gas dew point.

The source names no loops, trips or relief devices; relief, kiln and furnace safeguarding and dust handling
are project information.

## Outputs and provenance

Record route, crystal form basis and sources in `DESIGN.md`; draw with `process-design`.

## Required human judgment

Kiln and furnace safeguarding, dust explosion protection, chlorine handling, effluent and red mud disposal,
materials selection. This skill certifies none of them.

## References

- Speight, *Chemical Process and Design Handbook* (McGraw-Hill 2002), Part 2 (titanium dioxide, alumina,
  sodium carbonate, carbon black, lithopone, zinc oxide).
- Ray and Das, *Process Equipment and Plant Design* (Elsevier 2020), Ch 6.
- Independently verifiable general method: recycle and purge identification for each route.
- Needs review before operational use: all temperatures and assays above, carbon black quench basis, the
  seeding times.
