---
name: tech-petrochemicals
description: Index of the petrochemical technology skills (olefins, aromatics, methanol and syngas, ammonia and urea, oxygenates, styrene and phenol, polymers) and the reactor-plus-separation-train pattern they share. Use when the process is an olefin, aromatic, oxygenate, nitrogen or polymer plant, or to find the matching tech-petchem skill.
---

# Petrochemicals (hub)

## Purpose and when to use

Petrochemical plants look varied but are built from a few arrangements. Many are a reactor followed by a
separation train that returns unconverted feed, and most of the equipment is in the separation.

    feed treating -> reaction -> quench or cooling -> light ends removal
      -> product purification -> recycle of unconverted feed

Four things decide the cost:

- Conversion per pass: low conversion means a large recycle and separation train. Many processes run
  deliberately low conversion to hold selectivity, so a big recycle can be a design choice.
- Selectivity: every by-product needs a purge, a separate column or a hydrogenation step.
- Feed purity: catalysts are poisoned by what the feed carries, so an upstream treating step is normal and its
  absence is worth questioning.
- Heat: strongly exothermic reactions are usually run in tubular or multi-bed reactors with interbed cooling or
  quench, and the heat often raises steam.

| Skill | For |
|---|---|
| `tech-petchem-olefins` | Steam cracking, quench and cold separation train, on-purpose propylene |
| `tech-petchem-aromatics` | Extraction, transalkylation, isomerisation, paraxylene recovery |
| `tech-petchem-methanol-and-syngas` | Synthesis gas generation, methanol synthesis, derivatives |
| `tech-petchem-ammonia-and-urea` | The ammonia loop, urea synthesis and recovery |
| `tech-petchem-oxygenates` | Ethylene oxide and glycols, oxo products, acids and anhydrides |
| `tech-petchem-styrene-and-phenol` | Ethylbenzene, styrene, cumene, phenol and acetone |
| `tech-petchem-polymers` | Polyolefin and polyester trains, what replaces columns |

For arrangements implied by a reaction type (oxidation, hydrogenation, alkylation, dehydrogenation,
polymerisation, esterification) see `tech-heavy-chem-reaction-families`. Related core skills: `process-design`,
`reactions`, `route-selection`, `separation-method-selection`.

## Required inputs and missing inputs

Product, feed, capacity and route. These skills supply none of them.

## Workflow and tools

Engineering guidance only; core has no calculation for this. Use the members to decide what units and recycles a
flowsheet should contain, then write it with `process-design`. Core's reaction library has entries for several of
these processes (`cheme chemistry library`, see `reactions`); an entry is chemistry, not a reactor model.

## Validation and failure handling

The members draw on published handbooks and name no licensor. Treat what is common across a family as engineering
knowledge and any single arrangement as one option among several. Some families are covered by a thin entry in the
source, and a few important ones (phthalic anhydride, the vinyls chain, polycarbonate polymerisation) not at all:
say that the source does not support a confident answer rather than fill it in. Controls, trips, relief and
isolation are project information throughout.

## Outputs and provenance

Record route, variant and the source of each borrowed number in `DESIGN.md`.

## Required human judgment

Route and licensor/technology choice, hazard studies, relief and safeguarding. Nothing here certifies safety.

## References

- Speight, *Chemical Process and Design Handbook* (McGraw-Hill 2002); Speight, *Handbook of Industrial
  Hydrocarbon Processes* (Elsevier 2011), as cited in members.
- Independently verifiable general method: the four cost drivers above are qualitative engineering reasoning.
- Needs review before operational use: the pattern is a generalisation, not every plant follows it.
