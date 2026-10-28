---
name: tech-heavy-chem-chlor-alkali
description: Process knowledge for chlor-alkali plants - brine purification, diaphragm, membrane and mercury cells, chlorine drying and compression, hydrogen, caustic concentration, sodium chlorate - with the wet/dry chlorine and caustic strength materials breaks. Use when drafting or reviewing a chlor-alkali flowsheet.
---

# Chlor-alkali

## Purpose and when to use

Reached from `tech-heavy-chemicals`. A chlor-alkali plant electrolyses purified brine into chlorine
(anode) and hydrogen plus sodium hydroxide (cathode); much of the equipment cleans the brine before
and dries, concentrates and liquefies the products after. The reaction is driven by direct current, so
the energy balance is electrical work in, and the cell still rejects resistive heat.

## Required inputs and missing inputs

Cell type, capacity, caustic grade, salt source. The source gives no cell voltage, current density,
cell-exit caustic strength or evaporator duty, does not say which effect the caustic filter sits
between, and gives no numbers for the membrane cell: ask for them.

## Workflow and tools

Engineering guidance only; core has no calculation for this. Units in flow order (Speight, Part 2):

1. Salt dissolver and saturated brine storage.
2. Brine treatment: sodium carbonate removes calcium, sodium hydroxide magnesium, barium chloride
   sulfate; recycled salt from the caustic train joins here.
3. Settling and filtration; the loop purge is the solids draw plus a sulfate bleed.
4. Cells. Diaphragm: a diaphragm keeps feed brine from the catholyte, so caustic leaves dilute and
   salt-bearing; the anode liquid level is held above the cathode side to retard back migration
   (caustic reaching the anode makes hypochlorite). Membrane: a cation exchange membrane gives
   salt-free caustic at roughly 30 to 35 %. Mercury: flowing mercury cathode, amalgam decomposed in
   a separate chamber with the mercury returned.
5. Chlorine handling (diaphragm and mercury plants): vacuum collection, water wash and cooling, drying
   against concentrated sulfuric acid, compression or liquefaction; hydrogen is taken off the cathode side.
6. Caustic concentration to 50 %. A diaphragm plant runs evaporator, filter, evaporator because salt
   crystallises as strength rises, and the recovered salt returns to brine treatment. A membrane plant
   starts near 30 to 35 % and needs fewer effects, no salt filter and no salt recycle.

Sodium chlorate uses the same cell, then settler, filter, evaporator, crystalliser and dryer. Source
values: salt-brine about 26 % salt; chlorate cell about 40 degC; chlorate liquor heated to 90 degC to
destroy residual hypochlorite.

## Validation and failure handling

Questions to put to the design:

- Does a brine purification train with separate calcium, magnesium and sulfate additions and a solids
  separation sit ahead of the cells? On a diaphragm plant, does recovered salt return to it?
- Do both product gases have named destinations, with the chlorine path cooling and wash, drying, then
  compression or liquefaction?
- A salt filter and its recycle indicates a diaphragm plant; an evaporator alone says nothing about cell
  type. A mercury plant shows a denuding vessel and mercury return.
- Wet chlorine upstream of the dryer is titanium or lined service; dry chlorine downstream permits steel
  or nickel alloys (Speight, Part 1, halogenation). One specification spanning the dryer is a finding.
- The dryer is strong sulfuric acid service and its spent acid leaves diluted, a third specification.
- Caustic below about 40 % in stress-relieved carbon steel and stronger caustic in nickel (Ray and Das,
  Ch 6): the first and last evaporator effects differ.
- Chlorine and hydrogen must not meet. No source here covers the safeguarding scheme (venting, purging,
  start-up); do not invent loops. Vacuum collection of chlorine makes leak direction a design choice.
- Brine analysis is a process measurement because the cell is damaged by what passes the purification.

## Outputs and provenance

Record cell type, brine basis, caustic strength path and sources in `DESIGN.md`; draw with `process-design`.

## Required human judgment

Chlorine/hydrogen safeguarding, chlorine release protection, mercury containment where relevant,
materials selection, brine quality limits. This skill certifies none of them.

## References

- Speight, *Chemical Process and Design Handbook* (McGraw-Hill 2002), Part 2 (chlorine, chlor-alkali,
  sodium hydroxide, chlorate, sodium chloride) and Part 1 (halogenation).
- Ray and Das, *Process Equipment and Plant Design* (Elsevier 2020), Ch 6.
- Independently verifiable general method: electrolysis stoichiometry, brine impurity removal by
  precipitation, wet/dry chlorine service split.
- Needs review before operational use: all numbers above, the diaphragm material description (older
  plants used asbestos; confirm current diaphragm practice), the caustic strength limits.
