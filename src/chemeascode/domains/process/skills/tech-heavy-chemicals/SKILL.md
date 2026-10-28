---
name: tech-heavy-chemicals
description: Index of the heavy and inorganic chemicals technology skills (sulfuric acid, nitric acid and fertilizers, chlor-alkali, air separation, pigments and minerals, kraft pulping, reaction-type arrangements) and what these plants have in common. Use when the process is an acid, alkali, fertilizer, industrial gas, mineral or pulping plant, or to find the matching tech-heavy-chem skill.
---

# Heavy and inorganic chemicals (hub)

## Purpose and when to use

Heavy inorganic plants differ from hydrocarbon plants in ways that change what a flowsheet
contains. Use this hub to recognise the family and open the member that matches the process.

- The reaction is often the cheap part and the handling is not: solids, slurries, strong acids
  and alkalis and electrolytic cells dominate the equipment list.
- Materials of construction are a design variable. A change of concentration or of wet and dry
  service often changes the metallurgy or the lining.
- Heat recovery can be much of the economics: a strongly exothermic acid plant may export steam,
  so its boiler belongs to the process rather than to the utilities.
- Gas cleaning is a process step, because the off-gas often carries product or a regulated
  pollutant.

| Skill | For |
|---|---|
| `tech-heavy-chem-reaction-families` | Which reactor, separation and recycle arrangement a reaction type tends to imply; read first when the process is unfamiliar |
| `tech-heavy-chem-sulfuric-acid` | Sulfur burning, conversion, absorption and the steam system |
| `tech-heavy-chem-nitric-acid-and-fertilizers` | Ammonia oxidation, absorption, ammonium nitrate and phosphate fertilizer routes |
| `tech-heavy-chem-chlor-alkali` | Brine treatment, electrolysis, chlorine, hydrogen and caustic handling |
| `tech-heavy-chem-air-separation` | Cryogenic separation of air and the non-cryogenic alternatives |
| `tech-heavy-chem-pigments-and-minerals` | Titanium dioxide, alumina, soda ash and carbon black |
| `tech-heavy-chem-kraft-pulping` | Kraft pulping and its chemical recovery loop |

Related core skills: `process-design` (the flowsheet itself), `reactions` and `route-selection`
(reaction data and route choice, including the reaction library), `separation-method-selection`,
`process-simulation`.

## Required inputs and missing inputs

The process or route in question, its capacity and product specification, and the project
materials basis. These skills do not supply any of them. Where a member is silent (it says so),
the value is project information: ask for it and record it as `assumed` with the reason.

## Workflow and tools

Engineering guidance only; core has no calculation for this. The members describe what a process
consists of, in what order, and what feeds what. Write the resulting blocks and streams with
`process-design`; its checks (`cheme process build`, `streams`, `energy`) test the closure of the
values you give, not whether the technology is right.

## Validation and failure handling

The source behind the members is a block-flow level source: it gives reaction, sequence and
recycle and carries no control loops, relief devices, line sizes or instrumentation. For anything
on a P&ID (loops, trips, isolation, relief) the members say the source does not reach that level;
treat it as project information and do not fill the gap from this hub. Several routes in the source
are covered by a paragraph without a usable flowsheet (for example phosgene, polycarbonates,
polyurethane foams, most resins and pharmaceuticals): do not present them as described.

## Outputs and provenance

Record the chosen route or variant, the source of each number taken from a member and any
`assumed` value in `DESIGN.md`.

## Required human judgment

Route and variant choice, materials of construction, and every safeguarding decision (relief,
isolation, interlocks, hazard studies) belong to the engineer and the project's hazard process.
Nothing here certifies that a design is safe.

## References

- Speight, *Chemical Process and Design Handbook* (McGraw-Hill 2002), Part 2 (individual
  processes) and Part 1 (reaction types).
- Ray and Das, *Process Equipment and Plant Design* (Elsevier 2020), as cited in each member.
- General method, independently verifiable: the plant-wide observations above are qualitative.
  Needs review before operational use: the scope statement on the source's limits.
