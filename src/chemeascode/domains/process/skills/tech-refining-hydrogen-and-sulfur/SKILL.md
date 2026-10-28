---
name: tech-refining-hydrogen-and-sulfur
description: Reference for the refinery hydrogen and sulfur block. Steam reforming with shift and methanation, hydrogen recovery from off-gas, the amine circuit and the link to the Claus plant. Use when hydrogen supply or sulfur handling for refinery treaters is being discussed or reviewed.
---

# Hydrogen and sulfur

## Purpose and when to use

Every hydroprocessing unit needs a hydrogen source and every treater needs a destination for H2S, so
these blocks size together and grow with crude sourness. The amine circuit is the hinge: it takes H2S out
of gas streams and hands it to the Claus plant. Reached from `tech-refining`; the Claus plant and tail gas
detail is in `tech-gas-sulfur-recovery`.

## Required inputs and missing inputs

Hydrogen demand and purity, available feed (natural gas, naphtha, off-gas), acid gas flows from treaters
and sour water stripping, and the sulfur recovery requirement. Ask for any that is missing.

## Workflow and tools

Engineering guidance only; core has no calculation for this. Reformer and shift equilibria can in
principle be treated as reactions on defined components (see `reactions`, `cheme process reactors`), but
no hydrogen plant model is provided by core.

Steam reforming hydrogen plant: feed desulfurisation (solvent absorber for bulk sulfur, then guard beds,
mainly zinc oxide, with a hydrogenation catalyst where mercaptans or thiophene are present); steam
addition and primary reformer (nickel catalyst in fired tubes) with waste heat boiler; high-temperature
then low-temperature shift; acid gas removal (carbonate or amine); methanator to convert residual
carbon oxides. Hydrogen recovery on refinery off-gas (amine absorber, then pressure swing adsorption
with purge to fuel) is preferred over new manufacture because it is cheaper. A pressure swing route
replaces low-temperature shift, solvent CO2 removal and methanation; the sources give the substitution
and a recovery range but not valve sequencing or vessel count, so those are project information. Partial
oxidation of heavy residue is an alternative where an oxygen plant is available and the residue must be
disposed of.

Amine circuit: sour gas knockout, high-pressure and low-pressure absorbers, rich amine flash with
hydrocarbon skim, lean/rich exchanger, regenerator, acid gas to the sulfur plant, lean amine back to the
absorbers, filter slipstream, nitrogen-blanketed make-up tank. Control: circulation on rich loading and
lean amine temperature held above the sour gas so hydrocarbon does not condense (see
`tech-gas-acid-gas-removal` for the solvent loop in detail).

Sulfur side: straight-through Claus suits rich acid gas and split-flow the intermediate range, with
oxygen enrichment a common debottlenecking route; tail gas treatment falls into sub-dewpoint Claus,
direct oxidation, and reduction of all sulfur species to H2S with an amine absorber recycling acid gas
(Parkash, Ch 8). Control and hazards of the Claus plant: see `tech-gas-sulfur-recovery`.

Reformer control reported: steam to carbon ratio on the feed, outlet temperature on firing, shift inlet
temperatures on waste heat exchangers.

## Validation and failure handling

Questions for a flowsheet or P&ID:

- Does the amine circuit close, and do regenerator acid gas and sour water stripper gas route to the
  Claus plant rather than the fuel header?
- Does the reformer have sulfur guard beds upstream and a waste heat boiler with steam drum downstream?
- Where two shift stages are shown, is high temperature first with interstage cooling? (A pressure swing
  plant correctly shows only high-temperature shift.)
- Does hydrogen recovery show an amine absorber ahead of the adsorbers and a destination for the purge?

Sulfur and chloride are irreversible poisons for the reformer catalyst, so guard beds are upstream. The
methanation exotherm is bounded upstream by the CO2 removal specification rather than by a quench inside
the methanator, a point worth confirming with the designer. Ammonia from sour water stripping must burn in
the furnace or ammonium salts plug the beds. This skill does not certify any protection.

## Outputs and provenance

Hydrogen source and sulfur destination for each treater, with the open points. Source ranges quoted as
ranges, not as errors.

## Required human judgment

Hydrogen source choice, recovery versus manufacture, sulfur recovery requirement, catalyst guard design.

## References

- Parkash, *Refining Processes Handbook*, Elsevier 2003, Ch 8 (Claus recovery 90-95% over two stages
  and 95-97% over three); Kohl and Nielsen, *Gas Purification*, 5th ed., Gulf 1997, Ch 2 (amine design
  rules). Sources differ on recovery; no value is chosen here. Speight, *Handbook of Industrial
  Hydrocarbon Processes*, Elsevier 2011, Ch 8 (reformer reaction window consistent with the worked case).
- Figures for reformer, shift and Claus conditions were dropped. Needs review before operational use.
- `tech-gas-sulfur-recovery`, `tech-gas-acid-gas-removal`, `tech-refining-hydroprocessing`.
