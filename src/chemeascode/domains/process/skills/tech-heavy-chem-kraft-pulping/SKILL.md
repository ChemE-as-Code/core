---
name: tech-heavy-chem-kraft-pulping
description: Process knowledge for kraft pulp mills - digester, brown stock washing, bleaching, black liquor evaporation, recovery furnace, causticizing and lime kiln, by-products - with the nested sodium and calcium loops and materials breaks. Use when drafting or reviewing a kraft pulping flowsheet.
---

# Kraft pulping and chemical recovery

## Purpose and when to use

Reached from `tech-heavy-chemicals`. A kraft mill cooks wood chips in alkaline sulfide liquor to
separate fibre from lignin, then burns the lignin to recover the cooking chemicals. The chemical loop is
nearly closed, but the mill still takes water, steam, air, lime and make-up sodium sulfate and sends out
turpentine, tall oil, effluent, flue gas and often power. The cook is endothermic and steam driven;
recovery is the exothermic half.

## Required inputs and missing inputs

Wood type (hardwood has less lignin and more hemicellulose than softwood, changing cook and yield),
capacity, bleaching sequence, by-product recovery. The source gives no evaporator effect count,
furnace duty or bleach charge, and its wood composition is indicative only: ask.

## Workflow and tools

Engineering guidance only; core has no calculation for this. Units in flow order (Speight, Part 2):

1. Chip handling and digester (chips, steam, white liquor).
2. Blow and brown stock chest.
3. Pulp washers: black liquor leaves here carrying 95 to 98 % of the chemicals charged, so washing
   efficiency is recovery efficiency.
4. Screens, head box and dryer giving dried pulp. A paper machine is a separate plant; do not infer
   one from a pulp dryer.
5. Bleach plant where used, alternating oxidising stages with alkaline extraction.
6. Multiple-effect evaporators for weak black liquor, with disk or cascade evaporators for the final
   concentration (Ray and Das, Ch 6).
7. Recovery furnace: organics burn while sulfate is reduced to sulfide in the same vessel.
8. Dissolving tank (green liquor), causticizers (lime converts carbonate to caustic, giving white liquor),
   lime mud filter and lime kiln: a calcium loop nested inside the sodium loop.

By-products: turpentine from digester relief gases, tall oil soap skimmed from black liquor and acidified,
dimethyl sulfide and methyl mercaptan from digester and evaporator vapours. Dimethyl sulfoxide needs its own
oxidation unit. Vanillin comes from sulfite liquor, not kraft.

| Item | Source value |
|---|---|
| Digestion | 170 to 175 degC, 7 to 9 bar (100 to 135 psi), 2 to 5 h |
| Liquor ratio | 1 part wood to 4 parts white liquor |
| Digester | about 12 m high, 6 m diameter, up to 35 t chips |

## Validation and failure handling

Questions to put to the design:

- Is the recovery island complete (evaporators, furnace, dissolving tank, causticizers, lime kiln) with
  carbonate and white liquor both returned, and is black liquor drawn from the washers rather than the digester?
- Where does sodium sulfate make-up enter? Does the evaporator train show a feed preheater (a subcooled
  feed creates cold zones, Ray and Das Ch 6) and a named vapour destination?
- Does the bleach plant alternate oxidising and alkaline stages?
- How is a reducing bed held in the furnace while organics burn above it (air staging)? The source says
  the dual role exists but not how it is held.
- Material breaks: caustic digester (hot alkaline sulfide under pressure, embrittlement service); caustic
  below 40 % in stress-relieved carbon steel versus stronger in nickel across the evaporator train;
  oxidising chloride service in the bleach plant; abrasive green liquor and lime mud; acid service for
  tall oil.

The smelt-water hazard, digester relief and bleach plant chlorine safeguarding are covered by no source
here; they are project information. Cooking is a time and temperature schedule, not a continuous loop.

## Outputs and provenance

Record wood basis, washing efficiency target and sources in `DESIGN.md`; draw with `process-design`.

## Required human judgment

Smelt-water explosion protection, digester and recovery boiler safeguarding, bleach chemicals handling,
materials selection. This skill certifies none of them.

## References

- Speight, *Chemical Process and Design Handbook* (McGraw-Hill 2002), Part 2, kraft pulping, turpentine and
  tall oil.
- Ray and Das, *Process Equipment and Plant Design* (Elsevier 2020), Ch 6.
- Independently verifiable general method: sodium and calcium recovery loop logic.
- Needs review before operational use: cooking conditions and sizes (imperial values converted), the
  95 to 98 % chemicals figure, the wood composition, materials statements.
