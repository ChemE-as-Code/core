---
name: tech-heavy-chem-sulfuric-acid
description: Process knowledge for contact sulfuric acid plants - sulfur burning, waste heat recovery, multi-bed vanadium conversion with interbed cooling, intermediate and final absorption, acid circulation loops, oleum, hydrogen sulfide front end, and wet/dry materials breaks. Use when drafting or reviewing a sulfuric acid flowsheet.
---

# Sulfuric acid (contact process)

## Purpose and when to use

Reached from `tech-heavy-chemicals`. A contact plant burns sulfur, a sulfide ore or a hydrogen
sulfide stream to sulfur dioxide, oxidises it to sulfur trioxide over vanadium pentoxide, and
absorbs the trioxide into strong acid to make 98 to 99 % acid and oleum. All three steps release
heat, the oxidation is equilibrium limited, and diluting acid releases heat again.

## Required inputs and missing inputs

Sulfur source (molten sulfur, ore gas, hydrogen sulfide), acid and oleum product grades, whether
double absorption is required, and steam export. The source gives no bed depths, gas volumes or
steam pressures, and does not say whether the interbed coolers are boilers, superheaters or
economisers: ask.

## Workflow and tools

Engineering guidance only; core has no calculation for this. The reaction library has an entry
(`cheme chemistry library sulfuric_acid`, see `reactions`); it is chemistry, not a reactor model.
Units in flow order (Speight, Part 2):

1. Air blower and, where fitted, an air drying tower circulating 98 % acid.
2. Combustion chamber burning molten sulfur at about 1000 degC; the air ratio sets gas strength.
3. Waste heat boiler or gas to boiler-feedwater exchanger raising steam, treated as process
   equipment because much of the return is exported steam.
4. Converter with four vanadium layers and interbed cooling. Removing product between beds shifts
   the equilibrium.
5. Intermediate absorption tower after the third layer, reheat to converter inlet temperature,
   the fourth layer, the final tower and tail gas to the stack.
6. An acid circulation loop on each absorption tower: product acid is drawn at 98 to 99 %, water
   is the make-up, and the product draw is the purge of that loop. An oleum tower is added where
   oleum is sold.

Where the feed is hydrogen sulfide the front end is a sulfur recovery unit: reaction furnace,
waste heat boiler, then alternating reheaters, converters and sulfur condensers with mist
elimination (Kohl and Nielsen, Ch 8).

| Item | Source value |
|---|---|
| Burner gas | about 1000 degC (up to 1200 degC with tight air control), 16 to 18 vol % SO2 |
| Converter inlet | about 420 degC |
| First layer | 60 to 65 % conversion, 2 to 4 s, outlet about 600 degC, cooled to about 400 degC |
| After third layer | about 95 % converted |
| Overall, double absorption | about 99.7 % |

## Validation and failure handling

Questions to put to the design:

- Is there an absorption tower between catalyst beds? A single tail tower means single absorption
  and the conversion claim should match.
- Does each layer have cooling ahead of the next, reheat between the intermediate tower and the
  last layer, and a named steam destination for the burner-gas boiler?
- Does each absorption tower have a circulating acid loop (pump, cooler, strength control, product
  draw) with dilution water added to the circulating stream? Drying and oleum towers hold strength
  by acid or trioxide make-up and a bleed; water addition on an oleum loop is a finding.
- Where does dilute acid, wash water or condensate begin, and does the material specification
  change there, including tail gas path and stack liner? Wet/dry gas interfaces are the worst
  corrosion locations in SO2 scrubbing (Kohl and Nielsen, Ch 7).
- On a hydrogen sulfide front end, is the H2S to SO2 ratio entering the converters held near
  two to one with a trim from a tail gas analyser (Kohl and Nielsen)?
- If sulfur trioxide storage is drawn, is an inhibitor addition shown (pure trioxide crystallises
  or polymerises on standing)?

Operating handles named by the chemistry: air ratio to the burner, converter bed inlet
temperatures, acid strength in each loop. The source gives no relief, isolation or interlocks;
molten sulfur, acid storage, steam system and stack requirements are project information.

## Outputs and provenance

Record the absorption arrangement, conversion basis and the source of each number in `DESIGN.md`;
mark source table values as source values.

## Required human judgment

Materials for dilute and wet acid and for the dilution station (acid is added to water, with
controlled mixing, because dilution is strongly exothermic), relief and safeguarding of molten
sulfur, acid and steam systems, and emissions limits. This skill certifies none of them.

## References

- Speight, *Chemical Process and Design Handbook* (McGraw-Hill 2002), Part 2, sulfuric acid,
  sulfur dioxide, sulfur and sulfur trioxide.
- Kohl and Nielsen, *Gas Purification*, 5th ed. (Gulf 1997), Ch 7 and 8.
- Ray and Das, *Process Equipment and Plant Design* (Elsevier 2020), Ch 6: sulfuric acid service
  up to 50 % in graphite exchangers with non-metallic separators and piping.
- Independently verifiable general method: reaction thermochemistry and equilibrium logic, double
  absorption, interbed cooling, acid-to-water dilution.
- Needs review before operational use: temperatures and conversions above, the statement that
  acid above about 95 % suits carbon steel at moderate temperature (uncited in the source skill),
  and chapter numbers carried over from the source.
