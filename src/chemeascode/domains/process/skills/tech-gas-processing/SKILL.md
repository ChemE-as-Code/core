---
name: tech-gas-processing
description: Orient a natural gas plant. Which units a feed analysis and a product specification imply, in what order, and which member skill (tech-gas-*) holds the detail for each. Use when a gas treating, liquids recovery or liquefaction line-up has to be understood or discussed.
---

# Gas processing (hub)

## Purpose and when to use

A gas plant is a spine of units chosen by two things, the feed composition and the product
specification (Mokhatab, Poe and Mak, *Handbook of Natural Gas Transmission and Processing*,
3rd ed., Elsevier 2015, Ch 3). Use this hub to settle those two before discussing any unit, then
go to the member skill. It is a reference for the process family, not a design procedure.

## Required inputs and missing inputs

- The feed analysis: liquids content, H2S, CO2, water, inerts (N2), mercury, heavy aromatics.
- The product: sales gas, LNG or NGL, with its specification (H2S, CO2, water content,
  hydrocarbon dew point, inerts, heating value).
- Whether the acid gas can be reinjected, and whether ethane or only propane and heavier is to be
  recovered.

If the mercury analysis is missing, ask for it before calling a mercury bed missing or surplus.

## Workflow and tools

Engineering guidance only; core has no calculation for this. To record the chosen line-up as
blocks and steps of the flowsheet, use skill `process-design`.

1. Start from the product. Sales gas, LNG and NGL are three different plants, and a small change
   in one specification can change the whole line-up.
2. Pick the archetype. Dew-point control suits a lean feed; liquids recovery is chosen when the
   ethane and heavier fractions are worth extracting, which is a commercial decision before it is
   a technical one.
3. Take the usual order of the spine, and drop or add units from the feed:

```
slug catcher -> inlet separation -> acid gas removal -> dehydration -> mercury removal
  -> dew point control or NGL recovery -> nitrogen rejection -> compression -> sales gas
```

   Liquids go to stabilisation and fractionation; acid gas goes to sulfur recovery and tail-gas
   treating, or to reinjection.

What decides which units appear:

- Liquid in the feed brings condensate stabilisation.
- Acid gas brings acid gas removal and, unless it is reinjected, sulfur recovery behind it.
- High inerts bring nitrogen rejection, placed after liquids recovery because heavy aromatics
  would freeze in it.
- The depth of CO2 and water removal is set by the coldest downstream step rather than by the
  sales specification: CO2 has to go lower ahead of ethane recovery than ahead of propane
  recovery, and glycol drying suffices only for warm duty where molecular sieve is needed before
  cryogenic temperatures.
- Where the feed carries mercury, a bed belongs ahead of brazed aluminium exchangers, because
  mercury attacks aluminium. A feed shown to be free of it may need none.
- Letting the feed down for separation means recompression on the way out.

Side systems hang off the spine: sour water stripping, glycol or methanol regeneration, sulfur
degassing and storage, condensate storage and vapour recovery, flare and utilities.

| Skill | For |
|---|---|
| `tech-gas-inlet-and-separation` | Slug catchers, inlet separation, condensate stabilisation |
| `tech-gas-acid-gas-removal` | Amine and physical solvent loops, membranes, scavengers |
| `tech-gas-dehydration` | Glycol contactors and molecular sieve driers |
| `tech-gas-ngl-recovery` | Joule-Thomson, refrigeration and turboexpander recovery, fractionation |
| `tech-gas-sulfur-recovery` | Claus plants, tail-gas treating, degassing, liquid redox |
| `tech-gas-nitrogen-and-mercury` | Nitrogen rejection and mercury removal |
| `tech-gas-lng-liquefaction` | Refrigeration cycles for liquefaction, end flash |

Unit-operation fundamentals (absorbers, columns, separators) are covered by `separation-method-selection`
and `thermodynamic-model-selection` where their calculations apply.

## Validation and failure handling

- Sizing is not one case. The front end and the refrigeration are set by the rich feed case; the
  demethaniser and residue compressor by the lean or high-inert case (Mokhatab, Poe and Mak, Ch 3).
  A plant sized on one case is wrong at the other: ask which cases the basis covers.
- The literature describes line-ups confidently but control schemes and trips thinly. Treat a
  unit's control philosophy and trip matrix as project information unless a cited source states
  it.

## Outputs and provenance

A short written line-up (units in order, why each is present or absent, the feed and product
basis, open questions) for `DESIGN.md`. Say which statements are general method and which are
indicative figures from the cited chapters.

## Required human judgment

Product slate, the choice between dew-point control and deep recovery, whether acid gas is
reinjected, flexibility to later ethane rejection or recovery, and every control and safeguarding
decision are the project's.

## References

- Mokhatab, Poe and Mak, *Handbook of Natural Gas Transmission and Processing*, 3rd ed.,
  Elsevier 2015, Ch 3. Retained as general method: product-first selection, the order of the
  spine, the dependence of removal depth on the cold section. Needs review before operational
  use: the sizing-case remark and the flexibility advice, which are guidance rather than rules.
- Member skills `tech-gas-*`; `process-design`.
