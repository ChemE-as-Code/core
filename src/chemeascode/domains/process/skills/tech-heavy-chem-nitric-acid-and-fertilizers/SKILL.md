---
name: tech-heavy-chem-nitric-acid-and-fertilizers
description: Process knowledge for nitric acid (ammonia oxidation, absorption, tail gas, concentration), ammonium nitrate, wet-process phosphoric acid and phosphate fertilizers - units, conditions, materials breaks and what to question. Use when drafting or reviewing a nitric acid or fertilizer flowsheet.
---

# Nitric acid and fertilizers

## Purpose and when to use

Reached from `tech-heavy-chemicals`. This family turns ammonia into nitric acid and nitrates, and
separately turns phosphate rock and sulfuric acid into phosphoric acid and phosphate fertilizers.
Ammonia burns over a platinum-rhodium gauze to nitric oxide and water (strongly exothermic); the
oxide oxidises further and hydrates to nitric acid, also exothermic. Neutralising nitric or
phosphoric acid with ammonia releases heat that does the first concentration, so reactor and
evaporator are coupled. Wet-process phosphoric acid is an acid attack on rock driven by the sulfuric
acid.

## Required inputs and missing inputs

Product and strength, route (prilling or melt for nitrate; fertilizer grade), ammonia, acid and rock
sources. The source gives no absorption tower residence time and no tray or packing count: ask.

## Workflow and tools

Engineering guidance only; core has no calculation for this. The reaction library has
`cheme chemistry library nitric_acid` (stoichiometry only, see `reactions`). Units (Speight, Part 2):

- Nitric acid: ammonia and filtered air to the gauze reactor (a stack of 10 to 30 sheets), cooling
  and heat recovery, absorption tower taking water and additional air (the nitric oxide must oxidise
  inside the tower before it hydrates; product about 65 %), tail gas treatment by reduction of
  nitrogen oxides with hydrogen or methane. Above 68 % the acid forms an azeotrope with water, so a
  concentration tower runs against strong sulfuric acid (or magnesium nitrate as drying agent).
- Ammonium nitrate: reactor on ammonia and about 60 % acid boiling on the neutralisation heat, vacuum
  evaporator, prilling tower, screen and dryer; a melt variant replaces the prill tower with a combined
  reactor-separator, cooling chamber and cooler.
- Wet-process phosphoric acid: rock ground with dilute product acid (the defining recycle), reactor with
  sulfuric acid, filter dropping calcium sulfate, evaporator; reactor off-gas to an absorber making
  fluorosilicic acid. Purification where needed is solvent extraction.
- Phosphates: monoammonium phosphate (ammonia and phosphoric acid, centrifuge, dryer); diammonium
  phosphate with a two-stage reactor to limit ammonia loss, then drum granulation; superphosphates
  as partial wet-process chemistry.

| Item | Source value |
|---|---|
| Gauze reactor | 750 to 920 degC, about 7 bar (100 psi), 2 to 10 % rhodium in platinum |
| Absorption product | about 65 %; azeotrope 68.4 % at 121.9 degC |
| Nitrate reactor and evaporator | to 85 % on neutralisation heat, then vacuum at 125 to 140 degC to 95 % |
| Prill tower | 60 to 70 m, 2 mm prills |
| Phosphoric reactor | 75 to 80 degC, 4 to 8 h, filtrate 28 to 35 % P2O5, 54 % after evaporation |

## Validation and failure handling

Questions to put to the design:

- Does the absorption tower have two feeds, water and air? Does a specification above 68 % show a
  concentration tower with a drying-agent stream and spent-agent draw?
- Does the tail gas reach an abatement step before the stack?
- Does the nitrate train sequence match the route (prilling or melt)?
- Does the phosphoric acid plant return dilute acid to the mill and send reactor vent to a fluoride
  absorber? Is calcium sulfate on a washed filter with filtrate returned, and are there two reaction
  stages for diammonium phosphate?
- Is the ammonia-to-air ratio at the burner a controlled composition (the mixture has a flammable
  range)? Absorption with reaction heats the lower tower, so heat removal is needed (Ray and Das, Ch 10).
- Ammonium nitrate: controlled decomposition begins at 200 to 260 degC and explosive decomposition is
  the failure mode; the source notes blending in calcium carbonate to reduce nitrogen from 35 to 26 %
  as hazard reduction. Ask what temperature and contamination safeguards the project has.

Materials: the 68 % boundary separates the usual austenitic stainless duty from strong nitric with
strong sulfuric acid at temperature, which the source assigns to silicon-iron or stoneware.
Wet-process phosphoric acid is fluoride service (lined, graphite or high alloy). Ammonium nitrate solids
need moisture exclusion, and hot concentrated solutions and melt are also corrosive. Judge against the
project materials basis. The source names no loops, trips or relief devices.

## Outputs and provenance

Record route, strength targets, tail gas basis and sources in `DESIGN.md`; draw with `process-design`.

## Required human judgment

Ammonium nitrate hazard management, ammonia-air explosion protection, tail gas limits, materials
selection, precious metal loss accounting. This skill certifies none of them.

## References

- Speight, *Chemical Process and Design Handbook* (McGraw-Hill 2002), Part 2 (nitric acid, ammonium
  nitrate, ammonium phosphate, phosphoric acid, fertilizers) and Part 1 (nitration).
- Ray and Das, *Process Equipment and Plant Design* (Elsevier 2020), Ch 10.
- Independently verifiable general method: reaction chemistry and exotherms, the nitric acid-water
  azeotrope, need for air to the absorber.
- Needs review before operational use: all conditions in the table, the ammonium nitrate decomposition
  and calcium carbonate statements (safety-critical), the materials statements.
