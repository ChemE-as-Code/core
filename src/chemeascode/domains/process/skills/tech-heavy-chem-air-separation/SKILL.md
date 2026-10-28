---
name: tech-heavy-chem-air-separation
description: Process knowledge for cryogenic and non-cryogenic air separation (nitrogen, oxygen, rare gases) - prepurification, main exchanger, column, the cold-side expansion that refrigerates the plant, argon and purity trade-offs, membrane and pressure swing alternatives. Use when drafting or reviewing an air separation flowsheet.
---

# Air separation and the industrial gases

## Purpose and when to use

Reached from `tech-heavy-chemicals`. An air separation plant delivers nitrogen and oxygen as gas
or liquid, with neon, krypton and xenon recovered alongside. Helium does not come from air; the
source takes it from natural gas.

There is no synthesis reaction. The separation is physical: nitrogen boils near 77 K and oxygen
near 90 K at atmospheric pressure, so a cold column separates them. Water and carbon dioxide must
leave the air before the cold end or they freeze in the exchanger and column. The refrigeration
comes from compression work and expansion, not from the process.

## Required inputs and missing inputs

Products and purities (oxygen mol%, nitrogen impurity limits), whether liquid is made, capacity,
the oxygen recovery target and whether argon is recovered. If the oxygen purity and the argon
pathway are not stated, ask: they set the column design. Metallurgy and cold-box details are not
in the source.

## Workflow and tools

Engineering guidance only; core has no calculation for this. Units in flow order (Speight, Part 2):

1. Air filter and compressor (the source gives about 5 bar discharge).
2. Aftercooler and water separator for bulk condensate.
3. Prepurification on a pair of switching molecular sieve beds, removing remaining water and
   carbon dioxide and adsorbing trace hydrocarbons. Air reaching the cold box must already be clean.
4. Main heat exchanger, cooling the clean air against returning product streams.
5. Fractionating column with an expansion at the feed. Neon boils below nitrogen and leaves
   overhead with it; krypton and xenon boil above oxygen and collect in the bottoms; argon lies
   between and stays with the oxygen unless it is rejected.
6. Cold-side expansion (valve or expansion engine): part of the stream is expanded and the cold
   gas returns through the main exchanger. That return is what makes the plant self-refrigerating.

An older arrangement freezes water and carbon dioxide out inside reversing exchangers and sweeps
them away by switching air and waste passages, with an oxidation step for hydrocarbons. It needs
exchangers and valves built for it; a plain exchanger with no prepurification is not that.

The non-cryogenic plants share a three-stage pretreatment (particulate, coalescing and carbon
filters after the compressor). A membrane unit then separates by permeation rate; a pressure
swing unit alternates two adsorbent beds (carbon molecular sieve for nitrogen).

| Item | Source value |
|---|---|
| Column feed | about -168 degC at about 5 bar (72 psi) |
| Boiling points | nitrogen -196 degC, oxygen -183 degC |
| Oxygen purity, plain column | 90 to 95 %, argon staying with the oxygen |
| Oxygen purity, extended column | 99.5 %, bought with extra plates |

For the double-column arrangement (high-pressure column coupled to a low-pressure column) and
how to set it up in the simulator, see `process-simulation`. The source describes one column;
do not read its purity figures as a limit on a double-column design. A high-purity oxygen
specification without an argon column implies argon leaves with a waste stream and oxygen
recovery drops; state the recovery and where the argon goes.
Plate count buys purity, so purity and tray count are one decision. Ray and Das give about 30 mm
water column per tray in a small cryogenic air column and about 20 mm in a large one (Ch 11).

Property coverage: `process-design` lists a validated package for N2, O2 and Ar over cryogenic
temperatures (check with `cheme process props --coverage`).

## Validation and failure handling

Questions to put to the design:

- Do water, carbon dioxide and hydrocarbon removal sit ahead of the cold box? A main exchanger
  asked to do that duty is either a reversing-exchanger plant (switching valves, oxidation step)
  or a finding.
- Does the main exchanger have a cold return from the expansion device, not only product streams?
- Does the claimed oxygen purity match the column and the argon pathway?
- Does a non-cryogenic unit show the three filters between compressor and separator, and a swing
  unit both beds with regeneration connections?
- Do rare gas draws come from the cryogenic column, and is helium absent as a product?

The source gives no metallurgy for the cold box, and no oxygen service safeguarding, relief on
the cold box or treatment of blocked-in cryogenic liquid: those are project information. The
column top pressure should be held steady since surges disturb trays and packing (Ray and Das,
Ch 11); the cold recycle rate is the refrigeration handle.

## Outputs and provenance

Record purity, recovery, the argon pathway and the source of each number in `DESIGN.md`; draw the
blocks with `process-design`. Mark numbers taken from the table as source values, not design values.

## Required human judgment

Cold-box and cryogenic materials, oxygen-service cleanliness and safeguarding, relief for
blocked-in cryogenic liquid, and hydrocarbon accumulation in oxygen-rich sumps are for the
engineer and the hazard study. This skill does not establish that any of them is adequate.

## References

- Speight, *Chemical Process and Design Handbook* (McGraw-Hill 2002), Part 2, nitrogen, oxygen
  and air separation.
- Ray and Das, *Process Equipment and Plant Design* (Elsevier 2020), Ch 11 and Ch 12.
- Independently verifiable general method: boiling-point basis of the separation, prepurification
  ahead of the cold end, self-refrigeration by expansion, neon/krypton/xenon/argon volatility order.
- Needs review before operational use: the temperatures, pressures and purity figures (source
  figures, two figures on one source page were numbered alike), the helium statement, tray
  pressure drops, and the purity-versus-column statement against core's ASU example.
